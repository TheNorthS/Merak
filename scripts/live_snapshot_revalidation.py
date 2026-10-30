"""Recheck already accepted upstream owners in an explicitly authorized copy.

This is not a workflow, a producer rerun, or a persisted-format migration. Every
owner must pass its current complete acceptance and exact source-run execution
gate before existing acceptance details may be rebound. Original run/trace
evidence is immutable; no new phase or model execution is claimed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from scripts.verify_offline_suite import canonical_io_path
from server.utils.atomic_write import atomic_write_bytes, path_lock
from server.workflows.models import WorkflowRun
from server.workflows.run_state import RunState


UPSTREAM_NODE_IDS = ("lit", "idea", "novelty", "exp-design", "exp-run", "results")
_RESEARCH_DIRECTORIES = ("ideas", "literature", "experiments")
_HISTORY_FIELDS = {"revision", "acceptance_rebindings", "acceptance_invalidations", "research_loop_rebuilds"}


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _scientific_inputs(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): _digest(path.read_bytes())
            for directory in _RESEARCH_DIRECTORIES for path in (root / directory).rglob("*")
            if path.is_file()}


@contextmanager
def _readonly_research_inputs(root: Path, state: Path, trace: Path) -> Iterator[list[bool]]:
    """Fail before any scientific write or execution; deactivate the audit on exit."""
    active = True
    allow_state_write = [False]

    def check(value: Any) -> None:
        if isinstance(value, (str, bytes, os.PathLike)):
            target = canonical_io_path(value)
            if not target.is_relative_to(root):
                raise PermissionError("Upstream revalidation cannot mutate paths outside its copy")
            if target == trace or target == state and not allow_state_write[0]:
                raise PermissionError("Upstream acceptance gates cannot mutate phase or execution evidence")
            atomic_sibling = target.name.startswith(".") and target.suffix == ".tmp"
            if target.is_file() and target.is_relative_to(root / ".merak/snapshot-source-traces") and not atomic_sibling:
                raise PermissionError("Upstream revalidation cannot overwrite immutable source archives")
            if any(target.is_relative_to(root / directory) for directory in _RESEARCH_DIRECTORIES):
                raise PermissionError("Upstream revalidation cannot mutate scientific inputs")

    def audit(event: str, arguments: tuple) -> None:
        if not active:
            return
        if event in {"subprocess.Popen", "socket.connect", "socket.getaddrinfo", "socket.gethostbyname"}:
            raise PermissionError("Upstream revalidation cannot execute a process or contact a model")
        if event == "open":
            value, mode, flags = arguments
            if (isinstance(mode, str) and any(flag in mode for flag in "wax+")) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
            ):
                check(value)
        elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.utime"}:
            check(arguments[0])
        elif event in {"os.rename", "os.link", "os.symlink"}:
            for value in arguments[:2]:
                check(value)

    sys.addaudithook(audit)
    try:
        yield allow_state_write
    finally:
        active = False


def _phase_identity(phase: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(phase.get(key) for key in ("status", "verdict_id", "reviewer", "accepted_at"))


def _source_context(host: Any, root: Path, original: Path, run_id: str) -> dict[str, Any]:
    if (root == original or root.is_relative_to(original) or original.is_relative_to(root)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id)):
        raise ValueError("Upstream revalidation requires a distinct isolated copy and stable run identifier")
    relative = f".merak/runs/{run_id}"
    source_path, trace_path = original / f"{relative}.json", root / f"{relative}.skills.json"
    source_bytes = source_path.read_bytes()
    run_archive = root / f".merak/snapshot-source-traces/{run_id}.run.original.json"
    if run_archive.exists() and run_archive.read_bytes() != source_bytes:
        raise ValueError("Immutable source run archive already contains different bytes")
    source = json.loads(source_bytes.decode("utf-8-sig"))
    durable = RunState(str(root), run_id)
    copied = durable.load() or {}
    nodes = host._get_default_nodes()
    expected_nodes = {node.id for node in nodes}
    if (source.get("schema") != 1 or source.get("run_id") != run_id or copied.get("schema") != 1
            or copied.get("run_id") != run_id or len(expected_nodes) != 13
            or set(source.get("phases") or {}) != expected_nodes or set(copied.get("phases") or {}) != expected_nodes
            or copied.get("config") != source.get("config")
            or copied.get("input_baseline") != source.get("input_baseline")):
        raise ValueError("Copied run identity, pipeline, configuration or input baseline differs from its source")
    for node_id in UPSTREAM_NODE_IDS:
        phase = source["phases"][node_id]
        if phase.get("status") != "accepted" or _phase_identity(copied["phases"][node_id]) != _phase_identity(phase):
            raise ValueError(f"{node_id}: only an already accepted source phase may be revalidated")
    source_trace_path = original / f"{relative}.skills.json"
    source_trace_bytes, trace_bytes = source_trace_path.read_bytes(), trace_path.read_bytes()
    source_trace, trace = (json.loads(value.decode("utf-8-sig")) for value in (source_trace_bytes, trace_bytes))
    provenance = trace.get("snapshot_provenance") or {}
    archive = root / f".merak/snapshot-source-traces/{run_id}.skills.original.json"
    if (source_trace.get("schema") != 2 or trace.get("schema") != 2
            or source_trace.get("run_id") != run_id or trace.get("run_id") != run_id
            or Path(str(source_trace.get("project_path") or "")).resolve() != original
            or Path(str(trace.get("project_path") or "")).resolve() != root
            or provenance.get("source_trace_sha256") != _digest(source_trace_bytes)
            or not archive.is_file() or archive.read_bytes() != source_trace_bytes
            or any(not source_trace.get("stages", {}).get(node_id)
                   or trace.get("stages", {}).get(node_id) != source_trace["stages"][node_id]
                   for node_id in UPSTREAM_NODE_IDS)):
        raise ValueError("Copied upstream execution evidence does not match its immutable source-run trace")
    options = dict((copied.get("config") or {}).get("options") or {})
    if options.get("run_experiment") is True:
        raise ValueError("Upstream snapshot revalidation does not authorize scientific execution")
    run = WorkflowRun(id=run_id, project_path=str(root), options=options, nodes=nodes,
                      input_baseline=dict(copied.get("input_baseline") or {}))
    return {"run": run, "durable": durable, "state_bytes": durable.path.read_bytes(),
            "source_path": source_path, "source_bytes": source_bytes,
            "source_trace_path": source_trace_path, "source_trace_bytes": source_trace_bytes,
            "trace_path": trace_path, "trace_bytes": trace_bytes, "assurance": str(copied["config"].get("assurance") or "draft")}


def _assert_unchanged(context: dict[str, Any], root: Path, scientific: dict[str, str]) -> None:
    if (_scientific_inputs(root) != scientific or context["trace_path"].read_bytes() != context["trace_bytes"]
            or context["source_path"].read_bytes() != context["source_bytes"]
            or context["source_trace_path"].read_bytes() != context["source_trace_bytes"]):
        raise ValueError("Scientific inputs or immutable source/current execution evidence changed during revalidation")


def _checked_gates(host: Any, context: dict[str, Any]) -> list[tuple[Any, dict[str, Any]]]:
    run = context["run"]
    gates = []
    for node_id in UPSTREAM_NODE_IDS:
        node = next(node for node in run.nodes if node.id == node_id)
        gate = host._acceptance_gate(node, run, context["assurance"], "", require_fresh=False)
        evidence = (gate.get("details") or {}).get("execution_evidence") or {}
        if (gate.get("accepted") is not True or evidence.get("accepted") is not True or evidence.get("issues")
                or Path(str(evidence.get("trace_path") or "")).resolve() != context["trace_path"]):
            raise ValueError(f"{node_id}: current complete acceptance and source-run execution gates must both pass")
        gates.append((node, gate))
    return gates


def _archive_source_run(root: Path, run_id: str, content: bytes) -> Path:
    archive = root / f".merak/snapshot-source-traces/{run_id}.run.original.json"
    with path_lock(archive):
        if archive.exists():
            if archive.read_bytes() != content:
                raise ValueError("Immutable source run archive already contains different bytes")
        else:
            atomic_write_bytes(archive, content)
    return archive


def _refresh_details(context: dict[str, Any], gates: list[tuple[Any, dict[str, Any]]], archive: Path) -> None:
    durable, run = context["durable"], context["run"]
    for node, gate in gates:
        details = {key: copy.deepcopy(value) for key, value in gate["details"].items() if key not in _HISTORY_FIELDS}
        details["snapshot_upstream_revalidation"] = {
            "source_run_id": run.id, "source_run_state_sha256": _digest(context["source_bytes"]),
            "source_run_state_archive": str(archive.relative_to(Path(run.project_path))),
            "source_trace_sha256": _digest(context["source_trace_bytes"]), "node_id": node.id,
            "current_acceptance_gate_passed": True, "source_run_execution_verified": True,
            "new_model_invocation": False, "scientific_execution_performed": False,
        }
        if not durable.refresh_accepted_details(
            node.id, details, reason="Authorized copy: current complete upstream gate and immutable source-run execution revalidated",
        ):
            raise ValueError(f"{node.id}: accepted phase changed before provenance refresh")


def revalidate_upstream_acceptance(host: Any, root: Path, original: Path, run_id: str) -> dict[str, Any]:
    """Rebind only six already accepted owners after every genuine gate passes.

No phase is promoted and verdict identity/history is preserved. Gate refusal,
input/trace drift, or failed persistence leaves copied phase state untouched.
The original project and archived original run bytes are never overwritten.
"""
    root, original = root.resolve(), original.resolve()
    context = _source_context(host, root, original, run_id)
    durable = context["durable"]
    with path_lock(durable.path), _readonly_research_inputs(root, durable.path, context["trace_path"]) as allow_state_write:
        if durable.path.read_bytes() != context["state_bytes"]:
            raise ValueError("Copied run changed before upstream revalidation acquired its state lock")
        scientific = _scientific_inputs(root)
        gates = _checked_gates(host, context)
        _assert_unchanged(context, root, scientific)
        for node, gate in gates:
            host._bind_gate_artifact_snapshot(node, context["run"], gate)
        _assert_unchanged(context, root, scientific)
        if durable.path.read_bytes() != context["state_bytes"]:
            raise ValueError("An acceptance gate unexpectedly mutated copied phase state")
        archive = _archive_source_run(root, run_id, context["source_bytes"])
        allow_state_write[0] = True
        try:
            _refresh_details(context, gates, archive)
            _assert_unchanged(context, root, scientific)
            initial, current = json.loads(context["state_bytes"].decode("utf-8-sig")), durable.load() or {}
            for node_id, previous in initial["phases"].items():
                updated = current.get("phases", {}).get(node_id, {})
                if (_phase_identity(updated) != _phase_identity(previous)
                        or node_id not in UPSTREAM_NODE_IDS and updated != previous):
                    raise ValueError("Upstream revalidation changed a phase identity or an out-of-scope phase")
        except BaseException:
            atomic_write_bytes(durable.path, context["state_bytes"])
            raise
    return {"revalidated_nodes": list(UPSTREAM_NODE_IDS), "original_run_archive": str(archive),
            "source_run_state_sha256": _digest(context["source_bytes"]), "scientific_inputs_unchanged": True,
            "source_and_current_execution_traces_unchanged": True, "new_model_invocation": False,
            "scientific_execution_performed": False, "phase_statuses_changed": False}
