"""Pure calibration table projections preserve every population/coverage row."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import re

import pytest

from server.services.simulation_calibration_table import (
    DATASET_CAPTION, append_calibration_panel_entries, calibration_cells, calibration_panels,
    has_dataset_calibration, render_dataset_calibration,
)
from server.services.paper_table_source_labels import selected_table_source_records
from server.services.simulation_table_publication import prepare_simulation_table_publication
from server.services.simulation_table_projection_binding import (
    PUBLICATION_BINDING, verify_simulation_table_projection,
)
from server.tests.test_simulation_table_publication import _current


LABEL = "tab:preview-calibration"


def _rows(number=20):
    datasets = ("FACED", "SEED-V", "PhysioNet-MI", "SHU-MI", "ISRUC")
    coverages = ("0.50", "0.65", "0.80", "0.90", "1.00")
    return [{"dataset": datasets[index % 5], "method": f"Declared method {index // 5}",
        "coverage": coverages[index % 5], "risk": f"0.{index + 100:03}",
        "risk_ci_low": f"0.{index + 90:03}", "risk_ci_high": f"0.{index + 110:03}",
        "value": "0.030", "ci_low": "0.020", "ci_high": "0.040"}
        for index in range(number)]


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def test_risk_bounds_do_not_invent_a_confidence_level():
    rows = _rows(5)
    before = copy.deepcopy(rows)
    text = render_dataset_calibration(rows, LABEL, "Retained coverage", "Risk")
    assert "Scenario bounds" in text and "no confidence level" in text
    assert "Selective-risk coordinates" in text and "Calibration by" not in text
    assert "95" not in text.split(r"\midrule", 1)[0]
    assert rows == before
    for row in rows:
        assert f"[{row['risk_ci_low']}, {row['risk_ci_high']}]" in text


def _files(root):
    return {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _dataset_bundle(root, monkeypatch, number=20):
    manifest = _current(root, monkeypatch)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    rows = _rows(number)
    relative = "experiments/results/simulated/calibration.csv"
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    (root / relative).write_text(output.getvalue(), encoding="utf-8", newline="")
    for item in payload["data_files"]:
        if item["path"] == relative:
            item["sha256"] = _sha((root / relative).read_bytes())
    table = root / payload["paper_table"]
    records = selected_table_source_records(table.read_text(encoding="utf-8"))
    body = "\n".join(" & ".join(calibration_cells(row)[1:]) + r" \\" for row in rows)
    old = (r"\begin{table*}\caption{Retained-coverage versus risk curves with uncertainty bands.}"
        r"\label{" + LABEL + r"}\small\begin{tabularx}{\textwidth}{X c c c}\toprule"
        r"Method & Retained coverage & Selective risk & 95\% CI \\\midrule" + "\n"
        + body + "\n" + r"\bottomrule\end{tabularx}\end{table*}")
    table.write_text(table.read_text(encoding="utf-8").replace(records[LABEL]["source"], old), encoding="utf-8")
    payload["paper_table_sha256"] = _sha(table.read_bytes())
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    registry_path = root / "figures/FIGURE_MANIFEST.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    selected_ids = {entry["id"] for entry in registry["figures"]}
    for entry in registry["figures"]:
        entry["metadata"]["simulation_manifest_sha256"] = _sha(manifest.read_bytes())
        entry["metadata"]["paper_selected"] = entry["id"] in selected_ids
        if relative in entry["metadata"].get("source_data", []):
            entry["metadata"]["source_data_sha256"][relative] = _sha((root / relative).read_bytes())
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    return manifest, payload, rows


def test_joint_dataset_coverage_projection_retains_all_original_rows_and_intervals():
    rows, before = _rows(), copy.deepcopy(_rows())
    text = render_dataset_calibration(rows, LABEL, "Retained coverage", "Risk")
    records = selected_table_source_records(text)
    assert set(records) == {LABEL, LABEL + "-panel-2"}
    assert DATASET_CAPTION in text and "within-population coverage effect" in text
    assert "Dataset / task & Method & Retained coverage & Risk" in text
    assert "risk curves" not in text and "selective-risk curve" not in text
    for row in rows:
        expected = " & ".join(calibration_cells(row))
        assert text.count(expected) == 1
    assert rows == before
    assert not any(command in text for command in (r"\tiny", r"\scriptsize", r"\resizebox", r"\scalebox"))
    assert all(len(indices) <= 16 for _label, indices in calibration_panels(rows, LABEL))
    assert sorted(index for _label, indices in calibration_panels(rows, LABEL) for index in indices) == list(range(len(rows)))


def test_single_row_remainder_is_partitioned_without_one_row_standalone_table():
    assert [len(indices) for _label, indices in calibration_panels(_rows(17), LABEL)] == [15, 2]


@pytest.mark.parametrize("defect", ["missing_dataset", "blank_dataset", "mixed_dataset", "missing_risk_endpoint",
    "nonfinite", "bad_interval", "out_of_range_coverage"])
def test_invalid_dataset_or_mixed_numeric_metadata_is_blocked_without_guessing(defect):
    rows = _rows()
    if defect in {"missing_dataset", "mixed_dataset"}: rows[1].pop("dataset")
    elif defect == "blank_dataset": rows[1]["dataset"] = ""
    elif defect == "missing_risk_endpoint": rows[1].pop("risk_ci_high")
    elif defect == "nonfinite": rows[1]["risk"] = "nan"
    elif defect == "bad_interval": rows[1]["risk_ci_low"] = "0.9"
    else: rows[1]["coverage"] = "1.10"
    before = copy.deepcopy(rows)
    with pytest.raises(ValueError):
        render_dataset_calibration(rows, LABEL, "Retained coverage", "Risk")
    assert rows == before


def test_no_dataset_preserves_generic_path_and_value_interval_fallback_is_complete():
    generic = [{"method": "Declared method", "coverage": "0.5", "value": "0.1", "ci_low": "0.05", "ci_high": "0.15"}]
    assert has_dataset_calibration(generic) is False
    row = {**generic[0], "dataset": "Declared population"}
    assert calibration_cells(row) == ("Declared population", "Declared method", "0.5", "0.1", "[0.05, 0.15]")
    row["risk"] = "0.11"
    with pytest.raises(ValueError, match="complete interval"):
        calibration_cells(row)


def test_initial_simulation_table_producer_uses_identical_dataset_projection():
    from server.services.simulation_asset_profile import simulation_asset_profile
    from server.services.simulation_table_projection import simulation_tables
    profile = simulation_asset_profile({"study_archetype": "algorithm_benchmark"})
    profile["contribution_type"] = "objective_mechanism"
    profile.update(coverage_x_label="Retained coverage", coverage_y_label="Selective risk", slice_metric_axis_label="Error rate")
    field = profile["sensitivity_field"]
    main = [{"method": "Declared baseline", "value": "0.5", "ci_low": "0.4", "ci_high": "0.6",
        "secondary_value": "0.4", "stress_value": "0.3", "calibration_value": "0.1"}]
    ablation = [{field: "Declared focal method", "delta": "+0.000"}, {field: "Without registered component", "delta": "-0.010"}]
    efficiency = [{"method": "Declared focal method", **{f"resource_{index}": "0.5" for index in range(1, 6)}}]
    text = simulation_tables(main, ablation, [], _rows(), efficiency, [], [], [], "shift", "Macro-F1", profile, "maximize")
    records = selected_table_source_records(text)
    expected = selected_table_source_records(render_dataset_calibration(_rows(), LABEL, "Retained coverage", "Risk"))
    assert {identity: records[identity] for identity in expected} == expected


def test_publication_owner_upgrades_datasetless_original_without_changing_frozen_csv_or_manifest(tmp_path, monkeypatch):
    manifest, payload, rows = _dataset_bundle(tmp_path, monkeypatch)
    before = _files(tmp_path)
    update = prepare_simulation_table_publication(tmp_path, "objective_mechanism")
    text = update.files[payload["paper_table"]].decode("utf-8")
    records = selected_table_source_records(text)
    for row in rows:
        assert " & ".join(calibration_cells(row)) in text
    assert "Dataset / task" in records[LABEL]["source"]
    assert _files(tmp_path) == before
    for relative, raw in update.files.items():
        (tmp_path / relative).write_bytes(raw)
    assert manifest.read_bytes() == before[manifest]
    assert all((tmp_path / item["path"]).read_bytes() == before[tmp_path / item["path"]] for item in payload["data_files"])
    verify_simulation_table_projection(tmp_path, payload)
    assert prepare_simulation_table_publication(tmp_path, "objective_mechanism").files == {}


def test_old_authenticated_projection_is_not_consumer_accepted_but_owner_can_reproject_exact_source(tmp_path, monkeypatch):
    import server.services.simulation_calibration_table as calibration
    manifest, payload, _rows_value = _dataset_bundle(tmp_path, monkeypatch)
    with monkeypatch.context() as old_fixture:
        old_fixture.setattr(calibration, "has_dataset_calibration", lambda _rows_value: False)
        prior = prepare_simulation_table_publication(tmp_path, "objective_mechanism")
    for relative, raw in prior.files.items():
        (tmp_path / relative).write_bytes(raw)
    before = _files(tmp_path)
    with pytest.raises(ValueError, match="canonical source-bound producer|dataset-calibration row binding"):
        verify_simulation_table_projection(tmp_path, payload)
    fresh = prepare_simulation_table_publication(tmp_path, "objective_mechanism")
    assert _files(tmp_path) == before
    for relative, raw in fresh.files.items():
        (tmp_path / relative).write_bytes(raw)
    verify_simulation_table_projection(tmp_path, payload)
    assert manifest.read_bytes() == before[manifest]


@pytest.mark.parametrize("defect", ["wrong_risk", "row_omission", "extra_row", "wrong_dataset", "tampered_proof_source"])
def test_owner_refuses_mutated_source_rows_or_forged_projection_before_writes(tmp_path, monkeypatch, defect):
    manifest, payload, _rows_value = _dataset_bundle(tmp_path, monkeypatch)
    table = tmp_path / payload["paper_table"]
    update = prepare_simulation_table_publication(tmp_path, "objective_mechanism")
    for relative, raw in update.files.items():
        (tmp_path / relative).write_bytes(raw)
    proof = json.loads((tmp_path / PUBLICATION_BINDING).read_text(encoding="utf-8"))
    text = table.read_text(encoding="utf-8")
    row = " & ".join(calibration_cells(_rows_value[0]))
    if defect == "wrong_risk": text = text.replace(row, row.replace("0.100", "0.999"), 1)
    elif defect == "row_omission": text = text.replace(row + r" \\", "", 1)
    elif defect == "extra_row": text = text.replace(row + r" \\", row + r" \\" + "\n" + row + r" \\", 1)
    elif defect == "wrong_dataset": text = text.replace(row, row.replace("FACED", "Invented population"), 1)
    else: proof["source_table_text"] += "forged"
    table.write_text(text, encoding="utf-8")
    proof["latex_sha256"] = _sha(table.read_bytes())
    (tmp_path / PUBLICATION_BINDING).write_text(json.dumps(proof), encoding="utf-8")
    before = _files(tmp_path)
    with pytest.raises(ValueError):
        prepare_simulation_table_publication(tmp_path, "objective_mechanism")
    assert _files(tmp_path) == before and manifest.read_bytes() == before[manifest]


def test_panel_registration_binds_exact_row_indices_and_does_not_waive_prose_references():
    rows = _rows()
    records = selected_table_source_records(render_dataset_calibration(rows, LABEL, "Retained coverage", "Risk"))
    entries = [{"id": "simulation_calibration_risk_coverage", "label": LABEL, "rows": len(rows)}]
    append_calibration_panel_entries(entries, rows, LABEL, records)
    assert [entry["rows"] for entry in entries] == [16, 4]
    assert [index for entry in entries for index in entry["calibration_panel_binding"]["source_row_indices"]] == list(range(20))
    assert all(entry["calibration_panel_binding"]["scientific_rows_recomputed"] is False for entry in entries)
    assert not any("prose_reference_shared" in entry for entry in entries)


def test_caption_links_do_not_resolve_calibration_panel_prose_obligation_or_hide_exact_results_owner(tmp_path):
    from types import SimpleNamespace
    from server.services.paper_complete_validation import _reference_issues
    from server.services.paper_consistency_findings import complete_consistency_findings
    from server.services.paper_prose_references import asset_prose_reference_keys
    from server.workflows import paper_acceptance_checks_3 as checks

    table_dir = tmp_path / "paper/tables"
    table_dir.mkdir(parents=True)
    rows = _rows()
    table = render_dataset_calibration(rows, LABEL, "Coverage", "Risk")
    records = selected_table_source_records(table)
    (table_dir / "calibration.tex").write_text(table, encoding="utf-8")
    (table_dir / "TABLE_MANIFEST.json").write_text(json.dumps({"schema": 3, "tables": [{
        "label": label, "scientific_role": "calibration", "latex_path": "paper/tables/calibration.tex",
        "paper_selected": True, "manuscript_eligible": True} for label in records]}), encoding="utf-8")
    section = tmp_path / "paper/sections/05_results.tex"
    section.parent.mkdir()
    prose = r"Table~\ref{" + LABEL + r"} compares joint dataset and coverage rows." + "\n" + r"\input{tables/calibration}"
    section.write_text(prose, encoding="utf-8")
    combined = prose + "\n" + table
    issues = []
    paths = {"root": tmp_path, "paper": tmp_path / "paper", "sections": section.parent}
    labels, full_refs, citations = _reference_issues(paths, combined, issues)
    assert LABEL + "-panel-2" in full_refs
    assert any(LABEL + "-panel-2" in issue and "never referenced" in issue for issue in issues)
    body_refs = asset_prose_reference_keys(tmp_path, combined)
    assert LABEL in body_refs and LABEL + "-panel-2" not in body_refs
    specs = [SimpleNamespace(id="results", filename="05_results.tex")]
    findings = complete_consistency_findings(paths, specs, {"results": prose}, labels, full_refs, citations, {},
        prose_refs=body_refs)
    assert len(findings) == 1 and findings[0]["reference_key"] == LABEL + "-panel-2"
    assert findings[0]["target_files"] == ["paper/sections/05_results.tex"]
    context = SimpleNamespace(root=tmp_path, expanded_main=combined, declared_labels=list(records),
        table_blocks=[item["source"] for item in records.values()], problems=[],
        discussion_terms=re.compile("compares"))
    checks.remove_float_blocks(context)
    checks.compile_reference_pattern(context)
    context.reference_matches = list(context.reference_command_re.finditer(context.prose_only))
    checks.validate_asset_discussion(context)
    assert any(LABEL + "-panel-2" in issue and "never referenced" in issue for issue in context.problems)


def test_undefined_caption_links_still_receive_full_source_reference_audit(tmp_path):
    from server.services.paper_complete_validation import _reference_issues

    (tmp_path / "paper").mkdir()
    text = r"\begin{table}\caption{See Table~\ref{tab:missing}}\label{tab:present}\end{table}"
    issues = []
    _reference_issues({"root": tmp_path, "paper": tmp_path / "paper"}, text, issues)
    assert "undefined references: tab:missing" in issues
    assert any("never referenced" in issue and "tab:present" in issue for issue in issues)


def test_calibration_partition_metadata_cannot_be_forged_by_resigning_runtime_proof(tmp_path, monkeypatch):
    _manifest, payload, _rows_value = _dataset_bundle(tmp_path, monkeypatch)
    update = prepare_simulation_table_publication(tmp_path, "objective_mechanism")
    for relative, raw in update.files.items():
        (tmp_path / relative).write_bytes(raw)
    path = tmp_path / PUBLICATION_BINDING
    proof = json.loads(path.read_text(encoding="utf-8"))
    assert proof["calibration_panels"][0]["source_row_indices"] == list(range(16))
    proof["calibration_panels"][0]["source_row_indices"] = list(range(15))
    path.write_text(json.dumps(proof), encoding="utf-8")
    with pytest.raises(ValueError, match="dataset-calibration row binding"):
        verify_simulation_table_projection(tmp_path, payload)


@pytest.mark.asyncio
async def test_actual_resume_refresh_orders_real_table_owner_before_strict_consumer_without_science_mutation(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from server.services import simulation_calibration_table as calibration
    from server.services import simulation_figure_refresh as figure_refresh
    from server.services.simulation_paper_projection import _projection, refresh_simulation_paper_projection
    from server.workflows.simulation_render_refresh import refresh_simulation_renderer

    manifest, payload, _rows_value = _dataset_bundle(tmp_path, monkeypatch)
    idea = tmp_path / "ideas/SELECTED_IDEA.json"
    idea.parent.mkdir(exist_ok=True)
    idea.write_text(json.dumps({"schema": 2, "title": "Declared fixture benchmark",
        "publication": {"contribution_type": "objective_mechanism"}}), encoding="utf-8")
    include = tmp_path / "paper/synthetic_preview_figures.tex"
    registry_path = tmp_path / "figures/FIGURE_MANIFEST.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    entries = {entry["id"]: entry for entry in registry["figures"]}
    for index, record in enumerate(payload["figure_files"]):
        record["label"] = "fig:declared-fixture-" + str(index)
        entries[record["id"]]["metadata"]["label"] = record["label"]
    canonical_include, selected_ids = _projection(tmp_path, payload, entries)
    include.write_bytes(canonical_include.encode("utf-8"))
    payload["paper_figures"] = "paper/synthetic_preview_figures.tex"
    payload["paper_figures_sha256"] = _sha(include.read_bytes())
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    for entry in registry["figures"]:
        entry["metadata"]["simulation_manifest_sha256"] = _sha(manifest.read_bytes())
        entry["metadata"]["paper_selected"] = entry["id"] in selected_ids
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    with monkeypatch.context() as prior_code:
        prior_code.setattr(calibration, "has_dataset_calibration", lambda _rows_value: False)
        prior = prepare_simulation_table_publication(tmp_path, "objective_mechanism")
    for relative, raw in prior.files.items():
        (tmp_path / relative).write_bytes(raw)
    # This actual reader must reject old producer output before owner refresh.
    with pytest.raises(ValueError):
        refresh_simulation_paper_projection(tmp_path)
    before = {tmp_path / item["path"]: (tmp_path / item["path"]).read_bytes() for item in payload["data_files"]}
    manifest_before, idea_before = manifest.read_bytes(), idea.read_bytes()
    calls = []
    async def no_plot_execution(_root):
        return []
    async def emitted(_run, event, data):
        calls.append((event, data))
    monkeypatch.setattr(figure_refresh, "refresh_existing_simulation_figures", no_plot_execution)
    run = SimpleNamespace(project_path=str(tmp_path), options={"run_experiment": False,
        "non_experiment_evidence_mode": "synthetic_preview"}, checkpoint_node_id="paper")
    assert await refresh_simulation_renderer(SimpleNamespace(_emit=emitted), run, "Fixture-only scope") is True
    verify_simulation_table_projection(tmp_path, payload)
    assert manifest.read_bytes() == manifest_before and idea.read_bytes() == idea_before
    assert all(path.read_bytes() == raw for path, raw in before.items())
    table_manifest = json.loads((tmp_path / "paper/tables/TABLE_MANIFEST.json").read_text(encoding="utf-8"))
    calibration_entries = [entry for entry in table_manifest["tables"] if entry["scientific_role"] == "calibration"]
    assert len(calibration_entries) == 2
    assert [entry["rows"] for entry in calibration_entries] == [16, 4]
    assert calls and calls[0][1]["table_projection_changed"] is True
