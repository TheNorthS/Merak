"""Verify one source-bound table's panels before sharing its prose interpretation.

Only the current primary-comparison producer can establish this relationship.
Labels, captions and registered hashes alone cannot waive an unrelated asset's
prose reference; every panel must reproduce its exact frozen source rows.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Sequence

from .paper_table_source_labels import selected_table_source_records
from .publication_labels import publication_metric_label, publication_metric_axis_label
from .simulation_policy import strip_latex_comments
from .simulation_primary_table import (
    PrimaryComparisonPanel, needs_primary_matrix, panel_binding,
    primary_comparison_panels, primary_source_caption, render_primary_comparison_panels,
)
from .simulation_table_portfolio import SimulationTableBinding, simulation_table_bindings_from_manifest
from .simulation_table_projection_binding import (
    CANONICAL_TABLE, SIMULATION_MANIFEST, verify_simulation_table_projection,
)


def _file(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"Primary table panel source is missing or outside the project: {relative}")
    return path


def _object(root: Path, relative: str) -> dict[str, Any]:
    try:
        value = json.loads(_file(root, relative).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Primary table panel binding is unreadable: {relative}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Primary table panel binding must be an object: {relative}")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _registered_panels(
    tables: list[dict[str, Any]], panels: tuple[PrimaryComparisonPanel, ...],
    binding: SimulationTableBinding, records: dict[str, dict[str, str]],
    data_sha256: str, latex_sha256: str,
) -> None:
    parent_id = "simulation_" + binding.stable_role
    entries = [item for item in tables if item.get("primary_panel_binding") is not None
               or str(item.get("id") or "").startswith(parent_id)
               or str(item.get("label") or "").startswith(binding.label)]
    if any(not isinstance(item.get("label"), str) or not isinstance(item.get("id"), str) for item in entries):
        raise ValueError("Primary table panel registration has an invalid identity")
    if len(entries) != len(panels) or {item.get("label") for item in entries} != {panel.label for panel in panels}:
        raise ValueError("Primary table panel registration is incomplete, duplicated or foreign")
    by_label = {item["label"]: item for item in entries}
    for number, panel in enumerate(panels, start=1):
        expected = {
            "id": parent_id if number == 1 else f"{parent_id}_panel_{number}",
            "label": panel.label, "latex_path": CANONICAL_TABLE, "data_path": binding.data_path,
            "data_sha256": data_sha256, "latex_sha256": latex_sha256,
            "rows": len(panel.source_row_indices), "primary_panel_binding": panel_binding(panel),
            "scientific_role": binding.scientific_role, "evidence_status": "synthetic_preview",
            "provenance_kind": "deterministic_simulation_preview", "source_data": [binding.data_path],
            "caption": records[panel.label]["caption"],
        }
        entry = by_label[panel.label]
        if (any(entry.get(key) != value for key, value in expected.items())
                or any(entry.get(key) is not True for key in ("paper_selected", "manuscript_eligible"))):
            raise ValueError(f"Primary table panel registration differs from its source-bound producer: {panel.label}")


def _exact_panel_sources(
    rows: list[dict[str, str]], panels: tuple[PrimaryComparisonPanel, ...],
    binding: SimulationTableBinding, payload: dict[str, Any], text: str,
    table_blocks: Sequence[str],
) -> dict[str, dict[str, str]]:
    records = selected_table_source_records(text)
    included = selected_table_source_records(strip_latex_comments("\n\n".join(table_blocks)))
    parent = records.get(binding.label)
    if parent is None:
        raise ValueError("Primary table panel parent has no current table source")
    metric = publication_metric_axis_label(payload["primary_metric"], payload["metric_direction"])
    from .simulation_score_label import scenario_score_label
    if scenario_score_label(metric) in parent['caption']:
        metric = scenario_score_label(metric)
    rendered = render_primary_comparison_panels(
        rows, metric,
        primary_source_caption(parent["source"], parent["caption"]), binding.label,
    )
    from .simulation_interval_caption import SCOPE_NOTE, scenario_table_captions
    if SCOPE_NOTE in text:
        rendered = scenario_table_captions(rendered)
    canonical = selected_table_source_records(rendered)
    effective_canonical = selected_table_source_records(strip_latex_comments(rendered))
    for panel in panels:
        if (records.get(panel.label) != canonical[panel.label]
                or included.get(panel.label) != effective_canonical[panel.label]):
            raise ValueError(f"Primary table panel is missing or differs from its exact current producer: {panel.label}")
    return records


def source_bound_primary_panel_parents(root: Path, table_blocks: Sequence[str]) -> dict[str, str]:
    """Return only complete, current producer-attested panel/parent relationships.

    Original simulation tables bind their exact manifest hash and are re-rendered
    from frozen CSV rows. Derived tables additionally require the current complete
    projection proof. This read-only contract never stamps hashes or edits assets.
    """
    root = root.resolve()
    if not table_blocks or not (root / "paper/tables/TABLE_MANIFEST.json").is_file():
        return {}
    manifest = _object(root, "paper/tables/TABLE_MANIFEST.json")
    tables = manifest.get("tables")
    if manifest.get("schema") != 3 or not isinstance(tables, list) or any(not isinstance(item, dict) for item in tables):
        raise ValueError("Primary table panel reference requires the current table manifest schema")
    if not any(item.get("primary_panel_binding") is not None for item in tables):
        return {}
    payload = _object(root, SIMULATION_MANIFEST)
    table = _file(root, CANONICAL_TABLE)
    try:
        proof = verify_simulation_table_projection(root, payload)
    except (OSError, UnicodeError, KeyError, TypeError, AttributeError) as error:
        raise ValueError("Primary table panel projection source is unreadable") from error
    publication = _object(root, "ideas/SELECTED_IDEA.json").get("publication")
    if not isinstance(publication, dict):
        raise ValueError("Primary table panels require the current selected publication contract")
    contribution = str(publication.get("contribution_type") or "")
    if proof is not None and proof.get("contribution_type") != contribution:
        raise ValueError("Primary table panel projection belongs to a different selected contribution")
    try:
        binding = next((item for item in simulation_table_bindings_from_manifest(payload, contribution)
                        if item.stable_role == "main_comparison"), None)
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Primary table panel simulation inventory is malformed") from error
    if binding is None:
        raise ValueError("Primary table panel parent is not selected by its current contribution")
    data = _file(root, binding.data_path)
    data_sha256 = _sha(data)
    registered_data = [item for item in payload.get("data_files") or []
                       if isinstance(item, dict) and item.get("path") == binding.data_path]
    if len(registered_data) != 1 or registered_data[0].get("sha256") != data_sha256:
        raise ValueError("Primary table panels no longer bind their frozen simulation CSV")
    from .simulation_table_publication import _csv
    rows = _csv(root, binding.data_path)
    if not needs_primary_matrix(rows):
        raise ValueError("Primary table panel registration has no source-grounded matrix partition")
    panels = primary_comparison_panels(rows, binding.label)
    records = _exact_panel_sources(rows, panels, binding, payload, table.read_text(encoding="utf-8-sig"), table_blocks)
    _registered_panels(tables, panels, binding, records, data_sha256, _sha(table))
    return {panel.label: binding.label for panel in panels[1:]}


def section_primary_panel_parents(root: Path, section_path: Path) -> dict[str, str]:
    """Verify panels from this section's actual reachable canonical table inputs.

    A sibling section, unused canonical file or copied table at another path
    cannot establish the input identity for the section currently under review.
    """
    from .latex_bundle import _reachable_sources

    root = root.resolve()
    sources = _reachable_sources(section_path, root / "paper", root)
    if (root / CANONICAL_TABLE).resolve() not in sources:
        return {}
    blocks = [block for source in sorted(sources)
              for block in re.findall(r"\\begin\{table\*?\}.*?\\end\{table\*?\}",
                                      source.read_text(encoding="utf-8-sig"), re.DOTALL)]
    return source_bound_primary_panel_parents(root, blocks)
