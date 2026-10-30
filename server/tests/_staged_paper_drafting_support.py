from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path

import pytest

from server.services.manuscript_language import (
    find_internal_contract_references,
    find_visible_code_artifact_references,
)
from server.services.paper_artifacts import build_table_manifest, paper_artifact_builder
from server.services.paper_drafting import (
    ADMIN_RE,
    ASSEMBLY_CONTRACT_VERSION,
    AUTHOR_STAGE_ORDER,
    CONSISTENCY_CONTRACT_VERSION,
    DISPLAY_MATH_RE,
    PAPER_STAGE_ORDER,
    SECTION_CONTRACT_SCHEMA_VERSION,
    SECTION_SPECS,
    PaperDraftingError,
    PaperDraftingService,
    citation_keys,
    final_consistency_verdict,
    reference_keys,
    stable_source_hash,
    synthetic_analysis_requirements,
    word_count,
)
from server.services.simulation_policy import (
    SIMULATION_END_DISCLOSURE,
    SIMULATION_END_DISCLOSURE_TITLE,
    visible_latex_prose,
)
from server.services.skill_orchestrator import SkillPlan, skill_orchestrator
from server.workflows.engine import WorkflowEngine, WorkflowNode, WorkflowRun
from server.workflows.run_state import RunState


def seed_project(root: Path) -> None:
    (root / "literature").mkdir(parents=True)
    (root / "ideas").mkdir()
    (root / "experiments" / "results").mkdir(parents=True)
    (root / "experiments" / "configs").mkdir(parents=True)
    (root / "figures").mkdir()
    (root / "paper" / "tables").mkdir(parents=True)
    (root / "literature" / "survey.md").write_text(
        "# Survey\nVerified related work.\n", encoding="utf-8"
    )
    (root / "literature" / "references.bib").write_text(
        "\n".join(
            f"@article{{ref{index}, title={{Reference {index}}}, "
            f"author={{Author}}, year={{2025}}, journal={{Journal}}}}"
            for index in range(1, 11)
        ),
        encoding="utf-8",
    )
    (root / "ideas" / "SELECTED_IDEA.json").write_text(
        json.dumps({
            "title": "Topology-aware robust representation learning",
            "hypothesis": "Topology metadata improves held-out layout robustness.",
            "mechanisms": [{
                "id": "M1",
                "name": "Topology-aware tokenizer",
                "publication_name": "Topology-aware tokenizer",
                "publication_description": "Encode signal observations using declared topology metadata.",
                "publication_evaluation": "Compare matched topology removals under held-out layout conditions.",
                "required": True,
            }],
            "claims": [{
                "id": "C1",
                "claim": "The mechanism reduces degradation under held-out layouts.",
                "measurable_endpoints": ["held-out degradation"],
            }],
        }),
        encoding="utf-8",
    )
    (root / "experiments" / "METHOD_CONTRACT.json").write_text(
        json.dumps({"mechanisms": ["M1"]}), encoding="utf-8"
    )
    (root / "experiments" / "EXPERIMENT_PLAN.md").write_text(
        "# Plan\nMatched baselines and held-out layouts.\n", encoding="utf-8"
    )
    (root / "experiments" / "RUN_SPEC.json").write_text(
        json.dumps({"seeds": [1, 2, 3]}), encoding="utf-8"
    )
    (root / "experiments" / "configs" / "main.yaml").write_text(
        "seed: 1\n", encoding="utf-8"
    )
    (root / "experiments" / "results" / "analysis.md").write_text(
        "Experiments have not run.\n", encoding="utf-8"
    )
    (root / "NARRATIVE_REPORT.md").write_text(
        "# Narrative\nThe evidence remains pending.\n", encoding="utf-8"
    )
    (root / "paper" / "PAPER_PLAN.md").write_text(
        "# Paper Plan\nMechanism, evaluation, and falsification.\n",
        encoding="utf-8",
    )
    (root / "figures" / "SCIENTIFIC_ASSET_PLAN.json").write_text(
        json.dumps({
            "evidence_mode": "design_only",
            "submission_eligible": False,
        }),
        encoding="utf-8",
    )
    (root / "figures" / "FIGURE_MANIFEST.json").write_text(
        json.dumps({"figures": []}), encoding="utf-8"
    )
    (root / "paper" / "tables" / "TABLE_MANIFEST.json").write_text(
        json.dumps(build_table_manifest(root, [])), encoding="utf-8"
    )


def _complete_synthetic_results_section() -> str:
    references = "\n".join(
        rf"Figure~\ref{{{label}}} is paired with the registered analysis."
        for label in (
            "fig:preview-main-comparison",
            "fig:preview-ablation",
            "fig:preview-training-dynamics",
            "fig:preview-robustness",
            "fig:preview-error-analysis",
            "fig:preview-calibration",
            "fig:preview-efficiency",
        )
    )
    references += "\n" + "\n".join(
        rf"Table~\ref{{{label}}} preserves the matching quantitative view."
        for label in (
            "tab:preview-main-results",
            "tab:preview-ablation",
            "tab:preview-robustness-calibration",
            "tab:preview-error-analysis",
            "tab:preview-calibration",
            "tab:preview-efficiency",
        )
    )
    analytical = r"""
The main comparison shows a consistent baseline ordering, while overlapping
confidence intervals identify pairwise differences that remain uncertain. The
component ablation is a matched removal analysis: the largest delta indicates
the strongest component contribution under fixed resource accounting.

The training dynamics trajectory improves over early epochs before reaching a
plateau, and the uncertainty band narrows near convergence. The robustness
stress curve shows progressive degradation and sensitivity under held-out
shift. Calibration is characterized through coverage and selective risk, while
uncertainty remains visible rather than collapsed into one score. The failure
analysis exposes the worst-case error slice and subgroup degradation.

The efficiency panel defines a performance--resource trade-off across compute,
latency, memory, throughput, and parameter count. The full configuration reaches
the strongest endpoint at higher cost, while lighter variants occupy more
efficient operating points. \cite{ref1,ref2}
"""
    padding = (
        "The analysis compares matched conditions, examines interval overlap, "
        "and records uncertainty at the independent run. Each trend is bounded "
        "to the registered benchmark, stress range, and evaluation endpoint. "
    ) * 16
    return (
        "\\section{Results}\n"
        "\\input{synthetic_preview_figures}\n"
        "\\input{tables/synthetic_preview_results}\n"
        + references
        + "\n\n"
        + analytical
        + "\n\n"
        + padding
    )
