"""Only trusted publication-table staging can write temporary validation CSVs."""

from contextlib import contextmanager
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from scripts import full_benchmark_scope as scope
from server.services import paper_submission_tables as producer
from server.services.paper_artifacts import paper_artifact_builder
from server.tests.test_publication_table_prose_transaction import _evidence
from server.utils.atomic_write import atomic_write_bytes
from scripts.verify_offline_suite import canonical_io_path


@contextmanager
def _csv_guard(root):
    active = True
    observations = []

    def check(value):
        if isinstance(value, (str, bytes, os.PathLike)):
            path = canonical_io_path(value)
            if scope._csv_target(path):
                allowed = scope.write_is_allowed(root, path, rerun_literature=False)
                observations.append((path, allowed))
                if not allowed:
                    raise PermissionError("Frozen canonical or unowned staging CSV")

    def audit(event, arguments):
        if not active:
            return
        if event == "open":
            path, mode, flags = arguments
            if isinstance(mode, str) and any(letter in mode for letter in "wax+") or isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
                check(path)
        elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.utime"}:
            check(arguments[0])
        elif event in {"os.rename", "os.link", "os.symlink"}:
            for path in arguments[:2]:
                check(path)

    sys.addaudithook(audit)
    try:
        yield observations
    finally:
        active = False


def _csvs(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*.csv") if path.is_file()}


def test_real_cached_table_producer_can_validate_stage_csv_and_atomic_tmp_without_touching_canonical_csv(tmp_path):
    evidence = _evidence(tmp_path, long=False)
    producer.write_submission_tables(evidence)
    baseline = _csvs(tmp_path)
    with scope.trusted_publication_table_staging(tmp_path), _csv_guard(tmp_path) as events:
        paper_artifact_builder._write_submission_tables(evidence)
    assert _csvs(tmp_path) == baseline
    assert events and all(allowed for _, allowed in events)
    assert any(path.name.endswith(".tmp") for path, _ in events)
    assert all(path.is_relative_to(tmp_path / ".merak/transactions") for path, _ in events)
    assert list((tmp_path / ".merak/transactions").glob("publication-tables-*")) == []
    assert scope._TABLE_PRODUCER.get() is scope._TABLE_STAGE.get() is None


@pytest.mark.parametrize("atomic", [False, True])
def test_model_cannot_write_same_named_transaction_csv_or_atomic_temp_without_producer_token(tmp_path, atomic):
    path = tmp_path / ".merak/transactions/publication-tables-model/experiments/results/simulated/raw.csv"
    path.parent.mkdir(parents=True)
    token = scope.MODEL_OWNER.set("paper")
    try:
        with scope.trusted_publication_table_staging(tmp_path), _csv_guard(tmp_path):
            with pytest.raises(PermissionError):
                atomic_write_bytes(path, b"untrusted,999\n") if atomic else path.write_bytes(b"untrusted,999\n")
        assert not path.exists()
    finally:
        scope.MODEL_OWNER.reset(token)


def test_model_cannot_request_the_trusted_producer_token_by_invoking_its_entrypoint(tmp_path):
    evidence = _evidence(tmp_path, long=False)
    token = scope.MODEL_OWNER.set("paper")
    try:
        with scope.trusted_publication_table_staging(tmp_path):
            with pytest.raises(PermissionError, match="Model tools"):
                producer.write_submission_tables(evidence)
    finally:
        scope.MODEL_OWNER.reset(token)
    assert scope._TABLE_PRODUCER.get() is scope._TABLE_STAGE.get() is None


@pytest.mark.parametrize("relative", ["experiments/results/simulated/raw.csv", "paper/tables/current.csv",
    "paper/tables/.current.csv.123.456." + "a" * 32 + ".tmp"])
def test_canonical_csv_and_atomic_siblings_are_not_authorized_even_during_real_producer(tmp_path, monkeypatch, relative):
    evidence = _evidence(tmp_path, long=False)
    producer.write_submission_tables(evidence)
    observed = []
    original = producer._write_design_tables

    def inspect(*args, **kwargs):
        observed.append(scope.write_is_allowed(tmp_path, tmp_path / relative, rerun_literature=False))
        return original(*args, **kwargs)

    monkeypatch.setattr(producer, "_write_design_tables", inspect)
    with scope.trusted_publication_table_staging(tmp_path), _csv_guard(tmp_path):
        producer.write_submission_tables(evidence)
    assert observed == [False]


def test_only_current_exact_random_stage_is_allowed_and_model_owner_cannot_borrow_live_token(tmp_path, monkeypatch):
    evidence = _evidence(tmp_path, long=False)
    producer.write_submission_tables(evidence)
    original = producer._write_design_tables
    checks = []

    def inspect(table_dir, *args, **kwargs):
        current = table_dir / "bound.csv"
        other = table_dir.parents[2] / "publication-tables-other/paper/tables/unbound.csv"
        checks.extend((scope.write_is_allowed(tmp_path, current, rerun_literature=False),
                       scope.write_is_allowed(tmp_path, other, rerun_literature=False)))
        token = scope.MODEL_OWNER.set("paper")
        try:
            checks.append(scope.write_is_allowed(tmp_path, current, rerun_literature=False))
        finally:
            scope.MODEL_OWNER.reset(token)
        return original(table_dir, *args, **kwargs)

    monkeypatch.setattr(producer, "_write_design_tables", inspect)
    with scope.trusted_publication_table_staging(tmp_path), _csv_guard(tmp_path):
        producer.write_submission_tables(evidence)
    assert checks == [True, False, False]


def test_producer_cannot_create_new_canonical_csv_under_full_verification(tmp_path):
    evidence = _evidence(tmp_path, long=False)
    with scope.trusted_publication_table_staging(tmp_path), _csv_guard(tmp_path):
        with pytest.raises(PermissionError, match="Frozen"):
            producer.write_submission_tables(evidence)
    assert _csvs(tmp_path) == {}
    assert scope._TABLE_PRODUCER.get() is scope._TABLE_STAGE.get() is None


def test_failed_table_transaction_retains_cleanup_token_then_restores_every_context(tmp_path, monkeypatch):
    evidence = _evidence(tmp_path, long=False)
    producer.write_submission_tables(evidence)
    baseline = _csvs(tmp_path)

    def failed(*_args, **_kwargs):
        raise ValueError("Pure staged table validation failed")

    monkeypatch.setattr(producer, "_write_executed_tables", failed)
    with scope.trusted_publication_table_staging(tmp_path), _csv_guard(tmp_path):
        with pytest.raises(ValueError, match="Pure staged"):
            producer.write_submission_tables(evidence)
    assert _csvs(tmp_path) == baseline
    assert list((tmp_path / ".merak/transactions").glob("publication-tables-*")) == []
    assert scope._TABLE_PRODUCER.get() is scope._TABLE_STAGE.get() is None


def test_foreign_project_or_direct_temp_allocator_cannot_borrow_the_producer_scope(tmp_path):
    original_temporary = producer.tempfile.TemporaryDirectory
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    with scope.trusted_publication_table_staging(tmp_path):
        with pytest.raises(PermissionError, match="foreign"):
            producer.write_submission_tables(SimpleNamespace(root=foreign))
        with pytest.raises(PermissionError, match="trusted producer"):
            with producer.tempfile.TemporaryDirectory(prefix="publication-tables-", dir=tmp_path / ".merak/transactions"):
                pytest.fail("Untrusted allocator was entered")
    assert producer.tempfile.TemporaryDirectory is original_temporary


def _refresh_fixture(root, monkeypatch):
    import json
    from server.tests.test_dataset_calibration_tables import _dataset_bundle

    bundle = _dataset_bundle(root, monkeypatch)
    selected = root / "ideas/SELECTED_IDEA.json"
    selected.parent.mkdir(parents=True, exist_ok=True)
    selected.write_text(json.dumps({"schema": 2, "publication": {
        "contribution_type": "objective_mechanism", "title": "Registered fixture objective",
        "method_name": "CSFS joint shared-private objective",
    }}), encoding="utf-8")
    return bundle


def test_real_simulation_table_refresh_uses_exact_stage_without_touching_frozen_csv(tmp_path, monkeypatch):
    from server.services import simulation_table_publication_refresh as refresh

    manifest, _payload, _rows = _refresh_fixture(tmp_path, monkeypatch)
    original_manifest = manifest.read_bytes()
    original_csv = _csvs(tmp_path)
    with scope.trusted_publication_table_staging(tmp_path), _csv_guard(tmp_path) as events:
        assert refresh.refresh_simulation_publication_tables(tmp_path) is True
    assert manifest.read_bytes() == original_manifest
    assert _csvs(tmp_path) == original_csv
    assert events and all(allowed for _, allowed in events)
    assert all(path.is_relative_to(tmp_path / ".merak/transactions") for path, _ in events)
    assert not list((tmp_path / ".merak/transactions").glob("publication-tables-*"))
    assert scope._TABLE_PRODUCER.get() is scope._TABLE_STAGE.get() is None
    with scope.trusted_publication_table_staging(tmp_path), _csv_guard(tmp_path) as repeated:
        assert refresh.refresh_simulation_publication_tables(tmp_path) is False
    assert not repeated and _csvs(tmp_path) == original_csv


def test_model_foreign_root_and_direct_refresh_allocator_cannot_borrow_staging(tmp_path):
    from server.services import simulation_table_publication_refresh as refresh

    original_allocator = refresh.tempfile.TemporaryDirectory
    with scope.trusted_publication_table_staging(tmp_path):
        token = scope.MODEL_OWNER.set("paper")
        try:
            with pytest.raises(PermissionError, match="Model tools"):
                refresh.refresh_simulation_publication_tables(tmp_path)
        finally:
            scope.MODEL_OWNER.reset(token)
        with pytest.raises(PermissionError, match="foreign"):
            refresh.refresh_simulation_publication_tables(tmp_path / "foreign")
        with pytest.raises(PermissionError, match="trusted producer"):
            with refresh.tempfile.TemporaryDirectory(prefix="publication-tables-", dir=tmp_path / ".merak/transactions"):
                pytest.fail("Direct refresh allocator must not acquire the trusted capability")
    assert refresh.tempfile.TemporaryDirectory is original_allocator
    assert scope._TABLE_PRODUCER.get() is scope._TABLE_STAGE.get() is None


def test_failed_real_refresh_restores_stage_scope_and_every_canonical_byte(tmp_path, monkeypatch):
    from server.services import simulation_table_publication_refresh as refresh
    from server.services import paper_table_transaction
    from server.tests.test_dataset_calibration_tables import _files

    _refresh_fixture(tmp_path, monkeypatch)
    before = _files(tmp_path)

    def rejected(*_arguments, **_keywords):
        raise ValueError("Current publication table validation rejected its transaction")

    monkeypatch.setattr(paper_table_transaction, "commit_prepared_table_bundle", rejected)
    with scope.trusted_publication_table_staging(tmp_path), _csv_guard(tmp_path):
        with pytest.raises(ValueError, match="publication table validation"):
            refresh.refresh_simulation_publication_tables(tmp_path)
    assert _files(tmp_path) == before
    assert not list((tmp_path / ".merak/transactions").glob("publication-tables-*"))
    assert scope._TABLE_PRODUCER.get() is scope._TABLE_STAGE.get() is None
