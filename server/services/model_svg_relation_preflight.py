"""Check model-authored method relations against the projected source scene.

This gate validates declared topology before native-image review. It does not
claim that an SVG arrow is visually legible; the pixel reviewer owns that check.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any
import xml.etree.ElementTree as ET

from .figure_semantic_projection import project_figure_semantics


_FLOW_KINDS = {
    "data": frozenset({"data"}),
    "causal": frozenset({"causal"}),
    "constraint": frozenset({"constraint", "control"}),
    "control": frozenset({"control", "constraint"}),
    "logical": frozenset({"logical"}),
    "feedback": frozenset({"control"}),
}
DIRECTED_SOURCE_RELATION_KINDS = frozenset(_FLOW_KINDS)
_CONTROL_KINDS = frozenset({"constraint", "control", "feedback"})
_ACTIVE_KINDS = frozenset({"data", "causal"})


def _identity(value: object) -> str:
    return str(value or "").strip()


def _projected_method(spec: dict[str, Any]) -> dict[str, Any] | None:
    if _identity(spec.get("scientific_role")) != "method":
        return None
    scene = spec.get("scientific_scene")
    if not isinstance(scene, dict):
        return None
    return project_figure_semantics(spec)


def _object_bindings(
    objects: dict[str, dict[str, Any]], blueprint: dict[str, Any],
) -> tuple[dict[str, str], list[str]]:
    bound: dict[str, str] = {}
    issues: list[str] = []
    for primitive in blueprint.get("primitives") or []:
        if not isinstance(primitive, dict):
            continue
        group = _identity(primitive.get("id"))
        explicit = _identity(primitive.get("scientific_object_id"))
        scene_id = explicit or (group if group in objects else "")
        if not scene_id:
            continue
        if scene_id not in objects:
            issues.append(
                f"primitive {group!r} binds scientific_object_id {scene_id!r} "
                "outside this figure's projected scientific_scene; repair the "
                "figure boundary or source contract"
            )
        elif scene_id in bound:
            issues.append(
                f"scientific_scene object {scene_id!r} is bound by both "
                f"{bound[scene_id]!r} and {group!r}; use one primary primitive"
            )
        else:
            bound[scene_id] = group
    return bound, issues


def _required_edges(
    projection: dict[str, Any], objects: dict[str, dict[str, Any]],
    bound: dict[str, str],
) -> tuple[list[dict[str, Any]], list[str]]:
    roles = projection.get("presentation_roles") or {}
    primary = set(roles.get("primary") or [])
    optional = set(roles.get("annotation_only") or []) | set(roles.get("compact_interfaces") or [])
    selected: list[dict[str, Any]] = []
    missing: set[str] = set()
    for relation in projection.get("relations") or []:
        if not isinstance(relation, dict):
            continue
        source, target = _identity(relation.get("from")), _identity(relation.get("to"))
        kind = _identity(relation.get("kind"))
        if kind not in _FLOW_KINDS:
            continue
        needed = {source, target}.intersection(primary)
        if target in primary and source not in optional and (
            objects.get(source, {}).get("kind") == "input"
        ):
            needed.add(source)
        if source in primary and target not in optional and (
            objects.get(target, {}).get("kind") == "output"
        ):
            needed.add(target)
        missing.update(needed - set(bound))
        if source in bound and target in bound:
            selected.append(relation)
    issues = [
        "projected scientific_scene relation endpoints need explicit "
        "visual_blueprint.primitives[].scientific_object_id bindings "
        "(or matching primitive ids): " + ", ".join(sorted(missing))
    ] if missing else []
    return selected, issues


def _flow_issues(
    required: list[dict[str, Any]], bound: dict[str, str],
    blueprint: dict[str, Any],
) -> list[str]:
    flows: dict[tuple[str, str], set[str]] = defaultdict(set)
    for flow in blueprint.get("flows") or []:
        if isinstance(flow, dict):
            flows[(_identity(flow.get("from")), _identity(flow.get("to")))].add(
                _identity(flow.get("kind"))
            )
    issues: list[str] = []
    for relation in required:
        source, target, kind = (
            _identity(relation.get(key)) for key in ("from", "to", "kind")
        )
        pair = (bound[source], bound[target])
        actual = flows.get(pair, set())
        if not actual.intersection(_FLOW_KINDS[kind]):
            issues.append(
                f"scientific_scene relation {source}->{target} ({kind}) requires "
                f"visual_blueprint flow {pair[0]}->{pair[1]} with kind "
                f"{', '.join(sorted(_FLOW_KINDS[kind]))}; found "
                f"{', '.join(sorted(actual)) or 'none'}"
            )
        if kind in _CONTROL_KINDS and actual.intersection(_ACTIVE_KINDS):
            issues.append(
                f"scientific_scene control {source}->{target} cannot be drawn "
                f"as active data/causal flow {pair[0]}->{pair[1]}"
            )
    return issues


def _unsupported_flow_issues(
    projection: dict[str, Any], bound: dict[str, str], blueprint: dict[str, Any],
) -> list[str]:
    """Bound scientific objects cannot gain relations absent from the owner scene."""
    scene_by_group = {group: scene_id for scene_id, group in bound.items()}
    source_kinds: dict[tuple[str, str], set[str]] = defaultdict(set)
    for relation in projection.get("relations") or []:
        if isinstance(relation, dict):
            source_kinds[(_identity(relation.get("from")), _identity(relation.get("to")))].add(
                _identity(relation.get("kind"))
            )
    issues: list[str] = []
    for flow in blueprint.get("flows") or []:
        if not isinstance(flow, dict):
            continue
        source, target = (
            scene_by_group.get(_identity(flow.get(key))) for key in ("from", "to")
        )
        kinds = source_kinds.get((source, target), set())
        if source and target and not kinds:
            issues.append(
                f"visual_blueprint flow {flow.get('from')}->{flow.get('to')} "
                f"introduces unsupported scientific_scene relation {source}->{target}; "
                "remove it or have the METHOD_CONTRACT owner author that relation"
            )
        elif source and target and not kinds.intersection(_FLOW_KINDS):
            issues.append(
                f"scientific_scene relation {source}->{target} declares "
                f"{', '.join(sorted(kinds))}, not a directed blueprint flow; "
                "preserve its structural meaning or ask the METHOD_CONTRACT "
                "owner to author the operative relation"
            )
    return issues


def _bound_structural_relation_issues(
    projection: dict[str, Any], bound: dict[str, str],
) -> list[str]:
    """Do not silently drop bound scene relations without a visual semantics."""
    issues: list[str] = []
    for relation in projection.get("relations") or []:
        if not isinstance(relation, dict):
            continue
        source = _identity(relation.get("from"))
        target = _identity(relation.get("to"))
        kind = _identity(relation.get("kind"))
        if source in bound and target in bound and kind not in _FLOW_KINDS:
            issues.append(
                f"bound scientific_scene relation {source}->{target} ({kind}) "
                "has no safe directed blueprint flow; preserve it as a typed "
                "structural relation or exclude one endpoint from this figure"
            )
    return issues


def method_relation_contract(spec: dict[str, Any]) -> dict[str, Any]:
    """Expose the same bounded source scene used by the pre-write relation gate."""
    projection = _projected_method(spec)
    if projection is None:
        return {}
    return {
        "schema": 1,
        "objects": projection.get("entities_states_transformations") or [],
        "relations": projection.get("relations") or [],
        "presentation_roles": projection.get("presentation_roles") or {},
        "excluded": projection.get("excluded") or {},
        "flow_kinds_by_source_relation": {
            key: sorted(value) for key, value in _FLOW_KINDS.items()
        },
        "binding_rule": (
            "scientific_object_id (or the primitive id itself) identifies one "
            "object from this projection; source_path alone never identifies an object"
        ),
        "relation_rule": (
            "Preserve directed relations between shown source objects. A shown primary "
            "object must keep its primary neighbors, declared input, and final output. "
            "Other excluded objects belong to companion figures, not this composition."
        ),
    }


def _svg_connector_issues(
    root: ET.Element | None, blueprint: dict[str, Any],
) -> list[str]:
    """Reject contradictory edge metadata where authors choose to supply it."""
    if root is None:
        return []
    flows = {
        (_identity(item.get("from")), _identity(item.get("to")))
        for item in blueprint.get("flows") or [] if isinstance(item, dict)
    }
    issues: list[str] = []
    for element in root.iter():
        source = _identity(element.attrib.get("data-from"))
        target = _identity(element.attrib.get("data-to"))
        if not source and not target:
            continue
        if not source or not target or (source, target) not in flows:
            identity = _identity(element.attrib.get("id")) or element.tag.rsplit("}", 1)[-1]
            issues.append(
                f"SVG connector {identity!r} data-from/data-to does not match "
                f"a visual_blueprint directed flow: {source or '?'}->{target or '?'}"
            )
    return issues


def method_relation_preflight_issues(
    spec: dict[str, Any], blueprint: dict[str, Any], root: ET.Element | None = None,
) -> list[str]:
    """Reject ungrounded method topology before model visual review.

    Only figure-scoped, source-authored relations are mandatory. Unsupported
    relation kinds are left to native review rather than mapped to invented
    scientific meaning.
    """
    projection = _projected_method(spec)
    if projection is None:
        return []
    objects = {
        _identity(item.get("id")): item
        for item in projection.get("entities_states_transformations") or []
        if isinstance(item, dict) and _identity(item.get("id"))
    }
    relations = projection.get("relations") or []
    if not relations:
        contract = spec.get("scene_contract") or {}
        scene = spec.get("scientific_scene") or {}
        authored_objects = scene.get("objects") or []
        missing_owner_relations = len(authored_objects) > 1 and not scene.get("relations")
        if (missing_owner_relations or len(objects) > 1) and (
            isinstance(contract, dict) and contract.get("contribution_type")
        ):
            return [
                "projected method scientific_scene has multiple objects but no "
                "authored relations; repair METHOD_CONTRACT.scientific_scene "
                "before drawing"
            ]
        return []
    bound, issues = _object_bindings(objects, blueprint)
    roles = projection.get("presentation_roles") or {}
    primary = set(roles.get("primary") or [])
    if primary and not primary.intersection(bound):
        issues.append(
            "method blueprint has no source-scene primary binding; set "
            "scientific_object_id on the focal primitive or use the stable "
            "scientific_scene object id as its primitive id"
        )
    required, edge_issues = _required_edges(projection, objects, bound)
    issues.extend(edge_issues)
    issues.extend(_flow_issues(required, bound, blueprint))
    issues.extend(_unsupported_flow_issues(projection, bound, blueprint))
    issues.extend(_bound_structural_relation_issues(projection, bound))
    issues.extend(_svg_connector_issues(root, blueprint))
    return list(dict.fromkeys(issues))
