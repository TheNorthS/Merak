"""Window budgets and launch boundaries without executing any optimization."""

import ast
from itertools import islice
from pathlib import Path

import pytest

from server.experiment_protocols.csfs_v1.protocol import (
    ProtocolError, registered_configuration, require_execution_authorization,
)
from server.experiment_protocols.csfs_v1.training_policy import AnomalyPolicy, SelectionPolicy, window_batches


def test_exact_windows_and_checkpoints_not_epochs():
    batches = list(window_batches(range(100000)))
    assert sum(len(batch) for batch in batches) == 100000
    accumulated = 0
    for batch in batches:
        previous = accumulated
        accumulated += len(batch)
        assert len(batch) <= 32
        assert previous // 1000 == (accumulated - 1) // 1000
    assert accumulated == 100000


def test_no_shortened_scientific_stream_or_imputed_windows():
    with pytest.raises(ProtocolError, match="ended before"):
        list(window_batches(range(999)))


def test_fresh_selection_budget_patience_and_earliest_tie():
    policy = SelectionPolicy()
    assert not policy.observe(1000, 0.5, 1000)
    for index in range(2, 11):
        assert not policy.observe(index * 1000, 0.5, 1000)
    assert policy.observe(11000, 0.5, 1000)
    assert policy.best_checkpoint == 1000
    assert policy.selection_updates == 11000
    policy.complete_probe(10000)
    with pytest.raises(ProtocolError):
        policy.complete_probe(10000)


@pytest.mark.parametrize("windows,updates", [(32, 1000), (2000, 1000), (1000, 999)])
def test_no_unregistered_checkpoint_or_extra_tuning(windows, updates):
    with pytest.raises(ProtocolError):
        SelectionPolicy().observe(windows, 0.6, updates)


def test_permission_checked_before_data_import_or_model_creation(monkeypatch, tmp_path):
    from server.experiment_protocols.csfs_v1 import study

    monkeypatch.setattr(study, "load_data_manifest", lambda *_args: pytest.fail("data must not be read"))
    config = {"protocol": registered_configuration(), "research_contract": {"execution_authorized": False},
              "execution": {"execution_prohibited_in_this_stage": True}}
    with pytest.raises(ProtocolError, match="not authorized"):
        study.run_study(tmp_path, config, allow_execution=False)
    with pytest.raises(ProtocolError, match="not authorized"):
        study.run_study(tmp_path, config, allow_execution=True)


def test_source_check_reads_no_data_or_tensors(tmp_path):
    from server.experiment_protocols.csfs_v1.cli import source_check

    report = source_check(tmp_path, {"protocol": registered_configuration()})
    assert report["source_parses"] and report["validation_level"] == "V0_static"
    assert not report["data_read"] and not report["training_performed"]
    assert not report["claims_supported"]


def test_anomalies_stop_without_corrupting_progress():
    now = [0]
    policy = AnomalyPolicy(lambda: now[0], 0, 0, 5000)
    with pytest.raises(ProtocolError, match="nonfinite"):
        policy.observe(float("nan"))
    policy.out_of_memory()
    with pytest.raises(ProtocolError, match="Two"):
        policy.out_of_memory()
    now[0] = 900
    with pytest.raises(ProtocolError, match="heartbeat"):
        policy.check_time()


def test_registered_budgets_cannot_be_modified_by_config():
    config = {"protocol": {**registered_configuration(), "pretraining_windows": 1000}}
    with pytest.raises(ProtocolError, match="differs"):
        require_execution_authorization(config, allow_execution=True)
