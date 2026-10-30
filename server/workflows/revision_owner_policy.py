"""Choose the producer responsible for a gate failure without changing artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from .models import WorkflowNode, WorkflowRun
from .revision_owner_rules import (
    BIBLIOGRAPHY_MARKERS,
    DETERMINISTIC_COMPILE_MARKERS,
    PATH_OWNER_RULES,
    PLATFORM_MARKERS,
    PROOF_CONTENT_MARKERS,
    SEMANTIC_OWNER_RULES,
    SOURCE_MARKERS,
    STALE_CONSUMER_MARKERS,
)


class RevisionOwnerHost(Protocol):
    def _gate_revision_diagnostics(self, gate: dict[str, Any]) -> dict[str, Any]: ...
    def _get_default_nodes(self) -> list[WorkflowNode]: ...
    def _find_node(self, run: WorkflowRun, node_id: str) -> WorkflowNode | None: ...
    def _revision_target_files(self, *values: Any) -> list[str]: ...


@dataclass(frozen=True)
class RoutingFacts:
    gate_text: str
    details: dict[str, Any]
    diagnostics: dict[str, Any]
    review_findings: list[dict[str, Any]]
    diagnostic_findings: list[dict[str, Any]]
    risk_findings: list[dict[str, Any]]


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _findings(value: Any) -> list[dict[str, Any]]:
    return (
        [item for item in value if isinstance(item, dict)]
        if isinstance(value, list)
        else []
    )


def _facts(host: RevisionOwnerHost, gate: dict[str, Any]) -> RoutingFacts:
    details = _mapping(gate.get("details"))
    diagnostics = host._gate_revision_diagnostics(gate)
    return RoutingFacts(
        json.dumps(gate, ensure_ascii=False).casefold(),
        details,
        diagnostics,
        _findings(details.get("review_findings")),
        _findings(diagnostics.get("findings")),
        _findings(_mapping(details.get("node_risk_audit")).get("findings")),
    )


def _owner_id(finding: dict[str, Any]) -> str:
    return str(finding.get("upstream_node") or finding.get("owner_node") or "")


def _blockers(
    findings: list[dict[str, Any]], default_severity: str = "blocker"
) -> list[dict[str, Any]]:
    return [
        item
        for item in findings
        if str(item.get("severity") or default_severity) == "blocker"
    ]


def _structured_candidates(
    host: RevisionOwnerHost,
    run: WorkflowRun,
    current: WorkflowNode,
    facts: RoutingFacts,
) -> list[WorkflowNode]:
    owner_ids = {
        _owner_id(item)
        for item in [
            *_blockers(facts.risk_findings, ""),
            *_blockers(facts.review_findings),
            *_blockers(facts.diagnostic_findings),
        ]
        if _owner_id(item)
    }
    by_id = {node.id: node for node in run.nodes}
    canonical = host._get_default_nodes()
    canonical_ids = {node.id for node in canonical}
    candidates = [by_id.get(node.id, node) for node in canonical]
    candidates.extend(node for node in run.nodes if node.id not in canonical_ids)
    seen: set[str] = set()
    ordered = []
    for node in candidates:
        if node.id in owner_ids and node.id not in seen:
            seen.add(node.id)
            ordered.append(node)
    integrity_ids = {
        _owner_id(item)
        for item in _blockers(facts.diagnostic_findings)
        if str(item.get("category") or "").casefold() == "upstream_integrity"
    }
    integrity = [node for node in ordered if node.id in integrity_ids]
    ordered = integrity or ordered
    upstream = [node for node in ordered if node.id != current.id]
    return upstream or ordered


def _select_candidate(
    candidates: list[WorkflowNode],
    facts: RoutingFacts,
    owner_rounds: dict[str, int] | None,
) -> WorkflowNode:
    ids = {node.id for node in candidates}
    routed = [
        item
        for item in _blockers([*facts.review_findings, *facts.diagnostic_findings])
        if _owner_id(item) in ids
    ]
    layout_findings = all(
        str(item.get("category") or "").casefold() == "visual_layout"
        for item in routed
    ) or "layout" in facts.gate_text
    independent_layout = (
        owner_rounds is not None
        and len(candidates) > 1
        and routed
        and layout_findings
    )
    if independent_layout:
        return min(
            candidates, key=lambda node: int((owner_rounds or {}).get(node.id, 0) or 0)
        )
    return candidates[0]


def _review_text(gate: dict[str, Any], facts: RoutingFacts) -> str:
    return " ".join(
        [
            str(gate.get("reason") or ""),
            str(gate.get("summary") or ""),
            *(
                str(item.get("message") or item.get("plain_message") or "")
                for item in facts.review_findings
            ),
            *(str(item) for item in facts.details.get("issues", [])),
            *(str(item) for item in facts.diagnostics.get("issues", [])),
        ]
    ).casefold()


def _target_owner(
    host: RevisionOwnerHost,
    facts: RoutingFacts,
    review_text: str,
) -> str | None:
    scope = _mapping(facts.diagnostics.get("repair_scope"))
    targets = host._revision_target_files(
        facts.review_findings,
        facts.diagnostic_findings,
        scope.get("target_files"),
        facts.details.get("target_files"),
        facts.details.get("issues"),
    )
    paths = [str(item).replace("\\", "/").casefold() for item in targets]
    proof_targeted = any(
        path.endswith("paper/proof_audit.json")
        or "/paper/proof_audit.json" in f"/{path}"
        for path in paths
    )
    if proof_targeted:
        return (
            "paper"
            if any(marker in review_text for marker in PROOF_CONTENT_MARKERS)
            else "audit"
        )
    for owner, markers in PATH_OWNER_RULES:
        if any(marker in path for path in paths for marker in markers):
            return owner
    return None


def _semantic_owner(review_text: str, run: WorkflowRun) -> str | None:
    for owner, markers in SEMANTIC_OWNER_RULES:
        if any(marker in review_text for marker in markers):
            if owner == "exp-run" and run.options.get("run_experiment") is not True:
                continue
            return owner
    return None


def _compile_owner(text: str) -> str | None:
    if any(marker in text for marker in BIBLIOGRAPHY_MARKERS):
        return "lit"
    explicit_location = bool(re.search(r"(?:^|[\\/\s])[^\s]+\.tex:\d+", text))
    source_owned = explicit_location or any(marker in text for marker in SOURCE_MARKERS)
    platform_owned = any(marker in text for marker in PLATFORM_MARKERS)
    return "paper" if source_owned and not platform_owned else None


def _resolve_owner(
    host: RevisionOwnerHost, run: WorkflowRun, owner_id: str
) -> WorkflowNode:
    existing = host._find_node(run, owner_id)
    if existing is not None:
        return existing
    return next(node for node in host._get_default_nodes() if node.id == owner_id)


def revision_owner_for_gate(
    host: RevisionOwnerHost,
    current_node: WorkflowNode,
    run: WorkflowRun,
    gate: dict[str, Any],
    owner_rounds: dict[str, int] | None = None,
) -> WorkflowNode:
    facts = _facts(host, gate)
    if current_node.id == "audit" and any(marker in facts.gate_text for marker in (
        "policy provenance is missing or stale", "policy binding is stale", "reviewer route is missing or stale",
        "audit runtime component hashes are missing or stale", "audit bundle provenance or freshness validation failed",
    )):
        return current_node
    if current_node.id == "compile" and any(
        marker in facts.gate_text for marker in DETERMINISTIC_COMPILE_MARKERS
    ):
        return current_node
    compile_failure = " ".join(str(gate.get(key) or "") for key in ("reason", "summary")).casefold()
    if current_node.id == "compile" and any(marker in compile_failure for marker in PLATFORM_MARKERS):
        return current_node
    if any(
        marker in facts.gate_text
        for marker in STALE_CONSUMER_MARKERS.get(current_node.id, ())
    ):
        return current_node
    candidates = _structured_candidates(host, run, current_node, facts)
    if candidates:
        return _select_candidate(candidates, facts, owner_rounds)
    if current_node.id in {"paper", "review", "audit", "compile", "ppt"}:
        text = _review_text(gate, facts)
        owner = _target_owner(host, facts, text) or _semantic_owner(text, run)
        if owner:
            return _resolve_owner(host, run, owner)
    if current_node.id == "review":
        reconciliation = facts.details.get("paper_reconciliation")
        failed = isinstance(reconciliation, dict) and not reconciliation.get("passed")
        if failed or any(
            marker in facts.gate_text
            for marker in (
                "reviewed paper failed deterministic reconciliation",
                "section unfocused",
            )
        ):
            return _resolve_owner(host, run, "paper")
    if current_node.id == "compile":
        owner = _compile_owner(facts.gate_text)
        if owner:
            return _resolve_owner(host, run, owner)
    return current_node
