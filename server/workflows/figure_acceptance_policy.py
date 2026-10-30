"""Deterministic figure-manifest acceptance without model or renderer execution."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..services.figure_artifacts import figure_artifact_registry
from ..services.figure_routing import (
    expected_source_extensions,
    manifest_backend_matches,
)
from ..services.publication_figure_labels import validate_publication_labels


class FigureGateHost(Protocol):
    def _verified_figure_skill_invocation(
        self, root: Path, asset_id: str, skill: str
    ) -> bool: ...
    def _verdict_id(self, node_id: str, artifacts: list[Path]) -> str: ...


@dataclass
class FigureGateContext:
    host: FigureGateHost
    root: Path
    figures_root: Path
    manifest_path: Path
    specs_path: Path
    asset_plan_path: Path
    payload: dict[str, Any] = field(default_factory=dict)
    asset_plan: dict[str, Any] = field(default_factory=dict)
    planned_assets: dict[str, dict[str, Any]] = field(default_factory=dict)
    required_ids: set[str] = field(default_factory=set)
    paper_ready: list[dict[str, Any]] = field(default_factory=list)
    editable: list[dict[str, Any]] = field(default_factory=list)
    previews: list[dict[str, Any]] = field(default_factory=list)
    manifest_by_key: dict[str, dict[str, Any]] = field(default_factory=dict)
    preview_by_key: dict[str, dict[str, Any]] = field(default_factory=dict)
    evidence_mode: str = ""
    quantitative: list[dict[str, Any]] = field(default_factory=list)
    valid: bool = False
    problems: list[str] = field(default_factory=list)


def _read_object(path: Path, description: str, problems: list[str]) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        problems.append(f"missing {path.as_posix()}")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        problems.append(f"{description} is not valid JSON")
        return {}
    if not isinstance(payload, dict):
        problems.append(f"{description} root must be a JSON object")
        return {}
    return payload


def _load_context(host: FigureGateHost, project_path: str) -> FigureGateContext:
    root = Path(project_path).resolve()
    figures = root / "figures"
    manifest = figure_artifact_registry.manifest_path(figures)
    if not manifest.exists():
        figure_artifact_registry.reconcile(figures)
    context = FigureGateContext(
        host,
        root,
        figures,
        manifest,
        figures / "FIGURE_SPECS.json",
        figures / "SCIENTIFIC_ASSET_PLAN.json",
    )
    context.asset_plan = _read_object(
        context.asset_plan_path,
        "scientific asset plan",
        context.problems,
    )
    context.planned_assets = {
        str(item.get("id")): item
        for item in context.asset_plan.get("assets", [])
        if isinstance(item, dict) and item.get("id")
    }
    context.required_ids = {
        asset_id
        for asset_id, asset in context.planned_assets.items()
        if asset.get("kind") == "figure"
        and asset.get("required")
        and str(asset.get("generation_policy") or "generate").casefold() != "skip"
    }
    included = {
        asset_id
        for asset_id, asset in context.planned_assets.items()
        if asset.get("kind") == "figure"
        and str(asset.get("generation_policy") or "generate").casefold() != "skip"
    }
    figure_artifact_registry.curate_to_plan(
        figures,
        included,
        evidence_mode=str(context.asset_plan.get("evidence_mode") or "design_only"),
        planned_assets=context.planned_assets,
    )
    _refresh_registry(context)
    return context


def _refresh_registry(context: FigureGateContext) -> None:
    from ..services.deterministic_figure_freshness import deterministic_figure_freshness_issues

    context.valid, issues, context.payload = figure_artifact_registry.validate(
        context.figures_root
    )
    context.problems.extend(issues)
    context.problems.extend(deterministic_figure_freshness_issues(context.root))
    context.problems.extend(
        figure_artifact_registry.scientific_quality_issues(context.figures_root)
    )
    context.problems.extend(
        figure_artifact_registry.scientific_alignment_issues(context.figures_root)
    )
    figures = context.payload.get("figures", [])
    context.paper_ready = [
        item
        for item in figure_artifact_registry.paper_ready_entries(context.figures_root)
        if (item.get("metadata") or {}).get("evidence_status") != "placeholder"
    ]
    context.editable = [
        item
        for item in figures
        if item.get("editable")
        and (item.get("metadata") or {}).get("evidence_status") != "placeholder"
    ]
    context.previews = [
        item
        for item in figures
        if str((item.get("metadata") or {}).get("evidence_status") or "").casefold()
        == "synthetic_preview"
        and item.get("output_path")
        and item.get("source_path")
    ]


def _validate_specs(context: FigureGateContext) -> None:
    specs = _read_object(context.specs_path, "figure specification", context.problems)
    if specs.get("schema") != 4 or specs.get("publication_label_schema") != 1:
        context.problems.append("figure specification has an unsupported typed-label schema")
    items = specs.get("figures", [])
    if context.required_ids and not items:
        context.problems.append(
            "figure specification must define at least 1 manuscript figure"
        )
    required = {
        "id",
        "scientific_role",
        "scientific_question",
        "claim_ids",
        "source_data",
        "intended_comparison",
        "visual_encoding",
        "uncertainty_encoding",
        "evidence_status",
        "label",
        "caption",
        "recommended_backend",
        "recommended_skill",
    }
    for index, spec in enumerate(items if isinstance(items, list) else []):
        missing = (
            sorted(required - set(spec)) if isinstance(spec, dict) else sorted(required)
        )
        if missing:
            context.problems.append(
                f"figure spec {index + 1} missing: {', '.join(missing)}"
            )
        if (
            isinstance(spec, dict)
            and spec.get("generation_phase") == "phase_2b"
        ):
            _, issues = validate_publication_labels(spec.get("publication_labels"))
            context.problems.extend(
                f"figure spec {index + 1}: {issue}" for issue in issues
            )
            if spec.get("producer_kind") not in {"model", "deterministic"}:
                context.problems.append(
                    f"figure spec {index + 1} has no current producer_kind"
                )


def _validate_entry(
    context: FigureGateContext, asset_id: str, asset: dict[str, Any]
) -> None:
    preview_satisfies = (
        str(asset.get("evidence_status") or "").casefold() == "synthetic_preview"
        and asset_id in context.preview_by_key
    )
    if asset_id not in context.manifest_by_key and not preview_satisfies:
        context.problems.append(
            f"required scientific figure was not rendered: {asset_id}"
        )
        return
    entry = context.manifest_by_key.get(asset_id)
    if entry is None:
        return
    metadata = dict(entry.get("metadata") or {})
    backend = str(asset.get("recommended_backend") or "").strip()
    skill = str(asset.get("recommended_skill") or "").strip()
    actual_backend = str(entry.get("type") or "").strip()
    actual_skill = str(
        metadata.get("generator_skill") or metadata.get("skill") or ""
    ).strip()
    if backend and not manifest_backend_matches(backend, skill, actual_backend):
        context.problems.append(
            f"{asset_id} backend mismatch: expected {backend}, found {actual_backend or 'unknown'}"
        )
    source_value = str(entry.get("source_path") or "").strip()
    source = (context.root / source_value).resolve() if source_value else None
    extensions = expected_source_extensions(backend)
    if extensions and (
        source is None
        or not source.is_file()
        or source.suffix.casefold() not in extensions
    ):
        context.problems.append(
            f"{asset_id} has no editable {backend} source ({', '.join(sorted(extensions))})"
        )
    synthetic = (
        context.evidence_mode == "synthetic_preview"
        and str(metadata.get("evidence_status") or "").casefold() == "synthetic_preview"
        and str(metadata.get("provenance_kind") or "").casefold()
        == "deterministic_simulation_preview"
    )
    if not synthetic and skill and actual_skill != skill:
        context.problems.append(
            f"{asset_id} skill mismatch: expected /{skill}, found /{actual_skill or 'unknown'}"
        )
    if not synthetic and metadata.get("skill_invocation_verified") is not True:
        context.problems.append(
            f"{asset_id} has no runtime-verified skill invocation provenance"
        )
    if (
        actual_backend == "nano_banana"
        and skill == "paper-illustration"
        and not context.host._verified_figure_skill_invocation(
            context.root, asset_id, skill
        )
    ):
        context.problems.append(
            f"{asset_id} was not generated inside a durable /paper-illustration Skill session"
        )
    if metadata.get("renderer") in {"local-semantic-fallback", "local-semantic-repair"}:
        context.problems.append(f"{asset_id} uses a prohibited local fallback renderer")
    if backend == "excalidraw" and metadata.get("model_authored") is not True:
        context.problems.append(f"{asset_id} is missing model-authored provenance")


def _validate_required_assets(context: FigureGateContext) -> None:
    context.manifest_by_key = {
        str((item.get("metadata") or {}).get("semantic_key") or ""): item
        for item in context.paper_ready
    }
    context.preview_by_key = {
        str((item.get("metadata") or {}).get("semantic_key") or ""): item
        for item in context.previews
    }
    context.evidence_mode = str(
        context.asset_plan.get("evidence_mode") or ""
    ).casefold()
    for asset_id, asset in context.planned_assets.items():
        if asset.get("kind") == "figure" and asset.get("required"):
            _validate_entry(context, asset_id, asset)
    plan_path = context.root / "paper" / "PAPER_PLAN.md"
    if plan_path.is_file():
        text = plan_path.read_text(encoding="utf-8", errors="replace")
        from ..services.paper_plan_asset_links import missing_figure_links
        context.problems.extend(
            f"required figure is not referenced in paper/PAPER_PLAN.md: {asset_id}"
            for asset_id in missing_figure_links(text, context.planned_assets)
        )


def _validate_evidence_mode(context: FigureGateContext) -> None:
    mode = context.evidence_mode
    eligible = bool(context.asset_plan.get("submission_eligible"))
    if mode in {"executed", "existing_results", "secondary_analysis"} and not eligible:
        context.problems.append(
            f"{mode} mode is not backed by a submission-eligible evidence plan"
        )
    elif (
        eligible
        and mode not in {"executed", "existing_results", "secondary_analysis"}
    ):
        context.problems.append(
            f"non-empirical evidence mode {mode or 'unspecified'} cannot be submission-eligible"
        )
    if context.asset_plan.get("experiment_requested") or mode in {
        "existing_results",
        "secondary_analysis",
    }:
        context.problems.extend(
            str(item)
            for item in context.asset_plan.get("missing_requirements", [])
            if str(item).strip()
        )
    context.quantitative = [
        item
        for item in context.paper_ready
        if str((item.get("metadata") or {}).get("scientific_role") or "")
        in {"result", "ablation", "robustness"}
        and (
            (item.get("metadata") or {}).get("evidence_status") == "executed"
            or (
                mode == "synthetic_preview"
                and (item.get("metadata") or {}).get("evidence_status")
                == "synthetic_preview"
                and (item.get("metadata") or {}).get("provenance_kind")
                == "deterministic_simulation_preview"
            )
        )
    ]
    if (
        mode in {"executed", "existing_results", "synthetic_preview"}
        and not context.quantitative
    ):
        context.problems.append(
            f"{mode} mode requires at least one evidence-backed quantitative figure"
        )


def _validate_minimums(context: FigureGateContext) -> set[str]:
    if context.evidence_mode in {
        "design_only",
        "synthetic_preview",
        "execution_pending",
        "secondary_analysis",
    }:
        phase_ids = {
            asset_id
            for asset_id, asset in context.planned_assets.items()
            if asset.get("kind") == "figure"
            and asset.get("required")
            and str(asset.get("generation_phase") or "").casefold() == "phase_2b"
            and str(asset.get("generation_policy") or "generate").casefold() != "skip"
        }
        missing = sorted(phase_ids - set(context.manifest_by_key))
        if missing:
            context.problems.append(
                "non-executed mode requires a domain-specific method figure: "
                + ", ".join(missing)
            )
    if context.required_ids and not context.paper_ready:
        context.problems.append(
            f"need at least 1 paper-ready figure, found {len(context.paper_ready)}"
        )
    if context.required_ids and not context.editable:
        context.problems.append("need at least 1 editable figure source")
    roles = {
        str((item.get("metadata") or {}).get("scientific_role") or "")
        for item in context.paper_ready
    } - {""}
    leaked = sorted(
        roles
        & {
            "protocol",
            "administrative",
            "claim_map",
            "execution_status",
            "experimental_design",
            "internal_protocol",
        }
    )
    if leaked:
        context.problems.append(
            "internal-only figure roles were selected for the manuscript: "
            + ", ".join(leaked)
        )
    return roles


def _accepted_gate(context: FigureGateContext, roles: set[str]) -> dict[str, Any]:
    artifacts = [context.manifest_path, context.specs_path, context.asset_plan_path]
    for item in context.payload.get("figures", []):
        for key in ("output_path", "source_path"):
            value = item.get(key)
            if value:
                candidate = Path(value)
                artifacts.append(
                    candidate if candidate.is_absolute() else context.root / candidate
                )
    return {
        "accepted": True,
        "verdict_id": context.host._verdict_id("artifact:figure-manifest", artifacts),
        "reviewer": "deterministic:figure-manifest",
        "summary": (
            f"Verified {len(context.paper_ready)} paper-ready figure(s), "
            f"{len(context.editable)} editable source(s), and all persisted hashes."
        ),
        "details": {
            "manifest": str(context.manifest_path),
            "paper_ready": [item.get("output_path") for item in context.paper_ready],
            "editable": [item.get("source_path") for item in context.editable],
            "scientific_roles": sorted(roles),
            "specification": str(context.specs_path),
            "asset_plan": str(context.asset_plan_path),
            "evidence_mode": context.evidence_mode,
            "quantitative_count": len(context.quantitative),
            "preview_count": len(context.previews),
        },
    }


def figure_acceptance_gate(host: FigureGateHost, project_path: str) -> dict[str, Any]:
    context = _load_context(host, project_path)
    _validate_specs(context)
    _validate_required_assets(context)
    _validate_evidence_mode(context)
    roles = _validate_minimums(context)
    if not context.valid or context.problems:
        return {
            "accepted": False,
            "reason": "figure artifact contract failed",
            "summary": "; ".join(context.problems),
            "details": {
                "manifest": str(context.manifest_path),
                "paper_ready_count": len(context.paper_ready),
                "preview_count": len(context.previews),
                "editable_count": len(context.editable),
                "scientific_roles": sorted(roles),
                "issues": context.problems,
            },
        }
    return _accepted_gate(context, roles)
