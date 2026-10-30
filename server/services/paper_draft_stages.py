"""Stage ownership, fingerprints, and authoring asset inventory."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Iterable

from .manuscript_text import read_json, semantic_artifact_hash, sha256, write_json
from .simulation_policy import FORBIDDEN_RENDERED_SIMULATION_LABELS
from .paper_stage_validator_signature import stage_validator_signature


def stage_outputs(
    paths: dict[str, Path], stage_id: str, section_by_id: dict[str, Any]
) -> list[Path]:
    if stage_id == "blueprint":
        return [paths["blueprint"]]
    if stage_id == "front_matter":
        return [paths["title"], paths["sections"] / "00_abstract.tex"]
    if stage_id == "consistency":
        return [paths["cross_review"]]
    spec = section_by_id.get(stage_id)
    return [paths["sections"] / spec.filename] if spec else []


def stage_for_target(target: str, specs: Iterable[Any]) -> str:
    normalized = str(target or "").strip().replace("\\", "/")
    lower = normalized.casefold()
    marker = "/paper/"
    if marker in lower:
        index = lower.rfind(marker)
        normalized = "paper/" + normalized[index + len(marker):]
    key = normalized.lstrip("./").casefold()
    targets = {
        "paper/contribution_blueprint.md": "blueprint",
        "paper/title.txt": "front_matter",
        "paper/sections/00_abstract.tex": "front_matter",
        "paper/cross_section_review.md": "consistency",
        "paper/main.tex": "assembly",
    }
    targets.update({
        f"paper/sections/{spec.filename}".casefold(): spec.id for spec in specs
    })
    return targets.get(key, "")


def revision_target_paths(issues: Iterable[str]) -> list[str]:
    joined = " ".join(str(issue or "") for issue in issues)
    explicit = re.findall(r"(?i)Target artifact:\s*(paper[\\/][A-Za-z0-9_.\\/-]+\.[A-Za-z0-9]+)", joined)
    if explicit:
        return list(dict.fromkeys(target.replace("\\", "/") for target in explicit))
    return list(dict.fromkeys(
        match.group(1).replace("\\", "/")
        for match in re.finditer(
            r"(?i)(paper[\\/][A-Za-z0-9_.\\/-]+\.[A-Za-z0-9]+)", joined
        )
    ))


def stage_contract_version(
    stage_id: str, section_version: int, consistency_version: int, assembly_version: int
) -> int:
    if stage_id == "consistency":
        return consistency_version
    if stage_id == "assembly":
        return assembly_version
    return section_version


def stage_write_targets(
    paths: dict[str, Path], stage_id: str, *, section_by_id: dict[str, Any],
    author_order: tuple[str, ...],
) -> list[Path]:
    # Cross-section review is not an unbounded author. Concrete defects route
    # back to their section producer before the report is freshly revalidated.
    return stage_outputs(paths, stage_id, section_by_id)


def target_semantic_signature(paths: dict[str, Path], targets: Iterable[Path]) -> str:
    payload: dict[str, str] = {}
    for path in targets:
        try:
            identity = path.relative_to(paths["root"]).as_posix()
        except ValueError:
            identity = path.as_posix()
        payload[identity] = semantic_artifact_hash(path)
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def stage_input_signature(
    paths: dict[str, Path], stage_id: str, *, author_order: tuple[str, ...],
    section_by_id: dict[str, Any],
) -> str:
    if stage_id not in author_order:
        return ""
    inputs: dict[str, str] = {}
    for upstream in author_order[:author_order.index(stage_id)]:
        for path in stage_outputs(paths, upstream, section_by_id):
            try:
                identity = path.relative_to(paths["root"]).as_posix()
            except ValueError:
                identity = path.as_posix()
            inputs[identity] = sha256(path) or "<missing>"
    if stage_id == 'consistency':
        from .paper_consistency_identity import consistency_input_paths
        for name, path in consistency_input_paths(paths['root']).items():
            inputs[name] = sha256(path) or '<missing>'
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode("utf-8")).hexdigest()


def stage_outputs_match(
    outputs: Iterable[Path], record: dict[str, Any], contract_version: int, stage_id: str,
) -> bool:
    outputs = list(outputs)
    expected = dict(record.get("output_hashes") or {})
    return bool(
        record.get("status") == "completed" and outputs
        and record.get("contract_version") == contract_version
        and record.get("validator_signature") == stage_validator_signature(stage_id)
        and all(path.is_file() and path.stat().st_size > 0
                and expected.get(path.name) == sha256(path) for path in outputs)
    )


def inventory(paths: Iterable[Path], root: Path) -> str:
    lines = []
    for path in paths:
        if path.is_file() and path.stat().st_size > 0:
            try:
                display = path.relative_to(root).as_posix()
            except ValueError:
                display = str(path)
            lines.append(f"- {display}")
    return "\n".join(lines) or "- (none)"


def write_authoring_asset_manifest(
    root: Path, target: Path, *, evidence_mode: str
) -> Path:
    raw_figures = read_json(root / "figures" / "FIGURE_MANIFEST.json")
    raw_tables = read_json(root / "paper" / "tables" / "TABLE_MANIFEST.json")
    from .paper_asset_reference_contract import selected_publication_references
    references = selected_publication_references(root)
    selected_figure_labels = {reference.label for reference in references if reference.kind == "figure"}
    selected_figures = {**raw_figures, "figures": [item for item in raw_figures.get("figures") or []
        if str((item.get("metadata") or {}).get("label") or "") in selected_figure_labels]}
    payload = {
        "schema": 1, "generated_at": time.time(), "evidence_mode": evidence_mode,
        "authoring_contract": (
            "Use only the registered scientific roles, captions, labels, and paths below. "
            "Internal filenames and identifiers are LaTeX plumbing and must not appear as manuscript prose."
        ),
        "figures": _authoring_figures(selected_figures),
        "tables": _authoring_tables(raw_tables),
    }
    write_json(target, payload)
    return target


def _authoring_figures(payload: dict[str, Any]) -> list[dict[str, Any]]:
    figures = []
    for index, item in enumerate(payload.get("figures") or [], start=1):
        if not isinstance(item, dict):
            continue
        metadata = dict(item.get("metadata") or {})
        role = str(metadata.get("scientific_role") or "").strip()
        label = str(metadata.get("label") or "").strip()
        caption = _authoring_text(
            metadata.get("caption") or item.get("description") or "", role, "figure"
        )
        output = str(item.get("output_path") or "").strip()
        if any((role, label, caption, output)):
            figures.append({
                "id": f"figure_{role or 'asset'}_{index}", "scientific_role": role,
                "label": label, "caption": caption, "output_path": output,
                "source_path": _source_identity(item.get("source_path")),
                "source_sha256": _source_identity(item.get("source_sha256")),
                "visible_scope": _figure_scope(metadata),
                "source_data": [str(value) for value in metadata.get("source_data") or []
                                if str(value).strip()],
            })
    return figures


def _source_identity(value: Any) -> str:
    """Expose only the canonical declaration; missing proof is never reconstructed."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("Authoring figure source identity must be a declared string")
    return value


def _figure_scope(metadata: dict[str, Any]) -> dict[str, Any]:
    """Preserve the native compiler's bounded projection, not the full research scene."""
    compiler = metadata.get("architecture_compiler")
    if compiler is None:
        return {}
    if not isinstance(compiler, dict):
        raise ValueError("Authoring figure compiler scope must be an object")
    lists = ("covered_component_ids", "excluded_component_ids")
    counts = ("rendered_node_count", "rendered_relation_count")
    if any(name not in compiler for name in (*lists, *counts)):
        raise ValueError("Authoring figure compiler scope is incomplete")
    result = {}
    for name in lists:
        values = compiler[name]
        if (not isinstance(values, list) or len(values) > 256
                or any(not isinstance(value, str) or not value.strip() or len(value) > 256 for value in values)
                or len(set(values)) != len(values)):
            raise ValueError("Authoring figure compiler identifiers are malformed or unbounded")
        result[name] = list(values)
    for name in counts:
        value = compiler[name]
        if type(value) is not int or not 0 <= value <= 1024:
            raise ValueError("Authoring figure compiler counts must be bounded non-negative integers")
        result[name] = value
    if (set(result[lists[0]]) & set(result[lists[1]])
            or result["rendered_node_count"] != len(result["covered_component_ids"])):
        raise ValueError("Authoring figure compiler scope has contradictory visible identities")
    return result


def _authoring_tables(payload: dict[str, Any]) -> list[dict[str, Any]]:
    tables = []
    for index, item in enumerate(payload.get("tables") or [], start=1):
        if not isinstance(item, dict):
            continue
        if item.get("paper_selected") is False or item.get("manuscript_eligible") is False:
            continue
        role = str(item.get("scientific_role") or "").strip()
        label = str(item.get("label") or "").strip()
        caption = _authoring_text(item.get("caption") or "", role, "table")
        latex_path = str(item.get("latex_path") or "").strip()
        if any((role, label, caption, latex_path)):
            tables.append({
                "id": f"table_{role or 'asset'}_{index}", "scientific_role": role,
                "label": label, "caption": caption, "latex_path": latex_path,
                "data_path": str(item.get("data_path") or "").strip(),
                "rows": int(item.get("rows") or 0),
                "uncertainty_encoding": _authoring_text(
                    item.get("uncertainty_encoding") or "", role, "uncertainty"
                ),
                "public_notes": [{
                    "note_number": note.get("note_number"), "row_label": note.get("row_label"),
                    "column_label": note.get("column_label"), "text": note.get("original_public_text"),
                    "display_reference": note.get("display_reference"),
                } for note in (item.get("publication_projection") or {}).get("notes") or []
                    if isinstance(note, dict)],
            })
    return tables


def _authoring_text(value: Any, role: str, kind: str) -> str:
    cleaned = " ".join(str(value or "").split())
    denied = (*FORBIDDEN_RENDERED_SIMULATION_LABELS, "preview", "placeholder",
              "not evidence", "visibly marked")
    if cleaned and not any(marker.casefold() in cleaned.casefold() for marker in denied):
        return cleaned
    if kind == "uncertainty":
        return "Registered condition-dependent 95% uncertainty interval."
    fallbacks = {
        "result": "Primary comparison with uncertainty intervals.",
        "ablation": "Controlled component analysis with uncertainty intervals.",
        "training_dynamics": "Training dynamics with uncertainty bands.",
        "robustness": "Robustness and sensitivity analysis.",
        "error_analysis": "Error-slice analysis with uncertainty intervals.",
        "calibration": "Calibration and selective-risk analysis.",
        "efficiency": "Performance and resource-efficiency analysis.",
        "method": "Method architecture and mechanism flow.",
        "evaluation_design": "Evaluation design and analysis units.",
    }
    return fallbacks.get(role, "Registered scientific figure." if kind == "figure"
                         else "Registered scientific table.")
