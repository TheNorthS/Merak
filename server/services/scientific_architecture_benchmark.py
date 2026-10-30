"""Comparative model-suite grammar for scientific architecture figures."""

from __future__ import annotations

from typing import Any

from .scientific_architecture_models import ArchitectureCompilation


def _model_configuration(grammar: Any, asset: dict[str, Any]) -> tuple[dict[str, Any], list[str], str]:
    brief = dict(asset.get("method_brief") or {})
    blueprint = dict(asset.get("architecture_blueprint") or {})
    config = dict(blueprint.get("model_configuration") or {})
    raw = list(config.get("model_suite") or brief.get("models") or [])
    models = [grammar._text(value).title() for value in raw if grammar._text(value)]
    defaults = ("Linear Reference", "MLP Reference", "Residual MLP")
    while len(models) < 3:
        models.append(defaults[len(models)])
    width, depth = config.get("hidden_dim") or "d", config.get("depth") or "K"
    expanded = str(int(width) * 2) if str(width).isdigit() else f"2×{width}"
    detail = f"{depth}× blocks: LN → Linear {expanded} → GELU → Dropout → Linear {width} + skip"
    if config.get("dropout") not in (None, ""):
        detail += f"  (dropout {config['dropout']})"
    return config, models[:3], detail


def _nodes(grammar: Any, config: dict[str, Any], models: list[str], residual: str) -> list[dict[str, Any]]:
    width, classes = config.get("hidden_dim") or "d", config.get("num_classes") or "C"
    definitions = (
        ("bench_input", "Versioned inputs", "features · labels · source groups", 140, 350, 210, 120, "database", "data"),
        ("bench_split", "Leakage-safe partitions", "train · selection · calibration · held-out", 140, 535, 210, 105, "matrix", "data"),
        ("bench_linear", models[0], f"flattened input → linear {classes}-class head", 455, 225, 235, 105, "head", "neutral"),
        ("bench_mlp", models[1], f"Linear {width} → GELU → repeated dense layers", 455, 405, 235, 115, "module_stack", "representation"),
        ("bench_residual_stem", models[2], f"input projection → {width}-dimensional representation", 455, 600, 235, 115, "embedding", "representation"),
        ("bench_residual_blocks", "Residual block stack", residual, 770, 600, 360, 150, "module_stack", "representation"),
        ("bench_head", "Shared task interface", f"{classes}-class logits → probabilities", 1170, 405, 225, 115, "head", "evaluation"),
        ("bench_calibration", "Temperature calibration", "fit on calibration split only", 1170, 600, 225, 100, "module", "conditioning"),
        ("bench_endpoints", "Held-out endpoints", "i.i.d. · shifts · NLL/Brier · latency/memory", 1475, 405, 245, 125, "metric_card", "data"),
        ("bench_decision", "Paired cross-axis decision", "5 seeds · 95% CI · MPID · Holm", 1780, 405, 245, 125, "metric_card", "objective"),
        ("bench_controls", "Matched controls", "one factor changes; data, budget, seeds stay fixed", 770, 790, 300, 100, "ledger", "conditioning"),
        ("bench_ledger", "Run-resolved evidence ledger", "data · split · config · prediction · device", 1730, 775, 300, 105, "audit", "neutral"),
    )
    return [
        grammar._node({}, node_id=i, label=label, sublabel=s, x=x, y=y, width=w,
                      height=h, visual_kind=k, palette_role=p)
        for i, label, s, x, y, w, h, k, p in definitions
    ]


def _edges() -> list[dict[str, Any]]:
    raw = (
        ("bench_input", "bench_split", "group identity", "#2563EB", 2.3, False, "solid"),
        ("bench_split", "bench_linear", "matched input", "#64748B", 2.1, False, "solid"),
        ("bench_split", "bench_mlp", "matched input", "#0F766E", 2.3, False, "solid"),
        ("bench_split", "bench_residual_stem", "matched input", "#0F766E", 2.5, False, "solid"),
        ("bench_residual_stem", "bench_residual_blocks", "residual path", "#0F766E", 2.7, False, "solid"),
        ("bench_linear", "bench_head", "logits", "#64748B", 2.0, True, "solid"),
        ("bench_mlp", "bench_head", "logits", "#0F766E", 2.1, False, "solid"),
        ("bench_residual_blocks", "bench_head", "representation", "#0F766E", 2.6, False, "solid"),
        ("bench_head", "bench_calibration", "calibration split", "#7C3AED", 2.0, False, "solid"),
        ("bench_head", "bench_endpoints", "held-out predictions", "#BE123C", 2.4, False, "solid"),
        ("bench_calibration", "bench_endpoints", "calibrated probabilities", "#7C3AED", 2.1, False, "solid"),
        ("bench_endpoints", "bench_decision", "paired effects", "#D97706", 2.5, False, "solid"),
        ("bench_controls", "bench_residual_stem", "single-factor variants", "#7C3AED", 2.0, False, "dashed"),
        ("bench_endpoints", "bench_ledger", "raw artifacts", "#64748B", 1.8, False, "dashed"),
        ("bench_ledger", "bench_decision", "admissibility", "#64748B", 1.9, False, "dashed"),
    )
    return [
        {"from": a, "to": b, "label": label, "color": color, "thickness": thick,
         **({"curve": True} if curve else {}), **({"style": style} if style != "solid" else {})}
        for a, b, label, color, thick, curve, style in raw
    ]


def _groups() -> list[dict[str, Any]]:
    return [
        {"id": "bench_data_group", "label": "1  DATA & ISOLATION", "node_ids": ["bench_input", "bench_split"], "padding": 24, "fill": "#FBFDFF", "stroke": "#CFE0F4"},
        {"id": "bench_models_group", "label": "2  MATCHED MODEL SUITE", "node_ids": ["bench_linear", "bench_mlp", "bench_residual_stem", "bench_residual_blocks"], "padding": 24, "fill": "#FBFDFC", "stroke": "#C9E7DE"},
        {"id": "bench_output_group", "label": "3  PREDICTION & CALIBRATION", "node_ids": ["bench_head", "bench_calibration"], "padding": 24, "fill": "#FDFCFF", "stroke": "#DED3F1"},
        {"id": "bench_inference_group", "label": "4  REGISTERED INFERENCE", "node_ids": ["bench_endpoints", "bench_decision"], "padding": 24, "fill": "#FFFCF8", "stroke": "#F0D7B4"},
    ]


def _target(grammar: Any, component: dict[str, Any]) -> str:
    text, lane = grammar._component_text(component), str(component.get("lane") or "").casefold()
    routes = (
        (("residual", "layernorm", "skip connection"), "bench_residual_blocks"),
        (("task head", "classifier", "logits"), "bench_head"),
        (("calibrat",), "bench_calibration"),
        (("ranking", "holm", "paired", "metric"), "bench_decision"),
        (("ledger", "provenance", "evidence", "hash"), "bench_ledger"),
        (("ablation", "single factor", "matched"), "bench_controls"),
    )
    if lane == "data_and_sampling":
        return "bench_split"
    for terms, target in routes:
        if any(term in text for term in terms):
            return target
    return "bench_residual_stem" if lane == "representation_model" else "bench_endpoints"


def _mappings(grammar: Any, components: list[dict[str, Any]], nodes: list[dict[str, Any]]) -> list[dict[str, str]]:
    mappings: list[dict[str, str]] = []
    for component in components:
        mapping = grammar._source_mapping(
            _target(grammar, component), component,
            semantic_role="aggregated benchmark-architecture evidence",
        )
        mapping["component_id"] = str(component.get("id") or "")
        mappings.append(mapping)
    mapped = {item["element_id"] for item in mappings}
    mappings.extend(
        grammar._source_mapping(
            node["id"], None, fallback_path="experiments/configs/main.yaml",
            semantic_role="declared benchmark model path",
        )
        for node in nodes if node["id"] not in mapped
    )
    return mappings


def _spec(title: str, nodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "title": title, "canvas": {"width": 2080, "height": 930},
        "style": {"font_family": "Helvetica", "font_size": 16, "bg_color": "#FFFFFF",
                  "palette": ["#2563EB", "#0F766E", "#7C3AED", "#D97706", "#BE123C", "#475569"]},
        "nodes": nodes, "edges": _edges(), "groups": _groups(),
        "regions": [
            {"id": "bench_main_band", "label": "EXECUTABLE PREDICTION PATH", "x": 15, "y": 105, "width": 2050, "height": 635, "fill": "#FFFFFF", "stroke": "#D8E0EA", "radius": 18},
            {"id": "bench_evidence_band", "label": "MATCHED CONTROLS & TRACEABLE EVIDENCE", "x": 285, "y": 750, "width": 1765, "height": 160, "fill": "#FBFCFE", "stroke": "#D8E0EA", "radius": 18},
        ],
        "labels": [
            {"text": title, "x": 1040, "y": 42, "font_size": 27, "font_weight": "bold", "color": "#0F172A", "anchor": "middle"},
            {"text": "Protected data → matched model paths → calibrated endpoints → paired cross-axis decision", "x": 1040, "y": 74, "font_size": 15, "color": "#64748B", "anchor": "middle"},
        ],
    }


def compile_benchmark_model_suite(
    grammar: Any, asset: dict[str, Any], components: list[dict[str, Any]], family: str,
) -> ArchitectureCompilation:
    brief = dict(asset.get("method_brief") or {})
    blueprint = dict(asset.get("architecture_blueprint") or {})
    config, models, residual = _model_configuration(grammar, asset)
    nodes = _nodes(grammar, config, models, residual)
    title = grammar._text(brief.get("title"), "Matched Predictive Benchmark")
    if len(title) > 66:
        title = "Matched Model Suite and Cross-Axis Evaluation"
    return ArchitectureCompilation(
        spec=_spec(title, nodes), element_mappings=_mappings(grammar, components, nodes),
        profile={
            "compiler": "scientific-architecture-v1", "grammar_version": 5,
            "architecture_family": family, "visual_grammar": "benchmark_model_suite",
            "component_count": len(components), "rendered_node_count": len(nodes),
            "covered_component_ids": [str(item.get("id") or "") for item in components],
            "semantic_aggregation": True,
            "implementation_status": blueprint.get("implementation_status"),
        },
    )
