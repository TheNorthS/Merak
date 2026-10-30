"""Atomic commit protocol for scientific audit and proof-checker results."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import structlog

from ..utils.atomic_write import path_lock
from .review_models import AuditResult, AuditSourceChangedError, Verdict

logger = structlog.get_logger()


def save_audit_results(
    results: list[AuditResult], project_path: str, evidence_mode: str = "executed", *,
    run_id: str = "", expected_source_bundle_sha256: str = "",
    expected_audit_runtime_signature: str = "",
    expected_reviewer_route_sha256: str = "",
    expected_policy_sha256: dict[int, str] | None = None,
    proof_detector: Callable[[str], Optional[AuditResult]],
) -> None:
    root = Path(project_path).expanduser().resolve()
    contract = _current_contract(root)
    expected = _expected_contract(
        contract, expected_source_bundle_sha256,
        expected_audit_runtime_signature, expected_reviewer_route_sha256,
        expected_policy_sha256,
    )
    _validate_contract(contract, expected, during="execution")
    scientific, proof = _partition_results(results, root, proof_detector)
    data = _scientific_payload(
        scientific, evidence_mode, contract
    )
    proof_hash, proof_inputs, _, _, _ = _api().proof_source_bundle(root)
    proof.audited_input_hashes = proof_inputs
    proof_payload = _proof_payload(
        proof, run_id, evidence_mode, proof_hash, proof_inputs, contract
    )
    _commit_bundle(
        root, data, proof, proof_payload, proof_hash, proof_inputs,
        evidence_mode, run_id, expected,
    )
    persisted = [*scientific, proof]
    all_pass = all(
        item.verdict in (Verdict.PASS, Verdict.NOT_APPLICABLE) for item in persisted
    )
    has_fail = any(
        item.verdict in (Verdict.FAIL, Verdict.BLOCKED, Verdict.ERROR)
        for item in persisted
    )
    logger.info(
        "Audit chain complete",
        summary="ALL_PASS" if all_pass else "BLOCKED" if has_fail else "WARNINGS",
    )


def _api() -> Any:
    from . import review_audit

    return review_audit


def _current_contract(root: Path) -> dict[str, Any]:
    api = _api()
    source_hash, source_paths = api.audit_source_bundle(root)
    runtime = api.audit_runtime_attestation()
    route = api.audit_reviewer_route()
    route_hash = api.audit_reviewer_route_sha256(route)
    policies = {
        layer: api.audit_policy_sha256(skill)
        for layer, skill in api.AUDIT_LAYER_SKILLS.items()
    }
    return {
        "source_hash": source_hash, "source_paths": source_paths,
        "runtime": runtime, "runtime_signature": str(runtime.get("signature") or ""),
        "route": route, "route_hash": route_hash, "policies": policies,
    }


def _expected_contract(
    current: dict[str, Any], source_hash: str, runtime_signature: str,
    route_hash: str, policies: dict[int, str] | None,
) -> dict[str, Any]:
    return {
        "source_hash": source_hash or current["source_hash"],
        "runtime_signature": runtime_signature or current["runtime_signature"],
        "route_hash": route_hash or current["route_hash"],
        "policies": dict(policies) if isinstance(policies, dict)
        else dict(current["policies"]),
    }


def _validate_contract(
    current: dict[str, Any], expected: dict[str, Any], *, during: str
) -> None:
    if current["source_hash"] != expected["source_hash"]:
        raise AuditSourceChangedError(
            f"audit source bundle changed during {during}; refusing to commit"
        )
    if (
        current["runtime_signature"] != expected["runtime_signature"]
        or current["route_hash"] != expected["route_hash"]
        or current["policies"] != expected["policies"]
    ):
        raise RuntimeError(
            f"audit policy, runtime, or reviewer route changed during {during}; refusing to commit"
        )


def _partition_results(
    results: list[AuditResult], root: Path,
    proof_detector: Callable[[str], Optional[AuditResult]],
) -> tuple[list[AuditResult], AuditResult]:
    scientific = sorted(
        (item for item in results if item.layer in range(1, 6)),
        key=lambda item: item.layer,
    )
    proof = next(
        (item for item in results
         if item.layer == 6 or item.skill_name == "proof-checker"),
        None,
    ) or proof_detector(str(root))
    if proof is None:
        _, inputs, _, _, _ = _api().proof_source_bundle(root)
        proof = AuditResult(
            layer=6, layer_name="Proof Checker", verdict=Verdict.ERROR,
            summary="Native audit did not produce the required proof-checker result.",
            details={"theorems_audited": 0, "issues": []},
            method="model_error", skill_name="proof-checker",
            policy_loaded=False, reason_code="reviewer_error",
            audited_input_hashes=inputs,
        )
    return scientific, proof


def _scientific_payload(
    results: list[AuditResult], evidence_mode: str, contract: dict[str, Any]
) -> list[dict[str, Any]]:
    return [
        {
            "layer": item.layer, "layer_name": item.layer_name,
            "verdict": item.verdict.value, "summary": item.summary,
            "details": item.details, "evidence": item.evidence,
            "evidence_mode": evidence_mode, "method": item.method,
            "delivery_goal": item.delivery_goal, "draft_blockers": item.draft_blockers,
            "skill_name": item.skill_name, "session_id": item.session_id,
            "policy_loaded": item.policy_loaded,
            "policy_sha256": contract["policies"].get(item.layer, ""),
            "model_name": item.model_name, "trace_path": item.trace_path,
            "managed_by": "merak_audit_chain",
            "audit_runtime_signature": contract["runtime_signature"],
            "reviewer_route_sha256": contract["route_hash"],
        }
        for item in results
    ]


def _proof_payload(
    proof: AuditResult, run_id: str, evidence_mode: str,
    source_hash: str, inputs: dict[str, str], contract: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "schema": 2, "managed_by": "merak_audit_chain",
        "audit_skill": "proof-checker", "run_id": run_id,
        "evidence_mode": evidence_mode, "verdict": proof.verdict.value,
        "reason_code": proof.reason_code, "summary": proof.summary,
        "audited_input_hashes": inputs,
        "proof_source_bundle_sha256": source_hash,
        "trace_path": proof.trace_path, "thread_id": proof.session_id,
        "session_id": proof.session_id, "reviewer_model": proof.model_name,
        "model_name": proof.model_name, "reviewer_reasoning": "provider-configured",
        "policy_loaded": proof.policy_loaded,
        "policy_sha256": contract["policies"].get(6, ""),
        "audit_runtime_signature": contract["runtime_signature"],
        "reviewer_route_sha256": contract["route_hash"],
        "method": proof.method,
        "generated_at": datetime.fromtimestamp(proof.timestamp, tz=timezone.utc).isoformat(),
        "evidence": proof.evidence,
        "details": proof.details if isinstance(proof.details, dict)
        else {"adjudication": str(proof.details or "")},
    }
    payload["proof_semantic_sha256"] = _api().proof_semantic_sha256(
        source_hash, payload
    )
    return payload


def _commit_bundle(
    root: Path, data: list[dict[str, Any]], proof: AuditResult,
    proof_payload: dict[str, Any], proof_source_hash: str,
    proof_inputs: dict[str, str], evidence_mode: str, run_id: str,
    expected: dict[str, Any],
) -> None:
    output_dir = root / "audit-results"
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "AUDIT_RESULTS.json"
    build_path = output_dir / "AUDIT_BUILD.json"
    proof_path = root / "paper" / "PROOF_AUDIT.json"
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    with path_lock(build_path):
        existing_build = _read_existing_object(build_path, "audit commit marker")
        existing_proof, existing_proof_bytes = _read_existing_proof(proof_path)
        preserve = _may_preserve_proof(
            existing_build, existing_proof, existing_proof_bytes,
            proof_payload, proof_source_hash, run_id, evidence_mode,
            expected,
        )
        _validate_contract(_current_contract(root), expected, during="execution")
        _write_json(results_path, data, indent=2)
        if not preserve:
            _write_json(proof_path, proof_payload, indent=2)
        committed = _committed_artifacts(results_path, proof_path, proof_source_hash)
        end = _current_contract(root)
        _validate_end_contract(root, end, expected, proof_source_hash, proof_inputs)
        build = _build_payload(
            root, data, committed, end, proof_source_hash,
            evidence_mode, run_id,
        )
        _write_json(build_path, build, indent=2)
        _invalidate_if_source_changed(root, build_path, expected, end, run_id, evidence_mode)


def _read_existing_object(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Existing {label} is unreadable or corrupt; refusing to overwrite it: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Existing {label} root must be a JSON object; refusing to overwrite it: {path}"
        )
    return payload


def _read_existing_proof(path: Path) -> tuple[dict[str, Any], bytes]:
    if not path.exists():
        return {}, b""
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Existing proof audit is unreadable or corrupt; refusing to overwrite it: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Existing proof audit root must be a JSON object; refusing to overwrite it: {path}"
        )
    return payload, raw


def _may_preserve_proof(
    build: dict[str, Any], proof: dict[str, Any], raw: bytes,
    proposed: dict[str, Any], source_hash: str, run_id: str,
    evidence_mode: str, expected: dict[str, Any],
) -> bool:
    if not raw:
        return False
    api = _api()
    artifact_hash = hashlib.sha256(raw).hexdigest()
    semantic_hash = api.proof_semantic_sha256(source_hash, proof)
    proposed_semantic = str(proposed.get("proof_semantic_sha256") or "")
    try:
        build_schema = int(build.get("schema") or 0)
        proof_schema = int(proof.get("schema") or 0)
    except (TypeError, ValueError):
        return False
    checks = (
        build_schema == api.AUDIT_BUNDLE_SCHEMA, build.get("status") == "complete",
        proof_schema >= 2, str(build.get("run_id") or "") == run_id,
        str(proof.get("run_id") or "") == run_id,
        str(build.get("evidence_mode") or "") == evidence_mode,
        str(proof.get("evidence_mode") or "") == evidence_mode,
        str(build.get("proof_audit_sha256") or "") == artifact_hash,
        str(build.get("proof_source_bundle_sha256") or "") == source_hash,
        str(proof.get("proof_source_bundle_sha256") or "") == source_hash,
        str(build.get("proof_policy_sha256") or "") == expected["policies"].get(6, ""),
        str(proof.get("policy_sha256") or "") == expected["policies"].get(6, ""),
        str(build.get("audit_runtime_signature") or "") == expected["runtime_signature"],
        str(proof.get("audit_runtime_signature") or "") == expected["runtime_signature"],
        str(build.get("reviewer_route_sha256") or "") == expected["route_hash"],
        str(proof.get("reviewer_route_sha256") or "") == expected["route_hash"],
        str(build.get("proof_semantic_sha256") or "") == proposed_semantic,
        str(proof.get("proof_semantic_sha256") or "") == proposed_semantic,
        semantic_hash == proposed_semantic,
    )
    return all(checks)


def _committed_artifacts(
    results_path: Path, proof_path: Path, proof_source_hash: str
) -> dict[str, Any]:
    results_hash = hashlib.sha256(results_path.read_bytes()).hexdigest()
    proof_bytes = proof_path.read_bytes()
    proof_hash = hashlib.sha256(proof_bytes).hexdigest()
    try:
        proof = json.loads(proof_bytes.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Committed proof audit became unreadable: {proof_path}") from exc
    if not isinstance(proof, dict):
        raise RuntimeError(f"Committed proof audit root is not an object: {proof_path}")
    return {
        "results_hash": results_hash, "proof_hash": proof_hash, "proof": proof,
        "proof_semantic_hash": _api().proof_semantic_sha256(proof_source_hash, proof),
    }


def _validate_end_contract(
    root: Path, end: dict[str, Any], expected: dict[str, Any],
    proof_source_hash: str, proof_inputs: dict[str, str],
) -> None:
    _validate_contract(end, expected, during="commit")
    current_proof_hash, current_inputs, _, _, _ = _api().proof_source_bundle(root)
    if current_proof_hash != proof_source_hash or current_inputs != proof_inputs:
        raise AuditSourceChangedError(
            "theorem-bearing sources changed before commit; no acceptable audit build was written"
        )


def _build_payload(
    root: Path, data: list[dict[str, Any]], committed: dict[str, Any],
    contract: dict[str, Any], proof_source_hash: str,
    evidence_mode: str, run_id: str,
) -> dict[str, Any]:
    api = _api()
    proof = committed["proof"]
    layer_contracts = [_layer_contract(item, contract) for item in data]
    layer_contracts.append({
        "layer": 6, "skill_name": "proof-checker",
        "policy_sha256": contract["policies"].get(6, ""),
        "audit_runtime_signature": contract["runtime_signature"],
        "reviewer_route_sha256": contract["route_hash"],
        "reviewer_model": str(proof.get("reviewer_model") or proof.get("model_name") or ""),
        "session_id": str(proof.get("session_id") or proof.get("thread_id") or ""),
        "method": str(proof.get("method") or ""),
        "artifact_sha256": committed["proof_hash"],
    })
    return {
        "schema": api.AUDIT_BUNDLE_SCHEMA, "status": "complete",
        "generated_at": time.time(), "run_id": run_id,
        "source_bundle_sha256": contract["source_hash"],
        "sources": [path.relative_to(root).as_posix() if path.is_relative_to(root)
                    else path.as_posix() for path in contract["source_paths"]],
        "results_sha256": committed["results_hash"],
        "proof_audit_path": "paper/PROOF_AUDIT.json",
        "proof_audit_sha256": committed["proof_hash"],
        "proof_semantic_sha256": committed["proof_semantic_hash"],
        "proof_source_bundle_sha256": proof_source_hash,
        "proof_policy_sha256": contract["policies"].get(6, ""),
        "evidence_mode": evidence_mode,
        "audit_runtime_signature": contract["runtime_signature"],
        "audit_runtime_components": dict(contract["runtime"].get("components") or {}),
        "reviewer_route": contract["route"],
        "reviewer_route_sha256": contract["route_hash"],
        "layer_contracts": layer_contracts,
    }


def _layer_contract(item: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "layer": int(item.get("layer") or 0),
        "skill_name": str(item.get("skill_name") or ""),
        "policy_sha256": str(item.get("policy_sha256") or ""),
        "audit_runtime_signature": contract["runtime_signature"],
        "reviewer_route_sha256": contract["route_hash"],
        "reviewer_model": str(item.get("model_name") or ""),
        "session_id": str(item.get("session_id") or ""),
        "method": str(item.get("method") or ""),
        "result_sha256": _api()._canonical_json_sha256(item),
    }


def _invalidate_if_source_changed(
    root: Path, build_path: Path, expected: dict[str, Any],
    end: dict[str, Any], run_id: str, evidence_mode: str,
) -> None:
    observed, _ = _api().audit_source_bundle(root)
    if observed == expected["source_hash"]:
        return
    _write_json(build_path, {
        "schema": _api().AUDIT_BUNDLE_SCHEMA, "status": "invalidated",
        "generated_at": time.time(), "run_id": run_id,
        "evidence_mode": evidence_mode, "reason": "source_changed_during_commit",
        "expected_source_bundle_sha256": expected["source_hash"],
        "observed_source_bundle_sha256": observed,
        "audit_runtime_signature": end["runtime_signature"],
        "reviewer_route_sha256": end["route_hash"],
    }, indent=2)
    raise AuditSourceChangedError(
        "audit source bundle changed during commit; the audit build was invalidated"
    )


def _write_json(path: Path, payload: Any, **kwargs: Any) -> None:
    """Preserve the public fault-injection hook on review_audit."""
    _api().atomic_write_json(path, payload, **kwargs)
