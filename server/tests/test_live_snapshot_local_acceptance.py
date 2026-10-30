"""Local reaccept transaction verifies every gate before standard persistence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import live_snapshot_local_acceptance as local
from server.workflows.engine import WorkflowEngine
from server.workflows.run_state import RunState


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root: Path):
    phases = {node.id: {"id": node.id, "status": "done" if node.id in local.LOCAL_REACCEPT_NODES else "awaiting_revision",
                       "verdict_id": "", "reviewer": "", "accepted_at": None,
                       "details": {"revision": {"round": 0, "history": []},
                                   "acceptance_invalidations": [{"reason": "Derived snapshot changed"}]}}
              for node in WorkflowEngine()._get_default_nodes()}
    run_id = "local-verification-fixture"
    state = root / f".merak/runs/{run_id}.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"schema": 1, "run_id": run_id, "status": "incomplete", "phases": phases,
                                 "config": {"assurance": "draft", "options": {
                                     "run_experiment": False, "non_experiment_evidence_mode": "synthetic_preview"}},
                                 "input_baseline": {"snapshot_id": "frozen-fixture"}}))
    trace = state.with_name(f"{run_id}.skills.json")
    trace.write_text('{"immutable":"existing runtime/model trace fixture"}')
    figures = root / "figures/FIGURE_MANIFEST.json"
    figures.parent.mkdir()
    figures.write_text('{"schema":1,"figures":[]}')
    figures.with_suffix(".md").write_bytes(b"Immutable previous figure listing fixture\n")
    for relative in ("experiments/results/locked.csv", "paper/sections/02_related_work.tex",
                     ".merak/skill-invocations/existing.json", ".merak/snapshot-source-traces/original.json"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"immutable local scientific/authorship fixture\n")
    return run_id, state, trace


def _adapter(monkeypatch, trace, *, defect="", fail_node="results"):
    calls = []

    def gate(_self, node, _run, _assurance, _result, require_fresh):
        assert require_fresh is False
        calls.append(node.id)
        result = {"accepted": True, "verdict_id": f"genuine-fixture-gate:{node.id}", "reviewer": "deterministic:fixture",
                  "details": {"execution_evidence": {"accepted": True, "issues": [], "trace_path": str(trace)},
                              "registered_scientific_identity": node.id}}
        if node.id == fail_node:
            if defect == "gate":
                result["accepted"] = False
            elif defect == "trace":
                result["details"]["execution_evidence"]["trace_path"] = str(trace.parent / "foreign.skills.json")
            elif defect == "evidence":
                result["details"]["execution_evidence"]["accepted"] = False
            elif defect == "identity":
                result["reviewer"] = ""
        return result

    def bind(_self, node, _run, result):
        result["details"]["artifact_snapshot"] = {"owned-fixture": node.id}

    monkeypatch.setattr(local.SnapshotEngine, "_acceptance_gate", gate)
    monkeypatch.setattr(local.SnapshotEngine, "_bind_gate_artifact_snapshot", bind)
    return calls


@pytest.mark.asyncio
async def test_all_seven_complete_gates_commit_new_acceptance_and_exact_checkpoint(tmp_path, monkeypatch):
    run_id, state, trace = _fixture(tmp_path)
    before, trace_bytes = state.read_bytes(), trace.read_bytes()
    prior = json.loads(before)
    calls = _adapter(monkeypatch, trace)
    result = await local.reaccept_current_gates(tmp_path, run_id, _hash(state))
    after = json.loads(state.read_bytes())
    assert calls == list(local.LOCAL_REACCEPT_NODES)
    assert result["accepted"] and result["state_after_sha256"] == _hash(state)
    assert result["state_before_sha256"] == hashlib.sha256(before).hexdigest()
    assert (tmp_path / result["state_checkpoint"]).read_bytes() == before
    assert trace.read_bytes() == trace_bytes
    for node, phase in prior["phases"].items():
        if node not in local.LOCAL_REACCEPT_NODES:
            assert after["phases"][node] == phase
        else:
            current = after["phases"][node]
            assert current["status"] == "accepted" and current["accepted_at"] is not None
            assert current["verdict_id"] == result["gates"][node]["verdict_id"]
            assert current["details"]["acceptance_invalidations"] == phase["details"]["acceptance_invalidations"]
            assert result["accepted_phases"][node] == current
    assert result["model_invoked"] is result["producer_invoked"] is result["scientific_execution"] is False


@pytest.mark.parametrize("defect", ["gate", "trace", "evidence", "identity"])
@pytest.mark.asyncio
async def test_rejected_or_unverified_gate_never_promotes_any_phase(tmp_path, monkeypatch, defect):
    run_id, state, trace = _fixture(tmp_path)
    before = state.read_bytes()
    calls = _adapter(monkeypatch, trace, defect=defect)
    with pytest.raises(ValueError, match="results: complete current gate"):
        await local.reaccept_current_gates(tmp_path, run_id, _hash(state))
    assert state.read_bytes() == before
    assert calls == list(local.LOCAL_REACCEPT_NODES[:6])
    assert (tmp_path / f".merak/transactions/local-reaccept-{hashlib.sha256(before).hexdigest()}.state.original.json").read_bytes() == before


@pytest.mark.asyncio
async def test_partial_standard_accept_failure_rolls_back_only_exact_owned_state(tmp_path, monkeypatch):
    run_id, state, trace = _fixture(tmp_path)
    before = state.read_bytes()
    _adapter(monkeypatch, trace)
    original = RunState.accept
    calls = []

    def fail_after_first(self, node, verdict, reviewer, details):
        calls.append(node)
        if len(calls) == 2:
            raise RuntimeError("finite acceptance persistence failure")
        return original(self, node, verdict, reviewer, details)

    monkeypatch.setattr(RunState, "accept", fail_after_first)
    with pytest.raises(RuntimeError, match="finite acceptance persistence failure"):
        await local.reaccept_current_gates(tmp_path, run_id, _hash(state))
    assert calls == ["lit", "idea"] and state.read_bytes() == before


@pytest.mark.asyncio
async def test_out_of_scope_phase_mutation_is_detected_and_transaction_rolled_back(tmp_path, monkeypatch):
    run_id, state, trace = _fixture(tmp_path)
    before = state.read_bytes()
    _adapter(monkeypatch, trace)
    original = RunState.accept

    def corrupt_unrelated(self, node, verdict, reviewer, details):
        original(self, node, verdict, reviewer, details)
        changed = self.load()
        changed["phases"]["paper"]["status"] = "accepted"
        self.save_state(changed)

    monkeypatch.setattr(RunState, "accept", corrupt_unrelated)
    with pytest.raises(ValueError, match="out-of-scope phase"):
        await local.reaccept_current_gates(tmp_path, run_id, _hash(state))
    assert state.read_bytes() == before


@pytest.mark.asyncio
async def test_gate_cannot_write_science_or_create_a_new_author_invocation(tmp_path, monkeypatch):
    run_id, state, trace = _fixture(tmp_path)
    before = state.read_bytes()
    _adapter(monkeypatch, trace)

    def forbidden_science(*_args, **_kwargs):
        (tmp_path / "experiments/results/locked.csv").write_bytes(b"rewritten")

    monkeypatch.setattr(local.SnapshotEngine, "_bind_gate_artifact_snapshot", forbidden_science)
    with pytest.raises(PermissionError, match="scientific inputs"):
        await local.reaccept_current_gates(tmp_path, run_id, _hash(state))
    assert state.read_bytes() == before
    assert (tmp_path / "experiments/results/locked.csv").read_bytes() == b"immutable local scientific/authorship fixture\n"


@pytest.mark.asyncio
async def test_wrong_state_pin_fails_before_any_gate(tmp_path, monkeypatch):
    run_id, state, trace = _fixture(tmp_path)
    calls = _adapter(monkeypatch, trace)
    with pytest.raises(ValueError, match="pinned stopped copy"):
        await local.reaccept_current_gates(tmp_path, run_id, "0" * 64)
    assert calls == []


@pytest.mark.parametrize("target", ["paper/sections/02_related_work.tex", ".merak/skill-invocations/new.json",
                                    ".merak/agent-sessions/new.json", "figures/diagrams/new.svg"])
@pytest.mark.asyncio
async def test_gate_cannot_author_or_create_execution_journals(tmp_path, monkeypatch, target):
    run_id, state, trace = _fixture(tmp_path)
    before = state.read_bytes()
    _adapter(monkeypatch, trace)
    path = tmp_path / target
    path.parent.mkdir(parents=True, exist_ok=True)
    original = path.read_bytes() if path.is_file() else None

    def forbidden_author(*_args, **_kwargs):
        path.write_bytes(b"A verifier cannot author this")

    monkeypatch.setattr(local.SnapshotEngine, "_bind_gate_artifact_snapshot", forbidden_author)
    with pytest.raises(PermissionError, match="authorship"):
        await local.reaccept_current_gates(tmp_path, run_id, _hash(state))
    assert state.read_bytes() == before
    assert (path.read_bytes() if path.exists() else None) == original


@pytest.mark.asyncio
async def test_figure_manifest_runtime_projection_is_allowed_but_assets_stay_frozen(tmp_path, monkeypatch):
    from server.utils.atomic_write import atomic_write_json, atomic_write_text

    run_id, state, trace = _fixture(tmp_path)
    _adapter(monkeypatch, trace)
    original = local.SnapshotEngine._acceptance_gate
    manifest = tmp_path / "figures/FIGURE_MANIFEST.json"
    old_hash = _hash(manifest)

    def project_runtime(self, node, run, assurance, result, require_fresh):
        gate = original(self, node, run, assurance, result, require_fresh)
        if node.id == "figure":
            atomic_write_json(manifest, {"schema": 1, "figures": [], "runtime_projection": "current"})
            atomic_write_text(manifest.with_suffix(".md"), "Current derived runtime figure listing\n")
        return gate

    monkeypatch.setattr(local.SnapshotEngine, "_acceptance_gate", project_runtime)
    result = await local.reaccept_current_gates(tmp_path, run_id, _hash(state))
    assert result["figure_manifests_before_sha256"]["figures/FIGURE_MANIFEST.json"] == old_hash
    assert result["figure_manifests_after_sha256"]["figures/FIGURE_MANIFEST.json"] == _hash(manifest)
    for name in local._RUNTIME_FIGURE_MANIFESTS:
        archived = tmp_path / result["figure_manifest_checkpoints"][name]
        assert _hash(archived) == result["figure_manifests_before_sha256"][name]


@pytest.mark.asyncio
async def test_failed_figure_gate_rolls_back_partial_runtime_manifest_projection(tmp_path, monkeypatch):
    from server.utils.atomic_write import atomic_write_json, atomic_write_text

    run_id, state, trace = _fixture(tmp_path)
    _adapter(monkeypatch, trace)
    original = local.SnapshotEngine._acceptance_gate
    manifest = tmp_path / "figures/FIGURE_MANIFEST.json"
    before_state, before_manifest = state.read_bytes(), manifest.read_bytes()
    before_listing = manifest.with_suffix(".md").read_bytes()

    def partial_projection(self, node, run, assurance, result, require_fresh):
        gate = original(self, node, run, assurance, result, require_fresh)
        if node.id == "figure":
            atomic_write_json(manifest, {"schema": 1, "figures": [], "partial": True})
            atomic_write_text(manifest.with_suffix(".md"), "Partial runtime listing\n")
            gate["accepted"] = False
        return gate

    monkeypatch.setattr(local.SnapshotEngine, "_acceptance_gate", partial_projection)
    with pytest.raises(ValueError, match="figure: complete current gate"):
        await local.reaccept_current_gates(tmp_path, run_id, _hash(state))
    assert state.read_bytes() == before_state and manifest.read_bytes() == before_manifest
    assert manifest.with_suffix(".md").read_bytes() == before_listing


@pytest.mark.asyncio
async def test_changed_registered_figure_hash_blocks_before_any_gate_or_metadata_write(tmp_path, monkeypatch):
    run_id, state, trace = _fixture(tmp_path)
    calls = _adapter(monkeypatch, trace)
    source = tmp_path / "figures/registered.svg"
    source.write_bytes(b"actual frozen figure source bytes")
    manifest = tmp_path / "figures/FIGURE_MANIFEST.json"
    manifest.write_text(json.dumps({"schema": 1, "figures": [{"id": "registered",
        "source_path": "figures/registered.svg", "source_sha256": "0" * 64, "metadata": {}}]}))
    before_state, before_manifest, before_source = state.read_bytes(), manifest.read_bytes(), source.read_bytes()
    with pytest.raises(ValueError, match="changed source/output hashes"):
        await local.reaccept_current_gates(tmp_path, run_id, _hash(state))
    assert calls == []
    assert state.read_bytes() == before_state and manifest.read_bytes() == before_manifest
    assert source.read_bytes() == before_source
