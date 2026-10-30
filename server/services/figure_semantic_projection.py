"""Contribution-driven projection from a full research scene to one figure story."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict, deque
from typing import Any


_EVALUATION_TERMS = re.compile(
    r"\b(?:evaluat(?:e|ion)|held[- ]?out|test(?:ing)?|inference|"
    r"probabilit(?:y|ies)|metric|endpoint|outcome|calibration|aggregation|"
    r"decision|analysis unit|confidence interval|sensitivity|specificity|"
    r"audit|validation|robustness|stress|falsification|probe)\b",
    re.IGNORECASE,
)
_PROTOCOL_TERMS = re.compile(
    r"\b(?:split|partition|cohort|sampling|eligibility|allocation|preprocess|"
    r"registry|manifest|randomi[sz]ation|blinding|recruitment)\b",
    re.IGNORECASE,
)
_METHOD_CONTRIBUTIONS = {
    "model_architecture", "objective_mechanism", "system_architecture",
    "clinical_biological_mechanism", "empirical_discovery",
}
_EVALUATION_ROLES = {"evaluation", "evaluation_design", "protocol", "result"}
_FOCUS_STOPWORDS = {
    "about", "after", "before", "between", "does", "from", "into", "method",
    "proposed", "scientific", "study", "that", "their", "these", "this", "under",
    "what", "when", "where", "which", "with",
}


def _normalized_objects(asset: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    scene = asset.get("scientific_scene")
    scene = scene if isinstance(scene, dict) else {}
    objects = [dict(item) for item in scene.get("objects") or [] if isinstance(item, dict)]
    ids = {str(item.get("id") or "") for item in objects}
    relations = [
        dict(item) for item in scene.get("relations") or []
        if isinstance(item, dict)
        and str(item.get("from") or "") in ids
        and str(item.get("to") or "") in ids
    ]
    return objects, relations


def _text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(key) or "") for key in (
        "label", "display_name", "source_path", "source_symbol",
    ))


def _is_evaluation(item: dict[str, Any]) -> bool:
    return bool(_EVALUATION_TERMS.search(_text(item)))


def _is_protocol(item: dict[str, Any]) -> bool:
    return bool(_PROTOCOL_TERMS.search(_text(item)))


def _graph(relations: list[dict[str, Any]]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    outgoing: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, list[str]] = defaultdict(list)
    for relation in relations:
        source, target = str(relation["from"]), str(relation["to"])
        outgoing[source].append(target)
        incoming[target].append(source)
    return outgoing, incoming


def _neighbors(seed: set[str], graph: dict[str, list[str]], depth: int) -> set[str]:
    reached, queue = set(seed), deque((identity, 0) for identity in seed)
    while queue:
        identity, level = queue.popleft()
        if level >= depth:
            continue
        for neighbor in graph.get(identity, []):
            if neighbor not in reached:
                reached.add(neighbor)
                queue.append((neighbor, level + 1))
    return reached


def _method_projection(
    asset: dict[str, Any], objects: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> tuple[set[str], dict[str, str]]:
    by_id = {str(item["id"]): item for item in objects}
    outgoing, incoming = _graph(relations)
    operations = {
        identity for identity, item in by_id.items()
        if str(item.get("kind") or "") in {"operation", "state"}
        and not _is_evaluation(item)
    }
    if not operations:
        operations = {
            identity for identity, item in by_id.items() if not _is_evaluation(item)
        }
    included = set(operations)
    # Include the shortest upstream scientific context and immediate method
    # interface, without dragging the downstream evaluation chain into view.
    ancestors = _neighbors(operations, incoming, 2)
    included.update(
        identity for identity in ancestors
        if not _is_evaluation(by_id[identity])
    )
    for identity in list(operations):
        for target in outgoing.get(identity, []):
            item = by_id[target]
            if not _is_evaluation(item):
                included.add(target)
    controls = {
        str(relation["from"])
        for relation in relations if relation.get("kind") == "constraint"
    }
    included.update(controls)
    excluded = {
        identity: (
            "downstream evaluation belongs to a separate evaluation figure"
            if _is_evaluation(item) else "outside the focal method transformation"
        )
        for identity, item in by_id.items() if identity not in included
    }
    return included, excluded


def _detail_projection(
    objects: list[dict[str, Any]], relations: list[dict[str, Any]],
) -> tuple[set[str], dict[str, str]]:
    """Keep authored internal mechanism objects, not an overview duplicate."""
    internal = {
        str(item.get("id") or "") for item in objects
        if str(item.get("kind") or "") in {"operation", "state"}
        and not _is_evaluation(item)
    }
    connected = {
        endpoint for relation in relations
        if str(relation.get("from") or "") in internal
        and str(relation.get("to") or "") in internal
        for endpoint in (str(relation["from"]), str(relation["to"]))
    }
    selected = connected or internal
    return selected, {
        str(item.get("id") or ""): "overview context or evaluation belongs outside mechanism detail"
        for item in objects if str(item.get("id") or "") not in selected
    }


def _evaluation_projection(
    objects: list[dict[str, Any]], relations: list[dict[str, Any]],
) -> tuple[set[str], dict[str, str]]:
    by_id = {str(item["id"]): item for item in objects}
    outgoing, incoming = _graph(relations)
    evaluation = {
        identity for identity, item in by_id.items()
        if _is_evaluation(item) or _is_protocol(item)
    }
    evaluation.update(
        str(relation["from"])
        for relation in relations if relation.get("kind") == "constraint"
    )
    included = _neighbors(evaluation, incoming, 1) | _neighbors(evaluation, outgoing, 1)
    excluded = {
        identity: "internal method detail is represented only by a compact interface"
        for identity in by_id if identity not in included
    }
    return included, excluded


def _generic_projection(
    objects: list[dict[str, Any]], relations: list[dict[str, Any]],
) -> tuple[set[str], dict[str, str]]:
    # For theory, qualitative frameworks, datasets, and other contribution
    # families, preserve the authored scene; layout competition provides focus.
    return {str(item["id"]) for item in objects}, {}


def _scoped_ids(
    asset: dict[str, Any], role: str, contribution: str, narrative: str,
    objects: list[dict[str, Any]], relations: list[dict[str, Any]],
) -> tuple[set[str], dict[str, str]]:
    if narrative == "mechanism_detail" and role == "method":
        return _detail_projection(objects, relations)
    if role in _EVALUATION_ROLES:
        return _evaluation_projection(objects, relations)
    if role == "method" or contribution in _METHOD_CONTRIBUTIONS:
        return _method_projection(asset, objects, relations)
    return _generic_projection(objects, relations)


def _focus_tokens(asset: dict[str, Any]) -> set[str]:
    value = " ".join(str(asset.get(key) or "") for key in (
        "scientific_question", "intended_comparison", "visual_encoding",
    ))
    publication_labels = " ".join(
        str(item.get("display_text") or "")
        for item in asset.get("publication_labels") or []
        if isinstance(item, dict)
    )
    value = f"{value} {publication_labels}"
    return {
        token for token in re.findall(r"[a-z][a-z0-9-]{3,}", value.casefold())
        if token not in _FOCUS_STOPWORDS
    }


def _presentation_roles(
    asset: dict[str, Any], selected: list[dict[str, Any]],
    relations: list[dict[str, Any]], controls: list[str], excluded: dict[str, str],
) -> dict[str, list[str]]:
    by_id = {str(item["id"]): item for item in selected}
    focus = _focus_tokens(asset)
    annotation_only = set(controls)
    context = {
        identity for identity, item in by_id.items()
        if str(item.get("kind") or "") == "input" or _is_protocol(item)
    } - annotation_only
    compact_interfaces: set[str] = set()
    for identity, item in by_id.items():
        exits_to_excluded = any(
            relation.get("from") == identity
            and str(relation.get("to") or "") in excluded
            for relation in relations
        )
        retains_authored_targets = any(
            relation.get("from") == identity
            and str(relation.get("to") or "") in by_id
            for relation in relations
        )
        item_tokens = set(re.findall(r"[a-z][a-z0-9-]{3,}", _text(item).casefold()))
        if (
            exits_to_excluded
            and not retains_authored_targets
            and str(item.get("kind") or "") in {"operation", "output"}
            and not focus.intersection(item_tokens)
        ):
            compact_interfaces.add(identity)
    primary = set(by_id) - annotation_only - context - compact_interfaces
    return {
        "primary": sorted(primary),
        "supporting_context": sorted(context),
        "annotation_only": sorted(annotation_only),
        "compact_interfaces": sorted(compact_interfaces),
    }


def _omit_unrelated_optionals(
    asset: dict[str, Any], objects: list[dict[str, Any]],
    relations: list[dict[str, Any]], presentation: dict[str, list[str]],
    excluded: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    optional = set(presentation["annotation_only"] + presentation["compact_interfaces"])
    focus = _focus_tokens(asset)
    if not optional or not focus:
        return objects, relations, excluded
    omit = {
        str(item["id"]) for item in objects
        if str(item["id"]) in optional
        and not focus.intersection(
            re.findall(r"[a-z][a-z0-9-]{3,}", _text(item).casefold())
        )
    }
    remaining_operations = [
        item for item in objects
        if str(item["id"]) not in omit
        and str(item.get("kind") or "") in {"operation", "state"}
    ]
    if not remaining_operations:
        focal_interface = next((
            str(item["id"]) for item in objects
            if str(item["id"]) in presentation["compact_interfaces"]
            and str(item.get("kind") or "") in {"operation", "state"}
        ), "")
        omit.discard(focal_interface)
    included = {str(item["id"]) for item in objects} - omit
    return (
        [item for item in objects if str(item["id"]) in included],
        [item for item in relations
         if str(item.get("from")) in included and str(item.get("to")) in included],
        {**excluded, **{
            identity: "incidental constraint or downstream interface; not focal to this figure"
            for identity in omit
        }},
    )


def project_figure_semantics(asset: dict[str, Any]) -> dict[str, Any]:
    """Return a domain-neutral, source-bound subscene for one figure question."""
    objects, relations = _normalized_objects(asset)
    role = str(asset.get("scientific_role") or "").strip().casefold()
    narrative = str(asset.get("narrative_level") or "").strip().casefold()
    contract = asset.get("scene_contract")
    contract = contract if isinstance(contract, dict) else {}
    contribution = str(contract.get("contribution_type") or "").strip().casefold()
    included, excluded = _scoped_ids(
        asset, role, contribution, narrative, objects, relations,
    )
    selected_objects = [item for item in objects if str(item.get("id")) in included]
    selected_relations = [
        item for item in relations
        if str(item.get("from")) in included and str(item.get("to")) in included
    ]
    controls = [
        str(item.get("id")) for item in selected_objects
        if any(
            relation.get("kind") == "constraint"
            and relation.get("from") == item.get("id")
            for relation in selected_relations
        )
    ]
    presentation = _presentation_roles(
        asset, selected_objects, relations, controls, excluded,
    )
    if role == "method" or contribution in _METHOD_CONTRIBUTIONS:
        selected_objects, selected_relations, excluded = _omit_unrelated_optionals(
            asset, selected_objects, selected_relations, presentation, excluded,
        )
        controls = [identity for identity in controls if identity not in excluded]
        presentation = _presentation_roles(
            asset, selected_objects, relations, controls, excluded,
        )
    method_brief = asset.get("method_brief")
    method_brief = method_brief if isinstance(method_brief, dict) else {}
    return {
        "schema": 1,
        "figure_type": str(asset.get("figure_type") or contract.get("figure_type") or ""),
        "narrative_level": str(
            asset.get("narrative_level") or contract.get("narrative_level") or ""
        ),
        "content_boundary": str(
            asset.get("content_boundary") or contract.get("content_boundary") or ""
        ),
        "production_strategy": str(asset.get("production_strategy") or ""),
        "composition_owner": str(asset.get("composition_owner") or ""),
        "full_svg_authority": asset.get("full_svg_authority") is True,
        "scientific_question": str(asset.get("scientific_question") or ""),
        "focal_claim": str(asset.get("intended_comparison") or asset.get("visual_encoding") or ""),
        "contribution_type": contribution,
        "entities_states_transformations": selected_objects,
        "relations": selected_relations,
        "controls": controls,
        "readouts": [
            str(item.get("id")) for item in selected_objects
            if str(item.get("kind") or "") == "output"
        ],
        "presentation_roles": presentation,
        "publication_labels": [
            str(item.get("display_text") or "").strip()
            for item in asset.get("publication_labels") or []
            if isinstance(item, dict) and str(item.get("display_text") or "").strip()
        ],
        "probe_configuration": [
            dict(item) for item in method_brief.get("probe_configuration") or []
            if isinstance(item, dict)
        ],
        "excluded": excluded,
        "boundary": (
            "Only presentation_roles.primary may become dominant mechanism regions. "
            "supporting_context stays compact, annotation_only cannot become a panel, "
            "and compact_interfaces appear only at the story boundary. Excluded content "
            "belongs to another figure or the caption."
        ),
    }


def semantic_projection_sha256(asset: dict[str, Any]) -> str:
    """Hash the exact figure-scoped scientific contract used by model delegates."""
    encoded = json.dumps(
        project_figure_semantics(asset), ensure_ascii=False,
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
