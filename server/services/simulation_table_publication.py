"""Prepare source-bound public-label repairs on current simulation table pixels.

Only textual table projections and runtime hash attestations change. Frozen CSV
values, seeds, roles, source scripts and figure variants are never executed or
rewritten. Unsupported layouts or stale bundle hashes fail before any mutation.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paper_table_source_labels import selected_table_source_records
from .publication_labels import publication_metric_label, publication_metric_axis_label
from .semantic_table import _escape
from .simulation_publication_attestation import _current_bundle, _registration_updates
from .simulation_table_portfolio import simulation_table_bindings_from_manifest
from .simulation_publication_names import named_focal_caption
from .simulation_score_label import scenario_score_label


@dataclass(frozen=True)
class SimulationTablePublicationUpdate:
    files: dict[str, bytes]
    source_hashes: dict[str, str]


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _renderer_digest() -> str:
    from .figure_producer_fingerprint import loaded_module_digest

    digest = hashlib.sha256()
    for module in ("simulation_table_publication", "simulation_table_portfolio",
                   "simulation_publication_names", "paper_table_source_labels", "publication_labels", "semantic_table",
                   "simulation_primary_table", "simulation_calibration_table", "simulation_robustness_table",
                   "simulation_interval_caption", "simulation_score_label"):
        digest.update(module.encode("utf-8"))
        digest.update(loaded_module_digest(module, __package__))
    return digest.hexdigest()


def _caption_projection(root: Path, block: str, rows: list[dict[str, str]], field: str) -> str:
    record = next(iter(selected_table_source_records(block).values()))
    caption = record["caption"]
    if not re.search(r"\b(?:full method|full specification)\b", caption, re.IGNORECASE):
        return block
    focal = str(rows[0].get(field) or "").strip()
    selected = root / "ideas/SELECTED_IDEA.json"
    if selected.is_file():
        idea = json.loads(selected.read_text(encoding="utf-8-sig"))
        declared = str((idea.get("publication") or {}).get("method_name") or "").strip()
        if declared and focal != declared:
            raise ValueError("Simulation focal condition conflicts with its declared public method name")
    updated = named_focal_caption(caption, _escape(focal))
    return block.replace(caption, updated, 1)


def _csv(root: Path, relative: str) -> list[dict[str, str]]:
    with (root / relative).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _ablation_projection(block: str, rows: list[dict[str, str]], field: str) -> str:
    match = re.search(r"\\midrule(?P<body>.*?)\\bottomrule", block, re.DOTALL)
    if match is None:
        raise ValueError("Current simulation ablation table has an unsupported source layout")
    lines = [line for line in match.group("body").splitlines() if "&" in line]
    if len(lines) != len(rows):
        raise ValueError("Current simulation ablation table does not bind every frozen CSV row")
    body = []
    for line, row in zip(lines, rows):
        cells = re.split(r"(?<!\\)&", line)
        current = cells[0].strip()
        public = str(row.get(field) or "").strip()
        declared = str(row.get("changed_factor") or "").strip()
        if not public or current not in {_escape(public), _escape(declared),
                                         r"\textbf{" + _escape(public) + "}",
                                         r"\textbf{" + _escape(declared) + "}"}:
            raise ValueError("Current ablation public condition is not bound to its scientific CSV row")
        cells[0] = (r"\textbf{" + _escape(public) + "}" if current.startswith(r"\textbf{") else _escape(public)) + " "
        body.append("&".join(cells))
    return block[:match.start("body")] + "\n" + "\n".join(body) + "\n" + block[match.end("body"):]


def _public_table_text(root: Path, payload: dict[str, Any], contribution: str, text: str) -> str:
    bindings = simulation_table_bindings_from_manifest(payload, contribution)
    records = selected_table_source_records(text)
    expected = {binding.label for binding in bindings}
    primary = next(binding for binding in bindings if binding.stable_role == "main_comparison")
    extra = {label for label in records if any(re.fullmatch(re.escape(binding.label)
        + r"-panel-(?:[2-9]|[1-9][0-9]+)", label) for binding in bindings
        if binding.stable_role in {"main_comparison", "calibration_risk_coverage"})}
    if set(records) != expected | extra:
        raise ValueError("Current simulation source labels conflict with its selected contribution portfolio")
    primary_extra = {label for label in extra if label.startswith(primary.label + "-panel-")}
    text = _bounded_primary_projection(root, payload, primary, records, text, primary_extra)
    profiles = {item["stable_role"]: item for item in payload["domain_asset_profile"]}
    for binding in bindings:
        original = records[binding.label]["source"]
        updated = original
        profile = profiles[binding.stable_role]
        if binding.stable_role == "component_ablation":
            rows, field = _csv(root, binding.data_path), str(profile["axis_field"])
            updated = _ablation_projection(updated, rows, field)
            updated = _caption_projection(root, updated, rows, field)
        if binding.stable_role == "robustness_sensitivity":
            axis = str(profile["axis_field"])
            updated = updated.replace(_escape(axis), _escape(publication_metric_label(axis)))
            from .simulation_robustness_table import bounded_robustness_table
            updated = bounded_robustness_table(updated, _csv(root, binding.data_path), axis,
                publication_metric_label(axis), scenario_score_label(publication_metric_axis_label(payload["primary_metric"], payload["metric_direction"])))
        if binding.stable_role == "calibration_risk_coverage":
            text = _calibration_projection(root, binding, records, text, extra)
            continue
        text = text.replace(original, updated)
    from .simulation_interval_caption import scenario_table_captions
    return scenario_table_captions(text)


def _calibration_projection(root: Path, binding: Any, records: dict, text: str, extra: set[str]) -> str:
    from .simulation_calibration_table import (
        calibration_panels, has_dataset_calibration, render_dataset_calibration, validate_calibration_source,
    )

    rows = _csv(root, binding.data_path)
    panels_extra = {label for label in extra if label.startswith(binding.label + "-panel-")}
    if not has_dataset_calibration(rows):
        if panels_extra:
            raise ValueError("Generic calibration table has unsupported dataset continuation panels")
        return text
    panels = calibration_panels(rows, binding.label)
    expected = {label for label, _indices in panels}
    if panels_extra and expected != {binding.label} | panels_extra:
        raise ValueError("Calibration panel inventory differs from its complete source rows")
    labels = [label for label, _indices in panels] if panels_extra else [binding.label]
    blocks = [records[label]["source"] for label in labels]
    validate_calibration_source(blocks, rows)
    rendered = render_dataset_calibration(rows, binding.label, "Retained coverage", "Risk")
    source = "\n\n".join(blocks)
    if panels_extra:
        if source + "\n" != rendered:
            raise ValueError("Calibration panels differ from their exact current source-bound producer")
        return text
    return text.replace(blocks[0], rendered.rstrip("\n"), 1)


def _bounded_primary_projection(root: Path, payload: dict, binding: Any, records: dict,
                                text: str, extra: set[str]) -> str:
    from .simulation_primary_table import (
        needs_primary_matrix, primary_comparison_panels, primary_source_caption, render_primary_comparison_panels,
    )

    rows = _csv(root, binding.data_path)
    if not needs_primary_matrix(rows):
        if extra:
            raise ValueError("Primary table has unsupported continuation panels")
        return text
    panels = primary_comparison_panels(rows, binding.label)
    labels = {panel.label for panel in panels}
    original = records[binding.label]
    caption = primary_source_caption(original["source"], original["caption"])
    rendered = render_primary_comparison_panels(rows, scenario_score_label(publication_metric_axis_label(payload["primary_metric"], payload["metric_direction"])), caption, binding.label)
    from .simulation_interval_caption import SCOPE_NOTE, scenario_table_captions
    if SCOPE_NOTE in text:
        rendered = scenario_table_captions(rendered)
    old_labels = [binding.label, *sorted(extra, key=lambda label: int(label.rsplit('-panel-', 1)[1]))]
    current_blocks = [records[label]["source"] for label in old_labels] if extra else [original["source"]]
    if extra:
        from .primary_table_repanel import verify_primary_panel_cells
        verify_primary_panel_cells(current_blocks, rows)
        expected = selected_table_source_records(rendered)
        if labels == set(old_labels):
            for label, block in zip(old_labels, current_blocks):
                text = text.replace(block, expected[label]["source"], 1)
            return text
        for index, block in enumerate(current_blocks):
            text = text.replace(block, rendered.rstrip('\n') if index == 0 else '', 1)
        return text
    body = re.search(r"\\midrule(.*?)\\bottomrule", original["source"], re.DOTALL)
    lines = [line for line in body.group(1).splitlines() if "&" in line] if body else []
    if len(lines) != len(rows):
        raise ValueError("Current primary table does not bind every frozen source row")
    for line, row in zip(lines, rows):
        interval = _escape(f"{row['value']} [{row['ci_low']}, {row['ci_high']}]")
        if any(value not in line for value in (_escape(row["dataset"]), _escape(row["method"]), interval)):
            raise ValueError("Current primary table numeric row differs from its frozen evidence")
    return text.replace(original["source"], rendered.rstrip("\n"), 1)


def prepare_simulation_table_publication(root: Path, contribution_type: str) -> SimulationTablePublicationUpdate:
    """Prepare current-owner text/hash changes for the outer publication transaction."""
    from .figure_artifacts import figure_artifact_registry

    manifest = "experiments/results/simulated/SIMULATION_MANIFEST.json"
    if not (root / manifest).is_file():
        return SimulationTablePublicationUpdate({}, {})
    payload = _current_bundle(root)
    table = str(payload.get("paper_table") or "")
    if table != "paper/tables/synthetic_preview_results.tex" or not (root / table).is_file():
        raise ValueError("Current simulation publication table has an unsupported canonical source path")
    table_bytes, manifest_bytes = (root / table).read_bytes(), (root / manifest).read_bytes()
    from .simulation_table_projection_binding import authenticated_projection_source, table_projection_record, PUBLICATION_BINDING
    previous_projection = authenticated_projection_source(root, payload)
    original_table = (previous_projection["source_table_text"].encode("utf-8")
                      if previous_projection is not None else table_bytes)
    text = _public_table_text(root, payload, contribution_type, original_table.decode("utf-8-sig"))
    updated_table = text.encode("utf-8")
    if (previous_projection is not None and previous_projection.get("renderer_sha256") == _renderer_digest()
            and table_bytes != updated_table):
        raise ValueError("Existing paper table differs from its authenticated source under the current producer")
    if updated_table == table_bytes:
        return SimulationTablePublicationUpdate({}, {})
    registry_path = "figures/FIGURE_MANIFEST.json"
    registry = figure_artifact_registry.load(root / "figures", strict=True)
    if registry.get("schema") != 1:
        raise ValueError("Current simulation publication figure registry schema is unsupported")
    _registration_updates(root, payload, registry, _digest(manifest_bytes))
    record = table_projection_record(root, payload, updated_table, original_table, contribution_type, _renderer_digest())
    files = {table: updated_table, PUBLICATION_BINDING: (
        json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")}
    hashes = {table: _digest(table_bytes), manifest: _digest(manifest_bytes),
              registry_path: _digest((root / registry_path).read_bytes())}
    hashes.update({record["path"]: record["sha256"] for record in payload["data_files"]})
    for record in payload["figure_files"]:
        hashes[record["source"]] = record["source_sha256"]
        hashes.update({relative: record["output_sha256"][kind] for kind, relative in record["outputs"].items()})
    return SimulationTablePublicationUpdate(files, hashes)


def _verify_bound_projection(root: Path, payload: dict[str, Any], text: str, record: dict[str, Any]) -> None:
    from .simulation_primary_table import needs_primary_matrix, primary_comparison_panels, panel_binding
    bindings = simulation_table_bindings_from_manifest(payload, str(record.get("contribution_type") or ""))
    primary = next(item for item in bindings if item.stable_role == "main_comparison")
    rows = _csv(root, primary.data_path)
    panels = primary_comparison_panels(rows, primary.label) if needs_primary_matrix(rows) else ()
    expected = [{"label": panel.label, **panel_binding(panel)} for panel in panels]
    if record.get("primary_panels") != expected or record.get("scientific_rows_recomputed") is not False:
        raise ValueError("Simulation table projection lost its complete primary scientific row binding")
    from .simulation_calibration_table import calibration_panels, has_dataset_calibration
    coverage = next((item for item in bindings if item.stable_role == "calibration_risk_coverage"), None)
    coverage_rows = _csv(root, coverage.data_path) if coverage else []
    coverage_panels = calibration_panels(coverage_rows, coverage.label) if has_dataset_calibration(coverage_rows) else ()
    expected_coverage = [{"label": label, "source_row_indices": list(indices)} for label, indices in coverage_panels]
    if record.get("calibration_panels", []) != expected_coverage:
        raise ValueError("Simulation table projection lost its complete dataset-calibration row binding")
    if _public_table_text(root, payload, str(record["contribution_type"]), record["source_table_text"].lstrip("\ufeff")) != text:
        raise ValueError("Simulation table projection differs from its canonical source-bound producer")
