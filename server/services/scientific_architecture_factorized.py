"""Factorized-representation grammar for scientific architecture figures."""

from __future__ import annotations

import re
from typing import Any

from .scientific_architecture_models import ArchitectureCompilation


def _context(grammar: Any, asset: dict[str, Any]) -> tuple[dict[str, Any], str, str, str]:
    brief = dict(asset.get("method_brief") or {})
    raw_title = grammar._text(
        brief.get("title") or asset.get("caption"), "Factorized representation method",
    )
    acronym = re.search(r"[（(]([A-Z][A-Z0-9-]{1,11})[）)]", raw_title)
    title = f"{acronym.group(1)} Method Architecture" if acronym else (
        raw_title[:60].rstrip(" ，,;；") + ("…" if len(raw_title) > 60 else "")
    )
    problem = " ".join((grammar._text(brief.get("problem")), raw_title)).casefold()
    input_label = next((label for marker, label in (
        ("eeg", "EEG windows"), ("ecg", "ECG windows"),
        ("image", "Images / patches"), ("text", "Token sequences"),
        ("graph", "Graph observations"), ("omics", "Molecular profiles"),
        ("clinical", "Cohort observations"),
    ) if marker in problem), "Scientific observations")
    endpoints = [
        grammar._text(value) for value in brief.get("reported_endpoints") or []
        if grammar._text(value).casefold() not in {
            "declared task output", "declared study output",
        }
    ][:3]
    return brief, title, input_label, " · ".join(endpoints) or "task utility · nuisance probes · uncertainty"


def _nodes(grammar: Any, input_label: str, endpoint_detail: str) -> list[dict[str, Any]]:
    definitions = (
        ("factor_input", input_label, "analysis units + acquisition metadata", 180, 270, 220, 140, "signal", "data"),
        ("factor_contract", "Leakage-safe split", "group-disjoint · source-only fitting", 180, 455, 220, 96, "database", "data"),
        ("factor_views", "Traceable paired views", "same-parent · label-safe · provenance-bound", 480, 270, 250, 140, "matrix", "conditioning"),
        ("factor_intervention", "Registered interventions", "channel · rate · reference · device", 480, 455, 250, 96, "ledger", "objective"),
        ("factor_encoder", "Shared encoder", "temporal stem · shared blocks · pooling", 790, 355, 230, 250, "module_stack", "representation"),
        ("factor_state", "Task-bearing state", "task-bearing invariant state", 1050, 290, 180, 98, "embedding", "representation"),
        ("factor_acquisition", "Acquisition state", "device · site · rate factors", 1150, 440, 180, 98, "embedding", "conditioning"),
        ("factor_task_head", "Task head", "logits · calibrated prediction", 1450, 290, 190, 98, "head", "evaluation"),
        ("factor_acq_head", "Acquisition head", "known acquisition metadata", 1450, 445, 190, 98, "head", "conditioning"),
        ("factor_registered_readouts", "Registered readouts", "task utility · state probe · acquisition probe", 1870, 355, 230, 170, "metric_card", "data"),
        ("factor_consistency", "Paired state consistency", "align task-bearing state across registered views", 500, 760, 240, 104, "loss", "objective"),
        ("factor_nuisance", "Nuisance constraint", "GRL / constrained acquisition decoding", 850, 760, 240, 104, "loss", "objective"),
        ("factor_joint_objective", "Matched objective", "consistency + task + acquisition + nuisance", 675, 900, 240, 92, "ledger", "objective"),
        ("factor_controls", "Single-deletion controls", "−pairing · −factorization · −GRL", 1150, 825, 235, 108, "ledger", "conditioning"),
        ("factor_audit", "Utility–nuisance Pareto audit", "frozen task utility + both nuisance probes", 1600, 825, 245, 120, "audit", "evaluation"),
        ("factor_output", "Held-out evidence", endpoint_detail[:70], 1880, 825, 235, 108, "metric_card", "data"),
    )
    return [grammar._node(
        {}, node_id=i, label=label, sublabel=detail, x=x, y=y,
        width=width, height=height, visual_kind=kind, palette_role=palette,
    ) for i, label, detail, x, y, width, height, kind, palette in definitions]


def _edges() -> list[dict[str, Any]]:
    return [
        {"from": "factor_input", "to": "factor_contract", "label": "records", "color": "#2563EB", "thickness": 2.3},
        {"from": "factor_contract", "to": "factor_views", "label": "audited batches", "color": "#7C3AED", "thickness": 2.3},
        {"from": "factor_intervention", "to": "factor_views", "label": "registered transforms", "color": "#D97706", "thickness": 2.0},
        {"from": "factor_views", "to": "factor_encoder", "label": "paired views", "color": "#0F766E", "thickness": 2.6},
        {"from": "factor_encoder", "to": "factor_state", "label": "factorize", "color": "#0F766E", "thickness": 2.5},
        {"from": "factor_encoder", "to": "factor_acquisition", "label": "factorize", "color": "#7C3AED", "thickness": 2.5},
        {"from": "factor_state", "to": "factor_task_head", "label": "task path", "color": "#BE123C", "thickness": 2.4},
        {"from": "factor_acquisition", "to": "factor_acq_head", "label": "metadata path", "color": "#7C3AED", "thickness": 2.4},
        {"from": "factor_intervention", "to": "factor_consistency", "label": "paired states", "color": "#D97706", "thickness": 2.1, "curve": True},
        {"from": "factor_acquisition", "to": "factor_nuisance", "label": "GRL", "color": "#D97706", "thickness": 2.1, "curve": True},
        {"from": "factor_consistency", "to": "factor_joint_objective", "label": "loss", "color": "#D97706", "thickness": 2.1},
        {"from": "factor_nuisance", "to": "factor_joint_objective", "label": "constraint", "color": "#D97706", "thickness": 2.1},
        {"from": "factor_joint_objective", "to": "factor_controls", "label": "single deletions", "color": "#7C3AED", "thickness": 2.0, "style": "dashed"},
        {"from": "factor_task_head", "to": "factor_registered_readouts", "label": "task output", "color": "#BE123C", "thickness": 2.2, "curve": True},
        {"from": "factor_acq_head", "to": "factor_registered_readouts", "label": "probe output", "color": "#7C3AED", "thickness": 2.0, "curve": True},
        {"from": "factor_registered_readouts", "to": "factor_audit", "label": "frozen readouts", "color": "#475569", "thickness": 2.2, "curve": True},
        {"from": "factor_audit", "to": "factor_output", "label": "joint decision", "color": "#2563EB", "thickness": 2.3},
    ]


def _groups() -> list[dict[str, Any]]:
    raw = (
        ("factor_data_group", "1  LEAKAGE-AUDITED INPUT", ["factor_input", "factor_contract"], (35, 165, 285, 375), "#D7E6F7"),
        ("factor_views_group", "2  PAIRED INTERVENTIONS", ["factor_views", "factor_intervention"], (325, 165, 310, 375), "#E3D8F6"),
        ("factor_model_group", "3  FACTORIZED REPRESENTATION", ["factor_encoder", "factor_state", "factor_acquisition"], (640, 165, 630, 375), "#CDE8E2"),
        ("factor_heads_group", "4  TASK & ACQUISITION HEADS", ["factor_task_head", "factor_acq_head"], (1275, 165, 350, 375), "#F0D8E1"),
        ("factor_readouts_group", "5  REGISTERED READOUTS", ["factor_registered_readouts"], (1630, 165, 385, 375), "#D7E6F7"),
        ("factor_training_group", "MATCHED TRAINING OBJECTIVE", ["factor_consistency", "factor_nuisance", "factor_joint_objective"], (350, 680, 650, 295), "#F3DFC4"),
        ("factor_evaluation_group", "ABLATIONS → JOINT AUDIT → EVIDENCE", ["factor_controls", "factor_audit", "factor_output"], (1005, 680, 1015, 295), "#D9E0E8"),
    )
    return [{
        "id": i, "label": label, "node_ids": ids,
        "bounds": {"x": b[0], "y": b[1], "width": b[2], "height": b[3]},
        "padding": 28, "fill": "#FFFFFF", "stroke": stroke,
    } for i, label, ids, b, stroke in raw]


def _target(grammar: Any, component: dict[str, Any]) -> str:
    lane, text = str(component.get("lane") or "").casefold(), grammar._component_text(component)
    if lane == "data_and_sampling":
        return "factor_views" if any(term in text for term in ("intervention", "paired", "counterfactual")) else "factor_contract"
    if lane == "training_objective" or any(term in text for term in ("loss", "objective")):
        return "factor_joint_objective"
    if lane == "evaluation":
        return "factor_audit"
    for terms, target in (
        (("acquisition", "metadata", "acq"), "factor_acquisition"),
        (("state", "projection", "embedding"), "factor_state"),
        (("head", "predict", "logit"), "factor_task_head"),
    ):
        if any(term in text for term in terms):
            return target
    return "factor_encoder"


def _mappings(grammar: Any, components: list[dict[str, Any]], nodes: list[dict[str, Any]]) -> list[dict[str, str]]:
    mappings: list[dict[str, str]] = []
    for component in components:
        mapping = grammar._source_mapping(
            _target(grammar, component), component,
            semantic_role="aggregated factorized-architecture evidence",
        )
        mapping["component_id"] = str(component.get("id") or "")
        mappings.append(mapping)
    mapped = {item["element_id"] for item in mappings}
    mappings.extend(grammar._source_mapping(
        node["id"], None, fallback_path="experiments/METHOD_CONTRACT.json",
        semantic_role="declared mechanism visualization",
    ) for node in nodes if node["id"] not in mapped)
    return mappings


def _spec(title: str, nodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "title": title, "canvas": {"width": 2050, "height": 1020},
        "style": {"font_family": "Helvetica", "font_size": 15, "bg_color": "#FFFFFF",
                  "palette": ["#2563EB", "#0F766E", "#7C3AED", "#D97706", "#BE123C", "#475569"]},
        "nodes": nodes, "edges": _edges(), "groups": _groups(),
        "regions": [
            {"id": "executable_method_band", "label": "EXECUTABLE METHOD PATH", "x": 20, "y": 120, "width": 2010, "height": 465, "fill": "#FBFCFE", "stroke": "#D8E0EA", "radius": 18},
            {"id": "mechanism_evidence_band", "label": "MECHANISM, ABLATION, AND HELD-OUT EVIDENCE", "x": 20, "y": 640, "width": 2010, "height": 350, "fill": "#FBFCFE", "stroke": "#D8E0EA", "radius": 18},
        ],
        "labels": [
            {"text": title, "x": 1025, "y": 46, "font_size": 27, "font_weight": "bold", "color": "#0F172A", "anchor": "middle"},
            {"text": "Paired intervention → shared encoder → factorized latents → preregistered held-out audit", "x": 1025, "y": 76, "font_size": 15, "color": "#64748B", "anchor": "middle"},
        ],
    }


def compile_factorized_representation_story(
    grammar: Any, asset: dict[str, Any], components: list[dict[str, Any]],
    family: str, mechanisms: list[dict[str, Any]],
) -> ArchitectureCompilation:
    _brief, title, input_label, endpoint_detail = _context(grammar, asset)
    nodes = _nodes(grammar, input_label, endpoint_detail)
    return ArchitectureCompilation(
        spec=_spec(title, nodes), element_mappings=_mappings(grammar, components, nodes),
        profile={
            "compiler": "scientific-architecture-v1", "grammar_version": 4,
            "architecture_family": family, "visual_grammar": "factorized_representation",
            "component_count": len(components), "rendered_node_count": len(nodes),
            "covered_component_ids": [str(item.get("id") or "") for item in components],
            "covered_mechanism_names": [grammar._text(item.get("name")) for item in mechanisms],
            "semantic_aggregation": True,
            "implementation_status": (asset.get("architecture_blueprint") or {}).get("implementation_status"),
        },
    )
