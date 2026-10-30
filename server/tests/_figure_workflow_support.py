from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import json
import os
import re
import textwrap
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from PIL import Image, ImageDraw
import pytest

from server.services.deterministic_figure_builder import ensure_evaluation_design
import server.services.figure_engine as figure_engine_module
from server.services.figure_engine import (
    FigureResult,
    FigureType,
    _benchmark_model_suite_svg,
    _evaluation_design_svg,
    figure_engine,
)
from server.services.figure_artifacts import figure_artifact_registry
from server.services.publication_figure_labels import publication_label_texts
from server.services.execution_provenance import execution_provenance_service
from server.services.paper_artifacts import (
    bind_table_manifest_hashes,
    paper_artifact_builder,
)
from server.services.paper_budget import paper_budget_service
from server.services.paper_compiler import paper_compiler
from server.services.paper_profile import paper_profile_service
from server.services.node_risk_audit import node_risk_audit_service
from server.services.process_runner import run_process
from server.services.scientific_assets import scientific_asset_service
from server.services.scientific_architecture import scientific_architecture_compiler
from server.services.scientific_scene_figure import compile_scientific_scene_figure
from server.services.scientific_plotting import build_scientific_plot_script
from server.services.simulation_policy import SIMULATION_END_DISCLOSURE
from server.services.workflow_readiness import validate_submission_start
from server.workflows.engine import WorkflowEngine, WorkflowRun
from server.agent import ToolCall
from server.agent.engine import AgentEngine


@pytest.fixture(autouse=True)
def _disable_live_electron_renderer_discovery(monkeypatch) -> None:
    """Unit tests must not turn into live desktop export jobs."""
    monkeypatch.setenv("MERAK_DISABLE_ELECTRON_RENDERER_DISCOVERY", "1")


def _seed_project(root: Path) -> None:
    (root / "literature").mkdir(parents=True)
    (root / "literature" / "survey.md").write_text(
        "# Survey\nEvidence-grounded literature review.",
        encoding="utf-8",
    )
    bibliography = "\n".join(
        f"@article{{paper{index}, title={{Paper {index}}}, author={{Author}}, year={{2025}}}}"
        for index in range(1, 6)
    )
    (root / "literature" / "references.bib").write_text(bibliography, encoding="utf-8")

    (root / "ideas").mkdir()
    (root / "ideas" / "ideas.md").write_text(
        "# Selected Idea\nArtifact-grounded research agent",
        encoding="utf-8",
    )
    (root / "ideas" / "SELECTED_IDEA.json").write_text(
        json.dumps({
            "schema": 2, "status": "accepted",
            "title": "Claim-linked research agent",
            "problem_statement": "Unsupported research claims escape review.",
            "hypothesis": "Claim-linked planning reduces unsupported research conclusions.",
            "claims": [
                {
                    "id": "C1",
                    "statement": "Claim-linked planning reduces unsupported conclusions.",
                    "publication_statement": "Claim-linked planning reduces unsupported conclusions.",
                }
            ],
            "mechanisms": [
                {
                    "id": "M1",
                    "name": "Claim-to-evidence binding",
                    "description": "Bind each claim to a decisive comparison and rejection rule.",
                    "publication_name": "Claim-to-evidence binding",
                    "publication_description": "Binds every claim to a decisive comparison and rejection rule.",
                    "publication_evaluation": "Matched unsupported-claim rate comparison.",
                },
                {
                    "id": "M2",
                    "name": "Matched-control falsification",
                    "description": "Compare the claim-linked workflow with the declared matched control.",
                    "publication_name": "Matched-control falsification",
                    "publication_description": "Tests the proposed mechanism against a matched workflow.",
                    "publication_evaluation": "Unsupported-claim rate under matched review budgets.",
                },
            ],
            "falsification_conditions": [
                "Reject C1 if a matched workflow has the same unsupported-claim rate."
            ],
            "publication": {
                "language": "en", "title": "Claim-Linked Research Planning",
                "method_name": "Claim-linked planner",
                "contribution_type": "system_architecture",
                "comparator_names": ["Claim-linked planner", "Matched workflow"],
            },
        }),
        encoding="utf-8",
    )
    (root / "experiments" / "configs").mkdir(parents=True)
    (root / "experiments" / "configs" / "main.yaml").write_text("seed: 42\n", encoding="utf-8")
    (root / "experiments" / "src").mkdir()
    (root / "experiments" / "src" / "train.py").write_text("def train():\n    return {''status'': ''dry-run''}\n", encoding="utf-8")
    (root / "experiments" / "EXPERIMENT_PLAN.md").write_text(
        "# Experiment Plan\n"
        "Primary metric: unsupported claim rate.\n"
        "Baseline: matched workflow without claim-to-evidence binding.\n"
        "Training objective: minimize unsupported claims under a fixed review budget.\n",
        encoding="utf-8",
    )
    (root / "experiments" / "METHOD_CONTRACT.json").write_text(
        json.dumps({
            "schema": 2,
            "status": "implementation_in_progress",
            "implementation_family": "computational_general",
            "implementation_checks": [],
            "scientific_scene": {
                "schema": 1,
                "objects": [
                    {"id": "research_inputs", "kind": "input", "label": "Research artifacts and observations", "source_path": "experiments/EXPERIMENT_PLAN.md"},
                    {"id": "claim_binding", "kind": "operation", "label": "Claim-to-evidence binding", "source_path": "ideas/SELECTED_IDEA.json"},
                    {"id": "matched_control", "kind": "intervention", "label": "Matched-control falsification", "source_path": "ideas/SELECTED_IDEA.json"},
                    {"id": "bounded_conclusion", "kind": "output", "label": "Evidence-bounded conclusion", "source_path": "experiments/EXPERIMENT_PLAN.md"},
                ],
                "relations": [
                    {"from": "research_inputs", "to": "claim_binding", "kind": "data"},
                    {"from": "claim_binding", "to": "bounded_conclusion", "kind": "data"},
                    {"from": "matched_control", "to": "claim_binding", "kind": "control"},
                    {"from": "matched_control", "to": "bounded_conclusion", "kind": "constraint"},
                ],
            },
            "evaluation_contract": {
                "comparators_or_controls": ["Matched workflow"],
                "primary_comparator": "Matched workflow",
                "primary_outcomes": ["Unsupported claim rate"],
            },
        }),
        encoding="utf-8",
    )
    (root / "experiments" / "RUN_SPEC.json").write_text(
        json.dumps({
            "primary_metric": "unsupported_claim_rate", "split": "test",
            "models": ["Claim-linked planner", "Matched workflow"],
            "tasks": ["Unsupported-claim review"],
            "scientific_outputs": {
                "primary_split": "test", "analysis_unit": "research task",
            },
        }),
        encoding="utf-8",
    )
    (root / "experiments" / "results").mkdir()
    (root / "experiments" / "results" / "analysis.md").write_text(
        "# Analysis\nExperiments are not run. No performance metric is reported.",
        encoding="utf-8",
    )


def _author_excalidraw_asset(root: Path, asset: dict) -> None:
    visible = publication_label_texts(asset.get("publication_labels"))
    title = str(asset.get("scientific_question") or asset.get("caption") or asset["id"])
    if asset["id"] == "method_architecture":
        labels = [
            "Research artifacts and observations",
            visible[0] if visible else "Claim-to-evidence binding",
            "Evidence-bounded conclusion",
            "Matched control and rejection rule",
        ]
        central_source = "experiments/src/train.py"
        central_symbol = "train"
    else:
        labels = [
            *(visible[:3] or ["Study data", "Leakage-safe split", "Held-out evaluation"]),
            "Independent-unit uncertainty aggregation",
        ][:4]
        while len(labels) < 4:
            labels.append("Prespecified evaluation condition")
        central_source = "experiments/RUN_SPEC.json"
        central_symbol = "primary_metric"
    remaining = visible[3:]
    scene = {
        "elements": [
            {
                "id": "title", "type": "text", "x": 110, "y": 0,
                "width": 1030, "height": 70, "fontSize": 27, "text": title,
            },
            {
                "id": "component-1", "type": "rectangle", "x": 0, "y": 150,
                "width": 300, "height": 150, "text": labels[0],
                "backgroundColor": "#E8F1F8", "strokeColor": "#33658A",
            },
            {
                "id": "component-2", "type": "rectangle", "x": 450, "y": 115,
                "width": 340, "height": 220, "text": labels[1],
                "backgroundColor": "#E8F5F2", "strokeColor": "#008C95",
            },
            {
                "id": "component-3", "type": "rectangle", "x": 940, "y": 150,
                "width": 300, "height": 150, "text": labels[2],
                "backgroundColor": "#FCEFE8", "strokeColor": "#C75B39",
            },
            {
                "id": "component-4", "type": "rectangle", "x": 450, "y": 470,
                "width": 340, "height": 130, "text": labels[3],
                "backgroundColor": "#F4F1E8", "strokeColor": "#8C6D31",
            },
            {"id": "flow-1", "type": "arrow", "startElementId": "component-1", "endElementId": "component-2"},
            {"id": "flow-2", "type": "arrow", "startElementId": "component-2", "endElementId": "component-3"},
            {"id": "flow-3", "type": "arrow", "startElementId": "component-4", "endElementId": "component-2"},
            *([{
                "id": "remaining-terms", "type": "text", "x": 80, "y": 675,
                "width": 1100, "height": 70, "fontSize": 17,
                "text": "Additional declared terms: " + "; ".join(remaining),
            }] if remaining else []),
        ]
    }
    mappings = [
        {"element_id": "component-1", "source_path": "ideas/SELECTED_IDEA.json", "semantic_role": "declared input"},
        {"element_id": "component-2", "source_path": central_source, "source_symbol": central_symbol, "semantic_role": "implemented mechanism or protocol"},
        {"element_id": "component-3", "source_path": "experiments/EXPERIMENT_PLAN.md", "semantic_role": "declared output or endpoint"},
        {"element_id": "component-4", "source_path": "experiments/METHOD_CONTRACT.json", "semantic_role": "training or control condition"},
    ]
    asset = {
        **asset,
        "scientific_scene": asset.get("scientific_scene") or {
            "schema": 1,
            "objects": [
                {"id": "component-1", "kind": "input", "label": labels[0], "source_path": "ideas/SELECTED_IDEA.json"},
                {"id": "component-2", "kind": "operation", "label": labels[1], "source_path": central_source},
                {"id": "component-3", "kind": "output", "label": labels[2], "source_path": "experiments/EXPERIMENT_PLAN.md"},
            ],
            "relations": [
                {"from": "component-1", "to": "component-2", "kind": "data"},
                {"from": "component-2", "to": "component-3", "kind": "data"},
            ],
        },
    }
    result = asyncio.run(figure_engine.generate(
        description=str(asset.get("caption") or title),
        artifact_name=str(asset["id"]),
        figure_type=FigureType.EXCALIDRAW,
        output_dir=str(root / "figures" / "diagrams"),
        code=json.dumps(scene),
        metadata={
            **asset,
            "element_mappings": mappings,
            "generator_skill": "excalidraw-skill",
            "skill": "excalidraw-skill",
            "skill_invocation_verified": True,
        },
    ))
    assert result.success is True, result.error


def _author_figurespec_asset(
    root: Path, asset: dict, publication_style: dict | None = None,
) -> None:
    assert asset.get("production_strategy") == "deterministic_architecture"
    compilation = compile_scientific_scene_figure(asset)
    skill = str(asset.get("recommended_skill") or "figure-spec")
    result = asyncio.run(figure_engine.generate(
        description=str(asset.get("caption") or asset["id"]),
        artifact_name=str(asset["id"]),
        figure_type=FigureType.FIGURESPEC,
        output_dir=str(root / "figures" / "diagrams"),
        code=json.dumps(compilation.spec, ensure_ascii=False, sort_keys=True),
        metadata={
            **asset,
            "semantic_key": asset["id"],
            "managed_by": "merak",
            "producer_kind": "deterministic",
            "paper_selected": True,
            "manuscript_eligible": True,
            "element_mappings": compilation.element_mappings,
            "architecture_compiler": compilation.profile,
            "architecture_source": "deterministic-source-grounded-scene",
            "style_profile": str(
                (publication_style or {}).get("visual_standard")
                or "field-adaptive-accessible-vector-v3"
            ),
            "generator_skill": skill,
            "skill": skill,
            "skill_invocation_verified": True,
            "skill_invocation_verified_by": "deterministic-runtime-figure-builder",
        },
    ))
    assert result.success is True, result.error


def _author_mermaid_asset(root: Path, asset: dict) -> None:
    visible = publication_label_texts(asset.get("publication_labels")) or [
        "Study data", "Leakage-safe split", "Held-out evaluation",
    ]
    labels = visible[:4]
    while len(labels) < 4:
        labels.append("Independent-unit aggregation")
    brief = dict(asset.get("method_brief") or {})
    study_title = str(brief.get("title") or "Registered study")
    mechanism_stages = [
        str(value).strip()
        for value in brief.get("mechanism_stages") or []
        if str(value).strip()
    ]
    mechanism = mechanism_stages[0] if mechanism_stages else "Declared mechanism"
    code = (
        "flowchart LR\n"
        f"    T[Evaluation of {study_title}] --> A[{labels[0]}]\n"
        f"    A --> B[{labels[1]}]\n"
        f"    B --> M[Target mechanism: {mechanism}]\n"
        f"    M --> C[{labels[2]}]\n"
        f"    C --> D[{labels[3]}]\n"
    )
    diagrams = root / "figures" / "diagrams"
    result = asyncio.run(figure_engine.generate(
        description=str(asset.get("caption") or asset["id"]),
        artifact_name=str(asset["id"]),
        figure_type=FigureType.MERMAID,
        output_dir=str(diagrams),
        code=code,
        metadata={
            **asset,
            "generator_skill": "mermaid-diagram",
            "skill": "mermaid-diagram",
            "skill_invocation_verified": True,
        },
    ))
    assert result.success is True, result.error
    if not result.output_path:
        preview = diagrams / f"{asset['id']}.png"
        figure_artifact_registry.render_mermaid_preview(
            code,
            preview,
            title=str(asset.get("scientific_question") or asset["id"]),
        )
        figure_artifact_registry.record(
            output_dir=diagrams,
            figure_type="mermaid",
            description=str(asset.get("caption") or asset["id"]),
            output_path=str(preview),
            source_path=str(diagrams / f"{asset['id']}.mmd"),
            metadata=dict(result.metadata or {}),
        )


def _author_rich_svg_asset(root: Path, asset: dict) -> None:
    scene = asset.get("scientific_scene") or {}
    scene_labels = [
        str(item.get("display_name") or item.get("label") or "").strip()
        for item in scene.get("objects") or [] if isinstance(item, dict)
    ]
    visible = list(dict.fromkeys([*filter(None, scene_labels), *publication_label_texts(
        asset.get("publication_labels"),
    )])) or [
        "Source-grounded mechanism", "Declared objective", "Held-out readout",
    ]
    sources = [
        str(value).strip()
        for value in asset.get("source_data") or []
        if str(value).strip() and (root / str(value)).is_file()
    ]
    mapped_source = sources[0] if sources else "experiments/METHOD_CONTRACT.json"
    colors = ["#E8F1FB", "#E4F5F1", "#FFF0DF", "#F1ECF8"]
    groups: list[str] = []
    mappings: list[dict[str, str]] = []
    for index in range(8):
        group_id = f"source_grounded_stage_{index + 1}"
        x = 55 + (index % 4) * 425
        y = 150 + (index // 4) * 260
        label = visible[index % len(visible)]
        title_lines = textwrap.wrap(label, width=19, break_long_words=False)[:2]
        title = "".join(
            f'<tspan x="{x + 22}" dy="{0 if row == 0 else 36}">{" " if row else ""}{line}</tspan>'
            for row, line in enumerate(title_lines)
        )
        groups.append(
            f'<g id="{group_id}">'
            f'<rect x="{x}" y="{y}" width="385" height="220" rx="14" '
            f'fill="{colors[index % 4]}" stroke="#52627A" stroke-width="2"/>'
            f'<rect x="{x + 20}" y="{y + 82}" width="345" height="105" rx="8" '
            'fill="#FFFFFF" stroke="#B7C3D3" stroke-width="1"/>'
            f'<text x="{x + 22}" y="{y + 35}" font-family="Arial" font-size="32" '
            f'font-weight="700" fill="#17233C">{title}</text>'
            + "".join(
                f'<text x="{x + 22}" y="{y + 118 + row * 45}" font-family="Arial" '
                f'font-size="32" fill="#52627A">Operation {row + 1}</text>'
                for row in range(2)
            )
            + "".join(
                f'<circle cx="{x + 70 + glyph * 70}" cy="{y + 190}" r="15" '
                f'fill="{colors[(index + glyph + 1) % 4]}" stroke="#17233C"/>'
                for glyph in range(4)
            )
            + "</g>"
        )
        mappings.append({
            "element_id": group_id,
            "source_path": mapped_source,
            "semantic_role": "source-grounded method stage",
        })
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="1000" '
        'viewBox="0 0 1800 1000">'
        '<rect x="0" y="0" width="1800" height="1000" fill="#FFFFFF"/>'
        '<text x="55" y="65" font-family="Arial" font-size="36" '
        'font-weight="700" fill="#17233C">Source-grounded method architecture</text>'
        '<text x="55" y="108" font-family="Arial" font-size="32" '
        'fill="#52627A">Internal mechanism, objectives, controls, and held-out evaluation</text>'
        + "".join(groups)
        + '<path d="M55 940 L1745 940" stroke="#17233C" stroke-width="2"/>'
        '</svg>'
    )
    protocol = str(asset.get("scientific_role") or "") in {"evaluation_design", "evaluation", "protocol"}
    roles = (
        ("source", "context", "control", "focal_process", "readout", "synthesis", "output", "constraint")
        if protocol else
        ("source", "context", "focal_process", "interaction", "synthesis", "readout", "output", "constraint")
    )
    forms = ("signal", "tensor", "matrix", "graph", "equation", "distribution", "table_inset", "proof")
    primitives = [
        {"id": f"source_grounded_stage_{index + 1}", "role": roles[index],
         "visual_form": forms[index], "public_label": f"Scientific stage {index + 1}",
         "scientific_meaning": f"Source-grounded operation {index + 1}",
         "annotations": ["declared operation"]}
        for index in range(8)
    ]
    blueprint = {
        "schema": 1, "compiler": "model-authored-svg-v1",
        "narrative_level": "study_protocol" if protocol else "method_overview",
        "figure_label": "Source-grounded scientific process",
        "focal_message": "Source-grounded operations connect the declared scientific stages",
        "primitives": primitives,
        "reading_order": [item["id"] for item in primitives],
        "flows": [
            {"from": primitives[index]["id"], "to": primitives[index + 1]["id"], "kind": "data"}
            for index in range(7)
        ],
    }
    result = asyncio.run(figure_engine.generate(
        description=str(asset.get("caption") or asset["id"]),
        artifact_name=str(asset["id"]),
        figure_type=FigureType.RICH_SVG,
        output_dir=str(root / "figures" / "diagrams"),
        code=svg,
        metadata={
            **asset,
            "element_mappings": mappings,
            "generator_skill": "rich-svg-figure",
            "skill": "rich-svg-figure",
            "skill_invocation_verified": True,
            "visual_blueprint": blueprint,
        },
    ))
    assert result.success is True, result.error


def _author_plan_figures(root: Path, plan: dict) -> None:
    publication_style = dict(plan.get("publication_style_contract") or {})
    deterministic_templates = []
    for asset in plan.get("assets", []):
        if asset.get("kind") != "figure" or not asset.get("required"):
            continue
        if asset.get("production_strategy") == "deterministic_architecture":
            _author_figurespec_asset(root, asset, publication_style)
            continue
        if asset.get("production_strategy") == "deterministic_template":
            deterministic_templates.append(asset)
            continue
        if asset.get("recommended_backend") == "rich_svg":
            _author_rich_svg_asset(root, asset)
            continue
        if asset.get("recommended_backend") == "figurespec":
            _author_figurespec_asset(root, asset)
            continue
        if asset.get("recommended_backend") == "excalidraw":
            _author_excalidraw_asset(root, asset)
            continue
        if asset.get("recommended_backend") == "mermaid":
            _author_mermaid_asset(root, asset)
            continue
        if not asset.get("data_path") or asset.get("evidence_status") != "executed":
            continue
        result = asyncio.run(figure_engine.generate(
            description=str(asset.get("caption") or asset.get("scientific_question") or asset["id"]),
            artifact_name=str(asset["id"]),
            figure_type=FigureType.MATPLOTLIB,
            output_dir=str(root / "figures" / "plots"),
            code=build_scientific_plot_script(
                asset,
                publication_style,
                idea=str(plan.get("selected_idea") or ""),
            ),
            metadata={
                **asset,
                "generator_skill": "paper-figure",
                "skill": "paper-figure",
                "skill_invocation_verified": True,
            },
        ))
        assert result.success is True, result.error
    if deterministic_templates:
        asyncio.run(ensure_evaluation_design(
            WorkflowEngine(), WorkflowRun(project_path=str(root)),
            root / "figures", deterministic_templates, plan,
            {str(asset["id"]) for asset in deterministic_templates},
            figure_artifact_registry,
        ))

def _build_figures(root: Path) -> WorkflowEngine:
    engine = WorkflowEngine()
    run = WorkflowRun(project_path=str(root), options={"run_experiment": False})
    plan = scientific_asset_service.build_plan(
        root,
        experiment_requested=False,
        requested_evidence_mode="design_only",
    )
    _author_plan_figures(root, plan)

    asyncio.run(engine._ensure_figure_artifacts(
        run,
        "Model-authored figures completed",
        "Artifact-grounded research agent",
    ))
    return engine
