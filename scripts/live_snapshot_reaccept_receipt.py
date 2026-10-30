"""Validate new local verdicts by pinned full gates, checkpoint and actual state."""

from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.live_snapshot_resume_validation import _json, scientific_digest


NODES = ("lit", "idea", "novelty", "exp-design", "exp-run", "results", "figure")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_local_receipt(root: Path, run_id: str, receipt_pin: str, copied: dict,
                            science_pin: str, prior_report_pin: str, source_trace_pin: str) -> dict:
    path = root / ".merak/LOCAL_REACCEPT_REPORT.json"
    if _digest(path) != receipt_pin:
        raise ValueError("Local acceptance receipt differs from its independently recorded digest")
    receipt = _json(path)
    identity = receipt.get("source_identity") or {}
    if (receipt.get("schema") != 1 or receipt.get("operation") != "genuine_local_reacceptance"
            or receipt.get("run_id") != run_id or receipt.get("snapshot_path") != str(root)
            or receipt.get("accepted") is not True or receipt.get("reaccepted_nodes") != list(NODES)
            or receipt.get("model_invoked") is not False or receipt.get("producer_invoked") is not False
            or receipt.get("scientific_execution") is not False
            or identity.get("science_sha256") != science_pin
            or identity.get("previous_report_sha256") != prior_report_pin
            or identity.get("source_trace_sha256") != source_trace_pin):
        raise ValueError("Local receipt is not bound to the explicit no-model source identity")
    state_path = root / f".merak/runs/{run_id}.json"
    trace_path = root / f".merak/runs/{run_id}.skills.json"
    if (receipt.get("state_after_sha256") != _digest(state_path)
            or receipt.get("execution_trace_sha256") != _digest(trace_path)):
        raise ValueError("Copied state or execution trace changed after genuine local acceptance")
    checkpoint = (root / str(receipt.get("state_checkpoint") or "")).resolve()
    if (not checkpoint.is_relative_to(root / ".merak/transactions") or not checkpoint.is_file()
            or _digest(checkpoint) != receipt.get("state_before_sha256")):
        raise ValueError("Local acceptance lacks its exact before-state transaction checkpoint")
    from scripts.live_snapshot_reaccept_identity import _invalidated_phases
    before_state = _json(checkpoint)
    source = _json(root / f".merak/snapshot-source-traces/{run_id}.run.original.json")
    report = _json(root / ".merak/LIVE_VERIFICATION_REPORT.json")
    _invalidated_phases(root, run_id, before_state, source, report)
    if (identity.get("state_before_sha256") != receipt.get("state_before_sha256")
            or identity.get("source_run_state_sha256") != _digest(root / f".merak/snapshot-source-traces/{run_id}.run.original.json")
            or before_state.get("schema") != 1 or before_state.get("run_id") != run_id
            or before_state.get("status") != "incomplete" or before_state.get("config") != copied.get("config")
            or before_state.get("input_baseline") != copied.get("input_baseline")):
        raise ValueError("Local receipt before-state does not match its pinned stopped source identity")
    for node, phase in before_state["phases"].items():
        if node not in NODES and (copied.get("phases") or {}).get(node) != phase:
            raise ValueError("Local acceptance receipt changed an out-of-scope phase")
    plan = root / f".merak/runs/{run_id}.specialists.json"
    if _digest(plan) != receipt.get("specialist_plan_after_sha256"):
        raise ValueError("Reused specialist source binding changed after local acceptance")
    _verify_derived_checkpoints(root, receipt)
    _verify_gates(root, receipt, copied, trace_path)
    _verify_frozen(root, receipt, science_pin)
    return receipt


def _checkpoint(root: Path, relative: str, expected: str) -> None:
    path = (root / relative).resolve()
    if not path.is_relative_to(root / ".merak/transactions") or not path.is_file() or _digest(path) != expected:
        raise ValueError("Local receipt is missing an exact derived-artifact transaction checkpoint")


def _verify_derived_checkpoints(root: Path, receipt: dict) -> None:
    _checkpoint(root, str(receipt.get("specialist_plan_checkpoint") or ""),
                 str(receipt.get("specialist_plan_before_sha256") or ""))
    before = receipt.get("figure_manifests_before_sha256") or {}
    after = receipt.get("figure_manifests_after_sha256") or {}
    checkpoints = receipt.get("figure_manifest_checkpoints") or {}
    expected = {"figures/FIGURE_MANIFEST.json", "figures/FIGURE_MANIFEST.md"}
    if set(before) != expected or set(after) != expected or set(checkpoints) != expected:
        raise ValueError("Local receipt does not bind both figure registration artifacts")
    for relative in sorted(expected):
        path = root / relative
        if after[relative] != (_digest(path) if path.is_file() else None):
            raise ValueError("Figure registration changed after genuine local acceptance")
        if before[relative] is not None:
            _checkpoint(root, str(checkpoints[relative]), str(before[relative]))
        elif checkpoints[relative] is not None:
            raise ValueError("Local receipt invented a previously missing figure sidecar")


def _verify_gates(root: Path, receipt: dict, copied: dict, trace_path: Path) -> None:
    gates, recorded = receipt.get("gates") or {}, receipt.get("accepted_phases") or {}
    if set(gates) != set(NODES) or set(recorded) != set(NODES):
        raise ValueError("Local acceptance receipt does not contain every authorized gate")
    for node in NODES:
        gate, phase = gates[node], (copied.get("phases") or {}).get(node) or {}
        evidence = (gate.get("details") or {}).get("execution_evidence") or {}
        if (gate.get("accepted") is not True or evidence.get("accepted") is not True or evidence.get("issues")
                or Path(str(evidence.get("trace_path") or "")).resolve() != trace_path
                or not gate.get("verdict_id") or not gate.get("reviewer") or phase != recorded[node]
                or phase.get("status") != "accepted" or phase.get("verdict_id") != gate["verdict_id"]
                or phase.get("reviewer") != gate["reviewer"] or not phase.get("accepted_at")):
            raise ValueError(f"{node}: persisted acceptance does not match a complete current local gate")


def _verify_frozen(root: Path, receipt: dict, science_pin: str) -> None:
    from scripts.verify_live_remaining_snapshot import protected_inputs

    if scientific_digest(protected_inputs(root)) != science_pin:
        raise ValueError("Scientific input bytes changed after local reacceptance")
    frozen = receipt.get("frozen_inputs_sha256")
    if not isinstance(frozen, dict) or not frozen:
        raise ValueError("Local receipt has no frozen authorship and execution input inventory")
    for relative, expected in frozen.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or _digest(path) != expected:
            raise ValueError("A frozen authored file or model invocation changed after local reacceptance")
