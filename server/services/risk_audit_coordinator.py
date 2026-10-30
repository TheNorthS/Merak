"""Coordinate node risk validation and persistence independently of stage rules."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from ..utils.atomic_write import atomic_write_json, path_lock
from .research_workflow_contract import NODE_CONTRACTS
from .risk_artifact_support import _finding, _has_content, _json
from .risk_constants import NODE_RISK_CHECKLIST, PROTECTED_UPSTREAM
from .risk_training_review import training_check_findings as _training_check_findings
from .risk_evidence_policy import workflow_evidence_mode as _workflow_evidence_mode

NODE_ORDER = tuple(NODE_CONTRACTS)
BLOCKING_SEVERITIES = {"blocker"}

def preflight_node(
    service,
    project_path: str | Path,
    node_id: str,
    options: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Check execution prerequisites before asking an agent to author files.

    This intentionally does not validate the current node's outputs: those do
    not exist yet. It only checks immutable upstream facts and contradictory
    run options. The full stage validator still runs after generation.
    """
    root = Path(project_path).expanduser().resolve()
    options = dict(options or {})
    findings: list[dict[str, Any]] = []
    if node_id not in NODE_CONTRACTS:
        return [_finding(
            "PREFLIGHT-UNKNOWN-001",
            "blocker",
            "workflow",
            f"No workflow contract exists for node {node_id!r}.",
            f"节点 {node_id} 没有科研契约，不能在没有检查规则的情况下执行。",
            [],
            "Register the node in NODE_CONTRACTS and NODE_RISK_CHECKLIST first.",
        )]
    if not root.is_dir():
        return [_finding(
            "PREFLIGHT-PROJECT-001",
            "blocker",
            "workflow",
            f"Project path is not a readable directory: {root}",
            "当前研究项目目录不存在或不可读，无法安全执行节点。",
            [str(root)],
            "Open a readable project directory and retry the workflow.",
        )]

    findings.extend(service.protected_upstream_findings(root, node_id, options))
    if options.get("run_experiment") is not True:
        target = str(options.get("gpu_target") or "none").strip().casefold()
        server_id = str(options.get("ssh_server_id") or "").strip()
        if target not in {"", "none"} or server_id:
            findings.append(_finding(
                "PREFLIGHT-RUN-001",
                "blocker",
                "execution_mode",
                "GPU/remote execution options are set although experiment execution is disabled.",
                "当前选择不运行实验，但仍保留了 GPU 或远程服务器目标；这会让后续节点误以为已启动实验。",
                [".merak/RESEARCH_WORKFLOW_CONTRACT.json"],
                "Set gpu_target=none and clear ssh_server_id before continuing in planned mode.",
            ))
    if node_id == "exp-run" and options.get("run_experiment") is True:
        findings.extend(_training_check_findings(options))
        target = str(options.get("gpu_target") or "local").strip().casefold()
        if target in {"remote", "ssh", "ssh_remote"} and not str(options.get("ssh_server_id") or "").strip():
            findings.append(_finding(
                "PREFLIGHT-RUN-002",
                "blocker",
                "deployment",
                "Remote execution was selected without a server identity.",
                "实验选择了远程 SSH，但没有指定已验证的服务器；不会让智能体先写一轮再发现部署无法启动。",
                ["experiments/RUN_SPEC.json"],
                "Select and test one SSH server, then resume the experiment node.",
            ))
    strategy = service._strategy(root, options)
    if node_id == "lit" and not strategy:
        findings.append(_finding(
            "PREFLIGHT-LIT-001",
            "warning",
            "research_scope",
            "No persisted literature strategy was found before retrieval.",
            "文献节点开始前没有持久化检索策略；年份、来源和关键词限制可能无法复核。",
            [".merak/research_strategy.json"],
            "Persist the resolved year window, sources, queries, and exclusion rules with the run.",
        ))
    return findings


def audit_workflow(
    service,
    project_path: str | Path,
    options: dict[str, Any] | None = None,
    *,
    through_node: str = "",
    persist: bool = True,
) -> dict[str, Any]:
    """Scan every generated stage and expose latent downstream drift.

    Future stages with no artifacts are reported as ``not_started`` rather
    than failed. Existing artifacts are always revalidated, even if an old
    run-state file says that their node was accepted.
    """
    root = Path(project_path).expanduser().resolve()
    options = dict(options or {})
    limit = NODE_ORDER.index(through_node) if through_node in NODE_ORDER else -1
    nodes: dict[str, Any] = {}
    blocker_count = 0
    warning_count = 0
    for index, node_id in enumerate(NODE_ORDER):
        outputs = NODE_CONTRACTS[node_id].get("outputs", [])
        generated = any(_has_content(root / relative) for relative in outputs)
        should_audit = (
            index <= limit
            if limit >= 0
            else generated
        )
        if should_audit:
            report = service.audit_node(root, node_id, options, persist=persist)
            nodes[node_id] = report
            blocker_count += int(report["counts"].get("blocker", 0))
            warning_count += int(report["counts"].get("warning", 0))
        else:
            nodes[node_id] = {
                "schema": 1,
                "node_id": node_id,
                "status": "not_started",
                "blocking": False,
                "counts": {"blocker": 0, "warning": 0, "info": 0},
                "checks_executed": list(NODE_RISK_CHECKLIST.get(node_id, ())),
                "findings": [],
            }
    snapshot = {
        "schema": 1,
        "generated_at": time.time(),
        "through_node": through_node or "",
        "status": (
            "blocked"
            if blocker_count
            else "advisory"
            if warning_count
            else "clear"
        ),
        "counts": {
            "blocker": blocker_count,
            "warning": warning_count,
            "info": sum(int(item["counts"].get("info", 0)) for item in nodes.values()),
        },
        "nodes": nodes,
    }
    if persist:
        path = root / service.snapshot_path
        try:
            atomic_write_json(path, snapshot)
            snapshot["report_path"] = str(path)
        except OSError as exc:
            snapshot["persistence_error"] = f"{type(exc).__name__}: {exc}"
    return snapshot


def protected_upstream_findings(
    service,
    project_path: str | Path,
    node_id: str,
    options: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Revalidate objective blockers owned by stages required by ``node_id``."""
    root = Path(project_path).expanduser().resolve()
    options = dict(options or {})
    findings: list[dict[str, Any]] = []
    for upstream_id in PROTECTED_UPSTREAM.get(node_id, ()):
        handler = getattr(service, f"_audit_{upstream_id.replace('-', '_')}", None)
        if not callable(handler):
            continue
        try:
            upstream_findings = service._cross_node_findings(
                root,
                upstream_id,
                options,
                include_upstream=False,
            )
            upstream_findings.extend(handler(root, options))
        except Exception as exc:
            upstream_findings = [_finding(
                f"{upstream_id.upper()}-VALIDATOR-ERROR",
                "blocker",
                "risk_validator",
                f"Risk validation for upstream node {upstream_id} failed: {type(exc).__name__}: {exc}",
                f"关键上游节点 {upstream_id} 的风险检查器执行失败，当前不能确认其产物仍然有效。",
                [f".merak/quality/{upstream_id}-risk.json"],
                f"Repair the {upstream_id} validator or malformed artifact, then rerun its audit.",
            )]
        upstream_blockers = [
            item for item in upstream_findings
            if item.get("severity") in BLOCKING_SEVERITIES
        ]
        for item in upstream_blockers[:8]:
            findings.append({
                **item,
                "id": f"UPSTREAM-{upstream_id.upper()}-{item.get('id')}",
                "upstream_node": upstream_id,
                "category": "upstream_integrity",
                "message": (
                    f"Upstream node {upstream_id} is no longer valid: "
                    f"{item.get('message')}"
                ),
                "plain_message": (
                    f"关键上游节点 {upstream_id} 的产物当前无效："
                    f"{item.get('plain_message') or item.get('message')}"
                ),
                "remediation": (
                    f"Return to {upstream_id}, repair and re-accept it before "
                    f"continuing {node_id}."
                ),
            })
    return findings


def audit_node(
    service,
    project_path: str | Path,
    node_id: str,
    options: dict[str, Any] | None = None,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    root = Path(project_path).expanduser().resolve()
    options = dict(options or {})
    handler: Callable[[Path, dict[str, Any]], list[dict[str, Any]]] | None = getattr(
        service, f"_audit_{node_id.replace('-', '_')}", None
    )
    if node_id not in NODE_CONTRACTS or handler is None:
        findings = [_finding(
            "NODE-UNKNOWN",
            "blocker",
            "workflow",
            f"No risk validator is registered for workflow node {node_id!r}.",
            f"节点 {node_id} 没有注册风险校验器，不能被静默放行。",
            [],
            "Register a stage-specific validator before enabling this node.",
        )]
    else:
        try:
            findings = handler(root, options)
            findings.extend(service._cross_node_findings(root, node_id, options))
        except Exception as exc:
            findings = [_finding(
                f"{node_id.upper()}-VALIDATOR-ERROR",
                "blocker",
                "risk_validator",
                f"Risk validation for node {node_id} failed: {type(exc).__name__}: {exc}",
                f"节点 {node_id} 的风险检查器执行失败，系统不能在检查缺失的情况下放行该节点。",
                [f".merak/quality/{node_id}-risk.json"],
                f"Repair the {node_id} validator or malformed artifact, then rerun this node audit.",
            )]
        preflight_by_node = options.get("_node_preflight_findings")
        if isinstance(preflight_by_node, dict):
            findings.extend(
                item for item in preflight_by_node.get(node_id, [])
                if isinstance(item, dict)
            )

    unique = _unique_findings(findings, node_id)
    counts = {
        severity: sum(1 for item in unique if item.get("severity") == severity)
        for severity in ("blocker", "warning", "info")
    }
    report = _node_report(node_id, options, unique, counts)
    if persist:
        _persist_node_report(service, root, node_id, report)
    return report


def _unique_findings(
    findings: list[dict[str, Any]], node_id: str,
) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in findings:
        item.setdefault("owner_node", item.get("upstream_node") or node_id)
        item.setdefault("confidence", "high" if item.get("severity") == "blocker" else "medium")
        marker = (str(item.get("id") or ""), str(item.get("message") or ""))
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(item)
    return unique


def _node_report(
    node_id: str, options: dict[str, Any], unique: list[dict[str, Any]],
    counts: dict[str, int],
) -> dict[str, Any]:
    return {
        "schema": 1,
        "node_id": node_id,
        "purpose": NODE_CONTRACTS.get(node_id, {}).get("purpose", ""),
        "generated_at": time.time(),
        "mode": _workflow_evidence_mode(options),
        "blocking": bool(counts["blocker"]),
        "status": "blocked" if counts["blocker"] else ("advisory" if counts["warning"] else "clear"),
        "counts": counts,
        "checks_executed": list(NODE_RISK_CHECKLIST.get(node_id, ())),
        "risk_policy": {
            "blocker": "objective contradiction, invalid artifact, or unsafe execution prerequisite",
            "warning": "plausible scientific or reproducibility risk that needs researcher judgment",
        },
        "findings": unique,
    }


def _persist_node_report(
    service: Any, root: Path, node_id: str, report: dict[str, Any],
) -> None:
    report_path = root / service.report_dir / f"{node_id}-risk.json"
    try:
        atomic_write_json(report_path, report)
        report["report_path"] = str(report_path)
        service._update_index(root, report)
    except (OSError, RuntimeError) as exc:
        report["persistence_error"] = f"{type(exc).__name__}: {exc}"


def apply_gate(
    service,
    gate: dict[str, Any],
    project_path: str | Path,
    node_id: str,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = service.audit_node(project_path, node_id, options, persist=True)
    details = gate.setdefault("details", {})
    if not isinstance(details, dict):
        details = {}
        gate["details"] = details
    details["node_risk_audit"] = report
    blockers = [item for item in report["findings"] if item["severity"] in BLOCKING_SEVERITIES]
    warnings = [item for item in report["findings"] if item["severity"] == "warning"]
    if blockers:
        primary_failure = gate.get("accepted") is False and bool(gate.get("reason"))
        existing = details.get("issues") if isinstance(details.get("issues"), list) else []
        details["issues"] = list(dict.fromkeys([
            *[str(item) for item in existing],
            *[str(item.get("plain_message") or item.get("message")) for item in blockers],
        ]))
        gate["accepted"] = False
        # Risk findings supplement an existing producer failure; they must not
        # hide it behind a downstream artifact intentionally not generated yet.
        if not primary_failure:
            gate["reason"] = "node-specific research risk audit failed"
            gate["summary"] = "；".join(
                str(item.get("plain_message") or item.get("message")) for item in blockers[:8]
            )
        return gate
    advisory_issues = [
        str(item.get("plain_message") or item.get("message"))
        for item in warnings
    ]
    if report.get("persistence_error"):
        advisory_issues.append(
            "节点风险检查已完成，但风险报告未能写入项目目录；请检查项目写权限。"
        )
    if gate.get("accepted") and advisory_issues:
        gate.setdefault("warnings", []).append({
            "kind": "node_risk",
            "issues": advisory_issues[:8],
            "report_path": report.get("report_path", ""),
            "warning_count": len(advisory_issues),
        })
        gate["summary"] = (
            f"{gate.get('summary', '')} Risk audit: {len(advisory_issues)} non-blocking issue(s)."
        ).strip()
    return gate


def _update_index(service, root: Path, report: dict[str, Any]) -> None:
    root = Path(root).expanduser().resolve()
    path = root / service.index_path
    with service._index_update_thread_lock:
        with path_lock(path):
            payload, read_error = _json(path)
            if path.exists() and read_error:
                raise RuntimeError(
                    "Risk report index is unreadable or corrupt; refusing "
                    f"to overwrite it: {path}: {read_error}"
                )
            if payload is None:
                payload = {"schema": 1, "nodes": {}}
            elif not isinstance(payload, dict):
                raise RuntimeError(
                    "Risk report index root must be a JSON object; refusing "
                    f"to overwrite it: {path}"
                )
            nodes = (
                payload.get("nodes")
                if isinstance(payload.get("nodes"), dict)
                else {}
            )
            nodes[report["node_id"]] = {
                "status": report["status"],
                "blocking": report["blocking"],
                "counts": report["counts"],
                "checks_executed": report.get("checks_executed", []),
                "report_path": str(
                    Path(report.get("report_path", "")).relative_to(root)
                ).replace("\\", "/")
                if report.get("report_path")
                else "",
                "updated_at": report["generated_at"],
            }
            payload.update({
                "schema": 1,
                "generated_at": time.time(),
                "nodes": nodes,
            })
            atomic_write_json(path, payload)


def _execute_handler(
    service: Any, handler: Callable, root: Path, node_id: str,
    options: dict[str, Any],
) -> list[dict[str, Any]]:
    findings = handler(root, options)
    findings.extend(service._cross_node_findings(root, node_id, options))
    return findings
