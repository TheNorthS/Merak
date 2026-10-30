"""Isolated continuation rejects altered identity, source archives and frozen data."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.live_snapshot_resume_validation import scientific_digest, validate_copy_boundary, validate_resume_identity


RUN_ID = "source-run"
NODES = ("lit", "idea", "novelty", "exp-design", "exp-run", "results",
         "narrative", "figure", "paper", "review", "audit", "compile", "ppt")


def _write(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def evidence(tmp_path):
    repository = tmp_path / "repository"
    original = tmp_path / "original"
    root = repository / "live-verification-106-fixture"
    config = {"direction": "frozen direction", "effort": "balanced", "assurance": "draft", "options": {
        "run_experiment": False, "non_experiment_evidence_mode": "synthetic_preview",
        "specialist_plan_path": str(original / f".merak/runs/{RUN_ID}.specialists.json"),
    }}
    phases = {node: {"status": "accepted" if index < 7 else "pending",
                     "accepted_at": 100 + index if index < 7 else None,
                     "verdict_id": "", "reviewer": ""} for index, node in enumerate(NODES)}
    source = {"schema": 1, "run_id": RUN_ID, "status": "cancelled", "config": config,
              "phases": phases, "input_baseline": {"snapshot_id": "frozen-baseline"}}
    trace = {"schema": 2, "run_id": RUN_ID, "project_path": str(original),
             "stages": {node: {"owner": node, "session_id": node + "-session"} for node in NODES[:6]}}
    source_hash = _write(original / f".merak/runs/{RUN_ID}.json", source)
    trace_hash = _write(original / f".merak/runs/{RUN_ID}.skills.json", trace)
    specialist = {"schema": 1, "run_id": RUN_ID, "subnodes": []}
    plan_hash = _write(original / f".merak/runs/{RUN_ID}.specialists.json", specialist)
    for suffix, value in (("run", source), ("skills", trace), ("specialists", specialist)):
        _write(root / f".merak/snapshot-source-traces/{RUN_ID}.{suffix}.original.json", value)
    invocation = {"skill": "source-owner", "session_id": "source-session", "status": "completed"}
    _write(original / ".merak/skill-invocations/source.json", invocation)
    _write(root / ".merak/skill-invocations/source.json", invocation)
    copied = copy.deepcopy(source)
    copied["status"] = "incomplete"
    copied["phases"]["figure"]["status"] = "accepted"
    copied["phases"]["paper"]["status"] = "awaiting_revision"
    copied["config"]["options"].update({
        "reused_search_evidence_run_id": RUN_ID,
        "specialist_plan_path": str(root / f".merak/runs/{RUN_ID}.specialists.json"),
    })
    _write(root / f".merak/runs/{RUN_ID}.json", copied)
    cloned_trace = copy.deepcopy(trace)
    cloned_trace["project_path"] = str(root)
    cloned_trace["snapshot_provenance"] = {"source_project": str(original), "source_run_id": RUN_ID,
        "source_trace_sha256": trace_hash, "upstream_invocations_rewritten": False,
        "new_upstream_execution_claimed": False}
    _write(root / f".merak/runs/{RUN_ID}.skills.json", cloned_trace)
    report = {"status": "incomplete", "accepted": False, "snapshot_path": str(root),
              "phases": {node: phase["status"] for node, phase in copied["phases"].items()},
              "real_model_execution": True, "training_authorized": False, "original_workflow_resumed": False,
              "scientific_inputs_unchanged": True, "original_inputs_unchanged": True, "blocked_operations": [],
              "source_specialist_snapshot": {"source_plan_sha256": plan_hash},
              "upstream_readonly_revalidation": {"source_run_state_sha256": source_hash}}
    report_hash = _write(root / ".merak/LIVE_VERIFICATION_REPORT.json", report)
    inputs = {"ideas/SELECTED_IDEA.json": "a" * 64, "experiments/results/frozen.csv": "b" * 64}
    return {"root": root, "original": original, "repository": repository,
            "inputs": inputs, "scientific": scientific_digest(inputs), "report": report_hash, "trace": trace_hash}


def _validate(evidence):
    return validate_resume_identity(evidence["root"], evidence["original"], RUN_ID,
                                    evidence["scientific"], evidence["report"], evidence["trace"],
                                    evidence["inputs"], evidence["repository"])


def test_recorded_incomplete_copy_with_exact_archives_can_continue(evidence):
    result = _validate(evidence)
    assert result["source_run_id"] == RUN_ID
    assert result["scientific_inputs_sha256"] == evidence["scientific"]
    assert result["previous_report_sha256"] == evidence["report"]


@pytest.mark.parametrize("mutation", ["science", "report", "archive", "invocation", "trace", "phase", "options", "direction"])
def test_changed_snapshot_evidence_is_refused_before_configuration_or_execution(evidence, mutation):
    root = evidence["root"]
    if mutation == "science":
        evidence["inputs"]["experiments/results/frozen.csv"] = "c" * 64
    elif mutation == "report":
        report = root / ".merak/LIVE_VERIFICATION_REPORT.json"
        report.write_text(report.read_text() + " ", encoding="utf-8")
    elif mutation in {"archive", "invocation"}:
        path = root / (f".merak/snapshot-source-traces/{RUN_ID}.run.original.json" if mutation == "archive"
                       else ".merak/skill-invocations/source.json")
        path.write_text("{}", encoding="utf-8")
    elif mutation == "trace":
        path = root / f".merak/runs/{RUN_ID}.skills.json"
        value = json.loads(path.read_text())
        value["stages"]["results"]["session_id"] = "invented-upstream-execution"
        _write(path, value)
    else:
        path = root / f".merak/runs/{RUN_ID}.json"
        value = json.loads(path.read_text())
        if mutation == "phase":
            value["phases"]["lit"]["accepted_at"] = 999
        elif mutation == "options":
            value["config"]["options"]["run_experiment"] = True
        else:
            value["config"]["direction"] = "different research"
        _write(path, value)
    with pytest.raises(ValueError):
        _validate(evidence)


def test_original_project_cannot_be_used_as_continuation_target(evidence):
    evidence["root"] = evidence["original"]
    with pytest.raises(ValueError, match="isolated copy"):
        _validate(evidence)


def test_extra_frozen_file_cannot_be_silently_added_to_baseline(evidence):
    evidence["inputs"]["experiments/results/new.csv"] = "d" * 64
    with pytest.raises(ValueError, match="pinned frozen"):
        _validate(evidence)


def test_copy_metadata_resolved_outside_root_is_refused_before_diagnostic_write(evidence, monkeypatch):
    root, original = evidence["root"], evidence["original"]
    original_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == root / ".merak":
            return original / ".merak"
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(ValueError, match="escapes"):
        validate_copy_boundary(root)


def test_missing_upstream_stage_on_both_sides_is_not_execution_proof(evidence):
    original, root = evidence["original"], evidence["root"]
    source_path = original / f".merak/runs/{RUN_ID}.skills.json"
    value = json.loads(source_path.read_text())
    value["stages"].pop("results")
    evidence["trace"] = _write(source_path, value)
    _write(root / f".merak/snapshot-source-traces/{RUN_ID}.skills.original.json", value)
    copied_path = root / f".merak/runs/{RUN_ID}.skills.json"
    copied = json.loads(copied_path.read_text())
    copied["stages"].pop("results")
    copied["snapshot_provenance"]["source_trace_sha256"] = evidence["trace"]
    _write(copied_path, copied)
    with pytest.raises(ValueError, match="upstream acceptance or execution"):
        _validate(evidence)


def test_source_trace_drift_cannot_be_replaced_by_current_archive_equality(evidence):
    path = evidence["original"] / f".merak/runs/{RUN_ID}.skills.json"
    changed = json.loads(path.read_text())
    changed["stages"]["results"]["session_id"] = "foreign-session"
    _write(path, changed)
    _write(evidence["root"] / f".merak/snapshot-source-traces/{RUN_ID}.skills.original.json", changed)
    with pytest.raises(ValueError, match="independently recorded digest"):
        _validate(evidence)


def test_hard_linked_copy_file_is_rejected_before_any_write(evidence, monkeypatch):
    target = evidence["root"] / ".merak/LIVE_VERIFICATION_REPORT.json"
    original_stat = Path.stat

    def stat(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path == target:
            return SimpleNamespace(st_nlink=2, st_mode=result.st_mode)
        return result

    monkeypatch.setattr(Path, "stat", stat)
    with pytest.raises(ValueError, match="hard-linked"):
        validate_copy_boundary(evidence["root"])
