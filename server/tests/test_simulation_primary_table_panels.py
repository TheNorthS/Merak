"""Bound primary panels preserve every immutable comparison and interval."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

import pytest

from server.services.paper_table_source_labels import selected_table_source_records
from server.services.simulation_primary_table import primary_comparison_panels, render_primary_comparison_panels
from server.services.simulation_table_publication import prepare_simulation_table_publication
from server.tests.test_simulation_table_publication import _current


LABEL = "tab:preview-main-results"


def _rows() -> list[dict[str, str]]:
    return [{"dataset": f"Dataset {dataset} / declared task", "method": f"Named matched condition {method} with a long registered objective",
             "value": f"0.{dataset}{method}5", "ci_low": f"0.{dataset}{method}1", "ci_high": f"0.{dataset}{method}9"}
            for method in range(8) for dataset in range(8)]


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _files(root: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_complete_64_row_matrix_has_bounded_panels_and_exact_estimates():
    rows = _rows()
    panels = primary_comparison_panels(rows, LABEL)
    text = render_primary_comparison_panels(rows, "Macro-F1", "Matched comparison", LABEL)
    records = selected_table_source_records(text)
    assert len(panels) == 8 and set(records) == {panel.label for panel in panels}
    assert all(len(panel.methods) <= 6 and len(panel.datasets) <= 2 for panel in panels)
    assert sorted(index for panel in panels for index in panel.source_row_indices) == list(range(64))
    for row in rows:
        assert text.count(f"{row['value']} [{row['ci_low']}, {row['ci_high']}]") == 1
    assert "\\small" in text and not any(token in text for token in ("\\tiny", "\\scriptsize", "\\resizebox", "\\scalebox"))
    for panel in panels:
        assert f"\\ref{{{panel.label}}}" in text
        body = re.search(r"\\midrule(.*?)\\bottomrule", records[panel.label]["source"], re.DOTALL).group(1)
        assert len([line for line in body.splitlines() if "&" in line]) <= 6
    assert rows == _rows()
    assert 'Planned condition &' in text and 'not a measured comparison of trained models' in text


def test_six_method_comparison_keeps_all_controls_together_per_task():
    rows = [row for row in _rows() if row['method'] in {item['method'] for item in _rows()[:48]}]
    panels = primary_comparison_panels(rows, LABEL)
    assert len(panels) == 4
    assert all(len(panel.methods) == 6 for panel in panels)
    assert sorted(index for panel in panels for index in panel.source_row_indices) == list(range(48))


@pytest.mark.parametrize('defect', ['', 'changed_value', 'duplicate', 'missing'])
def test_repanel_authenticates_all_original_cells(defect):
    from server.services.primary_table_repanel import verify_primary_panel_cells
    rows = _rows()
    text = render_primary_comparison_panels(rows, 'Macro-F1', 'Comparison', LABEL)
    blocks = [item['source'] for item in selected_table_source_records(text).values()]
    if defect == 'changed_value':
        blocks[0] = blocks[0].replace('0.005', '0.999')
    elif defect == 'duplicate':
        blocks.append(blocks[0])
    elif defect == 'missing':
        blocks.pop()
    if defect:
        with pytest.raises(ValueError):
            verify_primary_panel_cells(blocks, rows)
    else:
        verify_primary_panel_cells(blocks, rows)


def test_initial_simulation_table_producer_selects_the_same_bounded_primary_renderer():
    from server.services.simulation_asset_profile import simulation_asset_profile
    from server.services.simulation_table_projection import simulation_tables
    profile = simulation_asset_profile({"study_archetype": "algorithm_benchmark"})
    profile["contribution_type"] = "objective_mechanism"
    profile.update(coverage_x_label="Retained coverage", coverage_y_label="Selective risk", slice_metric_axis_label="Error rate")
    main = [{**row, "secondary_value": "0.500", "stress_value": "0.400", "calibration_value": "0.050"} for row in _rows()]
    field = profile["sensitivity_field"]
    ablation = [{field: "Named focal condition", "delta": "+0.000"}, {field: "Without named mechanism", "delta": "-0.012"}]
    efficiency = [{"method": "Named focal condition", **{f"resource_{index}": "0.5" for index in range(1, 6)}}]
    text = simulation_tables(main, ablation, [], [], efficiency, [], [], [], "shift", "Macro-F1", profile, "maximize")
    records = selected_table_source_records(text)
    panels = primary_comparison_panels(main, LABEL)
    assert {panel.label for panel in panels} <= set(records)
    assert len([label for label in records if label.startswith(LABEL)]) == 8
    assert all(text.count(f"{row['value']} [{row['ci_low']}, {row['ci_high']}]") == 1 for row in main)
    assert main == [{**row, "secondary_value": "0.500", "stress_value": "0.400", "calibration_value": "0.050"} for row in _rows()]


@pytest.mark.parametrize("defect", ["missing", "duplicate", "interval", "nonfinite", "long_label"])
def test_invalid_registered_matrix_is_not_padded_or_silently_subtracted(defect):
    rows = _rows()
    if defect == "missing":
        rows.pop()
    elif defect == "duplicate":
        rows.append(dict(rows[0]))
    elif defect == "interval":
        rows[0]["ci_low"] = "1.000"
    elif defect == "nonfinite":
        rows[0]["value"] = "nan"
    else:
        rows[0]["method"] = "A" * 181
    with pytest.raises(ValueError):
        primary_comparison_panels(rows, LABEL)


def _legacy_bundle(root, monkeypatch) -> Path:
    manifest = _current(root, monkeypatch)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["primary_metric"] = "macro_f1"
    payload["metric_direction"] = "maximize"
    data = root / "experiments/results/simulated/main_comparison.csv"
    rows = _rows()
    with data.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    table = root / payload["paper_table"]
    text = table.read_text(encoding="utf-8")
    original = selected_table_source_records(text)[LABEL]["source"]
    body = "\n".join(" & ".join((row["dataset"], row["method"], f"{row['value']} [{row['ci_low']}, {row['ci_high']}]")) + r" \\" for row in rows)
    replacement = r"\begin{table*}\caption{Primary comparison}\label{" + LABEL + r"}\small\midrule" + "\n" + body + r"\bottomrule\end{table*}"
    table.write_bytes(text.replace(original, replacement).encode("utf-8"))
    for record in payload["data_files"]:
        record["sha256"] = _sha((root / record["path"]).read_bytes())
    payload["paper_table_sha256"] = _sha(table.read_bytes())
    manifest.write_bytes(json.dumps(payload).encode("utf-8"))
    registry = root / "figures/FIGURE_MANIFEST.json"
    figures = json.loads(registry.read_text(encoding="utf-8"))
    for entry in figures["figures"]:
        entry["metadata"]["simulation_manifest_sha256"] = _sha(manifest.read_bytes())
        for relative in entry["metadata"]["source_data"]:
            entry["metadata"]["source_data_sha256"][relative] = _sha((root / relative).read_bytes())
    registry.write_bytes(json.dumps(figures).encode("utf-8"))
    planned = root / "experiments/results/templates/PLANNED_RESULT_MANIFEST.json"
    planned.parent.mkdir(parents=True, exist_ok=True)
    planned.write_bytes(json.dumps({"schema": 5, "simulation_manifest": manifest.relative_to(root).as_posix(),
                                   "simulation_manifest_sha256": _sha(manifest.read_bytes()), "figures": figures["figures"]}).encode("utf-8"))
    return manifest


def test_current_owner_reprojects_only_derived_sources_and_hash_bindings(tmp_path, monkeypatch):
    manifest = _legacy_bundle(tmp_path, monkeypatch)
    before = _files(tmp_path)
    update = prepare_simulation_table_publication(tmp_path, "objective_mechanism")
    table = "paper/tables/synthetic_preview_results.tex"
    records = selected_table_source_records(update.files[table].decode("utf-8"))
    assert {panel.label for panel in primary_comparison_panels(_rows(), LABEL)} <= set(records)
    assert _files(tmp_path) == before
    for relative, content in update.files.items():
        (tmp_path / relative).write_bytes(content)
    protected = {path: content for path, content in before.items() if path.relative_to(tmp_path).as_posix() not in update.files}
    assert all(path.read_bytes() == content for path, content in protected.items())
    assert prepare_simulation_table_publication(tmp_path, "objective_mechanism").files == {}
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    from server.services.planned_simulation_bindings import load_planned_simulation_binding
    load_planned_simulation_binding(tmp_path, _sha(manifest.read_bytes()), payload["figure_files"])


def test_registration_binds_every_panel_to_exact_source_row_indices(tmp_path, monkeypatch):
    _legacy_bundle(tmp_path, monkeypatch)
    update = prepare_simulation_table_publication(tmp_path, "objective_mechanism")
    for relative, content in update.files.items():
        (tmp_path / relative).write_bytes(content)
    from server.services.paper_evidence import PaperEvidence
    from server.services.paper_submission_tables import _synthetic_preview_entries
    from server.services.paper_artifacts import build_table_manifest
    evidence = PaperEvidence(tmp_path, "Study", "", "", "", "", "", "",
                             asset_plan={"evidence_mode": "synthetic_preview"},
                             selected_idea={"publication": {"contribution_type": "objective_mechanism"}})
    records = _synthetic_preview_entries(evidence, tmp_path / "paper/tables")
    primary = [record for record in records if record["id"].startswith("simulation_main_comparison")]
    assert len(primary) == 8 and sorted(index for record in primary for index in record["primary_panel_binding"]["source_row_indices"]) == list(range(64))
    bound = build_table_manifest(tmp_path, records)
    assert all(record["data_sha256"] == _sha((tmp_path / record["data_path"]).read_bytes()) for record in bound["tables"])


@pytest.mark.parametrize("defect", ["row", "value", "missing_panel", "stray_panel"])
def test_current_row_or_panel_drift_is_rejected_before_any_projection_write(tmp_path, monkeypatch, defect):
    manifest = _legacy_bundle(tmp_path, monkeypatch)
    table = tmp_path / "paper/tables/synthetic_preview_results.tex"
    if "panel" in defect:
        update = prepare_simulation_table_publication(tmp_path, "objective_mechanism")
        for relative, content in update.files.items():
            (tmp_path / relative).write_bytes(content)
        text = table.read_text(encoding="utf-8")
        if defect == "missing_panel":
            block = selected_table_source_records(text)[LABEL + "-panel-2"]["source"]
            text = text.replace(block, "")
        else:
            text += r"\begin{table*}\caption{Foreign panel}\label{" + LABEL + r"-panel-99}\midrule A & 0.1\\B & 0.2\\\bottomrule\end{table*}"
    else:
        text = table.read_text(encoding="utf-8")
        text = text.replace("0.005 [0.001, 0.009]", "0.005 [0.001, 0.008]") if defect == "value" else text.replace("Dataset 0 / declared task & ", "")
    table.write_bytes(text.encode("utf-8"))
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["paper_table_sha256"] = _sha(table.read_bytes())
    manifest.write_bytes(json.dumps(payload).encode("utf-8"))
    before = _files(tmp_path)
    with pytest.raises((ValueError, OSError)):
        prepare_simulation_table_publication(tmp_path, "objective_mechanism")
    assert _files(tmp_path) == before


@pytest.mark.parametrize("defect", ["missing", "table_hash", "source_table", "data_hash", "manifest_hash", "foreign_path", "numeric_rebind", "extra_row"])
def test_paper_projection_proof_cannot_forge_scientific_values_or_foreign_identity(tmp_path, monkeypatch, defect):
    manifest = _legacy_bundle(tmp_path, monkeypatch)
    update = prepare_simulation_table_publication(tmp_path, "objective_mechanism")
    for relative, content in update.files.items():
        (tmp_path / relative).write_bytes(content)
    from server.services.simulation_table_projection_binding import PUBLICATION_BINDING, verify_simulation_table_projection
    proof_path = tmp_path / PUBLICATION_BINDING
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    table = tmp_path / proof["latex_path"]
    if defect == "missing":
        proof_path.unlink()
    elif defect in {"numeric_rebind", "extra_row"}:
        text = table.read_text(encoding="utf-8")
        text = text.replace("0.005 [0.001, 0.009]", "0.006 [0.001, 0.009]") if defect == "numeric_rebind" else text.replace(r"\bottomrule", r"Invented & 0.7 [0.6, 0.8] & 0.5 [0.4, 0.6]\\\bottomrule", 1)
        table.write_bytes(text.encode("utf-8"))
        proof["latex_sha256"] = _sha(table.read_bytes())
        proof_path.write_bytes(json.dumps(proof).encode("utf-8"))
    else:
        key, value = {"table_hash": ("latex_sha256", "0" * 64), "source_table": ("source_table_text", "Invented old table"),
                      "data_hash": ("source_hashes", {}), "manifest_hash": ("simulation_manifest_sha256", "0" * 64),
                      "foreign_path": ("latex_path", "../outside.tex")}[defect]
        proof[key] = value
        proof_path.write_bytes(json.dumps(proof).encode("utf-8"))
    before = _files(tmp_path)
    with pytest.raises((ValueError, OSError)):
        verify_simulation_table_projection(tmp_path, json.loads(manifest.read_text(encoding="utf-8")))
    assert _files(tmp_path) == before


def test_zero_original_paper_table_hash_is_rejected_with_exact_scientific_binding_field(tmp_path, monkeypatch):
    manifest = _legacy_bundle(tmp_path, monkeypatch)
    update = prepare_simulation_table_publication(tmp_path, "objective_mechanism")
    for relative, content in update.files.items():
        (tmp_path / relative).write_bytes(content)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["paper_table_sha256"] = "0" * 64
    manifest.write_bytes(json.dumps(payload).encode("utf-8"))
    before = _files(tmp_path)
    from server.services.simulation_table_projection_binding import verify_simulation_table_projection
    with pytest.raises(ValueError, match="paper_table_sha256"):
        verify_simulation_table_projection(tmp_path, payload)
    assert _files(tmp_path) == before
