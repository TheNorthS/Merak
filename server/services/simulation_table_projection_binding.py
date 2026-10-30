"""Verify paper-owned layout projections without rebinding frozen simulation science.

A projection binds the immutable original bundle/data/figure identities and the
exact derived LaTeX. Consumers are read-only; only the table producer creates
this current-schema record after checking every original source row.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PUBLICATION_BINDING = "paper/tables/SIMULATION_TABLE_PUBLICATION.json"
SIMULATION_MANIFEST = "experiments/results/simulated/SIMULATION_MANIFEST.json"
CANONICAL_TABLE = "paper/tables/synthetic_preview_results.tex"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _source_hashes(payload: dict[str, Any]) -> dict[str, str]:
    result = {item["path"]: item["sha256"] for item in payload["data_files"]}
    for item in payload["figure_files"]:
        result[item["source"]] = item["source_sha256"]
        result.update({relative: item["output_sha256"][kind] for kind, relative in item["outputs"].items()})
    return result


def authenticated_projection_source(root: Path, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Authenticate prior source/bytes only; never certify current rendering or acceptance."""
    root = root.resolve()
    if payload.get("paper_table") != CANONICAL_TABLE:
        raise ValueError("Simulation table projection path is not canonical")
    table = root / CANONICAL_TABLE
    digest = _sha(table.read_bytes())
    if digest == payload.get("paper_table_sha256"):
        return None
    path = root / PUBLICATION_BINDING
    try:
        record = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("SIMULATION_MANIFEST.paper_table_sha256 differs from paper/tables/synthetic_preview_results.tex; its paper-owned projection proof is missing or invalid") from error
    if not isinstance(record, dict):
        raise ValueError("Simulation table projection proof must be an object")
    if (record.get("source_table_sha256") != payload.get("paper_table_sha256")
            or not isinstance(record.get("source_table_text"), str)
            or _sha(record["source_table_text"].encode("utf-8")) != payload.get("paper_table_sha256")):
        raise ValueError("SIMULATION_MANIFEST.paper_table_sha256 conflicts with the immutable source_table_sha256 or source_table_text in its paper projection proof")
    if (not isinstance(record, dict) or record.get("schema") != 1
            or record.get("producer") != "simulation-table-publication"
            or record.get("simulation_manifest") != SIMULATION_MANIFEST
            or record.get("simulation_manifest_sha256") != _sha((root / SIMULATION_MANIFEST).read_bytes())
            or record.get("source_table_sha256") != payload.get("paper_table_sha256")
            or not isinstance(record.get("source_table_text"), str)
            or _sha(record["source_table_text"].encode("utf-8")) != payload.get("paper_table_sha256")
            or record.get("latex_path") != CANONICAL_TABLE or record.get("latex_sha256") != digest
            or record.get("source_hashes") != _source_hashes(payload)):
        raise ValueError("Simulation paper table projection binding is missing, stale or foreign")
    for relative, expected in record["source_hashes"].items():
        source = (root / relative).resolve()
        if not source.is_relative_to(root) or _sha(source.read_bytes()) != expected:
            raise ValueError("Simulation paper table projection scientific source changed")
    return record


def verify_simulation_table_projection(root: Path, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Accept original bytes or an exact CURRENT source-bound producer projection."""
    record = authenticated_projection_source(root, payload)
    if record is not None:
        from .simulation_table_publication import _verify_bound_projection

        _verify_bound_projection(root, payload, (root / CANONICAL_TABLE).read_bytes().decode("utf-8-sig"), record)
    return record


def table_projection_record(root: Path, payload: dict[str, Any], text: bytes, original: bytes,
                            contribution: str, renderer_digest: str) -> dict[str, Any]:
    """Record verified layout provenance without changing its scientific manifest."""
    from .simulation_primary_table import primary_comparison_panels, needs_primary_matrix, panel_binding
    from .simulation_table_publication import _csv
    from .simulation_table_portfolio import simulation_table_bindings_from_manifest

    primary = next(item for item in simulation_table_bindings_from_manifest(payload, contribution)
                   if item.stable_role == "main_comparison")
    rows = _csv(root, primary.data_path)
    panels = primary_comparison_panels(rows, primary.label) if needs_primary_matrix(rows) else ()
    from .simulation_calibration_table import calibration_panels, has_dataset_calibration
    coverage = next((item for item in simulation_table_bindings_from_manifest(payload, contribution)
                     if item.stable_role == "calibration_risk_coverage"), None)
    coverage_rows = _csv(root, coverage.data_path) if coverage else []
    coverage_panels = calibration_panels(coverage_rows, coverage.label) if has_dataset_calibration(coverage_rows) else ()
    return {"schema": 1, "producer": "simulation-table-publication", "contribution_type": contribution,
            "simulation_manifest": SIMULATION_MANIFEST,
            "simulation_manifest_sha256": _sha((root / SIMULATION_MANIFEST).read_bytes()),
            "source_table_sha256": payload["paper_table_sha256"], "latex_path": CANONICAL_TABLE,
            "source_table_text": original.decode("utf-8"),
            "latex_sha256": _sha(text), "renderer_sha256": renderer_digest,
            "source_hashes": _source_hashes(payload),
            "primary_panels": [{"label": panel.label, **panel_binding(panel)} for panel in panels],
            "calibration_panels": [{"label": label, "source_row_indices": list(indices)}
                                   for label, indices in coverage_panels],
            "scientific_rows_recomputed": False}
