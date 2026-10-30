"""Persist completed audit calls without certifying an incomplete audit bundle."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json
from .review_models import AuditResult, Verdict


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _path(context: Any, contract: dict) -> Path:
    identity = _digest([context.run_id, context.evidence_mode, contract])
    return Path(context.project_path) / ".merak/audit-checkpoints" / f"{identity}.json"


def _trace_hashes(root: Path, result: AuditResult, contract: dict) -> dict[str, str]:
    """Require a successful native reviewer receipt for the exact source and result."""
    if (result.method != "model" or not result.policy_loaded or not result.trace_path
            or not result.session_id or not result.model_name):
        return {}
    directory = (root / result.trace_path).resolve()
    if not directory.is_relative_to((root / ".merak/model-api-reviewer").resolve()):
        return {}
    try:
        files = {name: (directory / name).read_bytes() for name in ("meta.json", "response.txt")}
        meta, response = (json.loads(files[name]) for name in ("meta.json", "response.txt"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(meta, dict) or not isinstance(response, dict):
        return {}
    expected_source = contract["source_hash"]
    if result.delivery_goal == "reviewable_draft":
        from .review_audit import audit_source_bundle
        from .draft_audit_evidence import draft_audit_evidence
        current_hash, paths = audit_source_bundle(root)
        if current_hash != contract["source_hash"]:
            return {}
        expected_source, _, _ = draft_audit_evidence(root, paths, result.skill_name, allow_partition=True)
    batch_hashes = {}
    if (directory / "audit-batches.json").exists():
        from .audit_batch_receipts import verify_batch_receipt
        batch_hashes = verify_batch_receipt(root, directory, expected_source)
        expected_source = meta.get("evidence_packet", {}).get("source_bundle_sha256")
    if (meta.get("success") is not True or meta.get("invocation_id") != result.session_id
            or meta.get("purpose") != f"audit-{result.skill_name}"
            or meta.get("model_identity") != result.model_name
            or meta.get("evidence_packet", {}).get("source_bundle_sha256") != expected_source
            or meta.get("response_sha256") != hashlib.sha256(files["response.txt"]).hexdigest()
            or response.get("verdict") != result.verdict.value or response.get("summary") != result.summary):
        return {}
    return {**{name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}, **batch_hashes}


def load_layer_checkpoints(context: Any, contract: dict) -> dict[int, AuditResult]:
    """Reuse only same-run, same-source, same-policy calls with intact reviewer receipts."""
    if not context.run_id:
        return {}
    path = _path(context, contract)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(payload, dict) or payload.get("schema") != 1
            or payload.get("run_id") != context.run_id or payload.get("contract_hash") != _digest(contract)
            or not isinstance(payload.get("layers"), list)):
        raise ValueError(f"Invalid audit layer checkpoint: {path}")
    from .review_audit import AUDIT_LAYER_SKILLS

    results = {}
    for record in payload["layers"]:
        value = record.get("result", {})
        if record.get("result_hash") != _digest(value):
            continue
        result = AuditResult(**{**value, "verdict": Verdict(value["verdict"])})
        if (result.layer not in AUDIT_LAYER_SKILLS or result.skill_name != AUDIT_LAYER_SKILLS[result.layer]
                or result.verdict not in {Verdict.PASS, Verdict.WARN, Verdict.NOT_APPLICABLE, Verdict.FAIL, Verdict.BLOCKED}):
            continue
        traces = _trace_hashes(Path(context.project_path).resolve(), result, contract)
        if traces and traces == record.get("trace_hashes"):
            results[result.layer] = result
    return results


def save_layer_checkpoints(context: Any, contract: dict, results: list[AuditResult]) -> None:
    """Publish progress after source revalidation; final acceptance still needs all six layers."""
    if not context.run_id:
        return
    from .audit_coordinator import _start_contract
    from .audit_result_store import _validate_contract

    _validate_contract(_start_contract(context.project_path), contract, during="layer checkpoint")
    records = []
    for result in results:
        traces = _trace_hashes(Path(context.project_path).resolve(), result, contract)
        if traces:
            value = {**asdict(result), "verdict": result.verdict.value}
            records.append({"result": value, "result_hash": _digest(value), "trace_hashes": traces})
    if records:
        atomic_write_json(_path(context, contract), {"schema": 1, "run_id": context.run_id,
            "contract_hash": _digest(contract), "layers": records})
