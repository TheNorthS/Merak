"""Long source-owned public text becomes full prose, never truncation or partial writes."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from server.services.paper_evidence import PaperEvidence, _latex
from server.services.paper_submission_tables import write_submission_tables
from server.services.semantic_table import (
    MAX_PUBLIC_TABLE_CELL_CHARACTERS, ScientificTableSpec, TableColumn,
    SemanticTableContractError, compile_scientific_table,
)


LONG_EVALUATION = (
    "Compare restricted and unrestricted task readouts under the same frozen data, seeds, "
    "capacity, and optimization budget; reject the mechanism claim if any apparent advantage "
    "depends on source-state task access."
)


def _evidence(root: Path, *, long: bool = True, count: int = 2) -> PaperEvidence:
    selected = {"schema": 2, "mechanisms": [
        {"id": f"M{index + 1}", "name": f"Internal mechanism {index + 1}",
         "description": "Internal implementation bookkeeping must never replace public wording.",
         "publication_name": "Restricted task readout" if index == 0 else "Shared representation",
         "publication_description": "Only the shared representation reaches the task head.",
         "publication_evaluation": LONG_EVALUATION if index == 0 and long else "Compare matched controls."}
        for index in range(count)
    ]}
    path = root / "ideas/SELECTED_IDEA.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(selected), encoding="utf-8")
    return PaperEvidence(
        root=root, title="Restricted representation", direction="", idea_text="", survey_text="",
        narrative_text="", plan_text="", analysis_text="", selected_idea=selected,
        run_spec={"seeds": [13, 42, 73], "datasets": ["Declared cohort"],
                  "tasks": ["Classification"], "models": ["Declared predictor"]},
    )


def _files(root: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in root.rglob("*")
            if path.is_file() and ".merak/transactions/" not in path.as_posix()}


def test_full_long_cell_moves_to_bound_out_of_float_prose_and_csv_equals_table(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    source = (tmp_path / "ideas/SELECTED_IDEA.json").read_bytes()
    write_submission_tables(evidence)
    table = tmp_path / "paper/tables/method_components.tex"
    text = table.read_text(encoding="utf-8")
    with (table.with_suffix(".csv")).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["component"] == "Restricted task readout"
    assert rows[0]["evaluation"] == "Initial comparison checklist details (Note 1)"
    assert all(len(value) <= MAX_PUBLIC_TABLE_CELL_CHARACTERS for row in rows for value in row.values())
    assert _latex(LONG_EVALUATION) in text
    assert text.index(_latex(LONG_EVALUATION)) > text.rindex(r"\end{table}")
    assert r"\label{note:method_components-note-1}" in text
    assert "Internal implementation bookkeeping" not in text
    manifest = json.loads((tmp_path / "paper/tables/TABLE_MANIFEST.json").read_text())
    entry = next(item for item in manifest["tables"] if item["id"] == "method_components")
    projection = entry["publication_projection"]
    assert projection["compact_rows"] == rows
    assert projection["notes"][0]["original_public_text"] == LONG_EVALUATION
    assert projection["notes"][0]["source_bindings"][0]["source_symbol"] == (
        "/mechanisms/0/publication_evaluation"
    )
    raw = json.loads((tmp_path / ".merak/paper-table-records/method_components.json").read_text())
    assert raw["records"][0]["component"] == "Internal mechanism 1"
    assert (tmp_path / "ideas/SELECTED_IDEA.json").read_bytes() == source
    before = _files(tmp_path)
    write_submission_tables(evidence)
    assert _files(tmp_path) == before


def test_short_public_cells_remain_exact_and_reviewed_layout_survives(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path, long=False)
    write_submission_tables(evidence)
    table = tmp_path / "paper/tables/method_components.tex"
    marker = r"\setlength{\tabcolsep}{3pt}"
    table.write_text(table.read_text().replace("\\small\n", "\\small\n" + marker + "\n"))
    write_submission_tables(evidence)
    assert marker in table.read_text()
    assert "Initial comparison checklist details" not in table.read_text()
    with table.with_suffix(".csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["evaluation"] == "Compare matched controls."


def test_changed_bounded_function_and_missing_note_reference_rebuilds_authoritative_source(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    write_submission_tables(evidence)
    table = tmp_path / "paper/tables/method_components.tex"
    text = table.read_text(encoding="utf-8")
    table.write_text(text.replace("Initial comparison checklist details (Note 1)", "Unbound replacement")
                     .replace("Only the shared representation reaches the task head.", "Lost restriction."), encoding="utf-8")
    write_submission_tables(evidence)
    repaired = table.read_text(encoding="utf-8")
    assert "Initial comparison checklist details (Note 1)" in repaired
    assert "Only the shared representation reaches the task head." in repaired
    assert _latex(LONG_EVALUATION) in repaired


@pytest.mark.parametrize("length", [180, 181])
def test_public_cell_boundary_preserves_all_characters_without_threshold_change(tmp_path, length):
    evidence = _evidence(tmp_path, long=False)
    wording = "X" * length
    evidence.selected_idea["mechanisms"][0]["publication_evaluation"] = wording
    (tmp_path / "ideas/SELECTED_IDEA.json").write_text(json.dumps(evidence.selected_idea))
    write_submission_tables(evidence)
    text = (tmp_path / "paper/tables/method_components.tex").read_text(encoding="utf-8")
    assert wording in text
    assert ("Initial comparison checklist details (Note 1)" in text) is (length > 180)


def test_missing_public_contract_rejects_before_canonical_writes(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    evidence.selected_idea["mechanisms"][0].pop("publication_evaluation")
    with pytest.raises(ValueError, match="missing publication_evaluation"):
        write_submission_tables(evidence)
    assert not (tmp_path / "paper/tables/TABLE_MANIFEST.json").exists()
    assert not (tmp_path / "paper/tables/study_design.csv").exists()


def test_late_table_validation_failure_leaves_every_canonical_file_unchanged(tmp_path, monkeypatch) -> None:
    evidence = _evidence(tmp_path)
    write_submission_tables(evidence)
    before = _files(tmp_path)
    from server.services import paper_submission_tables as producer

    def fail(*_args, **_kwargs):
        raise ValueError("late public table validation fixture")

    monkeypatch.setattr(producer, "_write_executed_tables", fail)
    with pytest.raises(ValueError, match="late public table validation"):
        write_submission_tables(evidence)
    assert _files(tmp_path) == before


def test_unowned_user_table_is_not_overwritten_by_stale_preparation_copy(tmp_path, monkeypatch) -> None:
    evidence = _evidence(tmp_path)
    write_submission_tables(evidence)
    unowned = tmp_path / "paper/tables/user_appendix.tex"
    unowned.write_text("Original user table.", encoding="utf-8")
    from server.services import paper_submission_tables as producer
    original = producer._write_executed_tables

    def mutate_user(*args, **kwargs):
        unowned.write_text("New user-owned table edit.", encoding="utf-8")
        return original(*args, **kwargs)

    monkeypatch.setattr(producer, "_write_executed_tables", mutate_user)
    write_submission_tables(evidence)
    assert unowned.read_text(encoding="utf-8") == "New user-owned table edit."


def test_concurrent_canonical_layout_change_is_not_overwritten(tmp_path, monkeypatch) -> None:
    evidence = _evidence(tmp_path)
    write_submission_tables(evidence)
    table = tmp_path / "paper/tables/method_components.tex"
    original_text = table.read_text(encoding="utf-8")
    from server.services import paper_submission_tables as producer
    original = producer._write_executed_tables

    def mutate_owned(*args, **kwargs):
        table.write_text(original_text + "% concurrent layout change\n", encoding="utf-8")
        return original(*args, **kwargs)

    monkeypatch.setattr(producer, "_write_executed_tables", mutate_owned)
    with pytest.raises(ValueError, match="Canonical table changed during preparation"):
        write_submission_tables(evidence)
    assert table.read_text(encoding="utf-8").endswith("% concurrent layout change\n")


@pytest.mark.parametrize("invalid", [[], {"schema": 2, "tables": []}, {"schema": 3, "tables": "bad"}])
def test_unsupported_existing_manifest_is_never_silently_rewritten(tmp_path, invalid) -> None:
    evidence = _evidence(tmp_path)
    manifest = tmp_path / "paper/tables/TABLE_MANIFEST.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps(invalid), encoding="utf-8")
    before = _files(tmp_path)
    with pytest.raises(ValueError, match="unsupported contract"):
        write_submission_tables(evidence)
    assert _files(tmp_path) == before


def test_commit_failure_rolls_back_csv_latex_notes_raw_and_manifest(tmp_path, monkeypatch) -> None:
    evidence = _evidence(tmp_path)
    write_submission_tables(evidence)
    before = _files(tmp_path)
    evidence.selected_idea["mechanisms"][0]["publication_description"] = "Updated declared public description."
    selected_path = tmp_path / "ideas/SELECTED_IDEA.json"
    selected_path.write_text(json.dumps(evidence.selected_idea))
    before = _files(tmp_path)
    from server.services import paper_table_transaction as transaction
    original = transaction.atomic_write_bytes
    calls = 0

    def fail_second_canonical(path: Path, content: bytes):
        nonlocal calls
        if path.is_relative_to(tmp_path / "paper/tables"):
            calls += 1
            if calls == 2:
                raise OSError("canonical commit fixture failed")
        return original(path, content)

    monkeypatch.setattr(transaction, "atomic_write_bytes", fail_second_canonical)
    with pytest.raises(OSError, match="canonical commit fixture failed"):
        write_submission_tables(evidence)
    assert _files(tmp_path) == before


def test_single_component_is_complete_prose_not_a_fake_one_row_table(tmp_path) -> None:
    evidence = _evidence(tmp_path, count=1)
    write_submission_tables(evidence)
    text = (tmp_path / "paper/tables/method_components.tex").read_text()
    assert r"\begin{table}" not in text and _latex(LONG_EVALUATION) in text
    manifest = json.loads((tmp_path / "paper/tables/TABLE_MANIFEST.json").read_text())
    assert not any(item["id"] == "method_components" for item in manifest["tables"])


def test_zero_current_records_cannot_reuse_or_delete_stale_public_design_text(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    write_submission_tables(evidence)
    evidence.selected_idea["mechanisms"] = []
    (tmp_path / "ideas/SELECTED_IDEA.json").write_text(json.dumps(evidence.selected_idea))
    before = _files(tmp_path)
    with pytest.raises(ValueError, match="no current authored design records"):
        write_submission_tables(evidence)
    assert _files(tmp_path) == before


def test_executed_public_csv_is_the_exact_displayed_column_inventory(tmp_path) -> None:
    evidence = _evidence(tmp_path, long=False)
    evidence.asset_plan = {"evidence_mode": "executed", "assets": []}
    data = tmp_path / "experiments/results/aggregates/main_comparison.csv"
    data.parent.mkdir(parents=True)
    data.write_text(
        "method,metric,split,mean,std,n,ci95_low,ci95_high,internal_status\n"
        "Declared A,macro_f1,heldout,0.70,0.02,3,0.65,0.75,private\n"
        "Declared B,macro_f1,heldout,0.71,0.03,3,0.64,0.78,private\n"
    )
    write_submission_tables(evidence)
    with (tmp_path / "paper/tables/main_results.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == ["method", "metric", "split", "estimate", "n", "interval"]
    assert rows[0]["metric"] == "Macro-F1"
    assert rows[0]["estimate"] == "0.70 ± 0.02" and rows[0]["interval"] == "[0.65, 0.75]"
    assert "internal_status" not in rows[0]
    rendered = (tmp_path / "paper/tables/main_results.tex").read_text(encoding="utf-8")
    assert r"95\% confidence intervals" in rendered
    assert r"\textbackslash{}\% confidence intervals" not in rendered
    raw = json.loads((tmp_path / ".merak/paper-table-records/main_results.json").read_text())
    assert raw["records"][0]["internal_status"] == "private"


def test_oversized_numeric_cells_still_fail_with_precise_typed_target() -> None:
    spec = ScientificTableSpec("Question", "Caption", "tab:outcomes",
                               (TableColumn("condition", "Condition"), TableColumn("estimate", "Estimate", "number")),
                               "Participant", "Recorded uncertainty", ("measurements.csv",))
    with pytest.raises(SemanticTableContractError) as caught:
        compile_scientific_table(spec, [{"condition": "Declared cohort", "estimate": "1" * 181}])
    assert caught.value.table_label == "tab:outcomes"
    assert caught.value.row_index == 0 and caught.value.column_key == "estimate"
