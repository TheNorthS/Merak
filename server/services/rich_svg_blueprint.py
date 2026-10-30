"""Typed visual-intent contract for model-authored publication SVGs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import xml.etree.ElementTree as ET


VISUAL_FORM_VALUES = (
    "signal", "tensor", "matrix", "equation", "graph", "timeline",
    "spatial_map", "apparatus", "cohort", "distribution", "state_trace",
    "algorithm", "proof", "qualitative_map", "table_inset", "constraint",
)
FLOW_KIND_VALUES = (
    "data", "causal", "control", "constraint", "comparison", "logical",
)
NARRATIVE_LEVEL_VALUES = (
    "method_overview", "mechanism_detail", "study_protocol",
)
SCIENTIFIC_ROLE_VALUES = (
    "source", "context", "focal_process", "interaction", "control",
    "constraint", "synthesis", "readout", "output",
)

# Keep set aliases for membership checks and backwards-compatible imports.  The
# ordered tuples above are the canonical source for model-facing JSON schemas.
VISUAL_FORMS = frozenset(VISUAL_FORM_VALUES)
FLOW_KINDS = frozenset(FLOW_KIND_VALUES)
NARRATIVE_LEVELS = frozenset(NARRATIVE_LEVEL_VALUES)
SCIENTIFIC_ROLES = frozenset(SCIENTIFIC_ROLE_VALUES)

# Storyboard relations describe composition, whereas blueprint relations
# describe scientific semantics.  These are safe defaults, not extra accepted
# flow kinds; a model may choose another canonical flow kind when the source
# evidence supports it.
STORYBOARD_FLOW_KIND_DEFAULTS = {
    "main": "data",
    "constraint": "constraint",
    "feedback": "control",
    "side_output": "data",
}
MIN_BLUEPRINT_PRIMITIVES = 4
MAX_BLUEPRINT_PRIMITIVES = 12
MIN_BLUEPRINT_VISUAL_FORMS = 3
MIN_BLUEPRINT_READING_ORDER = 4
MIN_BLUEPRINT_FLOWS = 3
PUBLIC_LABEL_MAX_WORDS = 6


@dataclass(frozen=True)
class BlueprintMinimums:
    primitives: int
    visual_forms: int
    reading_order: int
    flows: int
    projected_kinds: frozenset[str] = frozenset()
    source_scoped: bool = False


def blueprint_minimums(source_spec: dict[str, Any] | None = None) -> BlueprintMinimums:
    """Bound model-composed requirements to the projected authored scene."""
    scene = source_spec.get("scientific_scene") if isinstance(source_spec, dict) else None
    if not isinstance(scene, dict) or not scene.get("objects"):
        return BlueprintMinimums(
            MIN_BLUEPRINT_PRIMITIVES, MIN_BLUEPRINT_VISUAL_FORMS,
            MIN_BLUEPRINT_READING_ORDER, MIN_BLUEPRINT_FLOWS,
        )
    from .figure_semantic_projection import project_figure_semantics
    from .model_svg_relation_preflight import DIRECTED_SOURCE_RELATION_KINDS

    projection = project_figure_semantics(source_spec)
    objects = [
        item for item in projection.get("entities_states_transformations") or []
        if isinstance(item, dict)
    ]
    if not objects:
        return BlueprintMinimums(
            MIN_BLUEPRINT_PRIMITIVES, MIN_BLUEPRINT_VISUAL_FORMS,
            MIN_BLUEPRINT_READING_ORDER, MIN_BLUEPRINT_FLOWS,
        )
    count = min(MIN_BLUEPRINT_PRIMITIVES, len(objects))
    relations = [
        item for item in projection.get("relations") or []
        if isinstance(item, dict)
        and str(item.get("kind") or "") in DIRECTED_SOURCE_RELATION_KINDS
    ]
    return BlueprintMinimums(
        count, min(MIN_BLUEPRINT_VISUAL_FORMS, count),
        min(MIN_BLUEPRINT_READING_ORDER, count), len(relations),
        frozenset(str(item.get("kind") or "") for item in objects), True,
    )


def is_concise_public_label(value: object) -> bool:
    """Keep semantic labels brief while leaving physical fit to the renderer."""
    label = " ".join(str(value or "").split())
    return bool(label) and len(label.split()) <= PUBLIC_LABEL_MAX_WORDS


def _narrative_role_issues(
    blueprint: dict[str, Any], primitives: list[dict[str, Any]],
    minimums: BlueprintMinimums,
) -> list[str]:
    level = blueprint.get("narrative_level")
    roles = {item.get("role") for item in primitives}
    issues: list[str] = []
    if minimums.source_scoped:
        kinds = minimums.projected_kinds
        if kinds.intersection({"operation", "state"}) and "focal_process" not in roles:
            issues.append("source-scoped method blueprint requires a focal_process role")
        if "input" in kinds and not roles.intersection({"source", "context"}):
            issues.append("source-scoped blueprint requires a source or context role")
        if "output" in kinds and not roles.intersection({"synthesis", "readout", "output"}):
            issues.append("source-scoped blueprint requires a synthesis, readout, or output role")
        return issues
    if level in {"method_overview", "mechanism_detail"}:
        if "focal_process" not in roles:
            issues.append("method blueprints require a focal_process role")
        if not roles.intersection({"source", "context"}):
            issues.append("method blueprints require a source or context role")
        if not roles.intersection({"synthesis", "readout", "output"}):
            issues.append("method blueprints require a synthesis, readout, or output role")
    elif level == "study_protocol":
        if not {"source", "readout"}.issubset(roles):
            issues.append("study_protocol requires source and readout roles")
        if not roles.intersection({"control", "constraint", "focal_process"}):
            issues.append("study_protocol requires a control, constraint, or focal_process role")
    return issues


def validate_visual_blueprint(
    value: Any, *, source_spec: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Validate semantic composition before inspecting SVG implementation details."""
    blueprint = dict(value) if isinstance(value, dict) else {}
    minimums = blueprint_minimums(source_spec)
    issues: list[str] = []
    if blueprint.get("schema") != 1:
        issues.append("visual_blueprint.schema must equal 1")
    if blueprint.get("compiler") != "model-authored-svg-v1":
        issues.append("visual_blueprint.compiler must equal model-authored-svg-v1")
    if blueprint.get("narrative_level") not in NARRATIVE_LEVELS:
        issues.append(
            "visual_blueprint.narrative_level is unsupported; accepted values: "
            + ", ".join(NARRATIVE_LEVEL_VALUES)
        )
    if len(str(blueprint.get("focal_message") or "").strip()) < 12:
        issues.append("visual_blueprint requires one concrete focal_message")
    figure_label = str(blueprint.get("figure_label") or "").strip()
    if not figure_label or len(figure_label) > 72 or len(figure_label.split()) > 10:
        issues.append("visual_blueprint requires a concise figure_label of ten words or fewer")
    primitives = [item for item in blueprint.get("primitives") or [] if isinstance(item, dict)]
    identifiers = [str(item.get("id") or "").strip() for item in primitives]
    if len(primitives) < minimums.primitives or any(not item for item in identifiers):
        issues.append(
            "visual_blueprint requires at least "
            f"{minimums.primitives} identified scientific primitives"
        )
    if len(primitives) > MAX_BLUEPRINT_PRIMITIVES:
        issues.append(
            "visual_blueprint supports at most "
            f"{MAX_BLUEPRINT_PRIMITIVES} primary primitives; split the scientific question"
        )
    if len(set(identifiers)) != len(identifiers):
        issues.append("visual_blueprint primitive ids must be unique")
    forms = {str(item.get("visual_form") or "") for item in primitives}
    unsupported = sorted(forms - VISUAL_FORMS)
    if unsupported:
        issues.append(
            "unsupported visual forms: " + ", ".join(unsupported)
            + "; accepted visual_form values: " + ", ".join(VISUAL_FORM_VALUES)
        )
    if len(forms & VISUAL_FORMS) < minimums.visual_forms:
        issues.append(
            "visual_blueprint requires at least "
            f"{minimums.visual_forms} distinct scientific visual forms; "
            "choose from: " + ", ".join(VISUAL_FORM_VALUES)
        )
    issues.extend(_primitive_detail_issues(blueprint, primitives))
    issues.extend(_reading_and_flow_issues(blueprint, identifiers, minimums))
    if blueprint.get("narrative_level") == "mechanism_detail" and not str(
        blueprint.get("formal_relation") or ""
    ).strip():
        issues.append("mechanism_detail requires a formal_relation or operative rule")
    issues.extend(_narrative_role_issues(blueprint, primitives, minimums))
    return blueprint, list(dict.fromkeys(issues))


def _primitive_detail_issues(
    blueprint: dict[str, Any], primitives: list[dict[str, Any]],
) -> list[str]:
    """Validate the public labels, scientific roles, and notation of primitives."""
    issues: list[str] = []
    for item in primitives:
        public_label = str(item.get("public_label") or "").strip()
        # Keep the semantic limit aligned with mechanism_ir.  Physical fit is
        # validated by the canvas layout/native review using the real box
        # width, so a fixed character cap would reject valid multi-line
        # publication labels before layout can wrap them.
        if not is_concise_public_label(public_label):
            issues.append(f"primitive {item.get('id') or '<unknown>'} requires a concise public_label")
        if not str(item.get("scientific_meaning") or "").strip():
            issues.append(f"primitive {item.get('id') or '<unknown>'} lacks scientific_meaning")
        if item.get("role") not in SCIENTIFIC_ROLES:
            issues.append(
                f"primitive {item.get('id') or '<unknown>'} has unsupported scientific role; "
                "accepted role values: " + ", ".join(SCIENTIFIC_ROLE_VALUES)
            )
        annotations = item.get("annotations") or []
        annotation_limit = 12 if item.get("role") in {"constraint", "control"} else 6
        annotation_chars = 80
        if not isinstance(annotations, list) or len(annotations) > annotation_limit or any(
            not str(value).strip() or len(str(value)) > annotation_chars for value in annotations
        ):
            issues.append(f"primitive {item.get('id') or '<unknown>'} annotations exceed its concise-label limit")
        if item.get("visual_form") == "equation" and not (
            str(item.get("notation") or "").strip()
            or str(blueprint.get("formal_relation") or "").strip()
            or annotations
        ):
            issues.append(f"equation primitive {item.get('id') or '<unknown>'} requires notation, formal_relation, or terms")
    return issues


def _reading_and_flow_issues(
    blueprint: dict[str, Any], identifiers: list[str], minimums: BlueprintMinimums,
) -> list[str]:
    """Validate reading-order coverage and each scientific relation."""
    issues: list[str] = []
    reading = [str(item) for item in blueprint.get("reading_order") or []]
    if len(reading) < minimums.reading_order or any(
        item not in identifiers for item in reading
    ):
        issues.append(
            "visual_blueprint reading_order must reference at least "
            f"{minimums.reading_order} primitives"
        )
    flows = [item for item in blueprint.get("flows") or [] if isinstance(item, dict)]
    if len(flows) < minimums.flows:
        issues.append(
            "visual_blueprint requires at least "
            f"{minimums.flows} scientific relations"
        )
    for flow in flows:
        if flow.get("from") not in identifiers or flow.get("to") not in identifiers:
            issues.append("visual_blueprint flow endpoints must reference primitive ids")
        if flow.get("kind") not in FLOW_KINDS:
            source = str(flow.get("from") or "<unknown>")
            target = str(flow.get("to") or "<unknown>")
            kind = str(flow.get("kind") or "")
            issues.append(
                f"visual_blueprint flow {source}->{target} has unsupported kind {kind!r}; "
                "accepted flow kind values: " + ", ".join(FLOW_KIND_VALUES)
            )
    return issues


def blueprint_svg_issues(blueprint: dict[str, Any], root: ET.Element) -> list[str]:
    """Bind semantic anchors to SVG groups without dictating local geometry."""
    planned = {
        str(item.get("id") or "").strip()
        for item in blueprint.get("primitives") or [] if isinstance(item, dict)
    }
    groups = {
        str(item.attrib.get("id") or ""): item for item in root.iter()
        if item.tag.rsplit("}", 1)[-1] == "g" and item.attrib.get("id")
    }
    missing = sorted(planned - set(groups))
    issues = ["SVG is missing visual_blueprint groups: " + ", ".join(missing)] if missing else []
    return issues
