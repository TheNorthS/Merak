"""Validate runtime provenance for configured literature search sources."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from .risk_artifact_support import _finding, _json


def search_evidence_findings(
    root: Path, node_id: str, options: dict[str, Any],
    strategy_loader: Callable[[Path, dict[str, Any]], dict[str, Any]],
) -> list[dict[str, Any]]:
    state, _ = _json(root / ".merak" / "research_strategy.json")
    if not isinstance(state, dict) or not str(state.get("run_id") or "").strip():
        return []
    selected = list(dict.fromkeys(
        str(item) for item in strategy_loader(root, options).get("literature_sources") or []
        if str(item).strip()
    ))
    if not selected:
        return []
    evidence, error = _json(root / "literature" / "SEARCH_EVIDENCE.json")
    prefix = "LIT" if node_id == "lit" else "NOV"
    paths = ["literature/SEARCH_EVIDENCE.json", ".merak/research_strategy.json"]
    invalid = _invalid_evidence(error, evidence, state, prefix, paths)
    if invalid:
        return invalid
    return _source_usage_findings(evidence, node_id, selected, prefix, paths)


def _invalid_evidence(
    error: str, evidence: Any, state: dict[str, Any], prefix: str,
    paths: list[str],
) -> list[dict[str, Any]]:
    if error or not isinstance(evidence, dict):
        return [_finding(
            f"{prefix}-SOURCE-001", "blocker", "retrieval_provenance",
            "Selected literature sources have no runtime-observed search evidence.",
            "已选择文献来源，但当前运行没有工具调用证据；仅在正文中声称使用过数据库不算完成检索。",
            paths, "Run every selected source through its dedicated tool and persist the runtime trace.",
        )]
    if str(evidence.get("run_id") or "") != str(state.get("run_id") or ""):
        return [_finding(
            f"{prefix}-SOURCE-002", "blocker", "retrieval_provenance",
            "Search evidence belongs to a different workflow run.",
            "检索证据来自其他工作流运行，不能证明本次运行实际使用了所选来源。",
            paths, "Repeat retrieval in the current run instead of reusing an old source claim.",
        )]
    return []


def _source_usage_findings(
    evidence: dict[str, Any], node_id: str, selected: list[str],
    prefix: str, paths: list[str],
) -> list[dict[str, Any]]:
    stages = evidence.get("stages") if isinstance(evidence.get("stages"), dict) else {}
    stage = stages.get(node_id) if isinstance(stages.get(node_id), dict) else {}
    usage = stage.get("source_usage") if isinstance(stage.get("source_usage"), dict) else {}
    missing = [source for source in selected
               if not isinstance(usage.get(source), dict) or usage[source].get("status") != "used"]
    if not missing:
        return []
    transient = _transient_failures(stage, missing)
    structured = {"arxiv", "semantic_scholar", "openalex", "pubmed", "zotero"}
    used_structured = any(
        source in structured and isinstance(usage.get(source), dict)
        and usage[source].get("status") == "used" for source in selected
    )
    statuses = ", ".join(
        f"{source}={str((usage.get(source) or {}).get('status') or 'not_used')}"
        for source in missing
    )
    if used_structured and set(missing) == transient:
        return [_finding(
            f"{prefix}-SOURCE-004", "warning", "retrieval_availability",
            f"Selected source(s) were temporarily unavailable during {node_id}: {statuses}; successful independent sources were retained.",
            f"{node_id} 阶段部分已选来源因限流或临时网络故障不可用：{statuses}；已有其他独立来源成功，因此不中断科研流程，但必须保留降级记录。",
            paths, "Retry the unavailable source later and disclose the temporary coverage gap.",
        )]
    return [_finding(
        f"{prefix}-SOURCE-003", "blocker", "retrieval_provenance",
        f"Selected sources were not successfully used by {node_id}: {statuses}.",
        f"{node_id} 阶段没有成功使用全部已选来源：{statuses}；不能用 WebSearch 替代已选的结构化数据库。",
        paths, "Call each selected source through its mapped tool; retry failed calls or change the source selection explicitly.",
    )]


def _transient_failures(stage: dict[str, Any], missing: list[str]) -> set[str]:
    pattern = re.compile(
        r"transport error|\b429\b|rate\s*limit|timed?\s*out|timeout|"
        r"temporar(?:y|ily) unavailable|\b50[0234]\b|bad gateway|service unavailable|"
        r"connection (?:reset|closed|aborted)|readerror|connecterror|remoteprotocolerror|peer closed|incomplete chunked read",
        re.I,
    )
    failures: dict[str, list[tuple[str, str]]] = {source: [] for source in missing}
    for attempt in stage.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        for call in attempt.get("calls") or []:
            if isinstance(call, dict) and call.get("source") in failures and call.get("success") is not True:
                failures[str(call["source"])].append((
                    str(call.get("output_preview") or ""), str(call.get("failure_kind") or ""),
                ))
    return {source for source, values in failures.items() if values and all(
        kind not in {"configuration_error", "request_invalid"}
        and not re.search(r"not configured|no search api configured|\b40[013]\b", output, re.I)
        and (kind == "platform_unavailable" or pattern.search(output))
        for output, kind in values
    )}
