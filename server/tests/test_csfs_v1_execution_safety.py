"""Pure fake state verifies OOM rollback/resume; no Torch, optimizer or experiment."""

from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.experiment_protocols.csfs_v1.execution_safety import StepOOMError, retry_oom_step
from server.experiment_protocols.csfs_v1.checkpoint_contract import (
    CheckpointIdentity, build_resume_checkpoint, load_bound_checkpoint, resume_seeded_stream,
    resumed_resource_origin, validate_resume_checkpoint,
)
from server.experiment_protocols.csfs_v1.protocol import ExecutionResources, ProtocolError
from server.experiment_protocols.csfs_v1.training_policy import AnomalyPolicy, SelectionPolicy
from server.tests.test_csfs_v1_statistics import _evaluation_fixture, VOCAB
from server.experiment_protocols.csfs_v1.evaluation import evaluate_frozen_probe


class _OOM(RuntimeError):
    pass


def _step_fixture():
    clock = [100.0]
    anomaly = AnomalyPolicy(lambda: clock[0], 100.0, 100.0, 1000)
    state = {"model": {"weight": 1.0}, "optimizer": {"moment": 2.0}, "gradients": {"weight": 0.0},
             "best_model": {"weight": 0.5},
             "rng": {"python": [1], "numpy": [2], "torch": [3], "cuda": [], "objective": [4]},
             "sampler": {"cursor": 0}, "budget": {"windows": 0, "updates": 0},
             "policy": {"best": 0.5}, "anomaly": {"loss_count": 0}}
    before = copy.deepcopy(state)
    restores, clears = [], []

    def restore(value):
        restores.append(copy.deepcopy(value))
        state.clear()
        state.update(copy.deepcopy(value))
        anomaly.oom_events = 0

    return state, before, clock, anomaly, restores, clears, restore


def test_first_oom_restores_model_optimizer_rng_sampler_and_budget_then_retries_exactly_once():
    state, before, clock, anomaly, restores, clears, restore = _step_fixture()
    attempts = []

    def operation():
        attempts.append(copy.deepcopy(state))
        state["model"]["weight"] += 1
        state["optimizer"]["moment"] += 1
        state["best_model"]["weight"] += 1
        state["rng"]["objective"][0] += 1
        state["sampler"]["cursor"] += 32
        state["budget"]["windows"] += 32
        state["budget"]["updates"] += 1
        clock[0] += 5
        if len(attempts) == 1:
            raise _OOM("exact first OOM")
        return "real step succeeded"

    result = retry_oom_step(operation, lambda: state, restore, anomaly, lambda: clears.append(True), oom_exception=_OOM)
    assert result == "real step succeeded" and attempts == [before, before]
    assert restores == [before] and len(clears) == 1 and anomaly.oom_events == 1
    assert state["budget"] == {"windows": 32, "updates": 1} and state["sampler"]["cursor"] == 32
    assert anomaly.started_at == 100 and clock[0] == 110


def test_second_oom_restores_exact_step_and_aborts_without_advancing_any_budget():
    state, before, clock, anomaly, restores, clears, restore = _step_fixture()

    def operation():
        state["budget"]["windows"] += 32
        state["model"]["weight"] = 999
        clock[0] += 1
        raise _OOM("second OOM")

    with pytest.raises(StepOOMError, match="Two out-of-memory"):
        retry_oom_step(operation, lambda: state, restore, anomaly, lambda: clears.append(True), oom_exception=_OOM)
    assert state == before and restores == [before, before] and anomaly.oom_events == 2
    assert len(clears) == 2 and clock[0] == 102


def test_prior_attempt_oom_count_survives_rollback_and_does_not_grant_another_retry():
    state, before, _clock, anomaly, restores, _clears, restore = _step_fixture()
    anomaly.oom_events = 1
    calls = []

    def operation():
        calls.append(True)
        state["budget"]["updates"] = 1
        raise _OOM("registered second event")

    with pytest.raises(StepOOMError):
        retry_oom_step(operation, lambda: state, restore, anomaly, lambda: None, oom_exception=_OOM)
    assert calls == [True] and restores == [before] and anomaly.oom_events == 2 and state == before


def test_arbitrary_runtime_errors_are_not_oom_and_are_never_retried_or_hidden():
    state, _before, _clock, anomaly, restores, clears, restore = _step_fixture()
    calls = []

    def operation():
        calls.append(True)
        raise RuntimeError("bad configuration not memory")

    with pytest.raises(RuntimeError, match="bad configuration"):
        retry_oom_step(operation, lambda: state, restore, anomaly, lambda: clears.append(True), oom_exception=_OOM)
    assert calls == [True] and restores == [] and clears == [] and anomaly.oom_events == 0
    with pytest.raises(ProtocolError, match="specific OOM"):
        retry_oom_step(operation, lambda: state, restore, anomaly, lambda: None, oom_exception=RuntimeError)


def test_oom_retry_cannot_restart_elapsed_wall_time_or_suppress_exhaustion():
    state, _before, clock, anomaly, _restores, _clears, restore = _step_fixture()
    anomaly.wall_time_limit = 10

    def operation():
        clock[0] += 11
        raise _OOM("exhausted wall time")

    with pytest.raises(StepOOMError, match="wall-time"):
        retry_oom_step(operation, lambda: state, restore, anomaly, lambda: None, oom_exception=_OOM)


@pytest.mark.parametrize("defect", ["missing_rng", "missing_budget", "missing_best", "device", "object"])
def test_rollback_snapshot_cannot_omit_rng_budget_or_retain_live_device_state(defect):
    state, _before, _clock, anomaly, _restores, _clears, restore = _step_fixture()
    if defect == "missing_rng": state["rng"].pop("numpy")
    elif defect == "missing_budget": state.pop("budget")
    elif defect == "missing_best": state.pop("best_model")
    elif defect == "device": state["model"]["weight"] = SimpleNamespace(device="cuda:0", requires_grad=False)
    else: state["model"]["weight"] = object()
    with pytest.raises(ProtocolError):
        retry_oom_step(lambda: "must not run", lambda: state, restore, anomaly, lambda: None, oom_exception=_OOM)


def _checkpoint():
    identity = CheckpointIdentity("a" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64,
                                  13, "csfs", "Target", "source_training", ExecutionResources("cpu", 3600, 10_000_000))
    policy = SelectionPolicy()
    policy.observe(1000, 0.7, 1000)
    payload = build_resume_checkpoint(identity, windows=1000, model={"weight": [1.0]}, optimizer={"state": {0: {"moment": 0.5}}},
        best_model={"weight": [1.0]}, policy=policy.__dict__, rng={"python": [3, [1, 2], None], "numpy": [1, 2],
        "torch": [3], "cuda": [], "objective": [4]}, sampler={"seed": 13, "cursor": 1000, "window_budget": 100000, "sampling_role": "pretrain"},
        anomaly={"oom_events": 1, "initial_losses": [0.2, 0.3], "pathological_losses": 0, "heartbeat_age_seconds": 5.0},
        resources_elapsed_seconds=100.0, saved_at_unix=1000.0)
    return identity, payload


def test_checkpoint_contract_is_complete_bound_and_does_not_promote_completion():
    identity, checkpoint = _checkpoint()
    before = copy.deepcopy(checkpoint)
    result = validate_resume_checkpoint(checkpoint, identity)
    assert result == before and result is not checkpoint
    assert "accepted" not in result and "completed" not in result and checkpoint == before
    assert result["policy"]["final_probe_updates"] == 0 and result["sampler"]["cursor"] == 1000


@pytest.mark.parametrize("field", ["config_sha256", "source_sha256", "corpus_sha256", "fold_sha256", "normalization_sha256", "seed", "method_id", "resources", "fit_role"])
def test_resume_rejects_every_changed_current_identity_before_state_restore(field):
    identity, checkpoint = _checkpoint()
    value = {"seed": 42, "method_id": "no_private", "resources": ExecutionResources("cpu", 3601, 10_000_000),
             "fit_role": "target_local_training"}.get(field, "f" * 64)
    with pytest.raises(ProtocolError, match="stale, foreign"):
        validate_resume_checkpoint(checkpoint, replace(identity, **{field: value}))


@pytest.mark.parametrize("defect", ["model", "optimizer", "best_model", "rng", "cursor", "budget", "events", "final_probe", "elapsed", "heartbeat", "oom", "schema"])
def test_resume_refuses_incomplete_or_overspent_state(defect):
    identity, checkpoint = _checkpoint()
    if defect in {"model", "optimizer", "best_model"}: checkpoint[defect] = {}
    elif defect == "rng": checkpoint["rng"].pop("cuda")
    elif defect == "cursor": checkpoint["sampler"]["cursor"] = 999
    elif defect == "budget": checkpoint["windows"] = 101000
    elif defect == "events": checkpoint["policy"]["best_score"] = 0.99
    elif defect == "final_probe": checkpoint["policy"]["final_probe_updates"] = 10000
    elif defect == "elapsed": checkpoint["resources_elapsed_seconds"] = 3600
    elif defect == "heartbeat": checkpoint["anomaly"]["heartbeat_age_seconds"] = 900
    elif defect == "oom": checkpoint["anomaly"]["oom_events"] = 2
    else: checkpoint["schema"] = 0
    with pytest.raises(ProtocolError): validate_resume_checkpoint(checkpoint, identity)


def test_checkpoint_hash_is_verified_before_weights_only_cpu_deserialization(tmp_path):
    identity, checkpoint = _checkpoint()
    path = tmp_path / "resume.pt"
    raw = b"known opaque source-owned checkpoint bytes"
    path.write_bytes(raw)
    calls = []

    def loader(buffer, **options):
        calls.append((buffer.read(), options))
        return checkpoint

    with pytest.raises(ProtocolError, match="bytes differ"):
        load_bound_checkpoint(path, "0" * 64, identity, owned_attempt_root=tmp_path, loader=loader)
    assert calls == []
    loaded = load_bound_checkpoint(path, hashlib.sha256(raw).hexdigest(), identity, owned_attempt_root=tmp_path, loader=loader)
    assert calls == [(raw, {"map_location": "cpu", "weights_only": True})] and loaded == checkpoint


def test_checkpoint_load_refuses_foreign_or_nested_paths_before_deserialization(tmp_path):
    identity, _checkpoint_value = _checkpoint()
    owned = tmp_path / "owned"
    owned.mkdir()
    foreign = tmp_path / "resume.pt"
    foreign.write_bytes(b"foreign")
    with pytest.raises(ProtocolError, match="direct unlinked"):
        load_bound_checkpoint(foreign, hashlib.sha256(b"foreign").hexdigest(), identity,
                              owned_attempt_root=owned, loader=lambda *_args, **_kwargs: pytest.fail("foreign loader"))


def test_seeded_sampler_resume_skips_exact_cursor_without_new_draws_or_guessing():
    stream = resume_seeded_stream(lambda: iter(range(100_000)), 1000)
    assert next(stream) == 1000 and next(stream) == 1001
    assert list(resume_seeded_stream(lambda: iter(range(3)), 3)) == []
    with pytest.raises(ProtocolError, match="exceeds"):
        resume_seeded_stream(lambda: iter(range(2)), 3)
    with pytest.raises(ProtocolError, match="outside"):
        resume_seeded_stream(lambda: iter(()), 100001)


def test_resume_carries_saved_elapsed_time_and_downtime_into_resource_and_heartbeat_limits():
    _identity_value, checkpoint = _checkpoint()
    started, heartbeat = resumed_resource_origin(lambda: 500.0, checkpoint, wallclock=lambda: 1030.0)
    assert started == 370.0 and heartbeat == 465.0
    with pytest.raises(ProtocolError, match="predates"):
        resumed_resource_origin(lambda: 500.0, checkpoint, wallclock=lambda: 999.0)


def test_evaluation_observer_checks_resources_before_and_after_every_frozen_batch():
    probe, bindings, batch = _evaluation_fixture()
    observed = []
    evaluate_frozen_probe(probe, [batch], bindings=bindings, label_vocabulary=VOCAB,
                          expected_segment_ids=("Segment",), on_batch=lambda: observed.append("checked"))
    assert observed == ["checked", "checked"]
    def exhausted(): raise ProtocolError("per-batch time/memory limit")
    with pytest.raises(ProtocolError, match="time/memory"):
        evaluate_frozen_probe(probe, [batch], bindings=bindings, label_vocabulary=VOCAB,
                              expected_segment_ids=("Segment",), on_batch=exhausted)
