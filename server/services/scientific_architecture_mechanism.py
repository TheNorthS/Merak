"""Mechanism-first grammar for protocol and functional study figures."""

from __future__ import annotations

import re
from typing import Any

from .scientific_architecture_models import ArchitectureCompilation


MARKER_GROUPS = (
    (("保留率", "retention"), "retention"),
    (("时间聚集", "temporal concentration"), "temporal concentration"),
    (("跨通道", "channel synchron"), "channel synchrony"),
    (("连续状态", "continuous"), "continuous tasks"),
    (("瞬态", "事件任务", "event task"), "event tasks"),
    (("留出", "held-out", "holdout"), "held-out domains"),
    (("塌缩", "collapse"), "collapse"),
    (("可恢复", "recoverab"), "recoverability"),
    (("身份", "捷径", "identity", "shortcut"), "shortcut probes"),
    (("随机标签", "random-label", "random label"), "random-label control"),
)


def _title(grammar: Any, brief: dict[str, Any], asset: dict[str, Any]) -> str:
    title = grammar._text(
        brief.get("title") or asset.get("caption"), "Source-grounded scientific method",
    )
    if len(title) <= 58:
        return title
    separator = re.search(r"\s*[:：—–-]\s*", title)
    if separator and separator.start() >= 12:
        title = title[:separator.start()].strip()
    return title if len(title) <= 58 else title[:55].rstrip(" ，,;；") + "…"


def _declared_input(grammar: Any, brief: dict[str, Any], title: str) -> str:
    values = [grammar._text(value) for value in brief.get("inputs") or [] if grammar._text(value)]
    generic = {"sample data", "available metadata", "observation state", "study data", "input data"}
    declared = next((value for value in values if value.casefold() not in generic), "")
    if declared:
        return declared
    problem = " ".join((grammar._text(brief.get("problem")), title)).casefold()
    return next((label for marker, label in (
        ("eeg", "EEG signal windows"), ("ecg", "ECG signal windows"),
        ("image", "Images / patches"), ("text", "Text / token sequences"),
        ("graph", "Graph observations"), ("omics", "Samples / molecular profiles"),
        ("clinical", "Cohort observations"), ("simulation", "Scenarios / parameters"),
    ) if marker in problem), "Scientific observations")


def _mechanism(grammar: Any, mechanisms: list[dict[str, Any]], index: int, fallback: str) -> tuple[str, str]:
    if index >= len(mechanisms):
        return fallback, "declared mechanism and controlled comparison"
    item = mechanisms[index]
    label = grammar._text(item.get("name"), fallback)[:54]
    detail = grammar._text(item.get("description"))
    normalized = detail.casefold()
    markers = [display for aliases, display in MARKER_GROUPS if any(alias in normalized for alias in aliases)][:3]
    marker_set = set(markers)
    compact = " · ".join(markers)
    if {"retention", "temporal concentration", "channel synchrony"} <= marker_set:
        return "Conditional Mask Geometry", "retention · time clustering · channel sync"
    if {"continuous tasks", "event tasks"} <= marker_set:
        label = "Task × Domain Interaction"
    elif marker_set & {"collapse", "recoverability", "shortcut probes"}:
        label = "Shortcut & Collapse Diagnostics"
    if not compact:
        compact = re.split(r"[。.;；]", detail, maxsplit=1)[0].strip()[:38]
    return label, compact or "declared mechanism and controls"


def _endpoint(grammar: Any, brief: dict[str, Any], family: str) -> str:
    values = [
        grammar._text(value)
        for value in brief.get("reported_endpoints") or brief.get("endpoints") or []
        if grammar._text(value)
    ][:3]
    detail = " · ".join(values)[:78]
    if detail and detail.casefold() not in {"declared task output", "declared study output"}:
        return detail
    return (
        "held-out performance · interaction · uncertainty"
        if family == "predictive_model"
        else "registered outcomes · uncertainty · sensitivity"
    )


def _nodes(
    grammar: Any, declared_input: str, mechanisms: list[tuple[str, str]],
    endpoint: str, family: str, labels: dict[str, str],
) -> list[dict[str, Any]]:
    first, second, third = mechanisms
    definitions = (
        ("story_input", declared_input, "observed input shape and analysis unit", 135, 230, 190, 104, "signal", "data"),
        ("story_data_contract", "Leakage-safe data contract", "group-disjoint split · train-only preprocessing", 370, 230, 220, 104, "database", "data"),
        ("story_intervention", first[0], first[1], 650, 230, 220, 112, "matrix", "conditioning"),
        ("story_core", "Shared representation encoder" if family == "predictive_model" else labels["method"].title(), "masking · encoder · shared parameters", 930, 230, 220, 112, "module_stack", "representation"),
        ("story_representation", second[0], second[1], 1210, 230, 220, 104, "embedding", "representation"),
        ("story_objective", "Matched pre-training objective" if family == "predictive_model" else labels["objectives"].title(), "matched tokens · updates · parameters", 760, 560, 240, 104, "loss", "objective"),
        ("story_diagnostics", "Mechanism objectives", "primary objective · auxiliary constraints", 1040, 560, 230, 108, "audit", "neutral"),
        ("story_evaluation", third[0], third[1], 1320, 560, 240, 108, "head", "evaluation"),
        ("story_outputs", labels["output"], endpoint, 1320, 760, 240, 104, "metric_card", "data"),
    )
    return [grammar._node(
        {}, node_id=i, label=label, sublabel=detail, x=x, y=y,
        width=width, height=height, visual_kind=kind, palette_role=palette,
    ) for i, label, detail, x, y, width, height, kind, palette in definitions]


def _edges() -> list[dict[str, Any]]:
    return [
        {"from": "story_input", "to": "story_data_contract", "label": "sampling", "color": "#2563EB", "thickness": 2.4},
        {"from": "story_data_contract", "to": "story_intervention", "label": "audited batches", "color": "#7C3AED", "thickness": 2.4},
        {"from": "story_intervention", "to": "story_core", "label": "conditioned input", "color": "#0F766E", "thickness": 2.6},
        {"from": "story_core", "to": "story_representation", "label": "encode", "color": "#0F766E", "thickness": 2.6},
        {"from": "story_representation", "to": "story_objective", "label": "training branch", "color": "#D97706", "thickness": 2.4, "curve": True},
        {"from": "story_objective", "to": "story_diagnostics", "label": "", "color": "#64748B", "thickness": 2.0},
        {"from": "story_representation", "to": "story_evaluation", "label": "held-out adaptation", "color": "#BE123C", "thickness": 2.4, "curve": True},
        {"from": "story_evaluation", "to": "story_outputs", "label": "registered evidence", "color": "#2563EB", "thickness": 2.3},
    ]


def _groups(labels: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {"id": "story_data_group", "label": "DATA & SAMPLING", "node_ids": ["story_input", "story_data_contract"], "padding": 20, "fill": "#F8FBFF", "stroke": "#D7E6F7"},
        {"id": "story_method_group", "label": labels["method"], "node_ids": ["story_intervention", "story_core", "story_representation"], "padding": 20, "fill": "#F3FAF8", "stroke": "#CDE8E2"},
        {"id": "story_training_group", "label": labels["objectives"], "node_ids": ["story_objective", "story_diagnostics"], "padding": 20, "fill": "#FFF9F2", "stroke": "#F3DFC4"},
        {"id": "story_evaluation_group", "label": labels["evaluation"], "node_ids": ["story_evaluation", "story_outputs"], "padding": 20, "fill": "#F8FAFC", "stroke": "#D9E0E8"},
    ]


def _target(grammar: Any, component: dict[str, Any]) -> str:
    lane, text = str(component.get("lane") or "").casefold(), grammar._component_text(component)
    if lane == "data_and_sampling":
        return "story_intervention" if any(term in text for term in ("mask", "geometry", "condition", "augment", "perturb")) else "story_data_contract"
    if lane == "training_objective":
        return "story_objective"
    if lane == "evaluation":
        return "story_outputs" if any(term in text for term in ("metric", "record", "persist", "aggregate", "bootstrap")) else "story_evaluation"
    if lane == "diagnostics_and_accounting" or any(term in text for term in ("provenance", "audit", "check step", "collapse", "probe")):
        return "story_diagnostics"
    for terms, target in (
        (("infer", "interaction", "heldout", "evaluation"), "story_evaluation"),
        (("objective", "loss", "optim", "weight"), "story_objective"),
        (("mask", "geometry", "condition", "intervention"), "story_intervention"),
        (("embedding", "projection", "representation", "pool"), "story_representation"),
    ):
        if any(term in text for term in terms):
            return target
    return "story_core"


def _mappings(grammar: Any, components: list[dict[str, Any]]) -> list[dict[str, str]]:
    mappings: list[dict[str, str]] = []
    for component in components:
        mapping = grammar._source_mapping(
            _target(grammar, component), component,
            semantic_role="aggregated implementation evidence",
        )
        mapping["component_id"] = str(component.get("id") or "")
        mappings.append(mapping)
    return mappings


def _spec(title: str, nodes: list[dict[str, Any]], labels: dict[str, str]) -> dict[str, Any]:
    return {
        "title": title, "canvas": {"width": 1600, "height": 900},
        "style": {"font_family": "Arial, Helvetica, sans-serif", "font_size": 16,
                  "bg_color": "#FFFFFF", "palette": ["#2563EB", "#0F766E", "#7C3AED", "#D97706", "#BE123C", "#475569"]},
        "nodes": nodes, "edges": _edges(), "groups": _groups(labels),
        "labels": [
            {"text": title, "x": 800, "y": 42, "font_size": 25, "color": "#0F172A", "anchor": "middle"},
            {"text": "Scientific idea first · implementation provenance retained · train/eval separated", "x": 800, "y": 72, "font_size": 14, "color": "#64748B", "anchor": "middle"},
        ],
    }


def compile_mechanism_story(
    grammar: Any, asset: dict[str, Any], components: list[dict[str, Any]], family: str,
) -> ArchitectureCompilation:
    brief = dict(asset.get("method_brief") or {})
    mechanisms = [
        dict(item) for item in brief.get("mechanism_nodes") or []
        if isinstance(item, dict) and grammar._text(item.get("name"))
    ][:3]
    title = _title(grammar, brief, asset)
    labels = grammar._profile_labels(family)
    mechanism_labels = [
        _mechanism(grammar, mechanisms, 0, "Scientific intervention"),
        _mechanism(grammar, mechanisms, 1, "Held-out task and domain evaluation"),
        _mechanism(grammar, mechanisms, 2, "Alternative-explanation diagnostics"),
    ]
    nodes = _nodes(
        grammar, _declared_input(grammar, brief, title), mechanism_labels,
        _endpoint(grammar, brief, family), family, labels,
    )
    return ArchitectureCompilation(
        spec=_spec(title, nodes, labels), element_mappings=_mappings(grammar, components),
        profile={
            "compiler": "scientific-architecture-v1", "grammar_version": 3,
            "architecture_family": family, "component_count": len(components),
            "rendered_node_count": len(nodes),
            "covered_component_ids": [str(item.get("id") or "") for item in components],
            "covered_mechanism_names": [grammar._text(item.get("name")) for item in mechanisms],
            "semantic_aggregation": True,
            "implementation_status": (asset.get("architecture_blueprint") or {}).get("implementation_status"),
        },
    )
