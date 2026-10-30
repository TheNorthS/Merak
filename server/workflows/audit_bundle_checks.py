"""Composable integrity checks for a committed audit bundle."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..utils.atomic_write import path_lock
from .review_models import Verdict


@dataclass
class BundleSnapshot:
    root: Path
    build_path: Path
    results_path: Path
    proof_path: Path
    build_bytes: bytes
    results_bytes: bytes
    proof_bytes: bytes
    build: dict[str, Any]
    entries: list[dict[str, Any]]
    proof: dict[str, Any]


@dataclass
class CurrentContract:
    source_hash: str
    source_paths: list[Path]
    source_names: list[str]
    runtime_signature: str
    runtime_components: dict[str, Any]
    reviewer_route: dict[str, Any]
    reviewer_route_hash: str
    executor_model: str
    reviewer_model: str
    policy_hashes: dict[int, str]


def validate_bundle(
    project_path: str | Path, *, run_id: str = "", evidence_mode: str = "",
    executor_model: str = "", allow_non_model_layers: bool = False,
) -> dict[str, Any]:
    root = Path(project_path).expanduser().resolve()
    issues: list[str] = []
    snapshot = _load_snapshot(root, issues)
    current = _current_contract(root, issues)
    selected_mode = _validate_build_header(
        snapshot, current, run_id, evidence_mode, issues
    )
    entries = _index_layers(snapshot.entries, issues, expected=[1, 2, 3, 4, 5])
    contracts = _index_layers(
        snapshot.build.get("layer_contracts"), issues,
        expected=[1, 2, 3, 4, 5, 6], label="audit build layer contracts",
    )
    scientific_verdicts = _validate_scientific_layers(
        snapshot, current, entries, contracts, selected_mode,
        allow_non_model_layers, issues,
    )
    proof_attestation = _validate_proof(
        snapshot, current, contracts.get(6), run_id, selected_mode,
        executor_model or current.executor_model, issues,
    )
    return _result(
        snapshot, current, entries, scientific_verdicts,
        proof_attestation, issues,
    )


def _api() -> Any:
    from . import review_audit

    return review_audit


def _load_snapshot(root: Path, issues: list[str]) -> BundleSnapshot:
    output = root / "audit-results"
    build_path = output / "AUDIT_BUILD.json"
    results_path = output / "AUDIT_RESULTS.json"
    proof_path = root / "paper" / "PROOF_AUDIT.json"

    def read_all() -> tuple[bytes, bytes, bytes, bytes]:
        return (
            _read_bytes(build_path), _read_bytes(results_path),
            _read_bytes(proof_path), _read_bytes(build_path),
        )

    if output.is_dir():
        with path_lock(build_path):
            build_before, results_bytes, proof_bytes, build_after = read_all()
    else:
        build_before, results_bytes, proof_bytes, build_after = read_all()
    if not build_before:
        issues.append("five-layer audit build attestation is missing")
    elif build_before != build_after:
        issues.append("AUDIT_BUILD.json changed during bundle validation")
    if not results_bytes:
        issues.append("AUDIT_RESULTS.json is missing or empty")
    if not proof_bytes:
        issues.append(
            "proof-checker artifact is missing or invalid: "
            "PROOF_AUDIT.json is missing or empty"
        )
    build = _decode(build_after or build_before, "AUDIT_BUILD.json", {}, issues)
    payload = _decode(results_bytes, "AUDIT_RESULTS.json", [], issues)
    proof = _decode(proof_bytes, "PROOF_AUDIT.json", {}, issues)
    if not isinstance(build, dict):
        issues.append("AUDIT_BUILD.json is not a JSON object")
        build = {}
    if not isinstance(payload, list):
        issues.append("AUDIT_RESULTS.json must be a JSON list")
        payload = []
    if not isinstance(proof, dict):
        issues.append("PROOF_AUDIT.json is not a JSON object")
        proof = {}
    entries = [item for item in payload if isinstance(item, dict)]
    if len(entries) != len(payload):
        issues.append("AUDIT_RESULTS.json contains a non-object layer")
    return BundleSnapshot(
        root, build_path, results_path, proof_path, build_after or build_before,
        results_bytes, proof_bytes, build, entries, proof,
    )


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def _decode(raw: bytes, label: str, default: Any, issues: list[str]) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError):
        issues.append(f"{label} is not valid UTF-8 JSON")
        return default


def _current_contract(root: Path, issues: list[str]) -> CurrentContract:
    api = _api()
    source_hash, source_paths = api.audit_source_bundle(root)
    source_names = [
        path.relative_to(root).as_posix() if path.is_relative_to(root)
        else path.as_posix() for path in source_paths
    ]
    runtime = api.audit_runtime_attestation()
    signature = str(runtime.get("signature") or "")
    components = runtime.get("components")
    components = components if isinstance(components, dict) else {}
    if not signature or any(value == "missing" for value in components.values()):
        issues.append("current audit runtime signature is incomplete")
    try:
        route = api.audit_reviewer_route()
        route_hash = api.audit_reviewer_route_sha256(route)
    except Exception as exc:
        route, route_hash = {}, ""
        issues.append(
            "current audit reviewer route could not be resolved: "
            f"{type(exc).__name__}"
        )
    executor = route.get("executor") if isinstance(route.get("executor"), dict) else {}
    reviewer = route.get("reviewer") if isinstance(route.get("reviewer"), dict) else {}
    executor_model = str(executor.get("model_identity") or "")
    reviewer_model = str(reviewer.get("model_identity") or "")
    if not executor_model or not reviewer_model:
        issues.append("current audit reviewer route has no concrete model identity")
    policies = {
        layer: api.audit_policy_sha256(skill)
        for layer, skill in api.AUDIT_LAYER_SKILLS.items()
    }
    for layer, policy_hash in policies.items():
        if not policy_hash:
            issues.append(f"audit policy /{api.AUDIT_LAYER_SKILLS[layer]} could not be loaded")
    return CurrentContract(
        source_hash, source_paths, source_names, signature, components,
        route, route_hash, executor_model, reviewer_model, policies,
    )


def _validate_build_header(
    snapshot: BundleSnapshot, current: CurrentContract,
    run_id: str, evidence_mode: str, issues: list[str],
) -> str:
    build = snapshot.build
    try:
        schema = int(build.get("schema") or 0)
    except (TypeError, ValueError):
        schema = 0
    expected_schema = _api().AUDIT_BUNDLE_SCHEMA
    if schema != expected_schema:
        issues.append(
            f"audit build schema is unsupported: expected {expected_schema}, found {schema}"
        )
    if build.get("status") != "complete":
        issues.append("audit build commit marker is not complete")
    recorded_run = str(build.get("run_id") or "")
    if not recorded_run:
        issues.append("audit build is missing its workflow run identity")
    elif run_id and recorded_run != run_id:
        issues.append("five-layer audit belongs to a different workflow run")
    recorded_mode = str(build.get("evidence_mode") or "")
    if not recorded_mode:
        issues.append("audit build is missing its evidence mode")
    elif evidence_mode and recorded_mode.casefold() != evidence_mode.casefold():
        issues.append("audit evidence mode does not match the workflow")
    _validate_build_bindings(snapshot, current, issues)
    return evidence_mode or recorded_mode


def _validate_build_bindings(
    snapshot: BundleSnapshot, current: CurrentContract, issues: list[str]
) -> None:
    build = snapshot.build
    source_hash = str(build.get("source_bundle_sha256") or "")
    if not source_hash:
        issues.append("audit build is missing its source bundle hash")
    elif source_hash != current.source_hash:
        issues.append("five-layer audit is stale relative to current sources")
    if build.get("sources") != current.source_names:
        issues.append("audit build source inventory does not match current sources")
    results_hash = hashlib.sha256(snapshot.results_bytes).hexdigest() if snapshot.results_bytes else ""
    expected_results = str(build.get("results_sha256") or "")
    if not expected_results:
        issues.append("audit build is missing its results hash")
    elif expected_results != results_hash:
        issues.append("AUDIT_RESULTS.json does not match AUDIT_BUILD.json")
    if str(build.get("audit_runtime_signature") or "") != current.runtime_signature:
        issues.append("audit runtime signature is missing or stale")
    if build.get("audit_runtime_components") != current.runtime_components:
        issues.append("audit runtime component hashes are missing or stale")
    if build.get("reviewer_route") != current.reviewer_route:
        issues.append("audit reviewer route is missing or stale")
    if str(build.get("reviewer_route_sha256") or "") != current.reviewer_route_hash:
        issues.append("audit reviewer route signature is missing or stale")


def _index_layers(
    raw: Any, issues: list[str], *, expected: list[int],
    label: str = "five-layer audit",
) -> dict[int, dict[str, Any]]:
    items = [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    numbers: list[int] = []
    indexed: dict[int, dict[str, Any]] = {}
    for item in items:
        try:
            layer = int(item.get("layer") or 0)
        except (TypeError, ValueError):
            layer = 0
        numbers.append(layer)
        if layer and layer not in indexed:
            indexed[layer] = item
    if sorted(numbers) != expected:
        if label == "five-layer audit":
            issues.append("five-layer audit does not contain exactly layers 1-5")
        else:
            issues.append("audit build does not bind exactly layer contracts 1-6")
    return indexed


def _validate_scientific_layers(
    snapshot: BundleSnapshot, current: CurrentContract,
    entries: dict[int, dict[str, Any]], contracts: dict[int, dict[str, Any]],
    evidence_mode: str, allow_non_model: bool, issues: list[str],
) -> list[str]:
    verdicts = []
    for layer in range(1, 6):
        item, contract = entries.get(layer), contracts.get(layer)
        if item is None or contract is None:
            continue
        verdict = str(item.get("verdict") or "").upper()
        verdicts.append(verdict)
        _validate_layer(
            layer, item, contract, current, evidence_mode,
            allow_non_model and item.get("method") != "model", issues,
        )
    return verdicts


def _validate_layer(
    layer: int, item: dict[str, Any], contract: dict[str, Any],
    current: CurrentContract, evidence_mode: str, relaxed: bool,
    issues: list[str],
) -> None:
    api = _api()
    skill = api.AUDIT_LAYER_SKILLS[layer]
    policy_hash = current.policy_hashes[layer]
    verdict = str(item.get("verdict") or "").upper()
    if verdict not in {value.value for value in Verdict}:
        issues.append(f"audit layer {layer} has an invalid verdict")
    checks = (
        (not relaxed and str(item.get("skill_name") or "") != skill,
         f"audit layer {layer} does not identify /{skill}"),
        (item.get("managed_by") != "merak_audit_chain", f"audit layer {layer} is not runtime-managed"),
        (not relaxed and item.get("method") != "model", f"audit layer {layer} lacks an independent model verdict"),
        (not relaxed and item.get("policy_loaded") is not True, f"audit layer {layer} did not load its audit skill"),
        (not relaxed and str(item.get("policy_sha256") or "") != policy_hash, f"audit layer {layer} policy provenance is missing or stale"),
        (str(item.get("audit_runtime_signature") or "") != current.runtime_signature, f"audit layer {layer} runtime signature is missing or stale"),
        (str(item.get("reviewer_route_sha256") or "") != current.reviewer_route_hash, f"audit layer {layer} reviewer route is missing or stale"),
        (bool(evidence_mode) and str(item.get("evidence_mode") or "").casefold() != evidence_mode.casefold(), f"audit layer {layer} has a mismatched evidence mode"),
        (not relaxed and not str(item.get("session_id") or "").strip(), f"audit layer {layer} has no durable session"),
        (not relaxed and not str(item.get("model_name") or "").strip(), f"audit layer {layer} has no model identity"),
        (not str(item.get("summary") or "").strip(), f"audit layer {layer} has no summary"),
    )
    issues.extend(message for failed, message in checks if failed)
    _validate_layer_contract(layer, item, contract, current, skill, policy_hash, relaxed, issues)


def _validate_layer_contract(
    layer: int, item: dict[str, Any], contract: dict[str, Any],
    current: CurrentContract, skill: str, policy_hash: str,
    relaxed: bool, issues: list[str],
) -> None:
    model, session = str(item.get("model_name") or ""), str(item.get("session_id") or "")
    checks = (
        (not relaxed and str(contract.get("skill_name") or "") != skill, f"audit build layer {layer} skill binding is stale"),
        (not relaxed and str(contract.get("policy_sha256") or "") != policy_hash, f"audit build layer {layer} policy binding is stale"),
        (str(contract.get("audit_runtime_signature") or "") != current.runtime_signature, f"audit build layer {layer} runtime binding is stale"),
        (str(contract.get("reviewer_route_sha256") or "") != current.reviewer_route_hash, f"audit build layer {layer} reviewer route binding is stale"),
        (not relaxed and str(contract.get("reviewer_model") or "") != model, f"audit build layer {layer} model binding does not match"),
        (not relaxed and str(contract.get("session_id") or "") != session, f"audit build layer {layer} session binding does not match"),
        (not relaxed and str(contract.get("method") or "") != str(item.get("method") or ""), f"audit build layer {layer} method binding does not match"),
        (str(contract.get("result_sha256") or "") != _api()._canonical_json_sha256(item), f"audit build layer {layer} result binding does not match"),
    )
    issues.extend(message for failed, message in checks if failed)


def _validate_proof(
    snapshot: BundleSnapshot, current: CurrentContract,
    contract: dict[str, Any] | None, run_id: str, evidence_mode: str,
    executor_model: str, issues: list[str],
) -> dict[str, Any]:
    proof_issues, attestation = _api().validate_proof_audit_artifact(
        snapshot.root, run_id=run_id, evidence_mode=evidence_mode,
        executor_model=executor_model, build=snapshot.build,
        proof=snapshot.proof, proof_bytes=snapshot.proof_bytes,
    )
    issues.extend(proof_issues)
    if snapshot.proof:
        if str(snapshot.proof.get("audit_runtime_signature") or "") != current.runtime_signature:
            issues.append("proof audit runtime signature is missing or stale")
        if str(snapshot.proof.get("reviewer_route_sha256") or "") != current.reviewer_route_hash:
            issues.append("proof audit reviewer route is missing or stale")
    if contract is not None:
        _validate_proof_contract(snapshot, current, contract, issues)
    return attestation


def _validate_proof_contract(
    snapshot: BundleSnapshot, current: CurrentContract,
    contract: dict[str, Any], issues: list[str],
) -> None:
    proof = snapshot.proof
    model = str(proof.get("reviewer_model") or proof.get("model_name") or "")
    session = str(proof.get("session_id") or proof.get("thread_id") or "")
    proof_hash = hashlib.sha256(snapshot.proof_bytes).hexdigest() if snapshot.proof_bytes else ""
    checks = (
        (str(contract.get("skill_name") or "") != "proof-checker", "audit build proof layer skill binding is stale"),
        (str(contract.get("policy_sha256") or "") != current.policy_hashes[6], "audit build proof layer policy binding is stale"),
        (str(contract.get("audit_runtime_signature") or "") != current.runtime_signature, "audit build proof layer runtime binding is stale"),
        (str(contract.get("reviewer_route_sha256") or "") != current.reviewer_route_hash, "audit build proof layer reviewer route binding is stale"),
        (str(contract.get("reviewer_model") or "") != model, "audit build proof layer model binding does not match"),
        (str(contract.get("session_id") or "") != session, "audit build proof layer session binding does not match"),
        (str(contract.get("method") or "") != str(proof.get("method") or ""), "audit build proof layer method binding does not match"),
        (str(contract.get("artifact_sha256") or "") != proof_hash, "audit build proof layer artifact binding does not match"),
    )
    issues.extend(message for failed, message in checks if failed)


def _result(
    snapshot: BundleSnapshot, current: CurrentContract,
    entries: dict[int, dict[str, Any]], scientific: list[str],
    proof: dict[str, Any], issues: list[str],
) -> dict[str, Any]:
    proof_verdict = str(proof.get("verdict") or "").upper()
    verdicts = [*scientific, *([proof_verdict] if proof_verdict else [])]
    blocking = [value for value in verdicts
                if value in {Verdict.FAIL.value, Verdict.BLOCKED.value, Verdict.ERROR.value}]
    warning_count = sum(value == Verdict.WARN.value for value in verdicts)
    unique = list(dict.fromkeys(issues))
    return {
        "valid": not unique, "accepted": not unique and not blocking,
        "issues": unique,
        "blocking_issues": ["audit gate blocked by verdicts: " + ", ".join(blocking)] if blocking else [],
        "advisories": ["submission audit retains warnings that require author review: " + ", ".join(verdicts)] if warning_count else [],
        "warning_count": warning_count, "entries": snapshot.entries,
        "build": snapshot.build, "proof_payload": snapshot.proof, "proof": proof,
        "scientific_verdicts": scientific, "verdicts": verdicts,
        "blocking_verdicts": blocking, "layers": sorted(entries),
        "source_bundle_sha256": current.source_hash,
        "source_count": len(current.source_paths),
        "audit_runtime_signature": current.runtime_signature,
        "reviewer_route": current.reviewer_route,
        "reviewer_route_sha256": current.reviewer_route_hash,
        "paths": {
            "results": str(snapshot.results_path), "build": str(snapshot.build_path),
            "proof": str(snapshot.proof_path),
        },
    }
