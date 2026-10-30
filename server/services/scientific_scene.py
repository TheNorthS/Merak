"""Domain-neutral scientific scene objects, relations and layout planning."""

from __future__ import annotations

from typing import Any
import json
from pathlib import Path

from .research_contract_versions import (
    METHOD_CONTRACT_SCHEMA,
    SCIENTIFIC_SCENE_SCHEMA,
)


RELATION_KINDS = frozenset({'data', 'causal', 'constraint', 'shared', 'control',
                            'containment', 'feedback', 'temporal', 'logical'})
OBJECT_KINDS = frozenset({'input', 'sample', 'state', 'tensor', 'population',
                         'apparatus', 'variable', 'assumption', 'theorem',
                         'operation', 'measurement', 'intervention', 'output'})


def method_scene_authoring_example(method_json: str, target_path: str) -> tuple[str, str]:
    """Authoring example only; the design owner must replace public labels."""
    payload = json.loads(method_json)
    target = Path(target_path)
    if target.is_file():
        current = json.loads(target.read_text(encoding="utf-8-sig"))
        if "status" in current:
            payload["status"] = current["status"]
        else:
            payload.pop("status", None)
    else:
        payload.pop("status", None)
    payload['schema'] = METHOD_CONTRACT_SCHEMA
    payload['scientific_scene'] = {'schema': SCIENTIFIC_SCENE_SCHEMA, 'objects': [
        {'id': 'observations', 'kind': 'input', 'label': 'Named scientific inputs', 'source_path': 'experiments/EXPERIMENT_PLAN.md'},
        {'id': 'mechanism', 'kind': 'operation', 'label': 'Named proposed scientific operation', 'source_path': 'ideas/SELECTED_IDEA.json'},
        {'id': 'outcomes', 'kind': 'output', 'label': 'Named registered outcomes', 'source_path': 'experiments/EXPERIMENT_PLAN.md'},
    ], 'relations': [
        {'from': 'observations', 'to': 'mechanism', 'kind': 'data'},
        {'from': 'mechanism', 'to': 'outcomes', 'kind': 'data'},
    ]}
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    return content, json.dumps({'path': target_path, 'content': content}, ensure_ascii=False)


def planned_scientific_scene(selected: dict[str, Any]) -> dict[str, Any]:
    """Represent declared method composition without inventing execution order."""
    publication = selected.get('publication') or {}
    name = str(publication.get('method_name') or '').strip()
    if not name:
        name = 'Planned scientific operation'
    objects = [{
        'id': 'planned_method', 'kind': 'operation', 'label': name,
        'description': str(selected.get('hypothesis') or '').strip(),
        'source_path': 'ideas/SELECTED_IDEA.json',
        'source_reference': 'publication/method_name',
    }]
    relations = []
    for index, mechanism in enumerate(selected.get('mechanisms') or []):
        if not isinstance(mechanism, dict):
            continue
        label = str(mechanism.get('publication_name') or '').strip()
        if not label:
            continue
        identity = f'declared_mechanism_{index + 1}'
        objects.append({
            'id': identity,
            'kind': 'operation',
            'label': label,
            'description': str(
                mechanism.get('publication_description') or ''
            ).strip(),
            'source_path': 'ideas/SELECTED_IDEA.json',
            'source_reference': f'mechanisms/{index}/publication_name',
        })
        relations.append({
            'from': 'planned_method',
            'to': identity,
            'kind': 'containment',
        })
    return {
        'schema': SCIENTIFIC_SCENE_SCHEMA,
        'objects': objects,
        'relations': relations,
    }


def validate_scientific_scene(scene: Any) -> list[str]:
    if not isinstance(scene, dict) or scene.get('schema') != SCIENTIFIC_SCENE_SCHEMA:
        return [f'scientific_scene must use schema={SCIENTIFIC_SCENE_SCHEMA}']
    nodes = scene.get('objects')
    if not isinstance(nodes, list) or not nodes:
        return ['scientific_scene requires public scientific objects']
    issues, ids = [], set()
    placeholders = ('named scientific', 'proposed operation', 'registered outcome',
                    'placeholder', 'replace with', 'to be defined')
    for item in nodes:
        if not isinstance(item, dict):
            issues.append('scientific object must be an object')
            continue
        identity = str(item.get('id') or '')
        if not identity or identity in ids:
            issues.append('scientific object requires a unique id')
        ids.add(identity)
        if item.get('kind') not in OBJECT_KINDS:
            issues.append(f'{identity}: unsupported scientific object kind')
        if not str(item.get('label') or '').strip():
            issues.append(f'{identity}: missing public label')
        elif any(marker in str(item.get('label')).casefold() for marker in placeholders):
            issues.append(f'{identity}: public label is a scaffold placeholder')
        if not str(item.get('source_path') or '').strip():
            issues.append(f'{identity}: missing provenance source')
    relations = scene.get('relations')
    if not isinstance(relations, list):
        issues.append('scientific_scene.relations must be a list')
        relations = []
    if len(nodes) > 1 and not relations:
        issues.append('scientific_scene with multiple objects requires authored relations')
    for index, relation in enumerate(relations):
        if not isinstance(relation, dict):
            issues.append('scientific relation must be an object')
        elif relation.get('kind') not in RELATION_KINDS:
            issues.append(f'scientific_scene.relations[{index}].kind={relation.get("kind")!r}: unsupported scientific relation kind; allowed={sorted(RELATION_KINDS)}')
        elif relation.get('from') not in ids or relation.get('to') not in ids:
            issues.append('scientific relation references an absent endpoint')
    return issues


def build_scientific_scene(context: dict[str, Any]) -> dict[str, Any]:
    """Use authored relations; never infer scientific edges from source call order."""
    explicit = (context.get('method_contract') or {}).get('scientific_scene')
    if explicit is None:
        raise ValueError('METHOD_CONTRACT requires scientific_scene before publication asset planning')
    issues = validate_scientific_scene(explicit)
    if issues:
        raise ValueError('; '.join(issues))
    return dict(explicit)


def _complexity_budget(
    maximum_nodes: int, supplied: dict[str, Any] | None,
) -> dict[str, Any]:
    from .scientific_asset_portfolio import DEFAULT_COMPLEXITY_BUDGET

    budget = dict(DEFAULT_COMPLEXITY_BUDGET)
    if isinstance(supplied, dict):
        budget.update(supplied)
    requested = max(2, int(maximum_nodes or 8))
    budget["maximum_primary_objects"] = min(
        requested,
        max(2, int(budget.get("maximum_primary_objects") or 8)),
    )
    for key, fallback in (
        ("maximum_primary_branches", 2),
        ("maximum_visible_labels", 12),
        ("maximum_label_words", 6),
    ):
        budget[key] = max(1, int(budget.get(key) or fallback))
    budget["minimum_placed_font_pt"] = max(
        8.0, float(budget.get("minimum_placed_font_pt") or 8.0)
    )
    return budget


def _label_weight(item: dict[str, Any]) -> int:
    subitems = [
        value for value in item.get("subitems") or []
        if isinstance(value, dict) and str(value.get("label") or "").strip()
    ]
    return 1 + len(subitems)


def _bounded_panels(
    objects: list[dict[str, Any]], *, maximum_nodes: int,
    maximum_labels: int,
) -> list[list[dict[str, Any]]]:
    panels: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    labels = 0
    for item in objects:
        weight = _label_weight(item)
        if current and (
            len(current) >= maximum_nodes or labels + weight > maximum_labels
        ):
            panels.append(current)
            current, labels = [], 0
        current.append(item)
        labels += weight
    if current:
        panels.append(current)
    return panels


def _branch_panels(
    objects: list[dict[str, Any]], relations: list[dict[str, Any]],
    maximum_branches: int,
) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]]]:
    """Split a single overloaded fan-out while repeating its context anchor."""
    by_id = {str(item["id"]): item for item in objects}
    outgoing: dict[str, list[str]] = {}
    for relation in relations:
        source, target = str(relation.get("from") or ""), str(
            relation.get("to") or ""
        )
        if source in by_id and target in by_id and target not in outgoing.setdefault(
            source, []
        ):
            outgoing[source].append(target)
    overloaded = [
        (source, targets) for source, targets in outgoing.items()
        if len(targets) > maximum_branches
    ]
    partitions = [{
        "anchor_id": source,
        "target_groups": [
            targets[index:index + maximum_branches]
            for index in range(0, len(targets), maximum_branches)
        ],
    } for source, targets in overloaded]
    if len(overloaded) != 1:
        return [], partitions
    source, targets = overloaded[0]
    target_groups = partitions[0]["target_groups"]
    panels = [[by_id[source], *(by_id[target] for target in group)]
              for group in target_groups]
    covered = {source, *targets}
    residual = [item for item in objects if str(item["id"]) not in covered]
    if residual:
        panels.append(residual)
    return panels, partitions


def _cross_panel_relations(
    panels: list[list[dict[str, Any]]], relations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    memberships: dict[str, set[int]] = {}
    for index, panel in enumerate(panels):
        for item in panel:
            memberships.setdefault(str(item["id"]), set()).add(index)
    return [dict(item) for item in relations if not (
        memberships.get(str(item.get("from") or ""), set())
        & memberships.get(str(item.get("to") or ""), set())
    )]


def _layout_diagnostics(
    objects: list[dict[str, Any]], relations: list[dict[str, Any]],
    panels: list[list[dict[str, Any]]], budget: dict[str, Any],
    branch_partitions: list[dict[str, Any]],
) -> dict[str, Any]:
    label_count = sum(_label_weight(item) for item in objects) + sum(
        bool(str(item.get("label") or "").strip()) for item in relations
    )
    outgoing_counts: dict[str, set[str]] = {}
    for relation in relations:
        outgoing_counts.setdefault(str(relation.get("from") or ""), set()).add(
            str(relation.get("to") or "")
        )
    maximum_outgoing = max(
        (len(value) for value in outgoing_counts.values()), default=0,
    )
    split_reasons = []
    if len(objects) > int(budget["maximum_primary_objects"]):
        split_reasons.append("primary_object_budget")
    if label_count > int(budget["maximum_visible_labels"]):
        split_reasons.append("visible_label_budget")
    if branch_partitions:
        split_reasons.append("primary_branch_budget")
    long_label_ids = [
        str(item["id"]) for item in objects
        if len(str(item.get("label") or "").split())
        > int(budget["maximum_label_words"])
    ]
    if long_label_ids:
        split_reasons.append("label_word_budget")
    occurrences: dict[str, int] = {}
    for panel in panels:
        for item in panel:
            identity = str(item["id"])
            occurrences[identity] = occurrences.get(identity, 0) + 1
    repeated = {
        identity for identity, count in occurrences.items() if count > 1
    }
    panel_contracts = [{
        "id": f"panel_{index + 1}",
        "object_ids": [str(item["id"]) for item in panel],
        "repeated_context_ids": [
            str(item["id"]) for item in panel if str(item["id"]) in repeated
        ],
        "owns_one_scientific_question": True,
    } for index, panel in enumerate(panels)]
    return {
        "label_count": label_count,
        "maximum_outgoing": maximum_outgoing,
        "split_reasons": list(dict.fromkeys(split_reasons)),
        "long_label_ids": long_label_ids,
        "panel_contracts": panel_contracts,
    }


def plan_scientific_layout(
    scene: dict[str, Any], maximum_nodes: int = 8,
    complexity_budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select topology and split excess detail instead of shrinking labels."""
    issues = validate_scientific_scene(scene)
    if issues:
        raise ValueError('; '.join(issues))
    kinds = {item.get('kind') for item in scene.get('relations') or []}
    topology = ('feedback' if 'feedback' in kinds else 'hierarchical' if 'containment' in kinds
                else 'temporal' if 'temporal' in kinds else 'logical' if 'logical' in kinds
                else 'causal' if 'causal' in kinds else 'parallel' if 'control' in kinds
                else 'directed' if kinds else 'independent_objects')
    objects = [dict(item) for item in scene['objects']]
    relations = [
        dict(item) for item in scene.get('relations') or []
        if isinstance(item, dict)
    ]
    budget = _complexity_budget(maximum_nodes, complexity_budget)
    maximum_objects = int(budget["maximum_primary_objects"])
    maximum_labels = int(budget["maximum_visible_labels"])
    maximum_branches = int(budget["maximum_primary_branches"])
    panels = _bounded_panels(
        objects, maximum_nodes=maximum_objects,
        maximum_labels=maximum_labels,
    )
    branch_panels, branch_partitions = _branch_panels(
        objects, relations, maximum_branches,
    )
    if len(panels) == 1 and branch_panels:
        panels = branch_panels
    from .scientific_scene_partitions import partition_combined_overflow

    panels = partition_combined_overflow(panels, relations, budget)
    diagnostics = _layout_diagnostics(
        objects, relations, panels, budget, branch_partitions,
    )
    from .scientific_scene_geometry import solve_scientific_panel

    panel_contracts = diagnostics["panel_contracts"]
    split_reasons = diagnostics["split_reasons"]
    long_label_ids = diagnostics["long_label_ids"]
    return {
        'topology': topology,
        'panels': [item["object_ids"] for item in panel_contracts],
        'panel_contracts': panel_contracts,
        'complexity_budget': budget,
        'complexity': {
            'primary_objects': len(objects),
            'visible_labels': diagnostics["label_count"],
            'maximum_outgoing_branches': diagnostics["maximum_outgoing"],
        },
        'split_reasons': split_reasons,
        'branch_partitions': branch_partitions,
        'cross_panel_relations': _cross_panel_relations(panels, relations),
        'label_rewrite_required': long_label_ids,
        'minimum_font_pt': budget["minimum_placed_font_pt"],
        'overlap_allowed': False,
        'connectors_must_avoid_text': True,
        'split_required': len(panels) > 1,
        'complexity_actions': {
            'split': len(panels) > 1,
            'rewrite_labels': bool(long_label_ids),
            'move_secondary_detail_to_caption': bool(split_reasons),
        },
        'overflow_action': 'split_into_companion_panels',
        'geometry': [solve_scientific_panel(panel, relations) for panel in panels],
    }
