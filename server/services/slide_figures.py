"""Hash-current figure selection for scientific slide decks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .simulation_policy import simulation_manifest_contract_issues
from .simulation_figure_portfolio import selected_simulation_figure_ids
from .simulation_publication_attestation import _current_bundle


SYNTHETIC_SLIDE_FIGURES: tuple[tuple[str, str], ...] = (
    ("synthetic_preview_main_comparison", "Primary Comparison"),
    ("synthetic_preview_ablation", "Component Analysis"),
    ("synthetic_preview_training_dynamics", "Training or Convergence Dynamics"),
    ("synthetic_preview_robustness", "Robustness and Sensitivity"),
    ("synthetic_preview_error_analysis", "Error and Failure Analysis"),
    ("synthetic_preview_calibration", "Calibration and Risk Coverage"),
    ("synthetic_preview_efficiency", "Performance and Resource Efficiency"),
)
SYNTHETIC_SLIDE_FIGURE_IDS = tuple(item[0] for item in SYNTHETIC_SLIDE_FIGURES)


def required_synthetic_figure_ids(root: Path) -> tuple[str, ...]:
    """Select the frozen contribution portfolio, never the surviving qualified set."""
    root = root.resolve()
    simulation = _current_bundle(root)
    if (simulation.get("explicit_user_mode") != "synthetic_preview"
            or simulation.get("evidence_status") != "synthetic_preview"
            or simulation.get("manuscript_eligible") is not True):
        raise ValueError("Simulation slide portfolio requires an explicitly manuscript-eligible scenario bundle")
    selected = selected_simulation_figure_ids(root, simulation["figure_files"])
    ordered = tuple(identity for identity in SYNTHETIC_SLIDE_FIGURE_IDS if identity in selected)
    if not ordered or set(ordered) != selected:
        raise ValueError("Simulation slide portfolio is empty or contains unsupported figures")
    return ordered


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def project_file(root: Path, value: Any) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        candidate = Path(raw)
        candidate = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate if candidate.is_relative_to(root) else None


def standard_figure_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    excluded_evidence = {"placeholder", "synthetic", "synthetic_preview", "administrative", "internal"}
    excluded_roles = {
        "protocol", "administrative", "claim_map", "execution_status",
        "experimental_design", "internal_protocol",
    }
    return [
        item for item in manifest.get("figures") or []
        if isinstance(item, dict)
        and item.get("paper_ready")
        and item.get("output_path")
        and str((item.get("metadata") or {}).get("evidence_status") or "").casefold() not in excluded_evidence
        and (item.get("metadata") or {}).get("paper_selected", True) is not False
        and str((item.get("metadata") or {}).get("scientific_role") or "").casefold() not in excluded_roles
    ]


def qualified_standard_figures(
    root: Path,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    from .slide_presentation_projection import project_slide_presentations

    return project_slide_presentations(root, _canonical_standard_figures(root, manifest))


def _canonical_standard_figures(root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    qualified: list[dict[str, Any]] = []
    for entry in standard_figure_entries(manifest):
        output = project_file(root, entry.get("output_path"))
        digest = str(entry.get("output_sha256") or "").strip()
        if output and output.is_file() and output.stat().st_size > 0 and digest:
            if _sha256(output) == digest:
                qualified.append(entry)
    return qualified


def _simulation_context(root: Path, manifest: dict[str, Any]) -> tuple[dict[str, Any], Path, str] | None:
    path = root / "experiments" / "results" / "simulated" / "SIMULATION_MANIFEST.json"
    try:
        simulation = _current_bundle(root)
        required_synthetic_figure_ids(root)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        return None
    digest = _sha256(path)
    if (
        simulation_manifest_contract_issues(simulation)
        or simulation.get("explicit_user_mode") != "synthetic_preview"
        or simulation.get("evidence_status") != "synthetic_preview"
        or simulation.get("manuscript_eligible") is not True
        or not digest
    ):
        return None
    records = {
        str(item.get("id") or "")
        for item in simulation.get("figure_files") or [] if isinstance(item, dict)
    }
    if not set(SYNTHETIC_SLIDE_FIGURE_IDS).issubset(records):
        return None
    return simulation, path, digest


def _source_data_current(root: Path, metadata: dict[str, Any]) -> bool:
    source_data = [str(item).strip() for item in metadata.get("source_data") or [] if str(item).strip()]
    source_hashes = dict(metadata.get("source_data_sha256") or {})
    return bool(source_data) and all(
        (path := project_file(root, relative)) is not None
        and path.is_file()
        and _sha256(path) == str(source_hashes.get(relative) or "")
        for relative in source_data
    )


def _synthetic_entry_current(
    root: Path,
    entry: dict[str, Any],
    record: dict[str, Any],
    manifest_path: Path,
    manifest_digest: str,
) -> bool:
    metadata = dict(entry.get("metadata") or {})
    output = project_file(root, entry.get("output_path"))
    relative_output = output.relative_to(root).as_posix() if output and output.is_relative_to(root) else ""
    output_digest = _sha256(output) if output else ""
    record_outputs = dict(record.get("outputs") or {})
    record_hashes = dict(record.get("output_sha256") or {})
    return bool(
        entry.get("paper_ready") is True
        and metadata.get("paper_selected") is True
        and metadata.get("manuscript_eligible") is True
        and metadata.get("submission_eligible") is False
        and metadata.get("evidence_status") == "synthetic_preview"
        and metadata.get("explicit_user_mode") == "synthetic_preview"
        and metadata.get("provenance_kind") == "deterministic_simulation_preview"
        and project_file(root, metadata.get("simulation_manifest")) == manifest_path
        and metadata.get("simulation_manifest_sha256") == manifest_digest
        and entry.get("source_path") == record.get("source")
        and entry.get("source_sha256") == record.get("source_sha256")
        and metadata.get("rendered_variants") == record_outputs
        and metadata.get("rendered_variant_sha256") == record_hashes
        and output and output.is_file() and relative_output.startswith("figures/simulated/")
        and output_digest and entry.get("output_sha256") == output_digest
        and record_outputs.get("pdf") == relative_output
        and record_hashes.get("pdf") == output_digest
        and _source_data_current(root, metadata)
    )


def qualified_synthetic_figures(
    root: Path,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    from .slide_presentation_projection import project_slide_presentations

    return project_slide_presentations(root, _canonical_synthetic_figures(root, manifest))


def _canonical_synthetic_figures(root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    context = _simulation_context(root, manifest)
    if context is None:
        return []
    simulation, manifest_path, manifest_digest = context
    records = {
        str(item.get("id") or ""): item
        for item in simulation.get("figure_files") or [] if isinstance(item, dict)
    }
    registry = {
        str((item.get("metadata") or {}).get("semantic_key") or item.get("id") or ""): item
        for item in manifest.get("figures") or [] if isinstance(item, dict)
    }
    qualified = [
        entry for figure_id in required_synthetic_figure_ids(root)
        if isinstance((entry := registry.get(figure_id)), dict)
        and isinstance((record := records.get(figure_id)), dict)
        and _synthetic_entry_current(root, entry, record, manifest_path, manifest_digest)
    ]
    return qualified


def deck_figures(
    root: Path,
    assets: dict[str, Any],
    manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    standard = _canonical_standard_figures(root, manifest)
    synthetic = _canonical_synthetic_figures(root, manifest) if (
        str(assets.get("evidence_mode") or "").casefold() == "synthetic_preview"
    ) else []
    from .slide_presentation_projection import project_slide_presentations

    current = project_slide_presentations(root, [*standard, *synthetic])
    return current[:len(standard)], current[len(standard):]


def referenced_figure_ids(
    root: Path,
    tex_text: str,
    assets: dict[str, Any],
    manifest: dict[str, Any],
) -> list[str]:
    standard, synthetic = deck_figures(root, assets, manifest)
    return _referenced_ids_from_current_figures(root, tex_text, [*standard, *synthetic])


def referenced_ids_from_figures(
    root: Path,
    tex_text: str,
    figures: list[dict[str, Any]],
) -> list[str]:
    from .slide_presentation_projection import project_slide_presentations

    return _referenced_ids_from_current_figures(root, tex_text, project_slide_presentations(root, figures))


def _referenced_ids_from_current_figures(root: Path, tex_text: str, figures: list[dict[str, Any]]) -> list[str]:
    from .latex_graphics_paths import resolved_graphics
    by_output: dict[Path, str] = {}
    by_name: dict[str, list[tuple[Path, str]]] = {}
    replaced_outputs: set[Path] = set()
    from .slide_presentation_projection import presentation_output_path

    for item in figures:
        output = project_file(root, presentation_output_path(item))
        if output is None:
            continue
        if item.get("slide_presentation"):
            original = project_file(root, item.get("output_path"))
            if original is not None:
                replaced_outputs.add(original)
        identity = str((item.get("metadata") or {}).get("semantic_key") or item.get("id") or "")
        by_output[output] = identity
        by_name.setdefault(output.name.casefold(), []).append((output, identity))
    selected: list[str] = []
    for candidate in resolved_graphics(root, root / "slides", tex_text):
        candidates = [candidate]
        if any(item in replaced_outputs for item in candidates):
            continue
        identity = next((by_output[item] for item in candidates if item in by_output), "")
        if not identity:
            identity = next((
                matched for item in candidates if item.is_file()
                for canonical, matched in by_name.get(item.name.casefold(), [])
                if len(by_name.get(item.name.casefold(), [])) == 1
                and _sha256(item) == _sha256(canonical)
            ), "")
        if identity and identity not in selected:
            selected.append(identity)
    return selected
