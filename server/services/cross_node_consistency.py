"""Check frozen claim, method, and figure identity across declared boundaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol
from .research_workflow_contract import NODE_CONTRACTS
from .risk_artifact_support import _finding, _json
from .risk_constants import PROTECTED_UPSTREAM
from .risk_validator_support import _ids

NODE_ORDER = tuple(NODE_CONTRACTS)


class CrossNodeAuditHost(Protocol):
    def protected_upstream_findings(
        self, root: Path, node_id: str, options: dict[str, Any]
    ) -> list[dict[str, Any]]: ...


def _method_identity_findings(
    title: str, method: dict[str, Any]
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    method_title = " ".join(str(method.get("selected_idea") or "").split())
    if title and method_title and (title.casefold() != method_title.casefold()):
        findings.append(
            _finding(
                "CROSS-IDEA-001",
                "blocker",
                "idea_drift",
                "METHOD_CONTRACT selected_idea differs from the frozen SELECTED_IDEA title.",
                "实验方法契约绑定了另一个 Idea，继续运行会偏离用户确认的研究目标。",
                ["ideas/SELECTED_IDEA.json", "experiments/METHOD_CONTRACT.json"],
                "Realign the method contract; do not silently rename or simplify the selected idea.",
            )
        )
    return findings


def _asset_identity_findings(
    title: str, selected: dict[str, Any], assets: dict[str, Any]
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    asset_title = " ".join(str(assets.get("selected_idea") or "").split())
    if title and asset_title and (title.casefold() != asset_title.casefold()):
        findings.append(
            _finding(
                "CROSS-IDEA-002",
                "blocker",
                "idea_drift",
                "SCIENTIFIC_ASSET_PLAN selected_idea differs from the frozen title.",
                "图表计划绑定的 Idea 与冻结 Idea 不一致，图片可能在说明另一项研究。",
                ["ideas/SELECTED_IDEA.json", "figures/SCIENTIFIC_ASSET_PLAN.json"],
                "Rebuild the asset plan from the current selected-idea contract.",
            )
        )
    selected_claims = set(_ids(selected.get("claims")))
    asset_claims = set(_ids(assets.get("claims")))
    if selected_claims and asset_claims != selected_claims:
        findings.append(
            _finding(
                "CROSS-CLAIM-001",
                "blocker",
                "claim_drift",
                f"Asset-plan claim IDs differ from the frozen claims: selected={sorted(selected_claims)}, assets={sorted(asset_claims)}",
                "图表计划没有完整保留冻结 claim ID，可能遗漏反例或改变论证边界。",
                ["ideas/SELECTED_IDEA.json", "figures/SCIENTIFIC_ASSET_PLAN.json"],
                "Regenerate claim-bearing assets from the frozen contract.",
            )
        )
    return findings


def _evidence_state_findings(
    options: dict[str, Any], assets: dict[str, Any]
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if (
        options.get("run_experiment") is not True
        and str(assets.get("evidence_mode") or "") == "executed"
    ):
        findings.append(
            _finding(
                "CROSS-EVID-001",
                "blocker",
                "evidence_state",
                "Asset plan is marked executed although workflow execution is disabled.",
                "工作流未运行实验，但图表计划被标记为 executed，存在模板值升级为证据的风险。",
                ["figures/SCIENTIFIC_ASSET_PLAN.json"],
                "Rebuild the asset plan in planned mode.",
            )
        )
    return findings


def cross_node_findings(
    host: CrossNodeAuditHost,
    root: Path,
    node_id: str,
    options: dict[str, Any],
    *,
    include_upstream: bool = True,
) -> list[dict[str, Any]]:
    if node_id not in NODE_ORDER:
        return []
    index = NODE_ORDER.index(node_id)
    if index < NODE_ORDER.index("exp-design"):
        return []
    selected, _ = _json(root / "ideas" / "SELECTED_IDEA.json")
    method, _ = _json(root / "experiments" / "METHOD_CONTRACT.json")
    assets, _ = _json(root / "figures" / "SCIENTIFIC_ASSET_PLAN.json")
    selected = selected if isinstance(selected, dict) else {}
    method = method if isinstance(method, dict) else {}
    assets = assets if isinstance(assets, dict) else {}
    title = " ".join(str(selected.get("title") or "").split())
    findings: list[dict[str, Any]] = []
    if include_upstream:
        findings.extend(host.protected_upstream_findings(root, node_id, options))
    findings.extend(_method_identity_findings(title, method))
    figure_is_available = node_id == "figure" or "figure" in PROTECTED_UPSTREAM.get(
        node_id, ()
    )
    if figure_is_available:
        findings.extend(_asset_identity_findings(title, selected, assets))
    findings.extend(_evidence_state_findings(options, assets))
    return findings
