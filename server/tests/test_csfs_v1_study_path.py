"""Traverse the actual study coordinator using fake producers, never optimizer steps."""

from types import SimpleNamespace

import pytest

from server.experiment_protocols.csfs_v1.protocol import registered_configuration
from server.experiment_protocols.csfs_v1 import study


def test_complete_study_calls_all_registered_conditions_and_locks_anchor_first(monkeypatch, tmp_path):
    calls = []
    corpus = SimpleNamespace(datasets=("target-a", "target-b", "target-c"),
        sha256="a" * 64, label_vocabulary=("no", "yes"), recording_fallback_datasets=())
    monkeypatch.setattr(study, "load_data_manifest", lambda *_args: corpus)
    monkeypatch.setattr(study, "build_ldo_fold", lambda corpus, target: SimpleNamespace(target_id=target, validation_id="val"))
    monkeypatch.setattr(study, "build_in_domain_fold", lambda corpus, target: SimpleNamespace(dataset_id=target))
    monkeypatch.setattr(study, "prepare_fold", lambda *_args: SimpleNamespace(target=("segment",)))
    monkeypatch.setattr(study, "verify_current_corpus", lambda *_args: None)
    monkeypatch.setattr(study, "source_inventory", lambda *_args: {"source": "b" * 64})
    from server.experiment_protocols.csfs_v1 import baselines, capacity
    monkeypatch.setattr(baselines, "build_method", lambda method: SimpleNamespace(method_id=method))
    monkeypatch.setattr(capacity, "capacity_ledger", lambda models: {"methods": list(models)})

    class Writer:
        def __init__(self, *args):
            self.identity = args[-1]
        def json(self, name, value):
            calls.append(("write", name))
            return "c" * 64
        def finish(self, **kwargs):
            calls.append(("finish", kwargs["success"]))

    monkeypatch.setattr(study, "AttemptWriter", Writer)

    def train(root, corpus, fold, prepared, method, seed, *_args):
        calls.append(("train", fold.target_id, method, seed))
        result = SimpleNamespace(selection_score=0.6 if method == "bendr_context" else 0.5,
                                 checkpoint_sha256="d" * 64, probe_sha256="e" * 64, budget={})
        return result, Writer({})

    def lock(target, fold, seed, trained, writer):
        assert {method for method in trained} == set(study.METHOD_IDS)
        calls.append(("anchor", target, seed))
        return SimpleNamespace(method_id="bendr_context")

    monkeypatch.setattr(study, "_train_one", train)
    monkeypatch.setattr(study, "_lock_anchor", lock)
    monkeypatch.setattr(study, "evaluation_bindings", lambda *args, **kwargs: args)

    def score(trained, corpus, bindings, segments, seed, resources):
        target = bindings[1].target_id
        assert ("anchor", target, seed) in calls
        calls.append(("target_score", target, bindings[3], seed))
        return {"score_record": (target, bindings[3], seed)}

    monkeypatch.setattr(study, "_score", score)
    monkeypatch.setattr(study, "_perturb_scores", lambda *args: ({"random": []}, {"random": []}, ["ledger"]))
    monkeypatch.setattr(study, "_in_domain", lambda *args: calls.append(("in_domain", args[2].dataset_id)) or [])
    monkeypatch.setattr(study, "evaluate_claims", lambda records, targets, **kwargs:
        {"count": len(records), "targets": list(targets), "c3_supplied": bool(kwargs["c3_inputs"])})
    config = {"protocol": registered_configuration(), "research_contract": {"execution_authorized": True},
        "execution": {"execution_prohibited_in_this_stage": False,
                      "resources": {"device": "cpu", "wall_time_seconds": 3600, "peak_memory_bytes": 1000000000}}}
    result = study.run_study(tmp_path, config, allow_execution=True)
    assert result["count"] == 3 * 5 * 9
    assert len([call for call in calls if call[0] == "train"]) == 135
    assert len([call for call in calls if call[0] == "anchor"]) == 15
    assert len([call for call in calls if call[0] == "in_domain"]) == 3
    assert result["c3_supplied"]


def test_resume_cannot_read_data_without_both_permissions(monkeypatch, tmp_path):
    monkeypatch.setattr(study, "load_data_manifest", lambda *_args: pytest.fail("not authorized to read research data"))
    with pytest.raises(ValueError, match="not authorized"):
        study.resume_condition(tmp_path, {"protocol": registered_configuration()}, {}, allow_execution=False)
