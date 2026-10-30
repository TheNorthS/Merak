"""Align publication figures with frozen claims, mechanisms, and implementation."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from .figure_artifact_support import GENERIC_DIAGRAM_SIGNATURES, _semantic_tokens
from .manuscript_language import (
    find_internal_contract_references,
    find_visible_code_artifact_references,
)
from .publication_figure_labels import (
    mask_typed_math_text,
    publication_label_texts,
    validate_publication_labels,
)
from .figure_mechanism_requirements import required_mechanism_labels
from .figure_semantic_projection import project_figure_semantics
from .scientific_scene_labels import projected_public_labels


def _contracts(
    root: Path, figures_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    try:
        selected = json.loads((root / "ideas" / "SELECTED_IDEA.json").read_text(encoding="utf-8-sig"))
        specs = json.loads((figures_root / "FIGURE_SPECS.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return (selected, specs) if isinstance(selected, dict) and isinstance(specs, dict) else None


def _idea_context(selected: dict[str, Any]) -> tuple[list[dict[str, Any]], set[str]]:
    claims = [item for item in selected.get("claims") or [] if isinstance(item, dict)]
    mechanisms = [
        {**item, 'name': item.get('publication_name'),
         'description': item.get('publication_description')}
        for item in selected.get("mechanisms") or []
        if isinstance(item, dict) and item.get("required", True)
    ]
    text = "\n".join([
        str((selected.get('publication') or {}).get('title') or ''), str(selected.get("problem_statement") or ""),
        str(selected.get("hypothesis") or ""),
        *[str(item.get('publication_statement') or '') for item in claims],
        *[f"{item.get('name') or ''} {item.get('description') or ''}" for item in mechanisms],
    ])
    return mechanisms, _semantic_tokens(text)


def _visible_source_issues(
    figure_id: str, role: str, source_text: str, *, raw_source: str,
    publication_labels: Any,
) -> list[str]:
    normalized = " ".join(source_text.casefold().split())
    issues: list[str] = []
    for signature in GENERIC_DIAGRAM_SIGNATURES:
        if all(token in normalized for token in signature):
            issues.append(f"{figure_id}: source is an unrelated generic template ({', '.join(signature)})")
            break
    internal = find_internal_contract_references(source_text)
    if internal:
        issues.append(f"{figure_id}: manuscript figure exposes internal contract IDs " + ", ".join(internal))
    code_text = mask_typed_math_text(source_text, raw_source, publication_labels)
    code = find_visible_code_artifact_references(code_text)
    if code:
        issues.append(f"{figure_id}: manuscript figure exposes code symbols or artifact paths " + ", ".join(code[:6]))
    if role == "method":
        patterns = {
            "pending/planned implementation status": r"\b(?:pending|planned\s+(?:inference|implementation|component)|design\s+scaffold|runtime[- ]verified)\b",
            "internal provenance implementation": r"\b(?:sha-?256|canonical\s+hash|build\s+(?:the\s+)?ledger(?:\s+record)?|persist\s+(?:the\s+)?evidence\s+bundle|event\s+logger|source[_ -]?run[_ -]?id)\b",
            "evidence-mode disclaimer": r"\b(?:no\s+empirical\s+(?:ranking\s+)?outcome|not\s+experimental\s+results|synthetic\s+preview|simulation\s+disclosure)\b",
        }
        issues.extend(
            f"{figure_id}: manuscript method figure exposes {label}; use publication-facing scientific concepts"
            for label, pattern in patterns.items() if re.search(pattern, source_text, re.IGNORECASE)
        )
    return issues


def _source_with_ids(source: Path, publication_text: str) -> str:
    if source.suffix.casefold() != ".svg":
        return publication_text.casefold()
    try:
        return source.read_text(encoding="utf-8-sig", errors="replace").casefold()
    except OSError:
        return publication_text.casefold()


def _aggregation(
    metadata: dict[str, Any], mechanisms: list[dict[str, Any]],
    source: Path, source_text: str, source_tokens: set[str],
) -> tuple[bool, set[str], list[dict[str, Any]]]:
    profile = dict(metadata.get("architecture_compiler") or {})
    mappings = [item for item in metadata.get("element_mappings") or [] if isinstance(item, dict)]
    source_with_ids = _source_with_ids(source, source_text)
    public_mappings = [
        item for item in mappings
        if str(item.get("element_id") or "").strip()
        and str(item.get("element_id") or "").strip().casefold() in source_with_ids
        and all(str(item.get(key) or "").strip() for key in (
            "semantic_role", "source_path", "source_symbol",
        ))
    ]
    public_names = {
        str(item.get("name") or "").strip().casefold()
        for item in mechanisms if str(item.get("name") or "").strip()
        and (lambda tokens: bool(tokens) and len(tokens & source_tokens) >= min(2, len(tokens)))(
            _semantic_tokens(str(item.get("name") or ""))
        )
    }
    public_aggregation = bool(
        len(public_mappings) >= min(4, max(1, len(mappings)))
        and (
            not mechanisms or len(public_names) >= min(
                len(mechanisms), max(1, math.ceil(len(mechanisms) * 0.67)),
            )
        )
    )
    covered = {
        str(value).strip().casefold()
        for value in profile.get("covered_mechanism_names") or [] if str(value).strip()
    }
    if public_aggregation:
        covered.update(public_names)
    return bool(profile.get("semantic_aggregation") or public_aggregation), covered, mappings


def _blueprint_issues(
    figure_id: str, spec: dict[str, Any], metadata: dict[str, Any],
    mappings: list[dict[str, Any]], source_tokens: set[str], aggregated: bool,
) -> list[str]:
    scene = spec.get('scientific_scene')
    if not isinstance(scene, dict):
        return [f'{figure_id}: scientific_scene is missing; repair the method-contract owner']
    scoped = spec.get("production_strategy") == "deterministic_architecture"
    objects = (
        project_figure_semantics(spec)["entities_states_transformations"]
        if scoped else scene.get("objects") or []
    )
    components = [
        item for item in objects
        if isinstance(item, dict) and item.get('priority', 'core') == 'core'
    ]
    if not components:
        return []
    labels = [
        str(item.get("display_name") or item.get("label") or "").strip()
        for item in components
        if str(item.get("display_name") or item.get("label") or "").strip()
    ][:12]
    covered_labels = [label for label in labels if _semantic_tokens(label) & source_tokens]
    minimum = min(len(labels), max(3, math.ceil(len(labels) * 0.7)))
    profile = dict(metadata.get("architecture_compiler") or {})
    required_ids = {str(item.get("id") or "").strip() for item in components[:12] if str(item.get("id") or "").strip()}
    compiler_ids = {str(value).strip() for value in profile.get("covered_component_ids") or [] if str(value).strip()}
    source_pairs = {
        (str(item.get("source_path") or "").replace("\\", "/"), str(item.get("source_symbol") or ""))
        for item in mappings
    }
    mapped_coverage = sum(
        (str(item.get("source_path") or "").replace("\\", "/"), str(item.get("source_symbol") or "")) in source_pairs
        for item in components
    )
    accepted_aggregation = bool(
        profile.get("semantic_aggregation") and len(required_ids & compiler_ids) >= minimum
    ) or bool(aggregated and mapped_coverage >= min(4, minimum))
    issues: list[str] = []
    if len(covered_labels) < minimum and not accepted_aggregation:
        missing = [label for label in labels if label not in covered_labels]
        issues.append(
            f"{figure_id}: architecture renders only {len(covered_labels)}/{len(labels)} "
            "required scientific objects; missing " + "; ".join(missing[:8])
        )
    expected_pairs = {
        (str(item.get("source_path") or "").replace("\\", "/"), str(item.get("source_symbol") or ""))
        for item in components
        if str(item.get("source_path") or "").strip()
        and str(item.get("source_symbol") or "").strip()
    }
    mapped_component_ids = {
        str(item.get("component_id") or "").strip()
        for item in mappings if str(item.get("component_id") or "").strip()
    }
    if expected_pairs and not source_pairs.intersection(expected_pairs) and not (
        mapped_component_ids & required_ids
    ):
        issues.append(f"{figure_id}: architecture has no verified element mapping to its declared implementation components")
    return issues


def _projected_relation_issues(
    figure_id: str, spec: dict[str, Any], source: Path,
) -> list[str]:
    """Check the editable deterministic source against the frozen figure story."""
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return [f"{figure_id}: deterministic FigureSpec source is unreadable"]
    if not isinstance(payload, dict):
        return [f"{figure_id}: deterministic FigureSpec source is not an object"]
    projected = project_figure_semantics(spec)
    expected_ids = {
        str(item.get("id") or "")
        for item in projected["entities_states_transformations"]
    }
    actual_ids = {
        str(item.get("id") or "")
        for item in payload.get("nodes") or [] if isinstance(item, dict)
    }
    expected_edges = {
        (str(item.get("from") or ""), str(item.get("to") or ""),
         str(item.get("kind") or ""))
        for item in projected["relations"]
    }
    actual_edges = {
        (str(item.get("from") or ""), str(item.get("to") or ""),
         str(item.get("scientific_kind") or ""))
        for item in payload.get("edges") or [] if isinstance(item, dict)
    }
    issues = []
    if actual_ids != expected_ids:
        issues.append(f"{figure_id}: FigureSpec objects differ from the frozen scientific projection")
    if actual_edges != expected_edges:
        issues.append(f"{figure_id}: FigureSpec relations differ from the frozen scientific projection")
    labels = {str(item.get("id") or ""): " ".join((str(item.get("label") or "") + " " + str(item.get("sublabel") or "")).split())
              for item in payload.get("nodes") or [] if isinstance(item, dict)}
    if labels != projected_public_labels(spec):
        issues.append(f"{figure_id}: FigureSpec labels differ from the frozen scientific projection")
    return issues


def _term_issues(
    registry: Any, figure_id: str, role: str, spec: dict[str, Any],
    mechanisms: list[dict[str, Any]], source_text: str, aggregated: bool,
    covered_names: set[str], required_terms: list[str] | None = None,
) -> list[str]:
    terms = list(required_terms) if required_terms is not None else publication_label_texts(
        spec.get("publication_labels")
    )
    if role == "method" and aggregated and required_terms is None:
        mechanism_terms = [str(item.get("name") or "").strip() for item in mechanisms if str(item.get("name") or "").strip()]
        terms = mechanism_terms or terms
    if role == "method" and not terms and required_terms is None:
        terms = [str(item.get("name") or "").strip() for item in mechanisms if str(item.get("name") or "").strip()]
    missing = [
        term for term in terms
        if not (aggregated and term.casefold() in covered_names)
        and not registry.mermaid_concept_present(term, source_text)
    ]
    return [
        f"{figure_id}: source omits required domain-facing terms " + "; ".join(missing[:6])
    ] if missing else []


def _idea_overlap_issue(
    figure_id: str, spec: dict[str, Any], metadata: dict[str, Any],
    anchor_tokens: set[str], source_tokens: set[str],
) -> list[str]:
    overlap = anchor_tokens & source_tokens
    minimum = min(4, max(2, len(anchor_tokens) // 25))
    spec_claims = {str(value).strip().casefold() for value in spec.get("claim_ids") or [] if str(value).strip()}
    artifact_claims = {str(value).strip().casefold() for value in metadata.get("claim_ids") or [] if str(value).strip()}
    if anchor_tokens and len(overlap) < minimum and not (spec_claims and spec_claims & artifact_claims):
        return [f"{figure_id}: source has weak semantic overlap with the frozen Idea ({len(overlap)} distinctive token(s))"]
    return []


def _figure_issues(
    registry: Any, spec: dict[str, Any], item: dict[str, Any], root: Path,
    mechanisms: list[dict[str, Any]], anchor_tokens: set[str],
    required_terms: list[str] | None = None,
) -> list[str]:
    figure_id = str(spec.get("id") or "").strip()
    source = Path(str(item.get("source_path") or ""))
    source = source if source.is_absolute() else root / source
    if not source.is_file():
        return [f"{figure_id}: editable source is missing"]
    source_text = registry._publication_semantic_text(item, root, source)
    metadata = dict(item.get("metadata") or {})
    role = str(spec.get("scientific_role") or "").casefold()
    tokens = _semantic_tokens(source_text)
    if "visible_terms" in spec:
        return [f"{figure_id}: visible_terms is unsupported; declare typed publication_labels"]
    labels, label_issues = validate_publication_labels(spec.get("publication_labels"))
    issues = [f"{figure_id}: {issue}" for issue in label_issues]
    try:
        raw_source = source.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        raw_source = ""
    issues.extend(_visible_source_issues(
        figure_id, role, source_text, raw_source=raw_source,
        publication_labels=labels,
    ))
    aggregated, covered_names, mappings = _aggregation(
        metadata, mechanisms, source, source_text, tokens,
    )
    if role == "method":
        issues.extend(_blueprint_issues(
            figure_id, spec, metadata, mappings, tokens, aggregated,
        ))
    if spec.get("production_strategy") == "deterministic_architecture":
        issues.extend(_projected_relation_issues(figure_id, spec, source))
        required_terms = list(projected_public_labels(spec).values())
    issues.extend(_term_issues(
        registry, figure_id, role, spec, mechanisms,
        source_text, aggregated, covered_names,
        required_terms=required_terms,
    ))
    issues.extend(_idea_overlap_issue(
        figure_id, spec, metadata, anchor_tokens, tokens,
    ))
    return issues


def candidate_scientific_alignment_issues(
    registry: Any, project_root: str | Path, metadata: dict[str, Any],
    source_path: str | Path,
) -> list[str]:
    """Validate a candidate source before its manifest transaction commits."""
    if not metadata.get("publication_labels"):
        return []
    root = Path(project_root).expanduser().resolve()
    try:
        selected = json.loads(
            (root / "ideas/SELECTED_IDEA.json").read_text(encoding="utf-8-sig")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ["frozen selected-idea contract is missing or invalid"]
    if not isinstance(selected, dict):
        return ["frozen selected-idea contract is missing or invalid"]
    mechanisms, anchors = _idea_context(selected)
    source = Path(source_path).expanduser().resolve()
    item = {
        "id": metadata.get("semantic_key") or metadata.get("id"),
        "source_path": str(source),
        "metadata": dict(metadata),
    }
    role = str(metadata.get("scientific_role") or "").casefold()
    focal_terms = required_mechanism_labels(root, str(item["id"])) if role == "method" else []
    return _figure_issues(
        registry, dict(metadata), item, root, mechanisms, anchors,
        required_terms=focal_terms or None,
    )


def scientific_alignment_issues(registry: Any, path: str | Path) -> list[str]:
    figures_root = registry.figures_root(path)
    root = registry.project_root(figures_root)
    contracts = _contracts(root, figures_root)
    if contracts is None:
        return []
    selected, specs = contracts
    mechanisms, anchor_tokens = _idea_context(selected)
    entries = {
        str((item.get("metadata") or {}).get("semantic_key") or item.get("id") or ""): item
        for item in registry.paper_ready_entries(figures_root)
    }
    return [
        issue
        for spec in specs.get("figures") or [] if isinstance(spec, dict)
        for item in [entries.get(str(spec.get("id") or "").strip())]
        if item
        for issue in _figure_issues(
            registry, spec, item, root, mechanisms, anchor_tokens,
        )
    ]
