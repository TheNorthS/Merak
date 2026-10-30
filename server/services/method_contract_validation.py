"""Focused validation helpers for method and selected-idea contracts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from .method_contract_evidence import (
    _config_keys,
    _python_structured_data_keys,
    _python_symbols,
    _text_without_comments,
)
from .method_contract_normalization import (
    _normalized,
    _string_list,
    implementation_evidence_register_map,
    normalize_implementation_evidence,
    resolve_implementation_evidence,
)
from .research_contract_versions import METHOD_CONTRACT_SCHEMA


def validate_named_records(
    records: list[Any],
    *,
    label: str,
    required_fields: tuple[str, ...],
) -> tuple[set[str], list[str]]:
    identities: set[str] = set()
    issues: list[str] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            issues.append(f"{label}[{index}] must be an object")
            continue
        identity = str(record.get("id") or "").strip()
        if not identity or any(not str(record.get(field) or "").strip() for field in required_fields):
            fields = ", ".join(("id", *required_fields))
            issues.append(f"{label}[{index}] requires {fields}")
        elif identity in identities:
            issues.append(f"duplicate selected-idea {label[:-1]} id: {identity}")
        identities.add(identity)
    return identities, issues


def _symbol_selector(candidate: Path, values: list[str]) -> tuple[list[str], list[str], str]:
    if candidate.suffix.casefold() == ".py":
        available, error = _python_symbols(candidate)
        available = available | {f"{candidate.stem}.{symbol}" for symbol in available}
        structured, structured_error = _python_structured_data_keys(candidate)
        error = error or structured_error
    else:
        text, error = _text_without_comments(candidate)
        available = set(re.findall(r"[A-Za-z_$][A-Za-z0-9_.$:-]*", text))
        structured = set()
    matched = [value for value in values if value in available]
    aliases = [value for value in values if value not in available and value in structured]
    missing = [value for value in values if value not in available and value not in structured]
    return matched, aliases, error or (", ".join(missing) if missing else "")


def _data_selector(candidate: Path, values: list[str]) -> tuple[list[str], str]:
    if candidate.suffix.casefold() != ".py":
        return [], f"data_keys are supported only for Python evidence: {candidate}"
    available, error = _python_structured_data_keys(candidate)
    matched = [value for value in values if value in available]
    missing = [value for value in values if value not in available]
    return matched, error or (", ".join(missing) if missing else "")


def _anchor_selector(candidate: Path, values: list[str]) -> tuple[list[str], str]:
    text, error = _text_without_comments(candidate)
    if error:
        return [], error
    normalized = _normalized(text)
    matched = [value for value in values if _normalized(value) in normalized]
    missing = [value for value in values if value not in matched]
    return matched, ", ".join(missing)


def _config_selector(candidate: Path, values: list[str]) -> tuple[list[str], str]:
    available, error = _config_keys(candidate)
    matched = [value for value in values if value in available]
    missing = [value for value in values if value not in available]
    return matched, error or (", ".join(missing) if missing else "")


def validate_evidence_selectors(
    candidate: Path,
    check_id: str,
    matched: dict[str, Any],
    selectors: dict[str, list[str]],
) -> list[str]:
    results: dict[str, bool] = {}
    selector_issues: list[str] = []
    for kind, values in selectors.items():
        if not values:
            continue
        if kind == "symbols":
            found, aliases, error = _symbol_selector(candidate, values)
            matched["symbols"] = found
            matched["data_keys"] = list(dict.fromkeys([*matched["data_keys"], *aliases]))
        elif kind == "data_keys":
            found, error = _data_selector(candidate, values)
            matched["data_keys"] = list(dict.fromkeys([*matched["data_keys"], *found]))
        elif kind == "anchors":
            found, error = _anchor_selector(candidate, values)
            matched["anchors"] = found
        else:
            found, error = _config_selector(candidate, values)
            matched["config_keys"] = found
        results[kind] = not error
        if error:
            labels = {
                "symbols": "missing declared symbol(s)",
                "data_keys": "missing declared data/output key(s)",
                "anchors": "missing declared anchor(s)",
                "config_keys": "missing config key(s)",
            }
            selector_issues.append(
                f"{check_id}: {labels[kind]} in {matched['path']}: {error}"
            )
    matched["selector_kinds_passed"] = sorted(kind for kind, passed in results.items() if passed)
    return selector_issues if results and not any(results.values()) else []


def validate_coverage(
    coverage: list[dict[str, Any]],
    idea_ids: set[str],
    check_ids: set[str],
    *,
    allow_planned: bool,
    planned: bool,
) -> tuple[set[str], list[str]]:
    issues: list[str] = []
    covered: set[str] = set()
    if not coverage:
        issues.append("method contract must declare mechanism_coverage")
    for index, item in enumerate(coverage):
        mechanism_id = str(item.get("idea_mechanism_id") or "").strip() if isinstance(item, dict) else ""
        linked = _string_list(item.get("implementation_check_ids")) if isinstance(item, dict) else []
        if mechanism_id not in idea_ids:
            issues.append(f"mechanism_coverage[{index}] references unknown idea mechanism: {mechanism_id or '[empty]'}")
        else:
            covered.add(mechanism_id)
        if not linked and not (allow_planned and planned):
            issues.append(f"mechanism_coverage[{index}] has no implementation_check_ids")
        issues.extend(
            f"mechanism {mechanism_id or '[empty]'} references unknown implementation check: {check_id}"
            for check_id in linked if check_id not in check_ids
        )
    return covered, issues


def validate_claim_plan(
    plan: list[dict[str, Any]],
    idea_ids: set[str],
) -> tuple[set[str], list[str]]:
    issues: list[str] = []
    covered: set[str] = set()
    if not plan:
        issues.append("method contract must declare claim_evidence_plan")
    for index, item in enumerate(plan):
        claim_id = str(item.get("idea_claim_id") or "").strip() if isinstance(item, dict) else ""
        if claim_id not in idea_ids:
            issues.append(f"claim_evidence_plan[{index}] references unknown idea claim: {claim_id or '[empty]'}")
        else:
            covered.add(claim_id)
        if not isinstance(item, dict) or not _string_list(item.get("outcomes")):
            issues.append(f"claim_evidence_plan[{index}] must declare outcomes")
        if not isinstance(item, dict) or not _string_list(item.get("failure_conditions")):
            issues.append(f"claim_evidence_plan[{index}] must declare failure_conditions")
    return covered, issues


def validate_implementation_checks(
    payload: dict[str, Any],
    validate_evidence: Callable[[str, dict[str, Any]], tuple[list[str], dict[str, Any]]],
    *,
    require_checks: bool,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]], list[str]]:
    checks = payload.get("implementation_checks")
    checks = checks if isinstance(checks, list) else []
    issues: list[str] = []
    check_map: dict[str, dict[str, Any]] = {}
    results: dict[str, list[dict[str, Any]]] = {}
    if require_checks and not checks:
        issues.append("method contract must declare implementation_checks")
    register = implementation_evidence_register_map(payload)
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            issues.append(f"implementation_checks[{index}] must be an object")
            continue
        check_id = str(check.get("id") or "").strip()
        description = str(check.get("description") or "").strip()
        if not check_id or not description:
            issues.append(f"implementation_checks[{index}] requires id and description")
            continue
        if check_id in check_map:
            issues.append(f"duplicate implementation check id: {check_id}")
            continue
        check_map[check_id] = check
        evidence_value = resolve_implementation_evidence(check, register.get(check_id))
        evidence_items = normalize_implementation_evidence(evidence_value)
        if not evidence_items:
            issues.append(f"{check_id}: implementation check has no evidence")
            continue
        if isinstance(evidence_value, dict) and not evidence_value.get("path"):
            for field in ("observation", "acceptance_criterion", "evidence_status"):
                if not str(evidence_value.get(field) or "").strip():
                    issues.append(f"{check_id}: structured evidence register requires {field}")
        results[check_id] = []
        for evidence in evidence_items:
            evidence_issues, result = validate_evidence(check_id, evidence)
            issues.extend(evidence_issues)
            results[check_id].append(result)
    return check_map, results, issues


def validate_method_header(
    payload: dict[str, Any],
    *,
    expected_title: str,
    expected_path: str,
    current_idea_hash: str,
    expected_idea_hash: str,
    allow_planned: bool,
) -> tuple[str, bool, list[str]]:
    issues: list[str] = []
    if int(payload.get("schema") or 0) != METHOD_CONTRACT_SCHEMA:
        issues.append(
            "method contract uses an unsupported schema; "
            f"current schema={METHOD_CONTRACT_SCHEMA}"
        )
    status = str(payload.get("status") or "").strip().casefold()
    planned = status == "planned"
    if status not in {"implemented", "ready", "complete"} and not (
        allow_planned and planned
    ):
        issues.append("method contract status must be implemented, ready, or complete")
    if _normalized(payload.get("selected_idea")) != _normalized(expected_title):
        issues.append(f"method contract does not bind the accepted Top-1 idea: {expected_title}")
    if str(payload.get("idea_contract_path") or "").replace("\\", "/") != expected_path:
        issues.append(f"method contract must reference {expected_path}")
    declared_hash = str(payload.get("idea_contract_sha256") or "").strip().casefold()
    if not declared_hash or declared_hash != current_idea_hash.casefold():
        issues.append("method contract idea_contract_sha256 does not match the current accepted idea contract")
    if expected_idea_hash and current_idea_hash.casefold() != expected_idea_hash.casefold():
        issues.append("accepted idea contract changed after the novelty gate; rerun novelty review")
    return status, planned, issues


def validate_evaluation_contract(
    payload: dict[str, Any],
    *,
    root: Path,
    expected_title: str,
) -> list[str]:
    evaluation = payload.get("evaluation_contract")
    issues: list[str] = []
    if not isinstance(evaluation, dict):
        issues.append("method contract must declare evaluation_contract")
        evaluation = {}
    for field in (
        "primary_outcomes", "comparators_or_controls", "component_tests",
        "failure_conditions",
    ):
        if not _string_list(evaluation.get(field)):
            issues.append(f"evaluation_contract.{field} must be a non-empty list")
    plan_path = root / "experiments" / "EXPERIMENT_PLAN.md"
    plan_text = plan_path.read_text(encoding="utf-8", errors="replace") if plan_path.is_file() else ""
    if not plan_path.is_file() or _normalized(expected_title) not in _normalized(plan_text):
        issues.append("experiments/EXPERIMENT_PLAN.md does not bind the accepted Top-1 idea")
    return issues


def method_validation_result(
    *,
    idea_ok: bool,
    issues: list[str],
    path: Path,
    path_hash: str,
    status: str,
    planned: bool,
    expected_title: str,
    idea_details: dict[str, Any],
    check_results: dict[str, list[dict[str, Any]]],
    covered_mechanisms: set[str],
    covered_claims: set[str],
) -> tuple[bool, list[str], dict[str, Any]]:
    unique_issues = list(dict.fromkeys(issues))
    details = {
        "path": str(path), "sha256": path_hash, "status": status,
        "implementation_pending": planned, "selected_idea": expected_title,
        "selected_idea_contract": idea_details,
        "implementation_checks": check_results,
        "covered_mechanism_ids": sorted(covered_mechanisms),
        "covered_claim_ids": sorted(covered_claims),
        "issues": unique_issues,
    }
    return bool(idea_ok and not unique_issues), unique_issues, details
