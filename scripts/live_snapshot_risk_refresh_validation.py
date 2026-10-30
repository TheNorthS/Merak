"""Prove one changed accepted-risk cache stamp without changing acceptance.

Historical and saved stamps name earlier implementations, not the current one.
Only a fresh, read-only audit with identical complete semantics proves reuse;
scientific inputs, registered snapshots and every copy file remain unchanged.
"""

from __future__ import annotations

import copy
import hashlib
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path

from scripts.live_snapshot_resume_validation import scientific_digest
from scripts.local_acceptance_scope import local_reacceptance_scope


_RISK_VOLATILE = frozenset({"generated_at", "report_path"})


def risk_semantic_report(report: dict, node: str) -> dict:
    """Exclude only the audit clock and optional persistence destination."""
    if not isinstance(report, dict):
        raise ValueError("Risk cache refresh requires an object-shaped report")
    counts = report.get("counts") or {}
    findings = report.get("findings")
    if (type(report.get("schema")) is not int or report.get("schema") != 1 or report.get("node_id") != node
            or report.get("blocking") is not False or not isinstance(counts, dict)
            or type(counts.get("blocker")) is not int or counts.get("blocker") != 0
            or not isinstance(findings, list) or any(
                not isinstance(item, dict) or item.get("severity") == "blocker" for item in findings)):
        raise ValueError("Risk cache refresh lacks a complete nonblocking node report")
    if any(type(counts.get(level)) is not int or counts[level] < 0
           or counts[level] != sum(item.get("severity") == level for item in findings)
           for level in ("blocker", "warning", "info")):
        raise ValueError("Risk cache refresh has inconsistent risk counters")
    return {key: value for key, value in report.items() if key not in _RISK_VOLATILE}


@contextmanager
def _readonly_files():
    """Reject and record side effects even when a validator catches the error."""
    active = True
    denied = []

    def audit(event: str, arguments: tuple) -> None:
        if not active:
            return
        if event == "open":
            _path, mode, flags = arguments
            writing = isinstance(mode, str) and any(item in mode for item in "wax+")
            if writing or isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
                denied.append(event)
                raise PermissionError("Risk cache reinspection cannot write any file")
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.link", "os.symlink",
                       "os.chmod", "os.utime", "os.system", "os.exec", "os.posix_spawn",
                       "subprocess.Popen", "socket.connect", "socket.getaddrinfo", "socket.gethostbyname"}:
            denied.append(event)
            raise PermissionError("Risk cache reinspection cannot mutate files or execute a producer")

    sys.addaudithook(audit)
    try:
        yield denied
    finally:
        active = False


def _copy_hashes(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


@contextmanager
def _permission_errors(denied: list[str]):
    """Observe earlier audit refusals while preserving an existing debugger trace."""
    previous = sys.gettrace()
    handlers, restorations = {}, {}

    def trace(frame, event, argument):
        if frame not in restorations:
            restorations[frame] = frame.f_trace
        if event == "exception" and issubclass(argument[0], PermissionError):
            denied.append("PermissionError")
        handler = handlers.get(frame, previous if event == "call" else None)
        if handler is not None:
            local = handler(frame, event, argument)
            if local is not None and not callable(local):
                raise ValueError("Risk reinspection cannot safely chain the existing exception tracer")
            handlers[frame], restorations[frame] = local, local
        return trace

    sys.settrace(trace)
    try:
        yield
        if sys.gettrace() is not trace:
            raise ValueError("Risk reinspection changed its exception-observation scope")
    finally:
        sys.settrace(previous)
        for frame, handler in restorations.items():
            frame.f_trace = handler
        handlers.clear()
        restorations.clear()


def _science_hash(files: dict[str, str]) -> str:
    return scientific_digest({name: value for name, value in files.items()
                              if name.startswith(("ideas/", "literature/", "experiments/"))})


def _source_hashes() -> dict[str, str]:
    from server.services.risk_validator_sources import risk_validator_source_paths

    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in risk_validator_source_paths(Path(__file__).resolve().parents[1] / "server/services")}


def _signature_history(phase: dict, previous: dict) -> tuple[str, str]:
    details, old = phase.get("details") or {}, previous.get("details") or {}
    prior, current = old.get("risk_audit_validator_signature"), details.get("risk_audit_validator_signature")
    history, prior_history = details.get("acceptance_rebindings") or [], old.get("acceptance_rebindings") or []
    if (not all(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) for value in (prior, current))
            or prior == current or details.get("risk_audit_bound") is not True or old.get("risk_audit_bound") is not True
            or not isinstance(history, list) or not isinstance(prior_history, list)
            or len(history) <= len(prior_history) or history[:len(prior_history)] != prior_history
            or any(not isinstance(item, dict) or item.get("reason") != "refreshed accepted-phase risk audit cache"
                   or item.get("verdict_id") != phase.get("verdict_id")
                   or item.get("reviewer") != phase.get("reviewer") for item in history[len(prior_history):])):
        raise ValueError("Changed risk cache signature lacks its exact accepted-phase refresh history")
    return prior, current


def _current_snapshot(root: Path, node: str, phase: dict, input_baseline: dict, host) -> None:
    from server.workflows.artifact_snapshot_ownership import owner_snapshot_view

    details = phase.get("details") or {}
    input_id = input_baseline.get("snapshot_id")
    snapshot = owner_snapshot_view(node, details.get("artifact_snapshot"))
    if (not input_id or details.get("input_baseline_snapshot_id") != input_id
            or not isinstance(snapshot, dict) or not snapshot):
        raise ValueError("Risk cache reinspection requires its current content-bound input and outputs")
    if any(not (root / relative).resolve().is_relative_to(root) for relative in snapshot):
        raise ValueError("Risk cache reinspection snapshot escapes its copy")
    issues = host._artifact_snapshot_issues(str(root), snapshot)
    if issues:
        raise ValueError("Risk cache reinspection changed accepted artifacts: " + "; ".join(issues[:8]))


def validate_risk_signature_refresh(root: Path, node: str, phase: dict, previous: dict,
                                    options: dict, input_baseline: dict, science_pin: str) -> dict:
    """Reinspect current contracts without writing state or claiming a new verdict."""
    prior, saved = _signature_history(phase, previous)
    old_semantic = risk_semantic_report((previous.get("details") or {}).get("node_risk_audit") or {}, node)
    current_semantic = risk_semantic_report((phase.get("details") or {}).get("node_risk_audit") or {}, node)
    if old_semantic != current_semantic:
        raise ValueError("Risk cache refresh changed its historical risk semantics")
    root, audit_options = root.resolve(strict=True), copy.deepcopy(options)
    with _readonly_files() as denied, local_reacceptance_scope():
        from server.services.node_risk_audit import node_risk_audit_service
        from server.workflows.engine import WorkflowEngine

        before, sources = _copy_hashes(root), _source_hashes()
        if _science_hash(before) != science_pin:
            raise ValueError("Risk cache reinspection changed frozen scientific inputs")
        host = object.__new__(WorkflowEngine)
        implementation = host._risk_audit_validator_signature(options)
        with _permission_errors(denied):
            _current_snapshot(root, node, phase, input_baseline, host)
            report = node_risk_audit_service.audit_node(root, node, audit_options, persist=False)
        if risk_semantic_report(report, node) != current_semantic:
            raise ValueError("Fresh current risk audit differs from its accepted risk verdict")
        if denied:
            raise ValueError("Risk cache reinspection attempted forbidden side effects")
        if (_copy_hashes(root) != before or _source_hashes() != sources or options != audit_options
                or host._risk_audit_validator_signature(options) != implementation):
            raise ValueError("Risk cache reinspection changed copy files, validator sources or options")
    return {"node_id": node, "historical_cache_implementation_sha256": prior,
            "saved_cache_implementation_sha256": saved, "current_validator_implementation_sha256": implementation,
            "current_risk_semantics_unchanged": True, "current_content_bound_snapshot_valid": True,
            "scientific_inputs_sha256": science_pin, "copy_files_unchanged": True,
            "acceptance_identity_changed": False, "model_or_producer_invoked": False}
