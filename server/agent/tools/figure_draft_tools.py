"""Bounded multi-call authoring for one model-owned SVG source."""

from __future__ import annotations

import json
import hashlib
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from server.services.model_composed_svg import (
    MODEL_COMPOSED_MODE,
    MODEL_COMPOSED_STRATEGY,
    current_source_bundle_matches,
    design_brief_svg_issues,
    element_mapping_candidates,
    element_mappings_sha256,
    figure_spec_sha256,
    is_model_composed_manifest,
    required_element_mapping_count,
    require_model_composed_spec,
    source_bundle_identity,
    validate_element_mappings,
    validate_full_svg,
)
from server.services.rich_svg_blueprint import (
    FLOW_KIND_VALUES,
    MAX_BLUEPRINT_PRIMITIVES,
    blueprint_minimums,
    NARRATIVE_LEVEL_VALUES,
    SCIENTIFIC_ROLE_VALUES,
    STORYBOARD_FLOW_KIND_DEFAULTS,
    VISUAL_FORM_VALUES,
)
from server.services.model_svg_relation_preflight import method_relation_contract
from server.utils.atomic_write import atomic_write_json, atomic_write_text


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{1,79}$")
_FORBIDDEN = re.compile(r"<(?:script|image|foreignObject)\b", re.IGNORECASE)
DRAFT_POLICY_VERSION = 14


def _positive_int(value: object, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _validate_opening_structure(fragment: str) -> None:
    try:
        root = ET.fromstring(fragment + "</svg>")
    except ET.ParseError as error:
        raise ValueError(f"opening_svg is malformed: {error}") from error
    allowed = {"defs", "style", "title", "desc", "metadata", "rect"}
    visible = [
        child.tag.rsplit("}", 1)[-1].casefold()
        for child in root if child.tag.rsplit("}", 1)[-1].casefold() not in allowed
    ]
    if visible:
        raise ValueError(
            "opening_svg may contain only definitions, styles, metadata, and a "
            "background rectangle; visible scientific content belongs in a region "
            f"fragment (found: {', '.join(sorted(set(visible)))})"
        )
def _draft_directory(project_path: str, artifact_name: str) -> tuple[Path, Path]:
    root = Path(project_path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("figure draft project_path is not a directory")
    if not _IDENTIFIER.fullmatch(artifact_name):
        raise ValueError("artifact_name must be stable snake_case")
    directory = (root / ".merak" / "figure-drafts" / artifact_name).resolve()
    directory.relative_to(root)
    return root, directory
def _storyboard_binding(
    root: Path, artifact_name: str, candidate_id: str = "",
) -> dict[str, str | int]:
    from .figure_storyboard_tools import load_selected_storyboard

    try:
        storyboard = load_selected_storyboard(root, artifact_name)
        selected = next(
            item for item in storyboard["candidates"]
            if item["id"] == storyboard["selected_id"]
        )
        policy_version = int(storyboard["layout_policy_version"])
        selected_id = str(storyboard["selected_id"])
    except (ValueError, StopIteration):
        # Standalone draft-tool tests and non-workflow callers remain usable,
        # but this unbound identity can never match a later workflow storyboard.
        selected = {"id": "unbound", "artifact_name": artifact_name}
        actual = selected
        policy_version = 0
        selected_id = "unbound"
        actual_id = "unbound"
    else:
        actual_id = str(candidate_id or selected_id)
        actual = next((
            item for item in storyboard["candidates"]
            if item["id"] == actual_id
        ), {"id": "missing", "requested_id": actual_id})
    selected_encoded = json.dumps(
        selected, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    actual_encoded = json.dumps(
        actual, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return {
        "layout_policy_version": policy_version,
        "storyboard_selected_id": selected_id,
        "storyboard_selected_sha256": hashlib.sha256(selected_encoded).hexdigest(),
        "storyboard_candidate_id": actual_id,
        "storyboard_candidate_sha256": hashlib.sha256(actual_encoded).hexdigest(),
    }
def current_draft_matches_storyboard(
    project_path: str | Path, artifact_name: str,
) -> bool:
    """Return true only when staged SVG and selected layout share one identity."""
    root, directory = _draft_directory(str(project_path), artifact_name)
    manifest_path = directory / "manifest.json"
    source = directory / f"{artifact_name}.svg"
    if not manifest_path.is_file() or not source.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if is_model_composed_manifest(manifest):
            content, _count = _assembled_content(directory, minimum_fragments=1)
            return (
                manifest.get("draft_policy_version") == DRAFT_POLICY_VERSION
                and manifest.get("source_sha256")
                == hashlib.sha256(content.encode("utf-8")).hexdigest()
                and current_source_bundle_matches(root, manifest)
            )
        binding = _storyboard_binding(
            root, artifact_name, str(manifest.get("storyboard_candidate_id") or ""),
        )
        _assembled_content(directory, minimum_fragments=1)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, StopIteration):
        return False
    return (
        manifest.get("draft_policy_version") == DRAFT_POLICY_VERSION
        and all(manifest.get(key) == value for key, value in binding.items())
    )
def _validate_fragment(value: str, *, opening: bool = False) -> str:
    fragment = str(value or "").strip()
    if not fragment:
        raise ValueError("SVG fragment must be nonempty")
    if _FORBIDDEN.search(fragment):
        raise ValueError("SVG draft forbids script, image, and foreignObject elements")
    if not opening and re.search(r"<style\b|!important", fragment, re.IGNORECASE):
        raise ValueError(
            "body fragments cannot append global CSS overrides; repair text and "
            "geometry in the owning semantic fragment"
        )
    if opening:
        if not fragment.startswith("<svg") or "</svg>" in fragment:
            raise ValueError("opening_svg must start <svg and must not close the document")
        _validate_opening_structure(fragment)
    elif "<svg" in fragment or "</svg>" in fragment:
        raise ValueError("body fragments cannot contain the SVG root element")
    return fragment


def _validate_named_fragment(fragment_id: str, value: str) -> str:
    fragment = _validate_fragment(value)
    try:
        wrapper = ET.fromstring(
            '<svg xmlns="http://www.w3.org/2000/svg">' + fragment + "</svg>"
        )
    except ET.ParseError as error:
        raise ValueError(f"SVG body fragment is malformed: {error}") from error
    children = list(wrapper)
    if len(children) != 1:
        raise ValueError(
            "each body fragment must contain exactly one top-level SVG group"
        )
    child = children[0]
    if (
        child.tag.rsplit("}", 1)[-1].casefold() != "g"
        or str(child.attrib.get("id") or "") != fragment_id
    ):
        raise ValueError(
            "the body fragment top-level group id must equal fragment_id"
        )
    return fragment


def _assembled_content(directory: Path, *, minimum_fragments: int) -> tuple[str, int]:
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("figure draft has not been started")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if is_model_composed_manifest(manifest):
        artifact_name = str(manifest.get("artifact_name") or "")
        source = directory / f"{artifact_name}.svg"
        if not source.is_file():
            raise ValueError("model-composed SVG source is missing")
        content = source.read_text(encoding="utf-8")
        try:
            svg = ET.fromstring(content)
        except ET.ParseError as error:
            raise ValueError(f"model-composed SVG is malformed: {error}") from error
        if svg.tag.rsplit("}", 1)[-1].casefold() != "svg":
            raise ValueError("model-composed source root must be SVG")
        return content, 1
    names = [str(value) for value in manifest.get("parts") or []]
    fragment_count = len(names) - 1
    if fragment_count < minimum_fragments:
        raise ValueError(
            f"figure draft needs at least {minimum_fragments} semantic body fragments"
        )
    fragments = [
        (directory / "parts" / name).read_text(encoding="utf-8") for name in names
    ]
    for fragment in fragments[1:]:
        _validate_fragment(fragment)
    content = "\n".join(fragments) + "\n</svg>\n"
    try:
        svg = ET.fromstring(content)
    except ET.ParseError as error:
        raise ValueError(f"assembled SVG is malformed: {error}") from error
    if svg.tag.rsplit("}", 1)[-1].casefold() != "svg":
        raise ValueError("assembled source root must be SVG")
    return content, fragment_count


def begin_figure_svg_draft(
    artifact_name: str, opening_svg: str, project_path: str = "",
    storyboard_candidate_id: str = "",
) -> str:
    """Start a fresh staged SVG without creating a manuscript asset."""
    root, directory = _draft_directory(project_path, artifact_name)
    opening = _validate_fragment(opening_svg, opening=True)
    if directory.exists():
        # A new delegate/revision needs a clean active workspace, but the best
        # reviewed composition and its hash-bound previews are durable recovery
        # evidence.  Removing the entire directory made every new revision
        # forget the strongest prior draft.
        retained = {"best-composition", "composition-previews", "previews"}
        for current in directory.iterdir():
            if current.name in retained:
                continue
            if current.is_dir():
                shutil.rmtree(current)
            else:
                current.unlink()
    parts = directory / "parts"
    parts.mkdir(parents=True)
    atomic_write_text(parts / "000_open.svgfrag", opening)
    atomic_write_json(directory / "manifest.json", {
        "schema": 1, "artifact_name": artifact_name,
        "draft_policy_version": DRAFT_POLICY_VERSION,
        "parts": ["000_open.svgfrag"], "fragment_reviews": {},
        **_storyboard_binding(root, artifact_name, storyboard_candidate_id),
    })
    return json.dumps({
        "status": "started", "artifact_name": artifact_name,
        "draft_path": str((directory / f"{artifact_name}.svg").relative_to(root)),
    })


def prepare_model_svg_draft(
    artifact_name: str, project_path: str = "",
) -> str:
    """Return the source-bound brief for a model-owned full SVG draft."""
    root, _directory = _draft_directory(project_path, artifact_name)
    spec = require_model_composed_spec(root, artifact_name)
    bindings, bundle_sha256, issues = source_bundle_identity(root, spec)
    if issues:
        raise ValueError(
            "model-composed SVG has invalid source bindings: " + "; ".join(issues)
        )
    scene_contract = spec.get("scene_contract")
    scene_contract = scene_contract if isinstance(scene_contract, dict) else {}
    design_brief = spec.get("design_brief")
    design_brief = design_brief if isinstance(design_brief, dict) else {}
    scene_maximum = _positive_int(
        scene_contract.get("maximum_primary_nodes"), 7,
    )
    brief_maximum = _positive_int(
        design_brief.get("maximum_primary_objects"), 8,
    )
    effective_maximum = min(
        MAX_BLUEPRINT_PRIMITIVES, scene_maximum, brief_maximum,
    )
    minimums = blueprint_minimums(spec)
    mapping_candidates = element_mapping_candidates(root, spec)
    minimum_mappings = required_element_mapping_count(spec)
    if minimum_mappings and not mapping_candidates:
        raise ValueError(
            "model-composed SVG has no declared element-mapping sources; "
            "FIGURE_SPECS must provide scientific_scene object source_path, "
            "source_artifacts, source_data, or legacy element_mappings"
        )
    return json.dumps({
        "status": "prepared",
        "artifact_name": artifact_name,
        "production_strategy": MODEL_COMPOSED_STRATEGY,
        "composition_owner": "model",
        "scientific_question": str(spec.get("scientific_question") or ""),
        "design_brief": design_brief,
        "reading_goal": str(
            spec.get("reading_goal") or spec.get("focal_message") or ""
        ),
        "content_boundary": spec.get("content_boundary") or {},
        "publication_labels": spec.get("publication_labels") or [],
        "scientific_scene": spec.get("scientific_scene") or {},
        "scientific_relation_contract": method_relation_contract(spec),
        "probe_configuration": _probe_configuration_brief(spec),
        "scene_contract": {
            "target_width_fraction": scene_contract.get("target_width_fraction", 1.0),
            "minimum_placed_font_pt": scene_contract.get("minimum_placed_font_pt", 8.0),
            "maximum_primary_nodes": scene_maximum,
        },
        "visual_blueprint_contract": _prepared_blueprint_contract(
            effective_maximum, scene_maximum, brief_maximum, minimums,
        ),
        "element_mapping_contract": _prepared_mapping_contract(
            minimum_mappings, effective_maximum, mapping_candidates,
        ),
        "source_bindings": bindings,
        "source_bundle_sha256": bundle_sha256,
        "figure_spec_sha256": figure_spec_sha256(spec),
        "instruction": (
            "Design the entire editable SVG. You own all text, arrows, paths, "
            "spacing, and hierarchy. Use one stable <g id=...> per visual_blueprint "
            "primitive. Use only exact values from visual_blueprint_contract; never "
            "copy storyboard-only relation kinds into blueprint flows. Keep a single "
            "focal message and no more primary objects than scene_contract allows, "
            "bind method primitives to projected scientific_scene object ids with "
            "scientific_object_id (or use the scene id as the primitive id). Preserve "
            "the source direction and kind of each shown scientific relation; "
            "controls and constraints are not active data flows. Submit "
            "element_mappings for the scientific groups you actually "
            "drew. Choose only declared mapping_candidates; you do not need to use "
            "every candidate. Call submit_model_svg_draft with the SVG, blueprint, "
            "and mappings together."
        ),
    }, ensure_ascii=False)


def _prepared_mapping_contract(
    minimum: int, maximum: int, candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": 1, "required_fields": ["element_id", "source_path"],
        "optional_fields": ["source_symbol", "semantic_role"],
        "minimum_mapped_groups": minimum, "maximum_mapped_groups": maximum,
        "group_id_rule": (
            "element_id must exactly equal one visual_blueprint primitive id "
            "and the matching visible SVG <g id>"
        ),
        "source_path_rule": (
            "source_path must exactly match a source_path from mapping_candidates"
        ),
        "candidate_exhaustion_required": False, "mapping_candidates": candidates,
    }


def _probe_configuration_brief(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose only source-derived probe states, never the full run configuration."""
    brief = spec.get("method_brief")
    brief = brief if isinstance(brief, dict) else {}
    fields = (
        "name", "mechanism_id", "source_path", "training_mode", "head_status",
        "joint_objective_status", "missing_heads",
    )
    return [
        {key: item[key] for key in fields if key in item}
        for item in brief.get("probe_configuration") or [] if isinstance(item, dict)
    ]


def _prepared_blueprint_contract(
    effective_maximum: int, scene_maximum: int, brief_maximum: int,
    minimums: Any,
) -> dict[str, Any]:
    return {
        "schema": 1, "compiler": "model-authored-svg-v1",
        "narrative_levels": list(NARRATIVE_LEVEL_VALUES),
        "scientific_roles": list(SCIENTIFIC_ROLE_VALUES),
        "visual_forms": list(VISUAL_FORM_VALUES), "flow_kinds": list(FLOW_KIND_VALUES),
        "minimum_primitives": minimums.primitives,
        "maximum_primitives": effective_maximum,
        "runtime_maximum_primitives": MAX_BLUEPRINT_PRIMITIVES,
        "scene_maximum_primitives": scene_maximum,
        "design_brief_maximum_primitives": brief_maximum,
        "minimum_distinct_visual_forms": minimums.visual_forms,
        "minimum_reading_order": minimums.reading_order,
        "minimum_relations": minimums.flows,
        "source_scoped_minimums": minimums.source_scoped,
        "storyboard_flow_kind_defaults": dict(STORYBOARD_FLOW_KIND_DEFAULTS),
        "storyboard_relation_note": (
            "Storyboard connection kinds describe layout and are not blueprint "
            "flow kinds. Convert them with the defaults, then choose a different "
            "canonical flow kind only when source evidence requires it."
        ),
    }


def submit_model_svg_draft(
    artifact_name: str, svg_source: str, visual_blueprint: dict[str, Any],
    project_path: str = "", element_mappings: list[dict[str, Any]] | None = None,
) -> str:
    """Stage one complete model-owned SVG without runtime layout mutation."""
    root, directory = _draft_directory(project_path, artifact_name)
    spec = require_model_composed_spec(root, artifact_name)
    source, blueprint, svg_root, identifiers = validate_full_svg(
        svg_source, visual_blueprint, source_spec=spec,
    )
    brief_issues = design_brief_svg_issues(spec, blueprint, svg_root)
    semantic_group_ids = {
        str(item.get("id") or "") for item in blueprint.get("primitives") or []
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    mappings, mapping_issues = validate_element_mappings(
        root, spec, element_mappings,
        semantic_group_ids=semantic_group_ids,
    )
    if brief_issues or mapping_issues:
        raise ValueError(
            "model-composed SVG scientific contract failed: " + "; ".join(
                [*brief_issues, *mapping_issues]
            )
        )
    bindings, bundle_sha256, binding_issues = source_bundle_identity(root, spec)
    if binding_issues:
        raise ValueError(
            "model-composed SVG has invalid source bindings: " + "; ".join(binding_issues)
        )
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{artifact_name}.svg"
    manifest_path = directory / "manifest.json"
    previous = _previous_draft_manifest(manifest_path)
    for name in ("canvas-layout.json", "mechanism-ir.json"):
        (directory / name).unlink(missing_ok=True)
    atomic_write_text(target, source)
    atomic_write_json(directory / "visual-blueprint.json", blueprint)
    source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    manifest = {
        "schema": 2,
        "artifact_name": artifact_name,
        "draft_policy_version": DRAFT_POLICY_VERSION,
        "authoring_mode": MODEL_COMPOSED_MODE,
        "production_strategy": MODEL_COMPOSED_STRATEGY,
        "composition_owner": "model",
        "source_sha256": source_sha256,
        "visual_blueprint_sha256": _blueprint_sha256(blueprint),
        "source_bindings": bindings,
        "source_bundle_sha256": bundle_sha256,
        "figure_spec_sha256": figure_spec_sha256(spec),
        "element_mappings": mappings,
        "element_mappings_sha256": element_mappings_sha256(mappings),
        "fragment_reviews": {},
    }
    if _same_reviewed_model_source(previous, manifest):
        manifest["composition_review"] = previous["composition_review"]
    atomic_write_json(manifest_path, manifest)
    return json.dumps({
        "status": "finalized", "authoring_mode": MODEL_COMPOSED_MODE,
        "artifact_name": artifact_name,
        "source_path": str(target.relative_to(root)),
        "source_sha256": source_sha256, "source_bundle_sha256": bundle_sha256,
        "figure_spec_sha256": manifest["figure_spec_sha256"],
        "visual_blueprint_sha256": manifest["visual_blueprint_sha256"],
        "element_mappings": mappings,
        "element_mappings_sha256": manifest["element_mappings_sha256"],
        "semantic_group_ids": sorted(
            set(identifiers) & {
                str(item.get("id") or "") for item in blueprint.get("primitives") or []
            }
        ),
        "instruction": (
            "Run draft_print_diagnostics, then review_figure_svg_composition. "
            "Repair any finding by submitting a revised complete SVG with this tool; "
            "the runtime will not rewrite model-owned text, arrows, or layout."
        ),
    }, ensure_ascii=False)


def _previous_draft_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _same_reviewed_model_source(
    previous: dict[str, Any], current: dict[str, Any],
) -> bool:
    return isinstance(previous.get("composition_review"), dict) and all(
        previous.get(key) == current.get(key)
        for key in (
            "draft_policy_version", "source_sha256", "visual_blueprint_sha256",
            "source_bundle_sha256", "figure_spec_sha256", "element_mappings_sha256",
        )
    )


def append_figure_svg_fragment(
    artifact_name: str, fragment_id: str, svg_fragment: str,
    project_path: str = "",
) -> str:
    """Append one semantic SVG layer or mechanism group to the active draft."""
    _root, directory = _draft_directory(project_path, artifact_name)
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("figure draft has not been started")
    if not _IDENTIFIER.fullmatch(fragment_id):
        raise ValueError("fragment_id must be stable snake_case")
    fragment = _validate_named_fragment(fragment_id, svg_fragment)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parts = [str(value) for value in manifest.get("parts") or []]
    filename = f"{len(parts):03d}_{fragment_id}.svgfrag"
    if any(name.endswith(f"_{fragment_id}.svgfrag") for name in parts):
        raise ValueError(f"fragment_id {fragment_id!r} already exists")
    atomic_write_text(directory / "parts" / filename, fragment)
    parts.append(filename)
    manifest["parts"] = parts
    manifest.pop("composition_review", None)
    atomic_write_json(manifest_path, manifest)
    return json.dumps({
        "status": "appended", "artifact_name": artifact_name,
        "fragment_id": fragment_id, "fragment_count": len(parts) - 1,
    })


def replace_figure_svg_fragment(
    artifact_name: str, fragment_id: str, svg_fragment: str,
    project_path: str = "",
) -> str:
    """Replace one named layer while preserving all other reviewed work."""
    _root, directory = _draft_directory(project_path, artifact_name)
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("figure draft has not been started")
    if not _IDENTIFIER.fullmatch(fragment_id):
        raise ValueError("fragment_id must be stable snake_case")
    fragment = _validate_named_fragment(fragment_id, svg_fragment)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matches = [
        str(name) for name in manifest.get("parts") or []
        if str(name).endswith(f"_{fragment_id}.svgfrag")
    ]
    if len(matches) != 1:
        raise ValueError(f"fragment_id {fragment_id!r} is not uniquely present")
    atomic_write_text(directory / "parts" / matches[0], fragment)
    reviews = manifest.get("fragment_reviews")
    reviews = reviews if isinstance(reviews, dict) else {}
    reviews.pop(fragment_id, None)
    manifest["fragment_reviews"] = reviews
    manifest.pop("composition_review", None)
    atomic_write_json(manifest_path, manifest)
    assembled = directory / f"{artifact_name}.svg"
    assembled.unlink(missing_ok=True)
    return json.dumps({
        "status": "replaced", "artifact_name": artifact_name,
        "fragment_id": fragment_id, "requires_finalize": True,
    })


def finalize_figure_svg_draft(artifact_name: str, project_path: str = "") -> str:
    """Assemble and validate the exact model-authored SVG source."""
    root, directory = _draft_directory(project_path, artifact_name)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    content, fragment_count = _assembled_content(
        directory, minimum_fragments=1 if is_model_composed_manifest(manifest) else 3,
    )
    if is_model_composed_manifest(manifest):
        target = directory / f"{artifact_name}.svg"
        current_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if (
            manifest.get("draft_policy_version") != DRAFT_POLICY_VERSION
            or manifest.get("source_sha256") != current_hash
            or not current_source_bundle_matches(root, manifest)
        ):
            raise ValueError(
                "model-composed SVG or its source bindings changed after staging; "
                "submit the complete SVG again before review"
            )
        return json.dumps({
            "status": "finalized", "authoring_mode": MODEL_COMPOSED_MODE,
            "artifact_name": artifact_name,
            "source_path": str(target.relative_to(root)),
            "source_sha256": current_hash, "fragment_count": 1,
        })
    expected_binding = _storyboard_binding(
        root, artifact_name, str(manifest.get("storyboard_candidate_id") or ""),
    )
    if (
        manifest.get("draft_policy_version") != DRAFT_POLICY_VERSION
        or any(manifest.get(key) != value for key, value in expected_binding.items())
    ):
        raise ValueError(
            "figure draft was authored for a stale storyboard; start a fresh draft"
        )
    target = directory / f"{artifact_name}.svg"
    atomic_write_text(target, content)
    return json.dumps({
        "status": "finalized", "artifact_name": artifact_name,
        "source_path": str(target.relative_to(root)),
        "bytes": target.stat().st_size, "fragment_count": fragment_count,
        "reviewed_fragments": sorted((manifest.get("fragment_reviews") or {}).keys()),
    })


def _draft_print_issues(content: str) -> list[str]:
    from server.services.figure_print_policy import svg_print_contract_issues

    return svg_print_contract_issues(
        content, ET.fromstring(content),
        {"scene_contract": {
            "target_width_fraction": 1.0, "minimum_placed_font_pt": 8.0,
            "maximum_primary_nodes": 12,
        }},
    )


def _small_text_details(content: str, directory: Path) -> list[dict[str, Any]]:
    from server.services.figure_print_policy import _class_font_sizes, _text_font_size
    from server.services.figure_svg_text_targets import text_group_targets

    root = ET.fromstring(content)
    view_box = str(root.attrib.get("viewBox") or "").split()
    if len(view_box) != 4:
        return []
    try:
        width = float(view_box[2])
    except ValueError:
        return []
    if width <= 0:
        return []
    styles = _class_font_sizes(content)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    group_targets = text_group_targets(root) if is_model_composed_manifest(manifest) else {}
    sources = [
        (str(name).split("_", 1)[-1].removesuffix(".svgfrag"),
         (directory / "parts" / str(name)).read_text(encoding="utf-8"))
        for name in manifest.get("parts") or [] if not str(name).startswith("000_")
    ]
    small = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "text":
            continue
        label = " ".join("".join(element.itertext()).split())
        size = _text_font_size(element, styles)
        if not label or size is None:
            continue
        placed = size * 468.0 / width
        if placed >= 8.0:
            continue
        fragment = (
            group_targets.get(label)
            or next((
                identity for identity, source in sources
                if label in source or (label[:30] and label[:30] in source)
            ), "full_svg" if is_model_composed_manifest(manifest) else "opening_svg")
        )
        small.append({
            "text": label[:100], "fragment_id": fragment,
            "target_ids": [fragment],
            "font_units": round(size, 1), "placed_pt": round(placed, 1),
            "required_font_units": round(8.0 * width / 468.0, 1),
        })
    return sorted(small, key=lambda item: item["placed_pt"])[:12]


def draft_print_diagnostics(
    artifact_name: str, project_path: str = "",
) -> str:
    """Return exact text/fragment targets without invoking a visual model."""
    _root, directory = _draft_directory(project_path, artifact_name)
    content, count = _assembled_content(directory, minimum_fragments=1)
    issues = _draft_print_issues(content)
    return json.dumps({
        "status": "repair_required" if issues else "print_ready",
        "artifact_name": artifact_name, "fragment_count": count,
        "issues": issues, "small_text": _small_text_details(content, directory),
    }, ensure_ascii=False)


async def review_figure_svg_draft(
    artifact_name: str, focus_fragment: str, review_question: str,
    project_path: str = "",
) -> str:
    """Render current layers and obtain native-image feedback before final assembly."""
    from .figure_draft_review import review_figure_svg_draft as review

    return await review(
        artifact_name, focus_fragment, review_question, project_path,
    )


def _blueprint_sha256(visual_blueprint: dict[str, Any]) -> str:
    encoded = json.dumps(
        visual_blueprint, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def review_figure_svg_composition(
    artifact_name: str, visual_blueprint: dict[str, Any], project_path: str = "",
) -> str:
    """Apply the final native-image contract before consuming a formal submission."""
    from .figure_draft_review import review_figure_svg_composition as review

    return await review(artifact_name, visual_blueprint, project_path)


def require_current_composition_review(
    project_root: Path, artifact_name: str, source: Path,
    visual_blueprint: dict[str, Any],
) -> None:
    """Reject formal submission unless this exact SVG and blueprint passed preflight."""
    from .figure_draft_review import require_current_composition_review as require

    require(project_root, artifact_name, source, visual_blueprint)
