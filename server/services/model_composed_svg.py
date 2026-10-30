"""Contract and source binding for model-composed, full-canvas SVG figures.

The model owns the complete editable SVG in this mode (including typography,
connectors, and layout).  The runtime owns only deterministic validation,
same-source rendering, and review provenance.
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


MODEL_COMPOSED_STRATEGY = "model_composed_full_svg"
MODEL_COMPOSED_MODE = "model_composed"
SOURCE_MAPPED_ROLES = frozenset({
    "method", "evaluation_design", "evaluation", "protocol",
})
ELEMENT_MAPPING_FIELDS = frozenset({
    "element_id", "source_path", "source_symbol", "semantic_role",
})
_FORBIDDEN_TAGS = {"script", "image", "foreignobject", "iframe", "object", "embed"}
_EXTERNAL_REFERENCE = re.compile(r"^(?:https?:|file:|data:|javascript:|//)", re.IGNORECASE)


def is_model_composed_manifest(manifest: dict[str, Any]) -> bool:
    return (
        manifest.get("authoring_mode") == MODEL_COMPOSED_MODE
        or manifest.get("production_strategy") == MODEL_COMPOSED_STRATEGY
    )


def load_figure_spec(root: Path, artifact_name: str) -> dict[str, Any]:
    path = root / "figures" / "FIGURE_SPECS.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"figure specifications are missing or invalid: {path}") from error
    figures = payload.get("figures") if isinstance(payload, dict) else []
    spec = next((
        dict(item) for item in figures or []
        if isinstance(item, dict) and str(item.get("id") or "") == artifact_name
    ), None)
    if spec is None:
        raise ValueError(f"figure specification is missing for {artifact_name}")
    return spec


def require_model_composed_spec(root: Path, artifact_name: str) -> dict[str, Any]:
    spec = load_figure_spec(root, artifact_name)
    if (
        spec.get("production_strategy") != MODEL_COMPOSED_STRATEGY
        or spec.get("composition_owner") != "model"
        or spec.get("producer_kind") != "model"
        or spec.get("recommended_backend") != "rich_svg"
    ):
        raise ValueError(
            f"{artifact_name} is not routed to model-composed full SVG; "
            "the scientific asset plan must declare producer_kind=model, "
            "recommended_backend=rich_svg, composition_owner=model, and "
            f"production_strategy={MODEL_COMPOSED_STRATEGY}"
        )
    return spec


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def figure_spec_sha256(spec: dict[str, Any]) -> str:
    encoded = json.dumps(
        spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _directory_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for current in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = current.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256(current).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _declared_source_paths(spec: dict[str, Any]) -> list[str]:
    values: list[Any] = [
        *(spec.get("source_data") or []),
        *(spec.get("source_artifacts") or []),
    ]
    values.extend(
        item.get("source_path")
        for item in spec.get("element_mappings") or [] if isinstance(item, dict)
    )
    scene = spec.get("scientific_scene")
    scene = scene if isinstance(scene, dict) else {}
    values.extend(
        item.get("source_path")
        for item in scene.get("objects") or [] if isinstance(item, dict)
    )
    return list(dict.fromkeys(
        str(value).strip().replace("\\", "/")
        for value in values if str(value or "").strip()
    ))


def source_bundle(root: Path, spec: dict[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
    bindings: list[dict[str, str]] = []
    issues: list[str] = []
    for declared in _declared_source_paths(spec):
        candidate = Path(declared).expanduser()
        candidate = (candidate if candidate.is_absolute() else root / candidate).resolve()
        try:
            relative = candidate.relative_to(root).as_posix()
        except ValueError:
            bindings.append({"path": declared, "status": "outside-project"})
            issues.append(f"declared source escapes the project: {declared}")
            continue
        if candidate.is_file():
            bindings.append({"path": relative, "status": "file", "sha256": _sha256(candidate)})
        elif candidate.is_dir():
            bindings.append({
                "path": relative, "status": "directory",
                "sha256": _directory_sha256(candidate),
            })
        else:
            bindings.append({"path": relative, "status": "missing"})
            issues.append(f"declared source is missing: {relative}")
    return bindings, issues


def source_bundle_identity(root: Path, spec: dict[str, Any]) -> tuple[list[dict[str, str]], str, list[str]]:
    bindings, issues = source_bundle(root, spec)
    encoded = json.dumps(
        bindings, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return bindings, hashlib.sha256(encoded).hexdigest(), issues


def _project_relative_path(root: Path, value: object) -> str:
    declared = str(value or "").strip().replace("\\", "/")
    if not declared:
        return ""
    candidate = Path(declared).expanduser()
    candidate = (candidate if candidate.is_absolute() else root / candidate).resolve()
    try:
        return candidate.relative_to(root).as_posix()
    except ValueError:
        return declared


def element_mapping_candidates(
    root: Path, spec: dict[str, Any],
) -> list[dict[str, str]]:
    """Project legacy mappings and scene provenance into authoring candidates.

    A candidate declares a source the model may cite. Its suggested group or
    scene object is guidance only: model-owned SVG groups are created later and
    the author is not required to reproduce every scientific-scene object.
    """
    candidates: list[dict[str, str]] = []

    def append(raw: dict[str, Any], *, origin: str) -> None:
        source_path = _project_relative_path(root, raw.get("source_path"))
        if not source_path:
            return
        source = Path(source_path).expanduser()
        source = source if source.is_absolute() else root / source
        if not source.is_file():
            return
        candidate = {"source_path": source_path, "origin": origin}
        projected = {
            "source_symbol": raw.get("source_symbol"),
            "semantic_role": raw.get("semantic_role") or raw.get("kind"),
            "suggested_group_id": raw.get("element_id"),
            "scientific_object_id": raw.get("id"),
            "public_label": raw.get("label"),
            "source_reference": raw.get("source_reference"),
        }
        candidate.update({
            key: str(value).strip() for key, value in projected.items()
            if str(value or "").strip()
        })
        if candidate not in candidates:
            candidates.append(candidate)

    for item in spec.get("element_mappings") or []:
        if isinstance(item, dict):
            append(item, origin="legacy_element_mapping")
    scene = spec.get("scientific_scene")
    scene = scene if isinstance(scene, dict) else {}
    for item in scene.get("objects") or []:
        if isinstance(item, dict):
            append(item, origin="scientific_scene")
    for key in ("source_artifacts", "source_data"):
        for value in spec.get(key) or []:
            append({"source_path": value}, origin=key)
    return candidates


def required_element_mapping_count(spec: dict[str, Any]) -> int:
    role = re.sub(
        r"[^a-z0-9]+", "_", str(spec.get("scientific_role") or "").casefold(),
    ).strip("_")
    if role not in SOURCE_MAPPED_ROLES:
        return 0
    if spec.get("production_strategy") == MODEL_COMPOSED_STRATEGY:
        from .rich_svg_blueprint import blueprint_minimums

        minimums = blueprint_minimums(spec)
        if minimums.source_scoped:
            return minimums.primitives
    scene = spec.get("scientific_scene")
    scene = scene if isinstance(scene, dict) else {}
    scene_nodes = [
        item for item in scene.get("objects") or [] if isinstance(item, dict)
    ]
    return min(4, len(scene_nodes)) if scene_nodes else 4


def element_mappings_sha256(mappings: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        mappings, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_element_mappings(
    root: Path, spec: dict[str, Any], mappings: Any,
    *, semantic_group_ids: set[str],
) -> tuple[list[dict[str, str]], list[str]]:
    """Validate a mapping authored alongside one model-owned SVG."""
    if not isinstance(mappings, list):
        return [], ["element_mappings must be an array"]
    candidates = element_mapping_candidates(root, spec)
    allowed_paths = {
        str(item["source_path"]) for item in candidates if item.get("source_path")
    }
    allowed_symbols: dict[str, set[str]] = {}
    for candidate in candidates:
        symbol = str(candidate.get("source_symbol") or "").strip()
        if symbol:
            allowed_symbols.setdefault(str(candidate["source_path"]), set()).add(symbol)
    canonical: list[dict[str, str]] = []
    issues: list[str] = []
    seen_groups: set[str] = set()
    for index, raw in enumerate(mappings):
        position = index + 1
        if not isinstance(raw, dict):
            issues.append(f"element mapping {position} must be an object")
            continue
        unknown = sorted(set(raw) - ELEMENT_MAPPING_FIELDS)
        if unknown:
            issues.append(
                f"element mapping {position} has unsupported fields: "
                + ", ".join(unknown)
            )
        element_id = str(raw.get("element_id") or "").strip()
        source_path = _project_relative_path(root, raw.get("source_path"))
        source_symbol = str(raw.get("source_symbol") or "").strip()
        semantic_role = " ".join(str(raw.get("semantic_role") or "").split())
        if not element_id:
            issues.append(f"element mapping {position} has no element_id")
        elif element_id not in semantic_group_ids:
            issues.append(
                f"element mapping {position} references unknown semantic group "
                f"{element_id!r}; use a visual_blueprint primitive id"
            )
        elif element_id in seen_groups:
            issues.append(f"element mapping {position} duplicates group {element_id!r}")
        seen_groups.add(element_id)
        issues.extend(_mapping_source_issues(
            source_path, source_symbol, position, allowed_paths, allowed_symbols,
        ))
        mapping = {"element_id": element_id, "source_path": source_path}
        if source_symbol:
            mapping["source_symbol"] = source_symbol
        if semantic_role:
            mapping["semantic_role"] = semantic_role
        canonical.append(mapping)
    minimum = required_element_mapping_count(spec)
    valid_groups = {
        item["element_id"] for item in canonical
        if item.get("element_id") in semantic_group_ids
    }
    if len(valid_groups) < minimum:
        role = re.sub(
            r"[^a-z0-9]+", "_",
            str(spec.get("scientific_role") or "figure").casefold(),
        ).strip("_")
        issues.append(
            f"{role} model-composed SVG requires at least {minimum} "
            "source-mapped scientific groups"
        )
    if canonical:
        from .excalidraw_renderer import verify_element_mappings

        issues.extend(verify_element_mappings(
            {"elements": [{"id": value} for value in sorted(semantic_group_ids)]},
            canonical, root,
        ))
    return canonical, list(dict.fromkeys(issues))


def _mapping_source_issues(
    source_path: str, source_symbol: str, position: int,
    allowed_paths: set[str], allowed_symbols: dict[str, set[str]],
) -> list[str]:
    """Check each mapping against the declared source and symbol vocabulary."""
    if not source_path:
        return [f"element mapping {position} has no source_path"]
    if source_path not in allowed_paths:
        choices = ", ".join(sorted(allowed_paths)) or "<none declared>"
        return [
            f"element mapping {position} source {source_path!r} is not declared "
            f"by FIGURE_SPECS; choose one of: {choices}"
        ]
    if source_symbol and allowed_symbols.get(source_path) and (
        source_symbol not in allowed_symbols[source_path]
    ):
        return [
            f"element mapping {position} source_symbol {source_symbol!r} is not "
            f"declared for {source_path}"
        ]
    return []


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].casefold()


def _normalized_text(element: ET.Element) -> str:
    return " ".join(" ".join(element.itertext()).casefold().split())


def _semantic_tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) > 1
    }


def validate_full_svg(
    svg_source: str, visual_blueprint: dict[str, Any],
    source_spec: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any], ET.Element, list[str]]:
    """Validate editable SVG safety and bind blueprint primitives to SVG groups."""
    source = str(svg_source or "").strip()
    if not source:
        raise ValueError("svg_source must contain a complete SVG document")
    if len(source.encode("utf-8")) > 2_000_000:
        raise ValueError("svg_source exceeds the 2 MB authoring limit")
    if re.search(r"<!DOCTYPE|<!ENTITY", source, re.IGNORECASE):
        raise ValueError("svg_source cannot declare a doctype or entities")
    try:
        root = ET.fromstring(source)
    except ET.ParseError as error:
        raise ValueError(f"model-composed SVG is malformed: {error}") from error
    issues: list[str] = []
    if _local_name(root.tag) != "svg":
        issues.append("model-composed source root must be SVG")
    view_box = str(root.attrib.get("viewBox") or "").split()
    if len(view_box) != 4:
        issues.append("model-composed SVG requires a four-number viewBox")
    else:
        try:
            dimensions = [float(value) for value in view_box]
            if dimensions[2] <= 0 or dimensions[3] <= 0:
                issues.append("model-composed SVG canvas dimensions must be positive")
        except ValueError:
            issues.append("model-composed SVG viewBox must contain numbers")
    identifiers: list[str] = []
    for element in root.iter():
        tag = _local_name(element.tag)
        if tag in _FORBIDDEN_TAGS:
            issues.append(f"model-composed SVG forbids <{tag}> content")
        identity = str(element.attrib.get("id") or "").strip()
        if identity:
            identifiers.append(identity)
        for raw_name, raw_value in element.attrib.items():
            name = _local_name(raw_name)
            value = str(raw_value).strip()
            if name.startswith("on"):
                issues.append(f"model-composed SVG forbids event attribute {name}")
            if name in {"href", "src"} and value and not value.startswith("#"):
                if _EXTERNAL_REFERENCE.match(value) or ":" in value:
                    issues.append("model-composed SVG forbids external resource references")
    duplicates = sorted({value for value in identifiers if identifiers.count(value) > 1})
    if duplicates:
        issues.append("model-composed SVG has duplicate ids: " + ", ".join(duplicates[:12]))

    from .rich_svg_blueprint import blueprint_svg_issues, validate_visual_blueprint

    blueprint, blueprint_issues = validate_visual_blueprint(
        visual_blueprint, source_spec=source_spec,
    )
    issues.extend(blueprint_issues)
    if not blueprint_issues:
        issues.extend(blueprint_svg_issues(blueprint, root))
        groups = {
            str(element.attrib.get("id") or ""): element for element in root.iter()
            if _local_name(element.tag) == "g" and element.attrib.get("id")
        }
        issues.extend(_svg_primitive_label_issues(blueprint, root, groups))
    if issues:
        raise ValueError("model-composed SVG contract failed: " + "; ".join(dict.fromkeys(issues)))
    return source + "\n", blueprint, root, identifiers


def _svg_primitive_label_issues(
    blueprint: dict[str, Any], root: ET.Element, groups: dict[str, ET.Element],
) -> list[str]:
    """Require each authored primitive label to remain visible in the source."""
    global_text = _semantic_tokens(_normalized_text(root))
    issues: list[str] = []
    for primitive in blueprint.get("primitives") or []:
        identity = str(primitive.get("id") or "")
        label = " ".join(str(primitive.get("public_label") or "").split())
        group = groups.get(identity)
        if group is None or not label:
            continue
        label_tokens = _semantic_tokens(label)
        visible_tokens = _semantic_tokens(_normalized_text(group))
        required = min(2, len(label_tokens))
        if (
            required and len(label_tokens & visible_tokens) < required
            and len(label_tokens & global_text) < required
        ):
            issues.append(
                f"SVG does not visibly express primitive {identity} label: {label}"
            )
    return issues


def design_brief_svg_issues(
    spec: dict[str, Any], blueprint: dict[str, Any], root: ET.Element,
) -> list[str]:
    """Check the renderer-independent five-second brief against visible SVG text."""
    brief = spec.get("design_brief")
    brief = brief if isinstance(brief, dict) else {}
    issues: list[str] = []
    maximum = int(brief.get("maximum_primary_objects") or 8)
    primitives = [
        item for item in blueprint.get("primitives") or [] if isinstance(item, dict)
    ]
    if len(primitives) > maximum:
        issues.append(
            f"design brief permits at most {maximum} primary objects; "
            f"visual_blueprint declares {len(primitives)}"
        )
    visible_tokens = _semantic_tokens(_normalized_text(root))
    missing = []
    for raw in brief.get("must_show") or []:
        label = " ".join(str(raw or "").split())
        tokens = _semantic_tokens(label)
        if not tokens:
            continue
        required = min(2, len(tokens))
        if len(tokens & visible_tokens) < required:
            missing.append(label)
    if missing:
        issues.append("SVG omits design_brief.must_show labels: " + "; ".join(missing[:7]))
    from .model_svg_relation_preflight import method_relation_preflight_issues

    issues.extend(method_relation_preflight_issues(spec, blueprint, root))
    return issues


def source_mapping_issues(
    root: Path, spec: dict[str, Any], identifiers: list[str],
    mappings: Any = None,
) -> list[str]:
    """Mirror the formal rich-SVG source/group mapping gate at draft time."""
    selected = spec.get("element_mappings") if mappings is None else mappings
    _canonical, issues = validate_element_mappings(
        root, spec, selected, semantic_group_ids=set(identifiers),
    )
    return issues


def current_source_bundle_matches(root: Path, manifest: dict[str, Any]) -> bool:
    artifact_name = str(manifest.get("artifact_name") or "")
    mappings = manifest.get("element_mappings")
    if not isinstance(mappings, list) or not all(
        isinstance(item, dict) for item in mappings
    ):
        return False
    try:
        spec = require_model_composed_spec(root, artifact_name)
        _bindings, digest, issues = source_bundle_identity(root, spec)
    except ValueError:
        return False
    return (
        not issues
        and manifest.get("source_bundle_sha256") == digest
        and manifest.get("figure_spec_sha256") == figure_spec_sha256(spec)
        and manifest.get("element_mappings_sha256")
        == element_mappings_sha256(mappings)
    )
