"""Real retained design-table bindings remain complete in publication transactions."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import full_benchmark_scope as scope
from server.services import paper_artifacts, paper_table_transaction
from server.services import simulation_table_publication_refresh as refresh
from server.services.paper_submission_tables import write_submission_tables
from server.services.retained_table_input_closure import retained_table_input_hashes
from server.services.simulation_table_projection_binding import PUBLICATION_BINDING, verify_simulation_table_projection
from server.tests.test_dataset_calibration_tables import _dataset_bundle
from server.tests.test_full_benchmark_table_scope import _csv_guard
from server.tests.test_publication_table_prose_transaction import LONG_EVALUATION, _evidence
from server.utils.atomic_write import atomic_write_bytes


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _files(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*")
            if path.is_file() and not path.is_relative_to(root / ".merak/transactions")}


def _retained_bundle(root: Path, monkeypatch: pytest.MonkeyPatch):
    manifest, payload, _rows = _dataset_bundle(root, monkeypatch, number=10)
    evidence = _evidence(root)
    evidence.selected_idea["publication"] = {"contribution_type": "objective_mechanism",
        "title": "Declared source-bound mechanism fixture"}
    (root / "ideas/SELECTED_IDEA.json").write_text(json.dumps(evidence.selected_idea), encoding="utf-8")
    for relative, raw in {
        "experiments/RUN_SPEC.json": json.dumps(evidence.run_spec).encode("utf-8"),
        "experiments/METHOD_CONTRACT.json": b'{"schema":2,"description":"Declared fixture inputs"}',
        "experiments/configs/main.yaml": b"method:\n  name: Declared predictor\n",
    }.items():
        atomic_write_bytes(root / relative, raw)
    write_submission_tables(evidence)
    tables = json.loads((root / "paper/tables/TABLE_MANIFEST.json").read_text(encoding="utf-8"))
    entry = next(item for item in tables["tables"] if item["id"] == "method_components")
    assert entry["publication_projection"]["notes"][0]["original_public_text"] == LONG_EVALUATION
    return manifest, payload, tables["tables"]


def test_old_partial_stage_rejects_then_real_refresh_stages_full_provenance_under_native_csv_scope(tmp_path, monkeypatch):
    manifest, payload, retained = _retained_bundle(tmp_path, monkeypatch)
    before = _files(tmp_path)
    incomplete = tmp_path / ".merak/transactions/incomplete-source-fixture"
    for entry in retained:
        for key in ("data_path", "latex_path"):
            atomic_write_bytes(incomplete / entry[key], (tmp_path / entry[key]).read_bytes())
    with pytest.raises(ValueError, match="public row source binding is missing"):
        paper_artifacts.build_table_manifest(incomplete, retained)
    assert _files(tmp_path) == before

    observed = []
    original = paper_artifacts.build_table_manifest

    def inspect_complete_stage(stage, entries):
        for relative, digest in retained_table_input_hashes(tmp_path, retained).items():
            assert (stage / relative).read_bytes() == before[relative]
            assert _sha((stage / relative).read_bytes()) == digest
        observed.append(stage)
        return original(stage, entries)

    monkeypatch.setattr(paper_artifacts, "build_table_manifest", inspect_complete_stage)
    with scope.trusted_publication_table_staging(tmp_path), _csv_guard(tmp_path) as csv_events:
        assert refresh.refresh_simulation_publication_tables(tmp_path) is True
    assert observed and csv_events and all(allowed for _path, allowed in csv_events)
    assert all(path.is_relative_to(tmp_path / ".merak/transactions") for path, _allowed in csv_events)
    verify_simulation_table_projection(tmp_path, payload)
    assert manifest.read_bytes() == before[manifest.relative_to(tmp_path).as_posix()]
    allowed_changes = {"paper/tables/synthetic_preview_results.tex",
        PUBLICATION_BINDING, "paper/tables/TABLE_MANIFEST.json"}
    after = _files(tmp_path)
    assert all(after[path] == raw for path, raw in before.items() if path not in allowed_changes)
    current = json.loads(after["paper/tables/TABLE_MANIFEST.json"])
    assert [item for item in current["tables"] if item["evidence_status"] != "synthetic_preview"] == retained
    with scope.trusted_publication_table_staging(tmp_path), _csv_guard(tmp_path) as repeated:
        assert refresh.refresh_simulation_publication_tables(tmp_path) is False
    assert not repeated and _files(tmp_path) == after
    assert not list((tmp_path / ".merak/transactions").glob("publication-tables-*"))
    assert scope._TABLE_PRODUCER.get() is scope._TABLE_STAGE.get() is None


def test_closure_collects_declared_sources_and_notes_without_guessing_strings_or_changing_entries(tmp_path):
    evidence = _evidence(tmp_path)
    write_submission_tables(evidence)
    manifest = json.loads((tmp_path / "paper/tables/TABLE_MANIFEST.json").read_text(encoding="utf-8"))
    entries = manifest["tables"]
    before = _files(tmp_path)
    original = copy.deepcopy(entries)
    hashes = retained_table_input_hashes(tmp_path, entries)
    assert "ideas/SELECTED_IDEA.json" in hashes
    assert all(_sha(before[path]) == digest for path, digest in hashes.items())
    assert all(not path.startswith("/mechanisms/") for path in hashes)
    assert not any(path.startswith(".merak/paper-table-records/") for path in hashes)
    assert entries == original and _files(tmp_path) == before


@pytest.mark.parametrize("defect", ["changed_source", "missing_source", "missing_declared_input", "escaped_input",
    "escaped_binding", "wrong_binding_sha", "malformed_binding", "malformed_source_data"])
def test_retained_dependency_failures_reject_before_every_canonical_write(tmp_path, monkeypatch, defect):
    _manifest, _payload, _retained = _retained_bundle(tmp_path, monkeypatch)
    manifest = tmp_path / "paper/tables/TABLE_MANIFEST.json"
    tables = json.loads(manifest.read_text(encoding="utf-8"))
    entry = next(item for item in tables["tables"] if item["id"] == "method_components")
    binding = entry["publication_projection"]["source_bindings"][0]["component"][0]
    if defect == "changed_source":
        source = tmp_path / "ideas/SELECTED_IDEA.json"
        source.write_bytes(source.read_bytes() + b" ")
    elif defect == "missing_source":
        (tmp_path / "ideas/SELECTED_IDEA.json").unlink()
    elif defect == "missing_declared_input": entry["source_data"].append("experiments/absent.json")
    elif defect == "escaped_input": entry["source_data"].append("../foreign-source.json")
    elif defect == "escaped_binding": binding["source_path"] = "../foreign-source.json"
    elif defect == "wrong_binding_sha": binding["source_sha256"] = "0" * 64
    elif defect == "malformed_binding": binding.pop("source_sha256")
    else: entry["source_data"] = "ideas/SELECTED_IDEA.json"
    if defect not in {"changed_source", "missing_source"}:
        manifest.write_text(json.dumps(tables), encoding="utf-8")
    before = _files(tmp_path)
    with scope.trusted_publication_table_staging(tmp_path), _csv_guard(tmp_path):
        with pytest.raises((ValueError, FileNotFoundError)):
            refresh.refresh_simulation_publication_tables(tmp_path)
    assert _files(tmp_path) == before
    assert not list((tmp_path / ".merak/transactions").glob("publication-tables-*"))
    assert scope._TABLE_PRODUCER.get() is scope._TABLE_STAGE.get() is None


def test_copy_time_source_change_is_rejected_without_overwriting_retained_or_scientific_files(tmp_path, monkeypatch):
    _manifest, _payload, retained = _retained_bundle(tmp_path, monkeypatch)
    before = _files(tmp_path)
    original = paper_artifacts.build_table_manifest
    changed = tmp_path / "experiments/configs/main.yaml"

    def change_source_after_stage_validation(stage, entries):
        result = original(stage, entries)
        changed.write_bytes(before["experiments/configs/main.yaml"] + b"# concurrent external edit\n")
        return result

    monkeypatch.setattr(paper_artifacts, "build_table_manifest", change_source_after_stage_validation)
    with scope.trusted_publication_table_staging(tmp_path), _csv_guard(tmp_path):
        with pytest.raises(ValueError, match="Scientific table inputs changed"):
            refresh.refresh_simulation_publication_tables(tmp_path)
    after = _files(tmp_path)
    assert all(after[path] == raw for path, raw in before.items() if path != "experiments/configs/main.yaml")
    assert json.loads(after["paper/tables/TABLE_MANIFEST.json"])["tables"] == retained


def test_failed_canonical_commit_rolls_back_projection_and_preserves_full_retained_sources(tmp_path, monkeypatch):
    _manifest, _payload, _retained = _retained_bundle(tmp_path, monkeypatch)
    before = _files(tmp_path)
    original = paper_table_transaction.atomic_write_bytes
    rejected = False

    def fail_once(path, raw):
        nonlocal rejected
        if path == tmp_path / "paper/tables/TABLE_MANIFEST.json" and not rejected:
            rejected = True
            raise OSError("Fixture-only canonical commit failure")
        return original(path, raw)

    monkeypatch.setattr(paper_table_transaction, "atomic_write_bytes", fail_once)
    with scope.trusted_publication_table_staging(tmp_path), _csv_guard(tmp_path):
        with pytest.raises(OSError, match="Fixture-only canonical"):
            refresh.refresh_simulation_publication_tables(tmp_path)
    assert rejected and _files(tmp_path) == before
    assert scope._TABLE_PRODUCER.get() is scope._TABLE_STAGE.get() is None


def test_existing_manifest_concurrent_edit_is_rejected_not_overwritten_or_rolled_back(tmp_path, monkeypatch):
    _manifest, _payload, _retained = _retained_bundle(tmp_path, monkeypatch)
    before = _files(tmp_path)
    manifest = tmp_path / "paper/tables/TABLE_MANIFEST.json"
    concurrent = json.loads(before["paper/tables/TABLE_MANIFEST.json"])
    concurrent["operator_note"] = "Concurrent table owner edit must survive."
    concurrent_bytes = json.dumps(concurrent).encode("utf-8")
    original = paper_artifacts.build_table_manifest

    def edit_existing_manifest_after_complete_stage_validation(stage, entries):
        result = original(stage, entries)
        manifest.write_bytes(concurrent_bytes)
        return result

    monkeypatch.setattr(paper_artifacts, "build_table_manifest", edit_existing_manifest_after_complete_stage_validation)
    with scope.trusted_publication_table_staging(tmp_path), _csv_guard(tmp_path):
        with pytest.raises(ValueError, match="Canonical table changed during preparation: paper/tables/TABLE_MANIFEST.json"):
            refresh.refresh_simulation_publication_tables(tmp_path)
    after = _files(tmp_path)
    assert after["paper/tables/TABLE_MANIFEST.json"] == concurrent_bytes
    assert all(after[path] == raw for path, raw in before.items() if path != "paper/tables/TABLE_MANIFEST.json")
    assert scope._TABLE_PRODUCER.get() is scope._TABLE_STAGE.get() is None
