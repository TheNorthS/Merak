"""Generic source-grounded scientific architecture scene compiler."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .scientific_architecture_models import ArchitectureCompilation


@dataclass
class GenericScene:
    grammar: Any
    asset: dict[str, Any]
    blueprint: dict[str, Any]
    provenance_components: list[dict[str, Any]]
    components: list[dict[str, Any]]
    family: str
    labels: dict[str, str]
    data: list[dict[str, Any]]
    conditioning: list[dict[str, Any]]
    representation: list[dict[str, Any]]
    objectives: list[dict[str, Any]]
    evaluation: list[dict[str, Any]]
    diagnostics: list[dict[str, Any]]
    has_contrastive: bool
    has_masking: bool
    title: str
    nodes: list[dict[str, Any]] = field(default_factory=list)
    mappings: list[dict[str, str]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    groups: list[dict[str, Any]] = field(default_factory=list)
    branch_ids: list[str] = field(default_factory=list)
    objective_ids: list[str] = field(default_factory=list)
    last_data_id: str = ""
    last_rep_id: str = ""
    task_node: Optional[dict[str, Any]] = None
    metrics_id: str = "compiled_held_out_metrics"
    output_x: float = 0
    rep_start_x: float = 900
    rep_spacing: float = 220
    derived_source: str = "experiments/METHOD_CONTRACT.json"
    has_control: bool = False


def _components(asset: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    blueprint = dict(asset.get("architecture_blueprint") or {})
    provenance = [
        dict(item) for item in blueprint.get("components") or []
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]
    if not provenance:
        raise ValueError("architecture blueprint contains no source-grounded components")
    visible = [item for item in provenance if item.get("publication_visible", True) is not False]
    if not visible:
        raise ValueError("architecture blueprint contains no publication-visible scientific components")
    return blueprint, provenance, visible


def _mechanism_nodes(grammar: Any, asset: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    nodes = [
        dict(item) for item in (asset.get("method_brief") or {}).get("mechanism_nodes") or []
        if isinstance(item, dict) and grammar._text(item.get("name"))
    ]
    text = " ".join(
        f"{grammar._text(item.get('name'))} {grammar._text(item.get('description'))}"
        for item in nodes
    ).casefold().replace("_", " ")
    return nodes, text


def _predictive_structure(grammar: Any, components: list[dict[str, Any]], blueprint: dict[str, Any]) -> bool:
    terms = (
        "classifier", "task_head", "classification_head", "prediction_head",
        "logits", "encoder", "residual", "conv", "transformer", "softmax",
    )
    component_match = any(any(term in " ".join((
        grammar._text(item.get("label")), grammar._text(item.get("display_name")),
        grammar._text(item.get("source_symbol")), grammar._text(item.get("operation")),
    )).casefold().replace(" ", "_") for term in terms) for item in components)
    flow_match = any(
        isinstance(flow, dict) and str(flow.get("flow_kind") or "").casefold() == "data"
        for flow in blueprint.get("tensor_flow") or []
    )
    return component_match or flow_match


def _specialized(
    grammar: Any, asset: dict[str, Any], blueprint: dict[str, Any],
    provenance: list[dict[str, Any]], components: list[dict[str, Any]], family: str,
) -> Optional[ArchitectureCompilation]:
    mechanisms, mechanism_text = _mechanism_nodes(grammar, asset)
    factorized = ("z state" in mechanism_text and "z acq" in mechanism_text) or (
        any(term in mechanism_text for term in ("factorized", "factorised", "因子化", "分解"))
        and any(term in mechanism_text for term in ("acquisition", "采集", "nuisance"))
    )
    if family == "predictive_model" and factorized:
        return grammar._compile_factorized_representation_story(asset, provenance, family, mechanisms)
    predictive = _predictive_structure(grammar, components, blueprint)
    suite = list(
        (blueprint.get("model_configuration") or {}).get("model_suite")
        or (asset.get("method_brief") or {}).get("models") or []
    )
    if predictive and len(suite) >= 2:
        return grammar._compile_benchmark_model_suite(asset, provenance, family)
    if len(mechanisms) >= 2 and not predictive:
        return grammar._compile_mechanism_story(asset, provenance, family)
    return None


def _ordered(
    grammar: Any, blueprint: dict[str, Any], by_id: dict[str, dict[str, Any]],
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ids = {str(item["id"]) for item in items}
    order: list[str] = []
    for path in list(blueprint.get("inference_paths") or []) + list(blueprint.get("training_paths") or []):
        if isinstance(path, list):
            order.extend(str(value) for value in path if str(value) in ids)
    order.extend(str(item["id"]) for item in items)
    return [by_id[item_id] for item_id in grammar._dedupe(order) if item_id in by_id]


def _lanes(grammar: Any, blueprint: dict[str, Any], components: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    parents = {
        str(item.get("from") or "") for item in blueprint.get("tensor_flow") or []
        if isinstance(item, dict)
        and str(item.get("flow_kind") or "") in {"containment", "module_reference"}
    }
    renderable = [
        item for item in components
        if str(item.get("id") or "") not in parents
        or str(item.get("lane") or "") in {
            "data_and_sampling", "evaluation", "diagnostics_and_accounting",
        }
    ]
    raw: dict[str, list[dict[str, Any]]] = {}
    for item in renderable:
        raw.setdefault(str(item.get("lane") or "representation_model"), []).append(item)
    by_id = {str(item["id"]): item for item in components}
    return {key: _ordered(grammar, blueprint, by_id, items) for key, items in raw.items()}


def _representation(grammar: Any, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names = {"models.py", "model.py", "network.py", "networks.py", "architecture.py", "architectures.py"}
    terms = ("residual", "encoder", "backbone", "projection", "embedding", "classifier", "block", "attention", "convolution")

    def priority(item: dict[str, Any]) -> tuple[int, int]:
        text, score = grammar._component_text(item), 0
        if Path(str(item.get("source_path") or "").casefold()).name in names:
            score += 20
        score += sum(12 - min(weight, 10) for weight, term in enumerate(terms, 1) if term in text)
        if any(term in text for term in ("ledger", "registry", "config", "evidence", "orchestration", "ablation switches", "validate")):
            score -= 20
        return -score, items.index(item)

    return sorted(items, key=priority)[:5]


def _scene(grammar: Any, asset: dict[str, Any], blueprint: dict[str, Any], provenance: list[dict[str, Any]], components: list[dict[str, Any]], family: str) -> GenericScene:
    lanes = _lanes(grammar, blueprint, components)
    data_items = lanes.get("data_and_sampling", [])
    data = [item for item in data_items if grammar._visual_kind(item) in {"signal", "database"}][:2] or data_items[:1]
    conditioning = [item for item in data_items if grammar._visual_kind(item) == "matrix"][:1]
    representation = _representation(grammar, lanes.get("representation_model", []))
    objective_items = lanes.get("training_objective", [])
    objectives = [item for item in objective_items if grammar._visual_kind(item) in {"loss", "decoder"}][:3] or objective_items[:2]
    evaluation_items = lanes.get("evaluation", [])
    evaluation = sorted(evaluation_items, key=lambda item: (
        0 if any(term in grammar._component_text(item) for term in ("task head", "classification head", "prediction head", "logits")) else 1,
        evaluation_items.index(item),
    ))[:1]
    text = " ".join(grammar._component_text(item) for item in components)
    brief = dict(asset.get("method_brief") or {})
    title = grammar._text(brief.get("title") or asset.get("selected_idea") or asset.get("caption"), "Source-grounded model architecture")[:92]
    if not title or "�" in title:
        title = "Source-Grounded Model Architecture"
    return GenericScene(
        grammar, asset, blueprint, provenance, components, family,
        grammar._profile_labels(family), data, conditioning, representation,
        objectives, evaluation, lanes.get("diagnostics_and_accounting", [])[:1],
        family == "predictive_model" and any(term in text for term in ("contrastive", "xent", "two augmentation views")),
        family == "predictive_model" and any(term in text for term in ("masked view", "mask ratio", "topology mask", "reconstruct")),
        title,
    )


def _data_nodes(scene: GenericScene) -> None:
    for index, component in enumerate(scene.data):
        node = scene.grammar._node(component, x=(190, 430)[min(index, 1)], y=430, width=205, height=98)
        scene.nodes.append(node)
        scene.mappings.append(scene.grammar._source_mapping(node["id"], component))
        if index:
            scene.edges.append({"from": scene.nodes[-2]["id"], "to": node["id"], "label": "audited records", "color": "#2563EB", "thickness": 2.3})
    scene.last_data_id = scene.nodes[-1]["id"] if scene.nodes else ""
    scene.derived_source = next((
        str(item.get("source_path") or "")
        for item in scene.blueprint.get("configuration_constraints") or []
        if isinstance(item, dict) and str(item.get("source_path") or "")
    ), "experiments/METHOD_CONTRACT.json")


def _branch_node(scene: GenericScene, node: dict[str, Any], label: str, color: str) -> None:
    scene.nodes.append(node)
    scene.mappings.append(scene.grammar._source_mapping(
        node["id"], None, fallback_path=scene.derived_source,
        semantic_role=f"{label} architecture branch",
    ))
    scene.branch_ids.append(node["id"])
    if scene.last_data_id:
        scene.edges.append({"from": scene.last_data_id, "to": node["id"], "label": label, "color": color, "thickness": 2.1})


def _branch_nodes(scene: GenericScene) -> None:
    grammar = scene.grammar
    if scene.has_contrastive:
        for suffix, y in (("a", 245), ("b", 430)):
            _branch_node(scene, grammar._node(
                {}, node_id=f"compiled_temporal_view_{suffix}",
                label=f"Augmented view {suffix.upper()}", sublabel="shared augmentation policy",
                x=655, y=y, width=190, height=84, visual_kind="signal", palette_role="representation",
            ), f"view {suffix.upper()}", "#0F766E")
    if scene.has_masking:
        component = scene.conditioning[0] if scene.conditioning else None
        _branch_node(scene, grammar._node(
            component or {}, node_id=str(component.get("id")) if component else "compiled_masked_view",
            label=grammar._short_label(component) if component else "Masked view",
            sublabel=grammar._sublabel(component) if component else "structured corruption",
            x=655, y=615, width=190, height=86, visual_kind="matrix", palette_role="conditioning",
        ), "masked branch", "#7C3AED")


def _representation_nodes(scene: GenericScene) -> None:
    grammar = scene.grammar
    ids = {str(item.get("id") or "") for item in scene.representation}
    declared = [
        dict(item) for item in scene.blueprint.get("tensor_flow") or []
        if isinstance(item, dict) and str(item.get("from") or "") in ids
        and str(item.get("to") or "") in ids
        and str(item.get("flow_kind") or "") not in {"containment", "module_reference"}
    ]
    for index, component in enumerate(scene.representation):
        node = grammar._node(
            component, x=scene.rep_start_x + index * scene.rep_spacing, y=430,
            width=190 if index != 1 else 210, height=96,
        )
        scene.nodes.append(node)
        scene.mappings.append(grammar._source_mapping(node["id"], component))
        if index and not declared:
            scene.edges.append({
                "from": scene.representation[index - 1]["id"], "to": node["id"],
                "label": "" if index % 2 == 0 else scene.labels["flow"],
                "color": "#0F766E", "thickness": 2.6,
            })
    scene.edges.extend({
        "from": str(flow.get("from") or ""), "to": str(flow.get("to") or ""),
        "label": scene.labels["flow"] if index % 2 == 0 else "",
        "color": "#0F766E", "thickness": 2.6,
    } for index, flow in enumerate(declared[:10]))
    first = str(scene.representation[0]["id"]) if scene.representation else ""
    scene.last_rep_id = str(scene.representation[-1]["id"]) if scene.representation else ""
    if first and scene.branch_ids:
        scene.edges.extend({
            "from": branch, "to": first,
            "label": "shared weights" if scene.has_contrastive else "input",
            "color": "#0F766E" if "view" in branch else "#7C3AED", "thickness": 2.4,
        } for branch in scene.branch_ids)
    elif first and scene.last_data_id:
        scene.edges.append({"from": scene.last_data_id, "to": first, "label": "model input", "color": "#0F766E", "thickness": 2.4})
    last_x = scene.rep_start_x + max(0, len(scene.representation) - 1) * scene.rep_spacing
    scene.output_x = last_x + 285


def _objective_nodes(scene: GenericScene) -> None:
    positions = (205, 560, 705)
    for index, component in enumerate(scene.objectives):
        node = scene.grammar._node(
            component, x=scene.output_x, y=positions[min(index, 2)], width=235, height=96,
            palette_role="conditioning" if scene.grammar._visual_kind(component) == "decoder" else "objective",
        )
        scene.nodes.append(node)
        scene.mappings.append(scene.grammar._source_mapping(node["id"], component))
        scene.objective_ids.append(node["id"])
        if scene.last_rep_id:
            scene.edges.append({
                "from": scene.last_rep_id, "to": node["id"], "label": "objective branch",
                "color": node["stroke"], "thickness": 2.4, "curve": index == 0,
            })


def _task_node(scene: GenericScene) -> None:
    if not scene.evaluation:
        return
    component = scene.evaluation[0]
    node = scene.grammar._node(
        component, node_id=str(component.get("id") or "compiled_evaluation"),
        x=scene.output_x, y=875, width=240, height=98,
        visual_kind="head" if scene.family == "predictive_model" else scene.grammar._visual_kind(component),
        palette_role="neutral",
    )
    scene.task_node = node
    scene.nodes.append(node)
    scene.mappings.append(scene.grammar._source_mapping(
        node["id"], component, semantic_role="declared evaluation or outcome contract",
    ))
    if scene.last_rep_id:
        scene.edges.append({
            "from": scene.last_rep_id, "to": node["id"],
            "label": "adaptation" if scene.family == "predictive_model" else scene.labels["flow"],
            "color": "#475569", "thickness": 2.3, "curve": True,
        })


def _metric_terms(scene: GenericScene) -> list[str]:
    brief = scene.asset.get("method_brief") or {}
    terms = scene.grammar._dedupe(
        scene.grammar._text(value)[:24]
        for value in brief.get("reported_endpoints") or brief.get("endpoints") or []
    )[:4]
    if terms or not scene.evaluation:
        return terms
    text = scene.grammar._component_text(scene.evaluation[0])
    labels = (("balanced", "Balanced accuracy"), ("accuracy", "Accuracy"), ("auroc", "AUROC"), ("f1", "F1"), ("ece", "ECE"), ("brier", "Brier"), ("calibration", "Calibration"))
    terms = scene.grammar._dedupe(label for marker, label in labels if marker in text)[:4]
    if "Balanced accuracy" in terms and "Accuracy" in terms:
        terms.remove("Accuracy")
    return terms


def _metrics_node(scene: GenericScene) -> None:
    terms = _metric_terms(scene)
    node = scene.grammar._node(
        {}, node_id=scene.metrics_id, label=scene.labels["output"],
        sublabel=" · ".join(terms) if terms else "declared endpoints and uncertainty",
        x=scene.output_x + 285, y=875, width=250, height=98,
        visual_kind="metric_card", palette_role="data",
    )
    scene.nodes.append(node)
    scene.mappings.append(scene.grammar._source_mapping(
        scene.metrics_id, None, semantic_role="declared study outcomes",
    ))
    source = scene.task_node["id"] if scene.task_node else scene.last_rep_id or scene.last_data_id
    if source:
        scene.edges.append({
            "from": source, "to": scene.metrics_id,
            "label": "probabilities" if scene.family == "predictive_model" and scene.task_node else "reported as",
            "color": "#2563EB", "thickness": 2.2,
        })


def _diagnostic_node(scene: GenericScene) -> None:
    if not scene.diagnostics:
        return
    component = scene.diagnostics[0]
    node = scene.grammar._node(
        component, x=200, y=825, width=210, height=86,
        visual_kind="audit", palette_role="neutral",
    )
    scene.nodes.append(node)
    scene.mappings.append(scene.grammar._source_mapping(node["id"], component))
    if scene.data:
        scene.edges.append({
            "from": scene.data[0]["id"], "to": node["id"], "label": "provenance",
            "color": "#64748B", "thickness": 1.7, "style": "dashed",
        })


def _control_node(scene: GenericScene) -> None:
    brief = scene.asset.get("method_brief") or {}
    constraints = [dict(item) for item in scene.blueprint.get("configuration_constraints") or [] if isinstance(item, dict)]
    conditions = [scene.grammar._text(value) for value in brief.get("study_conditions") or [] if scene.grammar._text(value)]
    text = " ".join(scene.grammar._text(item.get("key") or item.get("purpose")) for item in constraints).casefold()
    scene.has_control = bool(conditions) or any(term in text for term in (
        "match", "budget", "control", "baseline", "random", "allocation", "adjust", "batch", "seed", "replicate",
    ))
    if not scene.has_control:
        return
    last_x = scene.rep_start_x + max(0, len(scene.representation) - 1) * scene.rep_spacing
    node = scene.grammar._node(
        {}, node_id="compiled_matched_control",
        label="Matched-budget control" if scene.family == "predictive_model" else "Controls and study conditions",
        sublabel=" · ".join(scene.grammar._dedupe(conditions)[:4]) or "declared constraints · comparators · replication",
        x=max(950, (scene.rep_start_x + last_x) / 2), y=920, width=350, height=90,
        visual_kind="ledger", palette_role="neutral",
    )
    scene.nodes.append(node)
    scene.mappings.append(scene.grammar._source_mapping(
        node["id"], None, fallback_path=scene.derived_source,
        semantic_role="declared control and comparison constraints",
    ))


def _groups(scene: GenericScene) -> None:
    definitions = [
        ("compiled_data_protocol", "DATA & SAMPLING", [str(item["id"]) for item in scene.data] + scene.branch_ids + ([str(scene.diagnostics[0]["id"])] if scene.diagnostics else []), "#F8FBFF", "#D7E6F7"),
        ("compiled_representation", scene.labels["method"], [str(item["id"]) for item in scene.representation], "#F3FAF8", "#CDE8E2"),
        ("compiled_objectives", scene.labels["objectives"], scene.objective_ids, "#FFF9F2", "#F3DFC4"),
        ("compiled_evaluation", scene.labels["evaluation"], ([scene.task_node["id"]] if scene.task_node else []) + [scene.metrics_id], "#F8FAFC", "#D9E0E8"),
    ]
    if scene.has_control:
        definitions.append(("compiled_control", "CONTROLS", ["compiled_matched_control"], "#F8FAFC", "#D9E0E8"))
    scene.groups.extend({
        "id": group_id, "label": label, "node_ids": scene.grammar._dedupe(ids),
        "padding": 20, "fill": fill, "stroke": stroke,
    } for group_id, label, ids, fill, stroke in definitions if ids)


def _result(scene: GenericScene) -> ArchitectureCompilation:
    width = max(2100, int(scene.output_x + 500))
    subtitle = (
        "Source-grounded modules · shared weights shown once · train/eval paths separated"
        if scene.family == "predictive_model"
        else "Source-grounded stages · declared dependencies · outcomes and controls separated"
    )
    spec = {
        "title": scene.title, "canvas": {"width": width, "height": 1060},
        "style": {"font_family": "Arial, Helvetica, sans-serif", "font_size": 16,
                  "bg_color": "#FFFFFF", "palette": ["#2563EB", "#0F766E", "#7C3AED", "#D97706", "#BE123C", "#475569"]},
        "nodes": scene.nodes, "edges": scene.edges[:24], "groups": scene.groups,
        "labels": [
            {"text": scene.title, "x": width / 2, "y": 52, "font_size": 28, "color": "#0F172A", "anchor": "middle"},
            {"text": subtitle, "x": width / 2, "y": 84, "font_size": 15, "color": "#64748B", "anchor": "middle"},
        ],
    }
    return ArchitectureCompilation(spec=spec, element_mappings=scene.mappings, profile={
        "compiler": "scientific-architecture-v1", "grammar_version": 2,
        "architecture_family": scene.family, "component_count": len(scene.components),
        "rendered_node_count": len(scene.nodes),
        "has_contrastive_branch": scene.has_contrastive,
        "has_masking_branch": scene.has_masking,
        "implementation_status": scene.blueprint.get("implementation_status"),
    })


def compile_architecture(grammar: Any, asset: dict[str, Any]) -> ArchitectureCompilation:
    blueprint, provenance, components = _components(asset)
    family = grammar._architecture_family(asset, components)
    specialized = _specialized(grammar, asset, blueprint, provenance, components, family)
    if specialized is not None:
        return specialized
    scene = _scene(grammar, asset, blueprint, provenance, components, family)
    _data_nodes(scene)
    _branch_nodes(scene)
    _representation_nodes(scene)
    _objective_nodes(scene)
    _task_node(scene)
    _metrics_node(scene)
    _diagnostic_node(scene)
    _control_node(scene)
    _groups(scene)
    return _result(scene)
