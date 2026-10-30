"""Persist a per-run, per-asset budget for automatic model-figure delegation.

The budget never accepts an artifact. It only prevents an unchanged failed or
interrupted delegate from spending another model session in an outer revision.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json, path_lock
from .figure_semantic_projection import semantic_projection_sha256
from .model_composed_svg import figure_spec_sha256, source_bundle_identity


_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_CODE_SOURCES = (
    "../merak-skills/model-svg-figure/SKILL.md",
    "../merak-skills/figure-spec/scripts/figure_renderer.py",
    "../merak-skills/figure-spec/scripts/figure_semantic_rendering.py",
    "agent/tools/figure_draft_tools.py",
    "agent/tools/figure_draft_review.py",
    "agent/tools/figure_tool.py",
    "services/figure_delegate_budget.py",
    "services/figure_semantic_projection.py",
    "services/figure_blind_readback.py",
    "services/figure_scientific_quality.py",
    "services/figure_spec_repository.py",
    "services/model_composed_svg.py",
    "services/model_svg_relation_preflight.py",
    "services/rich_svg_visual_review.py",
    "services/rich_svg_blueprint.py",
    "services/scientific_asset_builders.py",
    "services/scientific_asset_portfolio.py",
    "services/scientific_scene_figure.py",
    "services/scientific_scene_geometry.py",
    "services/scientific_scene_placement.py",
    "services/scientific_scene_labels.py",
    "services/scientific_scene_partitions.py",
    "services/scientific_scene_panel_figure.py",
    "services/deterministic_figure_builder.py",
    "services/figure_producer_fingerprint.py",
    "services/figure_producer_errors.py",
    "services/figure_execution_policy.py",
    "services/figure_execution_evidence.py",
    "services/node_execution_contract.py",
    "services/skill_selection.py",
    "services/planned_result_reuse.py",
    "services/skill_orchestrator.py",
    "services/skill_execution_trace.py",
    "services/figure_engine.py",
    "services/figure_generation_transaction.py",
    "services/figure_result_finalizer.py",
    "services/figure_diagram_text.py",
    "services/figure_scientific_alignment.py",
    "services/scientific_plotting.py",
    "services/scientific_plot_template.py",
    "services/figure_raster_quality.py",
    "services/svg_variant_conversion.py",
    "services/svg_marker_fallback.py",
    "services/figure_svg_sources.py",
    "services/scientific_asset_contract.py",
    "services/figurespec_backend.py",
    "services/figurespec_layout_policy.py",
    "services/evaluation_design_svg.py",
    "services/evaluation_design_contract.py",
    "services/evaluation_protocol_projection.py",
    "contracts/evaluation.py",
    "contracts/preparation.py",
    "services/evaluation_plan_projection.py",
    "services/evaluation_conditions_projection.py",
    "services/evaluation_design_content.py",
    "services/simulation_figure_refresh.py",
    "services/simulation_plot_layout.py",
    "services/simulation_plot_layout_refresh.py",
    "services/simulation_plot_template.py",
    "services/paper_trusted_plot_source.py",
    "services/simulation_publication_registry.py",
    "services/simulation_publication_attestation.py",
    "services/simulation_figure_portfolio.py",
    "services/simulation_paper_projection.py",
    "services/simulation_render_bundle.py",
    "services/planned_simulation_bindings.py",
    "services/simulation_comparison_plots.py",
    "services/simulation_plot_templates/multitask_matrix.py.tmpl",
    "workflows/simulation_render_refresh.py",
    "workflows/engine_inputs.py",
    "workflows/figure_execution_verification.py",
    "workflows/acceptance_pipeline.py",
    "workflows/revision_gate_phases.py",
    "workflows/figure_asset_delegates.py",
)


@dataclass(frozen=True)
class DelegateAttempt:
    """A reserved call or a prior unchanged call that must not be repeated."""

    allowed: bool
    attempt_id: str = ""
    last_error: str = ""
    last_guidance: str = ""


class FigureRetryDeferred(RuntimeError):
    """An unchanged unaccepted model asset has exhausted its automatic budget."""


def _budget_path(root: Path, run_id: str) -> Path:
    if not _IDENTIFIER.fullmatch(run_id):
        raise ValueError("figure delegate run id is not a stable identifier")
    return root / ".merak" / "runs" / f"{run_id}.figure-delegate-budget.json"


def _load_budget(path: Path, run_id: str) -> dict[str, Any]:
    if not path.is_file():
        return {"schema": 1, "run_id": run_id, "assets": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"figure delegate budget is unreadable: {path}") from error
    if not isinstance(payload, dict) or payload.get("schema") != 1 or payload.get("run_id") != run_id:
        raise ValueError(f"figure delegate budget has an unsupported schema: {path}")
    if not isinstance(payload.get("assets"), dict):
        raise ValueError(f"figure delegate budget has invalid assets: {path}")
    return payload


def failed_figure_asset_ids(root: Path, run_id: str) -> list[str]:
    """Return known unaccepted model assets without changing retry state."""
    assets = _load_budget(_budget_path(root, run_id), run_id)["assets"]
    return sorted(
        identity for identity, entry in assets.items()
        if _IDENTIFIER.fullmatch(identity)
        and isinstance(entry, dict)
        and entry.get("state") in {"failed", "in_progress"}
    )


def _code_source_path(relative: str) -> Path:
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parents[1] / relative
    bundle_root = getattr(sys, "_MEIPASS", None)
    if not isinstance(bundle_root, str) or not bundle_root:
        raise RuntimeError("frozen figure producer is missing its bundle resource root")
    if relative.startswith("../merak-skills/"):
        return Path(bundle_root) / relative.removeprefix("../")
    return Path(bundle_root) / "merak-source" / "server" / relative


def _code_sha256() -> str:
    """Hash actual producer source bytes; unavailable bundled sources fail closed."""
    digest = hashlib.sha256()
    for relative in _CODE_SOURCES:
        path = _code_source_path(relative)
        digest.update(relative.encode("utf-8"))
        try:
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        except OSError as error:
            raise RuntimeError(
                f"figure producer source snapshot is unavailable: {relative}"
            ) from error
    return digest.hexdigest()


def figure_producer_code_sha256() -> str:
    """Fingerprint the loaded model-figure producer for revision checkpoints."""
    return _code_sha256()


def figure_resume_input_sha256(root: Path) -> str:
    """Bind declared model-figure sources into the workflow resume signature."""
    spec_path = root / "figures" / "FIGURE_SPECS.json"
    if not spec_path.is_file():
        return "missing-figure-specs"
    try:
        payload = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "unreadable-figure-specs"
    figures = payload.get("figures") if isinstance(payload, dict) else None
    if not isinstance(figures, list):
        return "invalid-figure-specs"
    digest = hashlib.sha256(b"figure-resume-sources:v1")
    for asset in figures:
        if not isinstance(asset, dict) or asset.get("producer_kind") != "model":
            continue
        _, source_hash, issues = source_bundle_identity(root, asset)
        digest.update(str(asset.get("id") or "").encode("utf-8"))
        digest.update(source_hash.encode("ascii"))
        for issue in issues:
            digest.update(issue.encode("utf-8"))
    return digest.hexdigest()


def _identity(
    root: Path, asset: dict[str, Any], *, user_feedback: str,
) -> dict[str, str]:
    _bindings, source_hash, issues = source_bundle_identity(root, asset)
    if issues:
        raise ValueError(
            "figure delegate declared sources are unavailable: "
            + "; ".join(issues[:6])
        )
    return {
        "semantic_projection_sha256": semantic_projection_sha256(asset),
        "figure_spec_sha256": figure_spec_sha256(asset),
        "source_bundle_sha256": source_hash,
        "code_sha256": _code_sha256(),
        "feedback_sha256": hashlib.sha256(user_feedback.strip().encode()).hexdigest()
        if user_feedback.strip() else "",
    }


_CONTENT_KEYS = (
    "semantic_projection_sha256", "figure_spec_sha256",
    "source_bundle_sha256", "code_sha256",
)


def _content_changed(previous: dict[str, Any], current: dict[str, str]) -> bool:
    return any(previous.get(key) != current[key] for key in _CONTENT_KEYS)


def _feedback_history(previous: dict[str, Any]) -> list[str]:
    history = previous.get("feedback_sha256_history", [])
    if not isinstance(history, list) or any(not isinstance(item, str) for item in history):
        raise ValueError("figure delegate budget feedback history is invalid")
    prior = str(previous.get("feedback_sha256") or "")
    return list(dict.fromkeys([*history, *([prior] if prior else [])]))


def _may_retry(previous: dict[str, Any], current: dict[str, str]) -> bool:
    if _content_changed(previous, current):
        return True
    feedback_hash = current["feedback_sha256"]
    return bool(feedback_hash and feedback_hash not in _feedback_history(previous))


def begin_delegate_attempt(
    root: Path, run_id: str, asset: dict[str, Any],
    *, user_feedback: str = "", manual_resume_id: str = "",
) -> DelegateAttempt:
    """Atomically reserve one asset attempt; unchanged prior calls fail closed.

    The caller may perform bounded local and visual resubmissions in its single
    session after this reservation. A later outer revision cannot reserve again without changed
    inputs/code, new asset-scoped researcher feedback, or an explicit manual
    interruption-resume ID. Each manual ID grants at most one attempt; ordinary
    concurrency lease tokens grant none and never imply scientific acceptance.
    """
    identity = str(asset.get("id") or "")
    if not _IDENTIFIER.fullmatch(identity):
        raise ValueError("figure asset id is not a stable identifier")
    path = _budget_path(root, run_id)
    current = _identity(root, asset, user_feedback=user_feedback)
    with path_lock(path):
        budget = _load_budget(path, run_id)
        previous = budget["assets"].get(identity)
        if previous is not None and not isinstance(previous, dict):
            raise ValueError(f"figure delegate budget entry is invalid: {identity}")
        if isinstance(previous, dict) and not all(
            isinstance(previous.get(key), str) and previous.get(key)
            for key in (
                "semantic_projection_sha256", "figure_spec_sha256",
                "source_bundle_sha256", "code_sha256", "attempt_id",
            )
        ):
            raise ValueError(f"figure delegate budget entry is incomplete: {identity}")
        manual_retry = bool(manual_resume_id and isinstance(previous, dict)
                            and previous.get("manual_resume_id") != manual_resume_id)
        if isinstance(previous, dict) and not manual_retry and not _may_retry(previous, current):
            return DelegateAttempt(
                False, last_error=str(previous.get("last_error") or ""),
                last_guidance=str(previous.get("last_guidance") or ""),
            )
        attempt_id = uuid.uuid4().hex
        feedback_history = (
            [] if previous is None or _content_changed(previous, current)
            else _feedback_history(previous)
        )
        if current["feedback_sha256"]:
            feedback_history.append(current["feedback_sha256"])
        budget["assets"][identity] = {
            **current, "attempt_id": attempt_id, "state": "in_progress",
            "manual_resume_id": manual_resume_id,
            "last_error": "delegate attempt interrupted before acceptance",
            "last_guidance": "", "feedback_sha256_history": feedback_history,
        }
        atomic_write_json(path, budget)
    return DelegateAttempt(True, attempt_id=attempt_id)


def record_delegate_failure(
    root: Path, run_id: str, asset_id: str, attempt_id: str,
    *, error: str, guidance: str,
) -> None:
    """Record a failed call without overwriting a newer asset attempt."""
    path = _budget_path(root, run_id)
    with path_lock(path):
        budget = _load_budget(path, run_id)
        item = budget["assets"].get(asset_id)
        if not isinstance(item, dict) or item.get("attempt_id") != attempt_id:
            return
        item.update({
            "state": "failed", "last_error": error[:1000],
            "last_guidance": guidance[:1600],
        })
        atomic_write_json(path, budget)
