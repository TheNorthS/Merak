"""Pure revalidation-boundary fixtures, not evidence of actual model acceptance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.live_snapshot_revalidation import UPSTREAM_NODE_IDS, revalidate_upstream_acceptance
from server.workflows.models import WorkflowNode
from server.workflows.run_state import RunState


RUN_ID = "source-current-run"
NODES = (*UPSTREAM_NODE_IDS, "narrative", "figure", "paper", "review", "audit", "compile", "ppt")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class _GateFixtureHost:
    """Fixture gates exercise helper ordering only; production gates are not replaced by the runner."""

    def __init__(self, root: Path):
        self.root = root
        self.checked = []
        self.bound = []
        self.refused = ""
        self.unverified_execution = ""
        self.on_gate = None
        self.on_bind = None

    def _get_default_nodes(self):
        return [WorkflowNode(id=node, name=node, skill="fixture") for node in NODES]

    def _acceptance_gate(self, node, run, assurance, result, *, require_fresh):
        assert require_fresh is False
        assert run.id == RUN_ID and Path(run.project_path) == self.root
        assert len(run.nodes) == 13 and run.options["run_experiment"] is False
        assert assurance == "draft" and result == ""
        self.checked.append(node.id)
        if self.on_gate is not None:
            self.on_gate(node.id)
        return {"accepted": node.id != self.refused, "details": {
            "execution_evidence": {"accepted": node.id != self.unverified_execution, "issues": [],
                                   "trace_path": str(self.root / f".merak/runs/{RUN_ID}.skills.json")},
            "execution_gate_applied": True,
            "revision": {"must_not_overwrite_source_history": True},
            "acceptance_rebindings": [],
        }}

    def _bind_gate_artifact_snapshot(self, node, run, gate):
        assert self.checked == list(UPSTREAM_NODE_IDS)
        self.bound.append(node.id)
        if self.on_bind is not None:
            self.on_bind(node.id)
        gate["details"]["artifact_snapshot"] = {"fixture-owned-input": {"kind": "file", "sha256": "current-fixture"}}
        gate["details"]["input_baseline_snapshot_id"] = run.input_baseline["snapshot_id"]


@pytest.fixture
def copied_run(tmp_path):
    original, root = tmp_path / "source", tmp_path / "copy"
    state = {"schema": 1, "run_id": RUN_ID, "status": "cancelled",
             "config": {"assurance": "draft", "direction": "fixture", "options": {
                 "run_experiment": False, "non_experiment_evidence_mode": "synthetic_preview"}},
             "input_baseline": {"snapshot_id": "source-baseline", "entries": []},
             "phases": {node: {"status": "accepted" if node in UPSTREAM_NODE_IDS else "pending",
                                "verdict_id": f"source-{node}", "reviewer": "source-verifier", "accepted_at": 1,
                                "details": {"revision": {"history": ["original revision history"]},
                                            "acceptance_rebindings": [{"reason": "source history"}]}}
                        for node in NODES}}
    relative = f".merak/runs/{RUN_ID}"
    for project in (original, root):
        _write_json(project / f"{relative}.json", state)
        for directory in ("ideas", "literature", "experiments"):
            path = project / directory / "immutable.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"source {directory}", encoding="utf-8")
    trace = {"schema": 2, "run_id": RUN_ID, "project_path": str(original),
             "stages": {node: {"node_id": node, "invocations": [{"session_id": f"source-session-{node}"}]}
                        for node in UPSTREAM_NODE_IDS}}
    _write_json(original / f"{relative}.skills.json", trace)
    trace_bytes = (original / f"{relative}.skills.json").read_bytes()
    archive = root / f".merak/snapshot-source-traces/{RUN_ID}.skills.original.json"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(trace_bytes)
    trace["project_path"] = str(root)
    trace["snapshot_provenance"] = {"source_trace_sha256": hashlib.sha256(trace_bytes).hexdigest()}
    _write_json(root / f"{relative}.skills.json", trace)
    return original, root, _GateFixtureHost(root)


def _evidence_bytes(original, root):
    return {path: path.read_bytes() for project in (original, root)
            for path in project.rglob("*") if path.is_file()}


def test_all_current_fixture_gates_precede_binding_and_only_refresh_existing_acceptance(copied_run):
    original, root, host = copied_run
    before = _evidence_bytes(original, root)
    state_path = root / f".merak/runs/{RUN_ID}.json"
    initial = json.loads(state_path.read_text())
    result = revalidate_upstream_acceptance(host, root, original, RUN_ID)
    state = json.loads(state_path.read_text())
    assert host.checked == host.bound == list(UPSTREAM_NODE_IDS)
    assert result["phase_statuses_changed"] is False and result["new_model_invocation"] is False
    assert result["scientific_inputs_unchanged"] and result["source_and_current_execution_traces_unchanged"]
    assert state["status"] == initial["status"]
    for node in NODES:
        phase, previous = state["phases"][node], initial["phases"][node]
        if node not in UPSTREAM_NODE_IDS:
            assert phase == previous
            continue
        for key in ("status", "verdict_id", "reviewer", "accepted_at"):
            assert phase[key] == previous[key]
        assert phase["details"]["revision"] == previous["details"]["revision"]
        assert phase["details"]["acceptance_rebindings"][0] == {"reason": "source history"}
        provenance = phase["details"]["snapshot_upstream_revalidation"]
        assert provenance["current_acceptance_gate_passed"] and provenance["source_run_execution_verified"]
        assert not provenance["new_model_invocation"] and not provenance["scientific_execution_performed"]
    assert Path(result["original_run_archive"]).read_bytes() == before[original / f".merak/runs/{RUN_ID}.json"]
    assert all(path.read_bytes() == content for path, content in before.items() if path != state_path)


@pytest.mark.parametrize("node", UPSTREAM_NODE_IDS)
def test_one_refused_gate_leaves_every_phase_and_trace_untouched_without_binding(copied_run, node):
    original, root, host = copied_run
    host.refused = node
    before = _evidence_bytes(original, root)
    with pytest.raises(ValueError, match="complete acceptance"):
        revalidate_upstream_acceptance(host, root, original, RUN_ID)
    assert not host.bound
    assert _evidence_bytes(original, root) == before


def test_provisional_hybrid_gate_cannot_replace_verified_current_execution(copied_run):
    original, root, host = copied_run
    host.unverified_execution = "exp-design"
    before = _evidence_bytes(original, root)
    with pytest.raises(ValueError, match="source-run execution"):
        revalidate_upstream_acceptance(host, root, original, RUN_ID)
    assert not host.bound and _evidence_bytes(original, root) == before


@pytest.mark.parametrize("status", ["done", "pending", "awaiting_revision", "failed"])
def test_helper_never_promotes_an_unaccepted_phase(copied_run, status):
    original, root, host = copied_run
    state_path = root / f".merak/runs/{RUN_ID}.json"
    state = json.loads(state_path.read_text())
    state["phases"]["results"]["status"] = status
    _write_json(state_path, state)
    before = _evidence_bytes(original, root)
    with pytest.raises(ValueError, match="already accepted"):
        revalidate_upstream_acceptance(host, root, original, RUN_ID)
    assert not host.checked and not host.bound and _evidence_bytes(original, root) == before


@pytest.mark.parametrize("defect", ["wrong_run", "foreign_project", "source_digest", "upstream_stage", "source_archive"])
def test_wrong_or_modified_source_trace_fails_before_any_gate_or_state_write(copied_run, defect):
    original, root, host = copied_run
    path = root / f".merak/runs/{RUN_ID}.skills.json"
    trace = json.loads(path.read_text())
    if defect == "wrong_run":
        trace["run_id"] = "foreign-run"
    elif defect == "foreign_project":
        trace["project_path"] = str(original)
    elif defect == "source_digest":
        trace["snapshot_provenance"]["source_trace_sha256"] = "changed"
    elif defect == "upstream_stage":
        trace["stages"]["results"]["invocations"][0]["session_id"] = "invented-current-session"
    else:
        (root / f".merak/snapshot-source-traces/{RUN_ID}.skills.original.json").write_bytes(b"changed evidence")
    _write_json(path, trace)
    before = _evidence_bytes(original, root)
    with pytest.raises(ValueError, match="immutable source-run trace"):
        revalidate_upstream_acceptance(host, root, original, RUN_ID)
    assert not host.checked and not host.bound and _evidence_bytes(original, root) == before


@pytest.mark.parametrize("field", ["config", "input_baseline", "run_id"])
def test_copy_configuration_and_baseline_cannot_be_rewritten_to_fit_new_evidence(copied_run, field):
    original, root, host = copied_run
    path = root / f".merak/runs/{RUN_ID}.json"
    state = json.loads(path.read_text())
    state[field] = {"changed": True} if field != "run_id" else "foreign-run"
    _write_json(path, state)
    before = _evidence_bytes(original, root)
    with pytest.raises(ValueError, match="identity, pipeline, configuration"):
        revalidate_upstream_acceptance(host, root, original, RUN_ID)
    assert not host.checked and _evidence_bytes(original, root) == before


@pytest.mark.parametrize("target", ["experiments/immutable.txt", "ideas/immutable.txt", "literature/immutable.txt",
                                    f".merak/runs/{RUN_ID}.json", f".merak/runs/{RUN_ID}.skills.json"])
def test_scientific_phase_and_trace_writes_are_rejected_before_they_happen(copied_run, target):
    original, root, host = copied_run
    host.on_gate = lambda _node: (root / target).write_bytes(b"forbidden mutation")
    before = _evidence_bytes(original, root)
    with pytest.raises(PermissionError, match="cannot mutate"):
        revalidate_upstream_acceptance(host, root, original, RUN_ID)
    assert not host.bound and _evidence_bytes(original, root) == before
    # A completed/failed helper leaves no active guard outside its own scope.
    (root / "experiments/immutable.txt").write_text("fixture-only write after helper exits")


def test_original_project_is_readonly_even_if_a_gate_attempts_to_mutate_it(copied_run):
    original, root, host = copied_run
    host.on_gate = lambda _node: (original / "ideas/immutable.txt").write_bytes(b"forbidden original mutation")
    before = _evidence_bytes(original, root)
    with pytest.raises(PermissionError, match="outside its copy"):
        revalidate_upstream_acceptance(host, root, original, RUN_ID)
    assert not host.bound and _evidence_bytes(original, root) == before


def test_existing_different_original_run_archive_is_never_overwritten(copied_run):
    original, root, host = copied_run
    archive = root / f".merak/snapshot-source-traces/{RUN_ID}.run.original.json"
    archive.write_bytes(b"different immutable evidence")
    before = _evidence_bytes(original, root)
    with pytest.raises(ValueError, match="already contains different bytes"):
        revalidate_upstream_acceptance(host, root, original, RUN_ID)
    assert not host.checked and not host.bound and _evidence_bytes(original, root) == before


def test_identical_existing_archive_is_reused_without_overwriting_it(copied_run):
    original, root, host = copied_run
    archive = root / f".merak/snapshot-source-traces/{RUN_ID}.run.original.json"
    source = original / f".merak/runs/{RUN_ID}.json"
    archive.write_bytes(source.read_bytes())
    before = archive.stat().st_mtime_ns
    revalidate_upstream_acceptance(host, root, original, RUN_ID)
    assert archive.read_bytes() == source.read_bytes() and archive.stat().st_mtime_ns == before


def test_persistence_failure_rolls_back_all_copied_phase_changes(copied_run, monkeypatch):
    original, root, host = copied_run
    state_path = root / f".merak/runs/{RUN_ID}.json"
    initial = state_path.read_bytes()
    original_refresh = RunState.refresh_accepted_details
    calls = []

    def fail_second_refresh(self, node_id, details, *, reason):
        calls.append(node_id)
        if len(calls) == 2:
            raise OSError("fixture persistence failure")
        return original_refresh(self, node_id, details, reason=reason)

    monkeypatch.setattr(RunState, "refresh_accepted_details", fail_second_refresh)
    with pytest.raises(OSError, match="fixture persistence failure"):
        revalidate_upstream_acceptance(host, root, original, RUN_ID)
    assert calls == ["lit", "idea"] and state_path.read_bytes() == initial
    assert (root / f".merak/snapshot-source-traces/{RUN_ID}.run.original.json").read_bytes() == initial


def test_bind_stage_cannot_mutate_scientific_inputs_after_all_gates_pass(copied_run):
    original, root, host = copied_run
    host.on_bind = lambda _node: (root / "experiments/immutable.txt").write_bytes(b"forbidden binding write")
    before = _evidence_bytes(original, root)
    with pytest.raises(PermissionError, match="scientific inputs"):
        revalidate_upstream_acceptance(host, root, original, RUN_ID)
    assert host.checked == list(UPSTREAM_NODE_IDS)
    assert _evidence_bytes(original, root) == before
