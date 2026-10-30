from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import server.workflows.review_audit as review_audit_module
from server.agent import ToolCall
from server.services.research_quality import research_quality_service
from server.services.method_contract import _python_symbols, method_contract_service
from server.services.skill_orchestrator import skill_orchestrator
from server.services.skill_registry import skill_registry
from server.agent.engine import agent_engine
from server.agent.tools import invoke_skill, register_all_tools
from server.workflows.review_audit import AuditChain, AuditResult, Verdict
from server.workflows.engine import WorkflowEngine, WorkflowNode, WorkflowRun
from server.workflows.skill_inputs import get_skill_input_schema


def _write_selected_idea_contract(
    root: Path,
    title: str,
    mechanisms: list[dict],
) -> None:
    publication_mechanisms = [
        {
            **item,
            "description": str(item.get("description") or item.get("name") or ""),
            "publication_name": str(item.get("publication_name") or item.get("name") or ""),
            "publication_description": str(
                item.get("publication_description")
                or item.get("description")
                or item.get("name")
                or ""
            ),
            "publication_evaluation": str(
                item.get("publication_evaluation") or "Matched mechanism comparison"
            ),
        }
        for item in mechanisms
    ]
    ideas = root / "ideas"
    ideas.mkdir(exist_ok=True)
    (ideas / "novelty_report.md").write_text(
        f"# Novelty Report\n\nRecommended Top-1: {title}\n",
        encoding="utf-8",
    )
    (ideas / "SELECTED_IDEA.json").write_text(
        json.dumps({
            "schema": 2,
            "status": "accepted",
            "title": title,
            "problem_statement": "Test the selected research mechanism under controlled evidence.",
            "hypothesis": "The declared mechanism changes the primary outcome under matched controls.",
            "claims": [{
                "id": "C1",
                "statement": "The selected mechanism has a measurable effect.",
                "publication_statement": "The selected mechanism has a measurable effect.",
            }],
            "mechanisms": publication_mechanisms,
            "falsification_conditions": ["The matched mechanism test shows no reproducible effect."],
            "publication": {
                "language": "en",
                "title": title,
                "method_name": title,
                "contribution_type": "objective_mechanism",
                "comparator_names": [title, "Matched control"],
            },
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_method_contract(
    root: Path,
    title: str,
    checks: list[dict],
    coverage: list[dict],
) -> None:
    experiments = root / "experiments"
    (experiments / "METHOD_CONTRACT.json").write_text(
        json.dumps({
            "schema": 2,
            "status": "implemented",
            "selected_idea": title,
            "idea_contract_path": "ideas/SELECTED_IDEA.json",
            "idea_contract_sha256": "",
            "mechanism_coverage": coverage,
            "claim_evidence_plan": [{
                "idea_claim_id": "C1",
                "outcomes": ["Primary outcome with uncertainty"],
                "failure_conditions": ["No reproducible effect under matched control"],
            }],
            "implementation_checks": checks,
            "evaluation_contract": {
                "primary_outcomes": ["Primary outcome with uncertainty"],
                "comparators_or_controls": ["Matched control"],
                "component_tests": ["Mechanism-removal test"],
                "failure_conditions": ["Stop or pivot when the effect is not reproducible"],
            },
            "scientific_scene": {
                "schema": 1,
                "objects": [{
                    "id": "method",
                    "kind": "operation",
                    "label": title,
                    "source_path": "ideas/SELECTED_IDEA.json",
                }],
                "relations": [],
            },
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    assert method_contract_service.stamp_method_contract_idea_hash(root)


def _load_canonical_skills() -> int:
    root = Path(__file__).resolve().parents[2]
    return skill_registry.scan_directory(root / "merak-skills")


def _audit_results_for_reuse(
    verdicts: dict[int, Verdict] | None = None,
) -> list[AuditResult]:
    skills = {
        1: "experiment-audit",
        2: "result-to-claim",
        3: "paper-claim-audit",
        4: "citation-audit",
        5: "kill-argument",
    }
    selected = verdicts or {}
    return [
        AuditResult(
            layer=layer,
            layer_name=f"Layer {layer}",
            verdict=selected.get(layer, Verdict.PASS),
            summary=f"layer {layer} checked",
            details={"finding": f"layer-{layer}"},
            evidence=["paper/main.tex"],
            method="model",
            skill_name=skills[layer],
            session_id=f"layer-{layer}-session",
            policy_loaded=True,
            model_name="independent-reviewer",
        )
        for layer in range(1, 6)
    ]
