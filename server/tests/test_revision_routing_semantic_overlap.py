"""Pure repair-routing regressions for novelty gates and persisted diagnostics."""

from __future__ import annotations

from typing import Any

import pytest

from server.contracts.repairs import repair_capability_for
from server.workflows.models import WorkflowNode, WorkflowRun
from server.workflows.revision_diagnostics import normalize_gate_diagnostics
from server.workflows.revision_owner_policy import revision_owner_for_gate
from server.workflows.revision_targets import (
    paper_revision_fallback_targets,
    revision_asset_ids,
    revision_target_files,
    stable_revision_finding_text,
)


class DiagnosticHost:
    _revision_target_files = staticmethod(revision_target_files)
    _revision_asset_ids = staticmethod(revision_asset_ids)
    _stable_revision_finding_text = staticmethod(stable_revision_finding_text)
    _paper_revision_fallback_targets = staticmethod(paper_revision_fallback_targets)

    def _gate_revision_diagnostics(self, gate: dict[str, Any]) -> dict[str, Any]:
        return normalize_gate_diagnostics(self, gate)

    @staticmethod
    def _get_default_nodes() -> list[WorkflowNode]:
        return [WorkflowNode(id=value, name=value, skill=f"/{value}") for value in (
            "lit", "idea", "novelty", "exp-design", "exp-run", "results",
            "narrative", "figure", "paper", "review", "audit", "compile", "ppt",
        )]

    @staticmethod
    def _find_node(run: WorkflowRun, node_id: str) -> WorkflowNode | None:
        return next((node for node in run.nodes if node.id == node_id), None)


@pytest.mark.parametrize(("message", "category", "targets"), [
    (
        "missing quality dimension claim_delta: claim-level overlap and delta analysis",
        "quality", [],
    ),
    (
        "(?:overlap|difference|delta|重叠|差异|创新增量)", "novelty_logic",
        ["ideas/novelty_report.md", "literature/references.bib"],
    ),
    (
        "Frozen selected idea has no distinctive term overlap with the declared "
        "direction: Self-supervised Representation Learning and Foundation Models for EEG Signals",
        "research_scope", ["ideas/SELECTED_IDEA.json", ".merak/RESEARCH_WORKFLOW_CONTRACT.json"],
    ),
    ("The method diagram has claim overlap with prior art.", "novelty_logic", []),
    ("Figure terminology has overlap with the declared direction.", "research_scope", []),
])
def test_test102_semantic_overlap_never_selects_figure_capability(
    message: str, category: str, targets: list[str],
) -> None:
    assert repair_capability_for(
        message=message, target_files=targets, category=category,
    ) is None


@pytest.mark.parametrize(("owner_node", "message", "targets"), [
    ("novelty", "The novelty report has overlap with the nearest paper.", []),
    ("paper", "Table font and columns overlap.", ["paper/tables/results.tex"]),
    ("audit", "Proof provenance is invalid.", ["paper/PROOF_AUDIT.json"]),
    ("exp-run", "Metric provenance is missing.", ["experiments/results/metrics.json"]),
])
def test_capability_cannot_override_established_artifact_owner(
    owner_node: str, message: str, targets: list[str],
) -> None:
    capability = repair_capability_for(
        message=message, target_files=targets, owner_node=owner_node,
    )
    assert capability is None or capability.owner == owner_node


@pytest.mark.parametrize(("targets", "category", "owner_node"), [
    (["figures/diagrams/method.svg"], "quality", ""),
    ([], "figure_layout", ""),
    ([], "quality", "figure"),
])
def test_actual_figure_collision_retains_layout_capability(
    targets: list[str], category: str, owner_node: str,
) -> None:
    capability = repair_capability_for(
        message="SVG labels overlap", target_files=targets,
        category=category, owner_node=owner_node,
    )
    assert capability is not None
    assert capability.identity == "figure-layout"


def _novelty_gate() -> dict[str, Any]:
    missing = ["title", "problem_statement", "hypothesis", "claims", "mechanisms"]
    blockers = [{
        "id": f"NOV-CONTRACT-{index:03d}", "severity": "blocker", "category": "contract",
        "message": f"selected idea contract has no {field}",
        "plain_message": f"选定 Idea 契约缺少 {field}", "owner_node": "novelty",
        "evidence": ["ideas/SELECTED_IDEA.json", "ideas/novelty_report.md"],
        "remediation": "Repair the selected-idea contract without changing the selection.",
    } for index, field in enumerate(missing, start=1)]
    return {
        "accepted": False, "reason": "node-specific research risk audit failed",
        "summary": "Selected idea contract is incomplete.",
        "details": {
            "issues": [finding["plain_message"] for finding in blockers],
            "node_risk_audit": {"findings": [*blockers, {
                "id": "NOV-COMP-002", "severity": "warning", "category": "novelty_logic",
                "message": "(?:overlap|difference|delta|重叠|差异|创新增量)",
                "plain_message": "新颖性报告没有进行 claim-level 重叠/差异分析。",
                "owner_node": "novelty",
                "evidence": ["ideas/novelty_report.md", "literature/references.bib"],
            }]},
            "research_quality": {
                "passed": False, "score": 0.0, "threshold": 0.58,
                "issues": [
                    "missing quality dimension claim_delta: claim-level overlap and delta analysis",
                    "missing quality dimension verdict: explicit novelty verdict",
                ],
                "artifacts": ["ideas/novelty_report.md"],
                "report_path": ".merak/quality/novelty.json",
            },
        },
    }


def test_test102_missing_selected_idea_blockers_survive_repeated_normalization() -> None:
    host = DiagnosticHost()
    first = normalize_gate_diagnostics(host, _novelty_gate())
    second = normalize_gate_diagnostics(host, first)
    assert second == first
    blockers = [item for item in second["findings"] if item["id"].startswith("NOV-CONTRACT-")]
    assert len(blockers) == 5
    assert all(item["severity"] == "blocker" and item["owner_node"] == "novelty" for item in blockers)
    assert all(item["remediation"] for item in blockers)
    assert second["accepted"] is False
    assert "ideas/SELECTED_IDEA.json" in second["repair_scope"]["target_files"]
    assert second["component_statuses"]["content_quality"]["passed"] is False


def test_test102_persisted_gate_routes_missing_artifacts_to_novelty() -> None:
    host = DiagnosticHost()
    nodes = host._get_default_nodes()
    run = WorkflowRun(id="test102-routing", nodes=nodes)
    novelty = host._find_node(run, "novelty")
    assert novelty is not None
    gate = normalize_gate_diagnostics(host, _novelty_gate())
    owner = revision_owner_for_gate(host, novelty, run, gate)
    assert owner.id == "novelty"
    assert all(item["owner_node"] != "figure" for item in gate["findings"])


def test_exact_nov_comp_report_and_reference_evidence_remains_novelty() -> None:
    gate = _novelty_gate()
    gate["details"]["node_risk_audit"]["findings"] = [
        gate["details"]["node_risk_audit"]["findings"][-1],
    ]
    gate["details"].pop("issues")
    gate["details"].pop("research_quality")
    diagnostics = normalize_gate_diagnostics(DiagnosticHost(), gate)
    finding = diagnostics["findings"][0]
    assert finding["id"] == "NOV-COMP-002"
    assert finding["owner_node"] == "novelty"
    assert finding["repair_capability"] == ""


@pytest.mark.parametrize("target", ["ideas/SELECTED_IDEA.json", "ideas/novelty_report.md"])
def test_old_misrouted_figure_owner_is_corrected_by_canonical_novelty_target(target: str) -> None:
    diagnostics = normalize_gate_diagnostics(DiagnosticHost(), {
        "accepted": False, "findings": [{
            "id": "NOV-CONTRACT-001", "source": "risk_audit", "severity": "blocker",
            "owner_node": "figure", "message": "Selected idea term overlap is missing.",
            "target_files": [target], "repair_capability": "figure-layout",
        }],
    })
    assert diagnostics["findings"][0]["owner_node"] == "novelty"
    assert diagnostics["findings"][0]["repair_capability"] == ""


@pytest.mark.parametrize("layer", ["gate", "gate_details", "quality"])
def test_all_structured_gate_layers_retain_blocker_identity(layer: str) -> None:
    finding = {
        "id": "NOV-CONTRACT-001", "severity": "blocker", "category": "contract",
        "owner_node": "novelty", "message": "selected idea contract has no title",
        "target_files": ["ideas/SELECTED_IDEA.json"],
        "remediation": "Write the evidence-backed selected idea.",
    }
    gate: dict[str, Any] = {"accepted": False}
    container = gate if layer == "gate" else gate.setdefault("details", {})
    if layer == "quality":
        container = container.setdefault("research_quality", {})
    container["findings"] = [finding]
    normalized = normalize_gate_diagnostics(DiagnosticHost(), gate)
    assert len(normalized["findings"]) == 1
    assert normalized["findings"][0]["id"] == "NOV-CONTRACT-001"
    assert normalized["findings"][0]["severity"] == "blocker"
    assert normalized["findings"][0]["owner_node"] == "novelty"


def test_duplicate_advisory_cannot_hide_fresh_structured_blocker() -> None:
    finding = {
        "id": "NOV-CONTRACT-001", "owner_node": "novelty",
        "message": "selected idea contract has no title",
        "target_files": ["ideas/SELECTED_IDEA.json"],
    }
    diagnostics = normalize_gate_diagnostics(DiagnosticHost(), {
        "accepted": False,
        "findings": [{**finding, "severity": "warning"}],
        "details": {"node_risk_audit": {"findings": [{**finding, "severity": "blocker"}]}},
    })
    assert len(diagnostics["findings"]) == 1
    assert diagnostics["findings"][0]["severity"] == "blocker"


@pytest.mark.parametrize(("finding", "expected_owner"), [
    ({"message": "Text overlap in SVG", "target_files": ["figures/method.svg"]}, "figure"),
    ({"message": "Table font overlap", "target_files": ["paper/tables/results.tex"]}, "paper"),
    ({"message": "Proof checker evidence missing", "target_files": ["paper/PROOF_AUDIT.json"]}, "audit"),
    ({"message": "Invalid proof", "target_files": ["paper/PROOF_AUDIT.json"]}, "paper"),
    ({"message": "Metric provenance missing", "target_files": ["experiments/results/analysis.md"]}, "results"),
    ({"message": "Repair generated projection", "owner_node": "paper",
      "target_files": ["paper/generated_method_figures.tex"]}, "figure"),
    ({"message": "PDF table font overlaps", "category": "visual_layout", "owner_node": "paper",
      "target_files": ["paper/tables/synthetic_preview_results.tex"]}, "paper"),
])
def test_semantic_overlap_fix_preserves_existing_producer_routes(
    finding: dict[str, Any], expected_owner: str,
) -> None:
    diagnostics = normalize_gate_diagnostics(DiagnosticHost(), {
        "accepted": False, "details": {"review_findings": [finding]},
    })
    assert diagnostics["findings"][0]["owner_node"] == expected_owner
