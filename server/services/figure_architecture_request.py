"""Source-grounding and semantic gates for method-architecture requests."""

from __future__ import annotations

import json
import math
import re
from typing import Any

from .figure_models import FigureResult, FigureType


def architecture_tokens(value: Any) -> set[str]:
    return {
        token for token in re.findall(
            r"[a-z0-9\u4e00-\u9fff]+", str(value or "").casefold(),
        ) if len(token) > 1
    }


def reconcile_components(metadata: dict[str, Any], output_dir: str) -> list[dict[str, Any]]:
    blueprint = metadata.get("architecture_blueprint")
    components = blueprint.get("components") if isinstance(blueprint, dict) else []
    if not isinstance(components, list) or not components:
        return []
    from .excalidraw_renderer import verify_element_mappings
    from .figure_artifacts import figure_artifact_registry

    root = figure_artifact_registry.project_root(output_dir)
    live: list[dict[str, Any]] = []
    stale: list[dict[str, str]] = []
    for raw in components:
        if not isinstance(raw, dict):
            continue
        component = dict(raw)
        component_id = str(component.get("id") or "").strip()
        source_path = str(component.get("source_path") or "").strip()
        if not component_id or not source_path:
            live.append(component)
            continue
        mapping = {
            "element_id": component_id, "source_path": source_path,
            "semantic_role": "architecture blueprint component",
        }
        symbol = str(component.get("source_symbol") or "").strip()
        if symbol:
            mapping["source_symbol"] = symbol
        issues = verify_element_mappings(
            {"elements": [{"id": component_id}]}, [mapping], root,
        )
        if issues:
            stale.append({
                "component_id": component_id, "source_path": source_path,
                "source_symbol": symbol, "reason": issues[0],
            })
        else:
            live.append(component)
    if stale and live:
        refreshed = dict(blueprint)
        refreshed["components"] = live
        metadata["architecture_blueprint"] = refreshed
        metadata["stale_architecture_components_ignored"] = stale
    return live if live else [dict(item) for item in components if isinstance(item, dict)]


def _authored_payload(code: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str]:
    if not code.strip():
        return None, [], ""
    try:
        payload = json.loads(code)
    except json.JSONDecodeError:
        return None, [], ""
    if not isinstance(payload, dict):
        return None, [], ""
    nodes = [dict(item) for item in payload.get("nodes") or [] if isinstance(item, dict)]
    text = " ".join(
        str(value or "") for node in nodes
        for value in (node.get("id"), node.get("label"), node.get("sublabel"))
    ).casefold().replace("_", " ")
    return payload, nodes, text


def _component_coverage(
    components: list[dict[str, Any]], nodes: list[dict[str, Any]], text: str,
) -> tuple[list[dict[str, Any]], int]:
    required = [
        item for item in components if item.get("required_visual", True)
    ][:12]
    tokens = architecture_tokens(text)
    covered = [
        item for item in required
        if architecture_tokens(item.get("label")) & tokens
        or str(item.get("id") or "").casefold() in text.replace(" ", "_")
    ]
    minimum = min(len(required), max(3, math.ceil(len(required) * 0.7))) if required else 0
    return covered, minimum


def _mechanism_coverage(
    metadata: dict[str, Any], text: str,
) -> tuple[list[dict[str, Any]], list[str], list[str], int]:
    brief = metadata.get("method_brief")
    mechanisms = [
        dict(item) for item in (
            brief.get("mechanism_nodes") if isinstance(brief, dict) else []
        ) or [] if isinstance(item, dict)
    ]
    names = [str(item.get("name") or "").strip() for item in mechanisms if str(item.get("name") or "").strip()]
    tokens = architecture_tokens(text)
    covered = [
        name for name in names
        if len(architecture_tokens(name) & tokens) >= min(2, len(architecture_tokens(name)))
    ]
    minimum = min(len(names), max(2, math.ceil(len(names) * 0.75))) if names else 0
    return mechanisms, names, covered, minimum


def _detail_hits(text: str) -> set[str]:
    markers = {
        "paired_views": ("paired view", "paired intervention", "counterfactual view"),
        "state_latent": ("z state", "state latent", "state representation"),
        "acquisition_latent": ("z acq", "acquisition latent", "acquisition representation"),
        "task_head": ("task head", "task logits", "task prediction"),
        "acquisition_head": ("acquisition head", "metadata head"),
        "nuisance_constraint": ("grl", "gradient reversal", "nuisance constraint"),
        "held_out_audit": ("held out", "frozen evaluation", "pareto audit"),
    }
    return {key for key, aliases in markers.items() if any(alias in text for alias in aliases)}


def _grounding(
    metadata: dict[str, Any], components: list[dict[str, Any]],
    nodes: list[dict[str, Any]], text: str,
) -> dict[str, Any]:
    node_ids = {str(node.get("id") or "") for node in nodes if str(node.get("id") or "")}
    supplied = [
        dict(item) for item in metadata.get("element_mappings") or []
        if isinstance(item, dict) and str(item.get("element_id") or "") in node_ids
        and str(item.get("source_path") or "").strip()
    ]
    covered_components, component_minimum = _component_coverage(components, nodes, text)
    mechanisms, names, covered_names, mechanism_minimum = _mechanism_coverage(metadata, text)
    mapping_minimum = min(len(nodes), max(4, math.ceil(len(nodes) * 0.5))) if nodes else 0
    semantic = bool(names and len(covered_names) >= mechanism_minimum and len(supplied) >= mapping_minimum)
    sources = [str(value).strip() for value in (
        list(metadata.get("source_artifacts") or []) + list(metadata.get("source_data") or [])
    ) if str(value).strip()]
    hits = _detail_hits(text)
    detailed = bool(len(nodes) >= 8 and len(hits) >= 4 and (sources or components))
    accepted = bool(nodes and len(nodes) >= 4 and (
        len(covered_components) >= component_minimum or semantic or detailed
    ))
    return {
        "accepted": accepted, "supplied": supplied,
        "covered_components": covered_components, "component_minimum": component_minimum,
        "mechanisms": mechanisms, "covered_names": covered_names,
        "mechanism_minimum": mechanism_minimum, "mapping_minimum": mapping_minimum,
        "semantic": semantic, "hits": hits, "sources": sources,
    }


def _derived_mappings(
    components: list[dict[str, Any]], nodes: list[dict[str, Any]],
    planned_sources: list[str],
) -> list[dict[str, str]]:
    mappings: list[dict[str, str]] = []
    for component in components:
        tokens = architecture_tokens(component.get("label") or component.get("source_symbol"))
        ranked = sorted((
            (len(tokens & architecture_tokens(" ".join(
                str(node.get(key) or "") for key in ("id", "label", "sublabel")
            ))), str(node.get("id") or ""))
            for node in nodes if str(node.get("id") or "")
        ), reverse=True)
        if not ranked or ranked[0][0] <= 0:
            continue
        mapping = {
            "element_id": ranked[0][1],
            "source_path": str(component.get("source_path") or ""),
            "semantic_role": "model-authored architecture evidence",
            "component_id": str(component.get("id") or ""),
        }
        symbol = str(component.get("source_symbol") or "")
        if symbol and mapping["source_path"].casefold().endswith(".py"):
            mapping["source_symbol"] = symbol
        mappings.append(mapping)
    mapped = {item["element_id"] for item in mappings}
    fallback = next((
        value for value in planned_sources
        if value.casefold().endswith((".json", ".md", ".tex", ".py"))
    ), "experiments/METHOD_CONTRACT.json")
    mappings.extend({
        "element_id": str(node.get("id") or ""), "source_path": fallback,
        "semantic_role": "contract-bound editorial architecture node",
    } for node in nodes if str(node.get("id") or "") not in mapped)
    return mappings


def _accept_authored(
    metadata: dict[str, Any], components: list[dict[str, Any]],
    nodes: list[dict[str, Any]], grounding: dict[str, Any],
) -> None:
    mappings = grounding["supplied"] or _derived_mappings(
        components, nodes, grounding["sources"],
    )
    metadata["element_mappings"] = mappings
    metadata["architecture_compiler"] = {
        "compiler": "model-authored-source-grounded-v1",
        "architecture_family": "specialist_authored",
        "component_count": len(components), "rendered_node_count": len(nodes),
        "covered_component_ids": [
            str(item.get("id") or "") for item in (
                components if grounding["semantic"] else grounding["covered_components"]
            )
        ],
        "semantic_aggregation": grounding["semantic"],
        "covered_mechanism_names": grounding["covered_names"],
        "source_mapped_node_count": len(mappings),
        "architecture_detail_markers": sorted(grounding["hits"]),
    }
    metadata["architecture_source"] = "model-authored-source-grounded-spec"


def _fallback(
    metadata: dict[str, Any], grounding: dict[str, Any], nodes: list[dict[str, Any]],
) -> tuple[str, FigureResult | None]:
    metadata["authored_spec_rejection"] = {
        "authored_node_count": len(nodes),
        "component_coverage": len(grounding["covered_components"]),
        "component_coverage_required": grounding["component_minimum"],
        "mechanism_coverage": len(grounding["covered_names"]),
        "mechanism_coverage_required": grounding["mechanism_minimum"],
        "source_mapping_count": len(grounding["supplied"]),
        "source_mapping_required": grounding["mapping_minimum"],
        "architecture_detail_markers": sorted(grounding["hits"]),
    }
    try:
        from .scientific_architecture import scientific_architecture_compiler

        compilation = scientific_architecture_compiler.compile(metadata)
    except Exception as exc:
        return "", FigureResult(
            False, FigureType.FIGURESPEC,
            error=f"Scientific architecture compilation failed: {exc}",
        )
    metadata["element_mappings"] = compilation.element_mappings
    metadata["architecture_compiler"] = compilation.profile
    metadata["architecture_source"] = "deterministic-source-grounded-compiler"
    return json.dumps(compilation.spec, ensure_ascii=False, indent=2), None


def _factorization_issue(code: str, mechanisms: list[dict[str, Any]]) -> str:
    contract = " ".join(
        f"{item.get('name') or ''} {item.get('description') or ''}"
        for item in mechanisms
    ).casefold().replace("_", " ")
    declares = ("z state" in contract and "z acq" in contract) or (
        any(term in contract for term in ("factorized", "factorised", "因子化", "分解"))
        and any(term in contract for term in ("acquisition", "采集", "nuisance"))
    )
    if not declares:
        return ""
    try:
        payload = json.loads(code)
    except json.JSONDecodeError:
        return "method architecture is not valid FigureSpec JSON"
    texts = [
        " ".join(str(node.get(key) or "") for key in ("label", "sublabel")).casefold().replace("_", " ")
        for node in payload.get("nodes") or [] if isinstance(node, dict)
    ]
    state = any(any(term in text for term in (
        "task-bearing state", "task bearing state", "task state", "state factor", "z state",
    )) and "acquisition state" not in text for text in texts)
    acquisition = any(any(term in text for term in (
        "acquisition state", "acquisition factor", "nuisance factor", "z acq",
    )) for text in texts)
    return "" if state and acquisition else (
        "the frozen method declares factorized task-bearing and acquisition paths, "
        "but the diagram does not show them as separate visible architecture nodes"
    )


def prepare_method_architecture(
    code: str, metadata: dict[str, Any], components: list[dict[str, Any]],
) -> tuple[str, FigureResult | None]:
    payload, nodes, text = _authored_payload(code)
    grounding = _grounding(metadata, components, nodes, text)
    if payload is not None and grounding["accepted"]:
        _accept_authored(metadata, components, nodes, grounding)
    else:
        code, failure = _fallback(metadata, grounding, nodes)
        if failure:
            return code, failure
    issue = _factorization_issue(code, grounding["mechanisms"])
    if issue:
        return code, FigureResult(
            False, FigureType.FIGURESPEC,
            error=f"Method architecture semantic review failed: {issue}.",
        )
    return code, None
