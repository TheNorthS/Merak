"""Read-only authorization of genuine progress after pinned local reacceptance.

A new author invocation legitimately changes the copy's state and trace. This
validator never restores an old state: it proves immutable owners and inputs,
then binds the independently observed current state/trace to the prior receipt.
"""

from __future__ import annotations

import copy
import hashlib
import re
import time
from pathlib import Path

from scripts.live_snapshot_reaccept_identity import _pinned_source, _trace_identity
from scripts.live_snapshot_reaccept_receipt import NODES, _checkpoint, _verify_gates
from scripts.live_snapshot_resume_validation import (
    ALLOWED_NODES, UPSTREAM, _config_identity, _json, scientific_digest, validate_copy_boundary,
)


REPOSITORY = Path(__file__).resolve().parents[1]
_AUTHOR_FILES = {"paper/TITLE.txt", "paper/CONTRIBUTION_BLUEPRINT.md"}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _receipt_proof(root: Path, run_id: str, pin: str, science: str, report: str, source_trace: str) -> dict:
    path = root / ".merak/LOCAL_REACCEPT_REPORT.json"
    if _digest(path) != pin:
        raise ValueError("Authorized progress receipt differs from its independent digest")
    receipt = _json(path)
    identity = receipt.get("source_identity") or {}
    if (receipt.get("schema") != 1 or receipt.get("operation") != "genuine_local_reacceptance"
            or receipt.get("run_id") != run_id or receipt.get("snapshot_path") != str(root)
            or receipt.get("accepted") is not True or receipt.get("reaccepted_nodes") != list(NODES)
            or any(receipt.get(key) is not False for key in ("model_invoked", "producer_invoked", "scientific_execution"))
            or identity.get("science_sha256") != science or identity.get("previous_report_sha256") != report
            or identity.get("source_trace_sha256") != source_trace
            or not re.fullmatch(r"[a-f0-9]{64}", str(receipt.get("state_after_sha256") or ""))):
        raise ValueError("Authorized progress lacks a pinned no-model local-verifier identity")
    _checkpoint(root, str(receipt.get("state_checkpoint") or ""), str(receipt.get("state_before_sha256") or ""))
    before = _json(root / receipt["state_checkpoint"])
    if identity.get("state_before_sha256") != receipt["state_before_sha256"]:
        raise ValueError("Local receipt before-state identity is inconsistent")
    historical = copy.deepcopy(before)
    historical["phases"].update(copy.deepcopy(receipt.get("accepted_phases") or {}))
    _verify_gates(root, receipt, historical, root / f".merak/runs/{run_id}.skills.json")
    for relative, expected in (receipt.get("figure_manifests_before_sha256") or {}).items():
        if expected is not None:
            _checkpoint(root, str((receipt.get("figure_manifest_checkpoints") or {}).get(relative) or ""), expected)
    _checkpoint(root, str(receipt.get("specialist_plan_checkpoint") or ""), str(receipt.get("specialist_plan_before_sha256") or ""))
    return receipt


def _historical_acceptance(root: Path, run_id: str, receipt: dict, source: dict, report: dict) -> None:
    before = _json(root / receipt["state_checkpoint"])
    if (before.get("schema") != 1 or before.get("run_id") != run_id or before.get("status") != "incomplete"
            or receipt["source_identity"].get("source_run_state_sha256")
            != _digest(root / f".merak/snapshot-source-traces/{run_id}.run.original.json")):
        raise ValueError("Historical reacceptance checkpoint has a different source owner")
    for node in UPSTREAM:
        phase, original = before["phases"][node], source["phases"][node]
        history = (phase.get("details") or {}).get("acceptance_invalidations") or []
        if (phase.get("status") != "done" or phase.get("accepted_at") is not None or not history
                or report.get("phases", {}).get(node) != "accepted"
                or any(history[-1].get(key) != original.get(key) for key in ("verdict_id", "reviewer", "accepted_at"))):
            raise ValueError("Historical local gates do not follow authentic source acceptance invalidation")
    figure = before["phases"]["figure"]
    history = (figure.get("details") or {}).get("acceptance_invalidations") or []
    from json import loads
    events = [loads(line) for line in (root / f".merak/runs/{run_id}.events.jsonl").read_text(encoding="utf-8").splitlines()]
    accepted = [event.get("data") or {} for event in events if event.get("run_id") == run_id
                and event.get("event") == "node_accepted" and (event.get("data") or {}).get("node_id") == "figure"]
    if (figure.get("status") != "done" or not history or report.get("phases", {}).get("figure") != "accepted"
            or not any(all(history[-1].get(key) == event.get(key) for key in ("verdict_id", "reviewer")) for event in accepted)):
        raise ValueError("Figure local acceptance has no authentic prior copy verifier")


def _upstream_phase_progress(current: dict, recorded: dict, root: Path, science_pin: str) -> list[dict]:
    from scripts.live_snapshot_risk_refresh_validation import validate_risk_signature_refresh

    refresh_proofs = []
    for node in UPSTREAM:
        phase, old = current["phases"][node], recorded[node]
        if {key: value for key, value in phase.items() if key != "details"} != {
            key: value for key, value in old.items() if key != "details"
        }:
            raise ValueError("Authorized progress changed a frozen upstream acceptance identity")
        detail, previous = phase.get("details") or {}, old.get("details") or {}
        runtime = {"node_risk_audit", "acceptance_rebindings"}
        signature_changed = detail.get("risk_audit_validator_signature") != previous.get("risk_audit_validator_signature")
        if signature_changed:
            runtime.add("risk_audit_validator_signature")
        if {key: value for key, value in detail.items() if key not in runtime} != {
            key: value for key, value in previous.items() if key not in runtime
        }:
            raise ValueError("Authorized progress changed upstream scientific acceptance details")
        risk, prior_risk = detail.get("node_risk_audit") or {}, previous.get("node_risk_audit") or {}
        volatile = {"generated_at", "report_path"}
        if {key: value for key, value in risk.items() if key not in volatile} != {
            key: value for key, value in prior_risk.items() if key not in volatile
        } or risk.get("blocking") or any(item.get("severity") == "blocker" for item in risk.get("findings") or []):
            raise ValueError("Authorized progress altered the upstream risk verdict")
        old_history, history = previous.get("acceptance_rebindings") or [], detail.get("acceptance_rebindings") or []
        if history[:len(old_history)] != old_history or any(
            item.get("reason") != "refreshed accepted-phase risk audit cache"
            or item.get("verdict_id") != phase["verdict_id"] or item.get("reviewer") != phase["reviewer"]
            for item in history[len(old_history):]
        ):
            raise ValueError("Authorized progress invented an upstream acceptance rebind")
        if signature_changed:
            refresh_proofs.append(validate_risk_signature_refresh(
                root, node, phase, old, current["config"]["options"], current["input_baseline"], science_pin,
            ))
    return refresh_proofs


def _verified_figure_plan(root: Path, run_id: str, state: dict, trace: dict) -> None:
    """A changed derived plan needs a new complete figure verdict on exact current files."""
    from json import loads
    from server.services.figure_artifacts import figure_artifact_registry

    phase = (state.get("phases") or {}).get("figure") or {}
    details = phase.get("details") or {}
    evidence = details.get("execution_evidence") or {}
    runtime = phase.get("runtime_service")
    records = [item for item in (trace.get("stages", {}).get("figure") or {}).get("runtime_invocations") or []
               if item.get("runtime_service") == runtime]
    trace_path = root / f".merak/runs/{run_id}.skills.json"
    if (phase.get("status") != "accepted" or not phase.get("verdict_id") or not phase.get("reviewer")
            or not isinstance(phase.get("accepted_at"), (int, float)) or phase.get("execution_kind") != "runtime_owned"
            or runtime != "figure_renderers+figure_quality_gate" or not records
            or records[-1].get("status") != "completed" or records[-1].get("execution_verified") is not True
            or records[-1].get("run_id") != run_id or not records[-1].get("operation_id")
            or records[-1].get("updated_at", float("inf")) > phase["accepted_at"]
            or evidence.get("accepted") is not True or evidence.get("issues")
            or evidence.get("runtime_execution_verified") is not True
            or Path(str(evidence.get("trace_path") or "")).resolve() != trace_path):
        raise ValueError("Changed derived figure plan lacks its complete current-runtime acceptance")
    events = [loads(line) for line in (root / f".merak/runs/{run_id}.events.jsonl").read_text(encoding="utf-8").splitlines()]
    accepted = [event for event in events if event.get("run_id") == run_id and event.get("event") == "node_accepted"
                and (event.get("data") or {}).get("node_id") == "figure"]
    if (not accepted or any((accepted[-1].get("data") or {}).get(key) != phase.get(key)
                           for key in ("verdict_id", "reviewer"))
            or not phase["accepted_at"] <= accepted[-1].get("timestamp", 0) <= phase["accepted_at"] + 60):
        raise ValueError("Changed figure plan lacks its actual current acceptance event")
    _current_figure_snapshot(root, details.get("artifact_snapshot") or {})
    valid, issues, _manifest = figure_artifact_registry.validate(root / "figures")
    if not valid:
        raise ValueError("Changed figure plan has unverified physical assets: " + "; ".join(issues[:8]))


def _current_figure_snapshot(root: Path, snapshot: dict) -> None:
    from server.services.workflow_inputs import artifact_state, artifact_state_equal

    required = {"figures/SCIENTIFIC_ASSET_PLAN.json", "figures/FIGURE_SPECS.json", "figures/FIGURE_MANIFEST.json"}
    if not required <= set(snapshot):
        raise ValueError("Changed figure plan has no complete current source/specification snapshot")
    for relative, expected in snapshot.items():
        if not relative.startswith("figures/"):
            continue
        path = (root / relative).resolve()
        if (not path.is_relative_to(root / "figures") or expected.get("kind") != "file"
                or not artifact_state_equal(artifact_state(path), expected)):
            raise ValueError("Changed figure plan or source differs from its latest verified snapshot")


def _frozen_progress(root: Path, receipt: dict, science_pin: str, state: dict, trace: dict, run_id: str) -> set[str]:
    from scripts.verify_live_remaining_snapshot import protected_inputs

    if scientific_digest(protected_inputs(root)) != science_pin:
        raise ValueError("Authorized progress changed frozen scientific input bytes")
    frozen = receipt.get("frozen_inputs_sha256")
    if not isinstance(frozen, dict) or not frozen:
        raise ValueError("Authorized progress receipt lacks a complete frozen input inventory")
    for relative, expected in frozen.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Authorized progress frozen input path escapes its copy")
        if relative.startswith("paper/sections/") or relative in _AUTHOR_FILES:
            continue
        if not path.is_file() or _digest(path) != expected:
            if relative == "figures/SCIENTIFIC_ASSET_PLAN.json" and path.is_file():
                _verified_figure_plan(root, run_id, state, trace)
                continue
            raise ValueError("Authorized progress changed immutable assets or prior model invocation bytes")
    return set(frozen)


def _new_invocations(root: Path, frozen: set[str], trace: dict) -> list[str]:
    verified = []
    for path in (root / ".merak/skill-invocations").glob("*.json"):
        if path.relative_to(root).as_posix() in frozen:
            continue
        record = _json(path)
        skill, session = str(record.get("skill") or ""), str(record.get("session_id") or "")
        owners = [node for node in ALLOWED_NODES if skill in (trace.get("stages", {}).get(node) or {}).get("selected", [])]
        source = (REPOSITORY / "merak-skills" / skill / "SKILL.md").resolve()
        if (not owners or record.get("schema") != 1 or not session or record.get("policy_loaded") is not True
                or record.get("bounded_invocation") is not True or record.get("status") not in {"running", "completed", "failed", "interrupted"}
                or Path(str(record.get("project_path") or "")).resolve() != root
                or not source.is_relative_to(REPOSITORY / "merak-skills")
                or Path(str(record.get("skill_source") or "")).resolve() != source
                or not source.is_file() or _digest(source) != record.get("skill_sha256")
                or source.stat().st_size != record.get("skill_bytes")):
            raise ValueError("Authorized progress includes an unverified or out-of-scope model invocation")
        session_path = root / f".merak/agent-sessions/{session}.json"
        authored = _json(session_path)
        if (authored.get("schema") != 2 or authored.get("session_id") != session
                or not str(authored.get("context_key") or "").endswith(">" + skill)
                or authored.get("tool_policy") != "workflow_artifacts"
                or authored.get("workflow_node_id") not in {"", *owners}):
            raise ValueError("Authorized progress model call lacks its matching bounded session")
        verified.append(session)
    return verified


def _inactive_lease(root: Path, run_id: str) -> None:
    lease = root / ".merak/active-workflow.json"
    if lease.is_file():
        value = _json(lease)
        if value.get("run_id") != run_id or not isinstance(value.get("expires_at"), (int, float)):
            raise ValueError("Authorized progress has a different or malformed project lease")
        if value["expires_at"] > time.time():
            raise ValueError("Authorized progress cannot resume while its project lease is active")


def validate_authorized_progress(root: Path, original: Path, runid: str, local_receipt_pin: str,
                                current_state_pin: str, current_trace_pin: str, science_pin: str,
                                source_trace_pin: str, prior_report_pin: str) -> dict:
    """Require explicit pins for both observed current progress and historical proof."""
    root, original = root.resolve(strict=True), original.resolve(strict=True)
    pins = (local_receipt_pin, current_state_pin, current_trace_pin, science_pin, source_trace_pin, prior_report_pin)
    if (root == original or root.parent != REPOSITORY or not root.name.startswith("live-verification-106-")
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", runid)
            or any(not re.fullmatch(r"[a-f0-9]{64}", pin) for pin in pins)):
        raise ValueError("Authorized progress requires explicit independently observed copy identities")
    validate_copy_boundary(root)
    state_path, trace_path = root / f".merak/runs/{runid}.json", root / f".merak/runs/{runid}.skills.json"
    if _digest(state_path) != current_state_pin or _digest(trace_path) != current_trace_pin:
        raise ValueError("Authorized progress state or execution trace changed from its observed pin")
    _inactive_lease(root, runid)
    source, source_trace, report = _pinned_source(root, original, runid, prior_report_pin, source_trace_pin)
    trace, state = _trace_identity(root, original, runid, source_trace), _json(state_path)
    if (state.get("schema") != 1 or state.get("run_id") != runid or state.get("status") not in {"running", "incomplete", "failed"}
            or state.get("input_baseline") != source.get("input_baseline")
            or set(state.get("phases") or {}) != set(UPSTREAM) | set(ALLOWED_NODES)
            or not set(trace.get("stages") or {}).issubset(set(UPSTREAM) | set(ALLOWED_NODES))):
        raise ValueError("Authorized progress changed pipeline or original input identity")
    _config_identity(state, source, root, original, runid)
    receipt = _receipt_proof(root, runid, local_receipt_pin, science_pin, prior_report_pin, source_trace_pin)
    _historical_acceptance(root, runid, receipt, source, report)
    before = _json(root / receipt["state_checkpoint"])
    if state["config"] != before["config"] or state.get("input_baseline") != before.get("input_baseline"):
        raise ValueError("Authorized progress changed its reaccepted research configuration")
    frozen = _frozen_progress(root, receipt, science_pin, state, trace, runid)
    risk_refresh_proofs = _upstream_phase_progress(state, receipt["accepted_phases"], root, science_pin)
    sessions = _new_invocations(root, frozen, trace)
    return {"source_run_id": runid, "snapshot_path": str(root), "local_acceptance_receipt_sha256": local_receipt_pin,
            "current_state_sha256": current_state_pin, "current_execution_trace_sha256": current_trace_pin,
            "scientific_inputs_sha256": science_pin, "source_execution_trace_sha256": source_trace_pin,
            "previous_report_sha256": prior_report_pin, "authorized_new_model_sessions": sessions,
            "upstream_acceptance_unchanged": True, "risk_cache_refresh_proofs": risk_refresh_proofs,
            "workflow_or_model_invoked_by_validation": False}
