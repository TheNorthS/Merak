"""Typed object-level scientific mechanism contract for hybrid figures."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .rich_svg_blueprint import (
    FLOW_KIND_VALUES,
    FLOW_KINDS,
    SCIENTIFIC_ROLE_VALUES,
    SCIENTIFIC_ROLES,
    VISUAL_FORM_VALUES,
    VISUAL_FORMS,
    is_concise_public_label,
)


_ID = re.compile(r"^[a-z][a-z0-9_]{1,79}$")
MECHANISM_CANVAS_SCHEMA = 13
SYNTHESIS_TYPES = frozenset({
    "additive_objective", "comparison", "decision_gate", "causal_merge",
    "evidence_convergence", "reported_endpoint", "proof_implication",
})
READOUT_TYPES = frozenset({
    "comparison", "decision_gate", "evidence_convergence",
    "reported_endpoint", "proof_implication",
})


def _normalize_subitems(parent_id: str, value: Any) -> list[dict[str, str]]:
    if value is not None and not isinstance(value, list):
        raise ValueError(f"primitive {parent_id} subitems must be a list")
    values = value if isinstance(value, list) else []
    if len(values) > 6:
        raise ValueError(f"primitive {parent_id} supports at most six subitems")
    normalized: list[dict[str, str]] = []
    identities: set[str] = set()
    for index, raw in enumerate(values):
        item = dict(raw) if isinstance(raw, dict) else {"label": raw}
        identity = str(item.get("id") or f"{parent_id}_item_{index + 1}").strip()
        label = " ".join(str(item.get("label") or "").split())
        notation = " ".join(str(item.get("notation") or "").split())
        if not _ID.fullmatch(identity) or identity in identities:
            raise ValueError(f"primitive {parent_id} subitem ids must be unique snake_case")
        if not label or len(label) > 56 or len(label.split()) > 5:
            raise ValueError(f"primitive {parent_id} subitems require concise labels")
        if len(notation) > 32:
            raise ValueError(f"primitive {parent_id} subitem notation is too long")
        normalized.append({"id": identity, "label": label, "notation": notation})
        identities.add(identity)
    return normalized


def _typed_runtime_fields(
    item: dict[str, Any], identity: str, role: object, notation: str,
) -> tuple[str, str]:
    if role == "synthesis" and str(item.get("readout_type") or "").strip():
        raise ValueError(f"synthesis primitive {identity} cannot declare readout_type")
    if role != "synthesis" and str(item.get("synthesis_type") or "").strip():
        raise ValueError(f"primitive {identity} cannot declare synthesis_type")
    candidates = {
        str(item.get(key) or "").strip()
        for key in ("runtime_type", "synthesis_type", "readout_type")
        if str(item.get(key) or "").strip()
    }
    if len(candidates) > 1:
        raise ValueError(f"primitive {identity} declares conflicting runtime types")
    runtime_type = next(iter(candidates), "")
    if role == "synthesis":
        if not runtime_type and "=" in notation and "+" in notation:
            runtime_type = "additive_objective"
        if runtime_type not in SYNTHESIS_TYPES:
            raise ValueError(
                f"synthesis primitive {identity} requires a supported synthesis_type"
            )
    elif role in {"readout", "output"}:
        if runtime_type and runtime_type not in READOUT_TYPES:
            raise ValueError(
                f"{role} primitive {identity} has unsupported readout_type"
            )
    elif runtime_type:
        raise ValueError(
            f"primitive {identity} can only declare a runtime type for synthesis/readout/output"
        )
    output_label = " ".join(str(item.get("output_label") or "").split())
    if output_label and (len(output_label) > 56 or len(output_label.split()) > 5):
        raise ValueError(f"primitive {identity} requires a concise output_label")
    return runtime_type, output_label


def _normalize_primitives(
    payload: dict[str, Any], region_ids: set[str],
) -> tuple[list[dict[str, Any]], set[str], dict[str, int]]:
    primitives = [dict(item) for item in payload.get("primitives") or [] if isinstance(item, dict)]
    if not 5 <= len(primitives) <= 12:
        raise ValueError("mechanism_ir requires 5–12 primitives")
    ids: set[str] = set()
    normalized, per_region = [], defaultdict(int)
    for item in primitives:
        identity = str(item.get("id") or "").strip()
        region = str(item.get("region_id") or "").strip()
        label = " ".join(str(item.get("public_label") or "").split())
        if not _ID.fullmatch(identity) or identity in ids:
            raise ValueError("mechanism_ir primitive ids must be unique snake_case")
        if region not in region_ids:
            raise ValueError(f"primitive {identity} references unknown region {region}")
        # The canvas lays labels out against the actual primitive width and
        # wraps them at word boundaries.  A global character cap conflicts
        # with required publication labels (for example,
        # ``Acquisition-heterogeneity interaction``) even though those labels
        # are short in word count and fit once wrapped.
        if not is_concise_public_label(label):
            raise ValueError(f"primitive {identity} requires a concise public_label")
        role, form = item.get("role"), item.get("visual_form")
        if role not in SCIENTIFIC_ROLES:
            raise ValueError(
                f"primitive {identity} has unsupported role {role!r}; accepted values: "
                + ", ".join(SCIENTIFIC_ROLE_VALUES)
            )
        if form not in VISUAL_FORMS:
            raise ValueError(
                f"primitive {identity} has unsupported visual_form {form!r}; "
                "accepted values: " + ", ".join(VISUAL_FORM_VALUES)
            )
        notation = " ".join(str(item.get("notation") or "").split())[:100]
        cues = [" ".join(str(cue).split()) for cue in item.get("semantic_cues") or [] if str(cue).strip()]
        if not 1 <= len(cues) <= 2 or any(len(cue) > 52 or len(cue.split()) > 7 for cue in cues):
            raise ValueError(f"primitive {identity} requires concise semantic_cues")
        subitems = _normalize_subitems(identity, item.get("subitems"))
        runtime_type, output_label = _typed_runtime_fields(
            item, identity, role, notation,
        )
        if role == "interaction" and not notation:
            raise ValueError(f"primitive {identity} requires publication notation")
        if role == "readout" and not (notation or subitems or runtime_type):
            raise ValueError(f"primitive {identity} requires notation, subitems, or readout_type")
        if runtime_type == "additive_objective" and "=" not in notation:
            raise ValueError(f"synthesis primitive {identity} requires the complete operative equation")
        normalized_item = {"id": identity, "region_id": region, "public_label": label,
            "role": str(role), "visual_form": str(form), "notation": notation,
            "semantic_cues": cues, "subitems": subitems,
            "runtime_type": runtime_type, "output_label": output_label}
        if role == "synthesis":
            normalized_item["synthesis_type"] = runtime_type
        elif role in {"readout", "output"} and runtime_type:
            normalized_item["readout_type"] = runtime_type
        normalized.append(normalized_item)
        ids.add(identity)
        per_region[region] += 1
    if set(per_region) != region_ids:
        raise ValueError("every storyboard region must contain at least one mechanism primitive")
    return normalized, ids, per_region


def _normalize_flows(
    payload: dict[str, Any], primitives: list[dict[str, Any]], ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int]]:
    flows = [dict(item) for item in payload.get("flows") or [] if isinstance(item, dict)]
    if len(flows) < len(primitives) - 1:
        raise ValueError("mechanism_ir has too few relations to connect its primitives")
    by_id = {item["id"]: item for item in primitives}
    flow_ids, normalized, touched = set(), [], set()
    incoming, outgoing = defaultdict(int), defaultdict(int)
    for flow in flows:
        identity = str(flow.get("id") or "").strip()
        source = str(flow.get("from") or "")
        target = str(flow.get("to") or "")
        kind = str(flow.get("kind") or "")
        label = " ".join(str(flow.get("label") or "").split())
        if not _ID.fullmatch(identity) or identity in flow_ids:
            raise ValueError("mechanism_ir flow ids must be unique snake_case")
        if source not in ids or target not in ids or source == target:
            raise ValueError(f"flow {identity} has invalid endpoints")
        if kind not in FLOW_KINDS:
            raise ValueError(
                f"flow {identity} has unsupported kind {kind!r}; accepted values: "
                + ", ".join(FLOW_KIND_VALUES)
            )
        if not label or len(label) > 32 or len(label.split()) > 5:
            raise ValueError(f"flow {identity} requires a concise publication label")
        notation = str(by_id[source].get("notation") or "").replace(" ", "")
        if (
            by_id[target].get("runtime_type") == "additive_objective"
            and notation and notation not in label.replace(" ", "")
        ):
            raise ValueError(f"flow {identity} into synthesis must label source notation {by_id[source]['notation']}")
        normalized.append({"id": identity, "from": source, "to": target, "kind": kind, "label": label})
        flow_ids.add(identity)
        touched.update((source, target))
        incoming[target] += 1
        outgoing[source] += 1
    if touched != ids:
        raise ValueError("every mechanism primitive must participate in a relation")
    return normalized, incoming, outgoing


def _validate_structure(
    primitives: list[dict[str, Any]], flows: list[dict[str, Any]],
    incoming: dict[str, int], outgoing: dict[str, int],
) -> None:
    by_id = {item["id"]: item for item in primitives}
    for item in primitives:
        identity, role = item["id"], item["role"]
        if role in {"focal_process", "interaction", "readout", "output", "synthesis"} and incoming[identity] == 0:
            raise ValueError(f"primitive {identity} with role {role} requires an upstream input")
        if role in {"source", "focal_process", "interaction", "readout"} and outgoing[identity] == 0:
            raise ValueError(f"primitive {identity} with role {role} requires a downstream relation")
        if role != "synthesis":
            continue
        runtime_type = str(item.get("runtime_type") or "")
        if runtime_type in {
            "additive_objective", "comparison", "causal_merge", "evidence_convergence",
        } and incoming[identity] < 2:
            raise ValueError(f"synthesis primitive {identity} requires at least two explicit inputs")
        if incoming[identity] == 0:
            raise ValueError(f"synthesis primitive {identity} requires an explicit input")
        if runtime_type != "additive_objective":
            continue
        terms = [part for part in item["notation"].split("=", 1)[1].split("+") if part.strip()]
        incoming_flows = [flow for flow in flows if flow["to"] == identity]
        if len(terms) != len(incoming_flows):
            raise ValueError(f"synthesis primitive {identity} requires one explicit input per additive equation term")
        for flow in incoming_flows:
            source = by_id[flow["from"]]
            compact = str(source.get("notation") or "").replace(" ", "")
            if not compact or len(compact) > 24 or any(mark in compact for mark in (",", ";", "↔", "+", "=")):
                raise ValueError(f"primitive {source['id']} feeding synthesis requires one atomic output notation")
            if compact not in item["notation"].replace(" ", "") or outgoing[source["id"]] != 1:
                raise ValueError(f"synthesis input {source['id']} must be a terminal loss or readout")


def validate_mechanism_ir(
    value: Any, region_ids: set[str],
) -> dict[str, Any]:
    """Validate scientific objects before the runtime assigns any geometry."""
    payload = dict(value) if isinstance(value, dict) else {}
    if payload.get("schema") != 2:
        raise ValueError("mechanism_ir.schema must equal 2")
    normalized, ids, _ = _normalize_primitives(payload, region_ids)
    reading = [str(item) for item in payload.get("reading_order") or []]
    if set(reading) != ids or len(reading) != len(ids):
        raise ValueError("mechanism_ir reading_order must cover every primitive once")
    normalized_flows, incoming, outgoing = _normalize_flows(payload, normalized, ids)
    _validate_structure(normalized, normalized_flows, incoming, outgoing)
    return {
        "schema": 2, "primitives": normalized,
        "reading_order": reading, "flows": normalized_flows,
    }


def mechanism_blueprint_issues(
    mechanism_ir: dict[str, Any], blueprint: dict[str, Any],
) -> list[str]:
    """Require the final publication blueprint to describe the frozen mechanism IR."""
    mechanism_ids = {str(item["id"]) for item in mechanism_ir.get("primitives") or []}
    blueprint_ids = {
        str(item.get("id") or "") for item in blueprint.get("primitives") or []
        if isinstance(item, dict)
    }
    issues = []
    if mechanism_ids != blueprint_ids:
        issues.append("visual_blueprint primitive ids must exactly match mechanism_ir")
    mechanism_edges = {
        (str(item["from"]), str(item["to"]), str(item["kind"]))
        for item in mechanism_ir.get("flows") or []
    }
    blueprint_edges = {
        (str(item.get("from") or ""), str(item.get("to") or ""), str(item.get("kind") or ""))
        for item in blueprint.get("flows") or [] if isinstance(item, dict)
    }
    if mechanism_edges != blueprint_edges:
        issues.append("visual_blueprint flows must exactly match mechanism_ir")
    return issues


def canonicalize_mechanism_blueprint(
    mechanism_ir: dict[str, Any], blueprint: dict[str, Any],
) -> dict[str, Any]:
    """Bind duplicated blueprint structure to the authoritative mechanism IR."""
    result = dict(blueprint)
    authored = {
        str(item.get("id") or ""): dict(item)
        for item in blueprint.get("primitives") or [] if isinstance(item, dict)
    }
    primitives = []
    for item in mechanism_ir.get("primitives") or []:
        enriched = dict(authored.get(str(item["id"])) or {"id": item["id"]})
        for key in (
            "public_label", "role", "visual_form", "notation", "runtime_type",
            "synthesis_type", "readout_type", "output_label",
        ):
            enriched[key] = item.get(key) or ""
        enriched["subitems"] = [dict(value) for value in item.get("subitems") or []]
        primitives.append(enriched)
    result["primitives"] = primitives
    result["reading_order"] = list(mechanism_ir.get("reading_order") or [])
    result["flows"] = [{
        "from": item["from"], "to": item["to"], "kind": item["kind"],
    } for item in mechanism_ir.get("flows") or []]
    synthesis = next((
        item for item in mechanism_ir.get("primitives") or []
        if item.get("role") == "synthesis"
    ), next((
        item for item in reversed(mechanism_ir.get("primitives") or [])
        if item.get("runtime_type")
    ), {}))
    result["narrative_level"] = "mechanism_detail"
    result["figure_label"] = str(
        synthesis.get("public_label") or result.get("figure_label") or "Scientific mechanism"
    )
    result["formal_relation"] = str(synthesis.get("notation") or "")
    result["focal_message"] = (
        "The depicted source passes through the shared focal process; explicit "
        "scientific relations enter the shown typed synthesis or readout."
    )
    return result
