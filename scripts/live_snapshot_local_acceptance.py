"""Reaccept seven existing copy artifacts through genuine local gates only.

This is not a workflow or producer run. Source/copy identity authorization is
checked by the caller; this transaction pins the exact current state, preserves
all execution bytes and authorship, and commits only after every gate passes.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from scripts.live_snapshot_revalidation import _readonly_research_inputs, _scientific_inputs
from scripts.verify_figure_snapshot import SnapshotEngine
from scripts.verify_offline_suite import canonical_io_path
from server.utils.atomic_write import atomic_write_bytes, path_lock
from server.workflows.models import WorkflowRun
from server.workflows.run_state import RunState


LOCAL_REACCEPT_NODES = ("lit", "idea", "novelty", "exp-design", "exp-run", "results", "figure")
_HISTORY_FIELDS = {"revision", "acceptance_rebindings", "acceptance_invalidations", "research_loop_rebuilds"}
_READONLY_DIRECTORIES = (".merak/snapshot-source-traces", ".merak/skill-invocations", ".merak/agent-sessions",
                        "paper/sections", "figures")
_READONLY_PAPER_FILES = ("paper/TITLE.txt", "paper/CONTRIBUTION_BLUEPRINT.md", "paper/references.bib")
_RUNTIME_FIGURE_MANIFESTS = ("figures/FIGURE_MANIFEST.json", "figures/FIGURE_MANIFEST.md")


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _frozen_files(root: Path) -> dict[str, str]:
    """Preserve scientific inputs, source archives, existing calls and authored sections."""
    result = _scientific_inputs(root)
    for directory in _READONLY_DIRECTORIES:
        result.update({path.relative_to(root).as_posix(): _digest(path.read_bytes())
                       for path in (root / directory).rglob("*") if path.is_file()
                       and path.relative_to(root).as_posix() not in _RUNTIME_FIGURE_MANIFESTS})
    for relative in _READONLY_PAPER_FILES:
        path = root / relative
        if path.is_file():
            result[relative] = _digest(path.read_bytes())
    return result


def _runtime_manifest_target(root: Path, path: Path) -> bool:
    return any(path == root / name or (
        path.parent == (root / name).parent
        and re.fullmatch(r"\." + re.escape(Path(name).name) + r"\.\d+\.\d+\.[a-f0-9]{32}\.tmp", path.name)
    ) for name in _RUNTIME_FIGURE_MANIFESTS)


def _figure_checkpoint(root: Path) -> dict[Path, bytes | None]:
    from server.services.figure_artifacts import figure_artifact_registry

    if not (root / _RUNTIME_FIGURE_MANIFESTS[0]).is_file():
        raise ValueError("Local figure reaccept requires its current registered figure manifest")
    accepted, issues, _payload = figure_artifact_registry.validate(root / "figures")
    if not accepted:
        raise ValueError("Local figure reaccept refuses changed source/output hashes: " + "; ".join(issues[:8]))
    return {root / name: (root / name).read_bytes() if (root / name).is_file() else None
            for name in _RUNTIME_FIGURE_MANIFESTS}


@contextmanager
def _readonly_authorship(root: Path):
    """A local verifier cannot create sessions, alter an authored section or redraw assets."""
    active = True

    def check(value: Any) -> None:
        if isinstance(value, (str, bytes, os.PathLike)):
            path = canonical_io_path(value)
            if _runtime_manifest_target(root, path):
                return
            if any(path.is_relative_to(root / name) for name in _READONLY_DIRECTORIES) or any(
                path == root / name for name in _READONLY_PAPER_FILES
            ):
                raise PermissionError("Local reaccept cannot mutate authorship, figures or execution journals")

    def audit(event: str, args: tuple) -> None:
        if not active:
            return
        if event == "open":
            value, mode, flags = args
            if (isinstance(mode, str) and any(item in mode for item in "wax+")) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
            ):
                check(value)
        elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.utime"}:
            check(args[0])
        elif event in {"os.rename", "os.link", "os.symlink"}:
            for value in args[:2]:
                check(value)

    sys.addaudithook(audit)
    try:
        yield
    finally:
        active = False


def _load_context(root: Path, run_id: str, expected: str) -> tuple[RunState, bytes, dict, WorkflowRun]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id) or not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise ValueError("Local reaccept requires a stable run ID and pinned current state digest")
    durable = RunState(str(root), run_id)
    before = durable.path.read_bytes()
    state = json.loads(before.decode("utf-8-sig"))
    if (_digest(before) != expected or not isinstance(state, dict) or state.get("schema") != 1
            or state.get("run_id") != run_id or state.get("status") not in {"incomplete", "failed"}):
        raise ValueError("Local reaccept state differs from its independently pinned stopped copy")
    phases = state.get("phases") or {}
    if any((phases.get(node) or {}).get("status") not in {"done", "accepted"} for node in LOCAL_REACCEPT_NODES):
        raise ValueError("Local reaccept cannot run an unproduced or pending upstream node")
    config = state.get("config") or {}
    options = dict(config.get("options") or {})
    if options.get("run_experiment") is not False or options.get("non_experiment_evidence_mode") != "synthetic_preview":
        raise ValueError("Local reaccept cannot authorize scientific execution or evidence changes")
    host = SnapshotEngine()
    run = WorkflowRun(id=run_id, project_path=str(root), options=options, nodes=host._get_default_nodes(),
                      input_baseline=dict(state.get("input_baseline") or {}))
    return durable, before, state, run


def _checked_gates(host: Any, run: WorkflowRun, assurance: str, trace: Path) -> list[tuple[Any, dict]]:
    gates = []
    for node_id in LOCAL_REACCEPT_NODES:
        node = next(item for item in run.nodes if item.id == node_id)
        gate = host._acceptance_gate(node, run, assurance, "", require_fresh=False)
        evidence = (gate.get("details") or {}).get("execution_evidence") or {}
        if (gate.get("accepted") is not True or not gate.get("verdict_id") or not gate.get("reviewer")
                or evidence.get("accepted") is not True or evidence.get("issues")
                or Path(str(evidence.get("trace_path") or "")).resolve() != trace):
            raise ValueError(f"{node_id}: complete current gate, exact-copy execution and verifier identity must pass")
        gates.append((node, copy.deepcopy(gate)))
    return gates


def _assert_frozen(root: Path, trace: Path, trace_bytes: bytes, frozen: dict[str, str]) -> None:
    if trace.read_bytes() != trace_bytes or _frozen_files(root) != frozen:
        raise ValueError("Scientific, authored or immutable execution inputs changed during local reaccept")


def _commit_acceptance(durable: RunState, run: WorkflowRun, gates: list[tuple[Any, dict]], before_state: dict) -> dict:
    started = time.time()
    for node, gate in gates:
        details = {key: copy.deepcopy(value) for key, value in gate["details"].items() if key not in _HISTORY_FIELDS}
        durable.accept(node.id, str(gate["verdict_id"]), str(gate["reviewer"]), details)
    after = durable.load() or {}
    for node_id, phase in before_state["phases"].items():
        current = after.get("phases", {}).get(node_id)
        if node_id not in LOCAL_REACCEPT_NODES:
            if current != phase:
                raise ValueError("Local reaccept changed an out-of-scope phase")
        elif (current.get("status") != "accepted" or not isinstance(current.get("accepted_at"), (int, float))
              or current["accepted_at"] < started or current["accepted_at"] == phase.get("accepted_at")
              or (current.get("details") or {}).get("acceptance_invalidations")
              != (phase.get("details") or {}).get("acceptance_invalidations")):
            raise ValueError("Local reaccept did not persist fresh acceptance with preserved invalidation history")
    protected = {key: value for key, value in before_state.items() if key not in {"phases", "updated_at"}}
    if (set(after) - {"phases", "updated_at"} != set(protected)
            or any(after.get(key) != value for key, value in protected.items())):
        raise ValueError("Local reaccept changed stopped lifecycle or scientific configuration")
    return after


async def reaccept_current_gates(root: Path, run_id: str, expected_state_sha256: str) -> dict[str, Any]:
    """Commit actual local verifier verdicts atomically; never fabricate old acceptance."""
    root = root.resolve(strict=True)
    durable, before, state, run = _load_context(root, run_id, expected_state_sha256)
    host = SnapshotEngine()
    trace = root / f".merak/runs/{run_id}.skills.json"
    trace_bytes, frozen = trace.read_bytes(), _frozen_files(root)
    with path_lock(durable.path), path_lock(root / _RUNTIME_FIGURE_MANIFESTS[0]), _readonly_research_inputs(root, durable.path, trace) as allow_state_write, _readonly_authorship(root):
        if durable.path.read_bytes() != before:
            raise ValueError("Local reaccept state changed before the transaction lock")
        manifest_before = _figure_checkpoint(root)
        checkpoint = root / f".merak/transactions/local-reaccept-{_digest(before)}.state.original.json"
        if checkpoint.exists() and checkpoint.read_bytes() != before:
            raise ValueError("Local reaccept checkpoint conflicts with its exact pinned state")
        if not checkpoint.exists():
            atomic_write_bytes(checkpoint, before)
        manifest_checkpoints = {}
        for path, content in manifest_before.items():
            archived = checkpoint.with_name(checkpoint.stem + "." + path.name + ".original")
            if content is not None:
                if archived.exists() and archived.read_bytes() != content:
                    raise ValueError("Local reaccept manifest checkpoint conflicts with its original bytes")
                atomic_write_bytes(archived, content)
            manifest_checkpoints[path.relative_to(root).as_posix()] = archived.relative_to(root).as_posix() if content is not None else None
        try:
            gates = _checked_gates(host, run, str((state.get("config") or {}).get("assurance") or "draft"), trace)
            for node, gate in gates:
                host._bind_gate_artifact_snapshot(node, run, gate)
            _assert_frozen(root, trace, trace_bytes, frozen)
            if durable.path.read_bytes() != before:
                raise ValueError("A local gate unexpectedly mutated phase state before commit")
            allow_state_write[0] = True
            after = _commit_acceptance(durable, run, gates, state)
            _assert_frozen(root, trace, trace_bytes, frozen)
            after_bytes = durable.path.read_bytes()
        except BaseException:
            allow_state_write[0] = True
            atomic_write_bytes(durable.path, before)
            for path, content in manifest_before.items():
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write_bytes(path, content)
            raise
    return {"schema": 1, "operation": "genuine_local_reacceptance", "run_id": run_id,
            "snapshot_path": str(root), "accepted": True, "reaccepted_nodes": list(LOCAL_REACCEPT_NODES),
            "state_before_sha256": _digest(before), "state_after_sha256": _digest(after_bytes),
            "state_checkpoint": checkpoint.relative_to(root).as_posix(),
            "figure_manifest_checkpoints": manifest_checkpoints,
            "execution_trace_sha256": _digest(trace_bytes), "frozen_inputs_sha256": frozen,
            "figure_manifests_before_sha256": {path.relative_to(root).as_posix(): _digest(content)
                                                if content is not None else None for path, content in manifest_before.items()},
            "figure_manifests_after_sha256": {path.relative_to(root).as_posix(): _digest(path.read_bytes())
                                               if path.is_file() else None for path in manifest_before},
            "gates": {node.id: gate for node, gate in gates},
            "accepted_phases": {node: copy.deepcopy(after["phases"][node]) for node in LOCAL_REACCEPT_NODES},
            "model_invoked": False, "producer_invoked": False, "scientific_execution": False}
