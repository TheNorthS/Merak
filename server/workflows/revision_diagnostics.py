"""Preserve complete gate findings and producer ownership across checkpoints."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from typing import Any

from .revision_owner_rules import PATH_OWNER_RULES, PROOF_CONTENT_MARKERS
from ..contracts.repairs import repair_capability_for
from .paper_runtime_failure_diagnostics import (
    is_paper_print_runtime_finding, paper_runtime_failure_classification, print_runtime_observations,
)


def normalize_gate_diagnostics(owner: Any, gate: dict[str, Any]) -> dict[str, Any]:
    details = _mapping(gate.get("details"))
    quality = _mapping(details.get("research_quality"))
    risk = _mapping(details.get("node_risk_audit"))
    implementation = _mapping(details.get("implementation_contract"))
    findings, issues = _collect_findings(owner, gate, details, quality, risk, implementation)
    unique = _deduplicate(findings)
    score = quality.get("score", details.get("score", gate.get("score")))
    threshold = quality.get("threshold", details.get("threshold", gate.get("threshold")))
    target_files = owner._revision_target_files(
        _mapping(gate.get("repair_scope")).get("target_files"),
        quality.get("artifacts"), [item.get("target_files") for item in unique],
        details.get("target_files"), details.get("artifact_paths"),
    )
    return {
        **paper_runtime_failure_classification(gate, details),
        "accepted": bool(gate.get("accepted")),
        "reason": str(gate.get("reason") or ("" if gate.get("accepted") else "acceptance gate failed")),
        "summary": str(gate.get("summary") or ""), "score": score, "threshold": threshold,
        "issues": list(dict.fromkeys(issues)),
        "risk_remediations": list(dict.fromkeys([
            *gate.get("risk_remediations", []),
            *(
                str(item["remediation"]).strip() for item in risk.get("findings", [])
                if isinstance(item, dict) and str(item.get("remediation") or "").strip()
            ),
        ]))[:8],
        "report_path": str(quality.get("report_path") or risk.get("report_path")
                           or details.get("report_path") or details.get("path")
                           or gate.get("report_path") or ""),
        "component_statuses": {
            **_mapping(gate.get("component_statuses")),
            **_component_statuses(quality, implementation),
        },
        "findings": unique,
        "repair_scope": {
            "finding_ids": list(dict.fromkeys(str(item["id"]) for item in unique)),
            "target_files": target_files,
            "asset_ids": owner._revision_asset_ids(
                _mapping(gate.get("repair_scope")).get("asset_ids"),
                [item.get("asset_ids") for item in unique], details,
            ),
        },
    }


def _collect_findings(
    owner: Any, gate: dict[str, Any], details: dict[str, Any], quality: dict[str, Any],
    risk: dict[str, Any], implementation: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    structured = (
        ("gate", gate.get("findings"), "quality"),
        ("gate_details", details.get("findings"), "quality"),
        ("quality", quality.get("findings"), "quality"),
        ("risk_audit", risk.get("findings"), "risk"),
        ("peer_review", details.get("review_findings"), "peer_review"),
    )
    structured_messages = {
        str(message).strip() for _, values, _ in structured
        for finding in _finding_mappings(values)
        for message in (finding.get("message"), finding.get("plain_message"))
        if str(message or "").strip()
    }
    candidates: list[tuple[Any, str, dict[str, Any], str]] = []
    for source, values in (
        ("gate", gate.get("issues")), ("quality", quality.get("issues")),
        ("gate_details", details.get("issues")), ("missing", details.get("missing")),
    ):
        candidates.extend(_candidate_findings(values, source, "quality", structured_messages))
    for source, values, category in (
        *structured,
        ("implementation_contract", implementation.get("issues", []), "implementation"),
    ):
        candidates.extend(_candidate_findings(values, source, category, set()))
    findings, issues = [], []
    for issue, source, raw, category in candidates:
        finding = _normalize_finding(owner, issue, source, raw, category)
        if finding is not None:
            findings.append(finding)
            issues.append(finding["message"])
    if not issues and not gate.get("accepted"):
        summary = str(gate.get("summary") or gate.get("reason") or "").strip()
        finding = _normalize_finding(owner, summary, "gate_summary", {}, "quality")
        if finding is not None:
            findings.append(finding)
            issues.append(finding["message"])
    return findings, issues


def _finding_mappings(values: Any) -> list[dict[str, Any]]:
    if isinstance(values, dict):
        return [values]
    return [item for item in values if isinstance(item, dict)] if isinstance(values, (list, tuple)) else []


def _candidate_findings(
    values: Any, source: str, category: str, structured_messages: set[str],
) -> Iterator[tuple[Any, str, dict[str, Any], str]]:
    if isinstance(values, dict):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return
    for item in values:
        if isinstance(item, dict):
            yield item.get("plain_message") or item.get("message"), source, item, category
        elif str(item).strip().removeprefix("staged-paper: ") not in structured_messages:
            yield item, source, {}, category


def _normalize_finding(
    owner: Any, issue: Any, source: str, raw: dict[str, Any], category: str,
) -> dict[str, Any] | None:
    message = str(raw.get("plain_message") or raw.get("message") or issue or "").strip()
    if not message:
        return None
    technical = str(raw.get("message") or issue or message).strip()
    finding_id = str(raw.get("id") or raw.get("finding_id") or "").strip()
    if not finding_id:
        stable = owner._stable_revision_finding_text(technical)
        identity = f"{source}:{raw.get('category') or category}:{raw.get('owner_node') or raw.get('upstream_node') or ''}:{stable}"
        digest = hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()[:10]
        finding_id = f"{source.upper().replace('_', '-')}-{digest}"
    explicit = raw.get("target_files")
    targets = (owner._revision_target_files(explicit) if explicit is not None
               else owner._revision_target_files(raw, raw.get("evidence"), technical))
    owner_node, targets = _finding_owner(owner, raw, targets, technical)
    capability = repair_capability_for(
        message=technical,
        target_files=targets,
        category=str(raw.get("category") or category),
        owner_node=owner_node,
    )
    if capability is not None:
        owner_node = capability.owner
    return {
        "id": finding_id, "severity": str(raw.get("severity") or "blocker"),
        "category": str(raw.get("category") or category), "source": str(raw.get("source") or source),
        "message": technical, "plain_message": message,
        "remediation": str(raw.get("remediation") or "").strip(),
        "owner_node": owner_node, "upstream_node": str(raw.get("upstream_node") or "").strip(),
        "label": str(raw.get("label") or "").strip(), "page": raw.get("page"),
        "target_files": targets, "asset_ids": owner._revision_asset_ids(raw, technical),
        "repair_capability": capability.identity if capability else "",
        "validator": capability.validator if capability else "",
        **print_runtime_observations(raw, capability.identity if capability else ""),
        **{key: raw[key] for key in ("stage_id", "reference_key", "changed_inputs", "producer_kind",
                                    "runtime_operation", "required_citations", "current_citations",
                                    "citation_key", "current_verified_citations", "required_unique_citations",
                                    "needed_unique_citations", "available_unused_verified_keys",
                                    "candidate_inventory_is_relevance_recommendation", "legal_write_targets") if key in raw},
    }


def _finding_owner(
    owner: Any, raw: dict[str, Any], targets: list[str], technical: str,
) -> tuple[str, list[str]]:
    owner_node = str(raw.get("owner_node") or raw.get("upstream_node") or "").strip()
    if str(raw.get("id") or "") == "PAPER-STALE-001":
        return "paper", ["paper/DRAFT_STATE.json", "paper/SCIENTIFIC_FREEZE.json"]
    if str(raw.get("category") or "") == "publication_table" and owner_node == "paper":
        return owner_node, targets
    if is_paper_print_runtime_finding(raw, targets):
        return "paper", targets
    if (raw.get("category") == "paper_presentation" and owner_node == "paper"
            and raw.get("producer_kind") == "deterministic" and raw.get("legal_write_targets") == []
            and raw.get("runtime_operation") == "derive_paper_figure" and targets
            and all(path.replace("\\", "/").startswith(("paper/derived-figures/", "paper/assembly-layout/"))
                    for path in targets)):
        return "paper", targets
    normalized = {str(path).replace("\\", "/").casefold() for path in targets}
    projections = {
        "paper/synthetic_preview_figures.tex", "paper/generated_figures.tex",
        "paper/generated_method_figures.tex", "paper/generated_evaluation_figures.tex",
        "paper/generated_result_figures.tex",
    }
    generated_owner = "figure" if normalized.intersection(projections) else (
        "results" if "paper/tables/synthetic_preview_results.tex" in normalized else ""
    )
    table_layout = (str(raw.get("category") or "").casefold() == "visual_layout"
                    and owner_node == "paper" and normalized
                    and all(path.startswith("paper/tables/") and path.endswith(".tex") for path in normalized))
    if generated_owner and owner_node in {"", "paper"} and not table_layout:
        owner_node = generated_owner
    elif normalized:
        inferred = {_target_owner(path, technical) for path in normalized} - {""}
        if len(inferred) == 1:
            owner_node = next(iter(inferred))
    fallback = owner._paper_revision_fallback_targets(technical)
    if not targets and fallback and owner_node in {"", "paper"}:
        owner_node, targets = "paper", fallback
    return owner_node, targets


def _target_owner(path: str, technical: str) -> str:
    path = "/" + path.lstrip("/")
    if path.endswith("/paper/proof_audit.json"):
        return "paper" if any(marker in technical.casefold() for marker in PROOF_CONTENT_MARKERS) else "audit"
    for owner, markers in PATH_OWNER_RULES:
        if any(marker in path for marker in markers):
            return owner
    return ""


def _deduplicate(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique, positions = [], {}
    severity = {"info": 0, "warning": 1, "blocker": 2}
    for finding in findings:
        marker = (str(finding.get("id") or ""), str(finding.get("message") or ""))
        if marker not in positions:
            positions[marker] = len(unique)
            unique.append(finding)
        else:
            index = positions[marker]
            if severity.get(str(finding.get("severity")), 2) > severity.get(
                str(unique[index].get("severity")), 2,
            ):
                unique[index] = finding
    return unique


def _component_statuses(
    quality: dict[str, Any], implementation: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    statuses = {}
    if quality:
        passed = bool(quality.get("passed"))
        score, threshold = quality.get("score"), quality.get("threshold")
        if score is not None and threshold is not None:
            try:
                passed = passed or float(score) >= float(threshold)
            except (TypeError, ValueError):
                passed = bool(quality.get("passed"))
        statuses["content_quality"] = {
            "label": "内容质量", "applicable": bool(quality.get("applicable", True)),
            "passed": passed, "score": score, "threshold": threshold,
            "issues": list(quality.get("issues") or [])[:8],
        }
    if implementation:
        statuses["implementation_contract"] = {
            "label": "实现契约", "applicable": bool(implementation.get("applicable", True)),
            "passed": bool(implementation.get("passed")),
            "summary": str(implementation.get("summary") or ""),
            "issues": list(implementation.get("issues") or [])[:8],
        }
    return statuses


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
