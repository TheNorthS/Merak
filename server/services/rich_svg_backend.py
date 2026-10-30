"""Source review and same-source rendering for publication-grade rich SVG."""

from __future__ import annotations

import hashlib
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Optional

from ..utils.atomic_write import atomic_write_text
from .figure_models import FigureResult, FigureType


AppendReview = Callable[[Path, dict[str, Any]], list[dict[str, Any]]]


def _review(
    append_review: AppendReview, path: Path, metadata: dict[str, Any],
    status: str, issues: list[str], source_hash: str, render_hash: str = "",
) -> list[dict[str, Any]]:
    return append_review(path, {
        "status": status, "issues": list(dict.fromkeys(issues)),
        "content_sha256": source_hash, "render_sha256": render_hash,
        "reviewed_at": time.time(),
        "review_kind": (
            "enhanced_local_pixels"
            if str(metadata.get("visual_review_policy") or "").casefold()
            == "enhanced_local_pixels_required" else "source_and_pixels"
        ),
        "checks": [
            "svg_xml_and_vector_only_contract", "scientific_detail_density",
            "source_element_mapping", "raster_legibility", "canvas_edge_safety",
            "contrast_and_visual_differentiation",
        ],
    })


def _parse_svg(svg: str) -> tuple[Any, set[str], dict[str, int], set[str], list[str]]:
    issues: list[str] = []
    ids: set[str] = set()
    counts = {"text": 0, "rect": 0, "glyph": 0}
    fills: set[str] = set()
    try:
        root = ET.fromstring(svg.encode("utf-8"))
        if root.tag.rsplit("}", 1)[-1].casefold() != "svg":
            issues.append("rich SVG root element must be <svg>")
        view_box = str(root.attrib.get("viewBox") or "").split()
        if len(view_box) != 4:
            issues.append("rich SVG must declare a four-number viewBox")
        else:
            try:
                if float(view_box[2]) <= 0 or float(view_box[3]) <= 0:
                    issues.append("rich SVG canvas dimensions must be positive")
            except ValueError:
                issues.append("rich SVG viewBox contains non-numeric dimensions")
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1].casefold()
            if element.attrib.get("id"):
                ids.add(str(element.attrib["id"]).strip())
            if tag == "text":
                counts["text"] += 1
            elif tag == "rect":
                counts["rect"] += 1
            elif tag in {"path", "polyline", "polygon", "circle", "ellipse"}:
                counts["glyph"] += 1
            if tag in {"script", "foreignobject", "image"}:
                issues.append(f"rich SVG must remain editable vector content; <{tag}> is forbidden")
            fill = str(element.attrib.get("fill") or "").strip().casefold()
            if fill and fill not in {"none", "transparent", "white", "#ffffff"}:
                fills.add(fill)
        return root, ids, counts, fills, issues
    except (ET.ParseError, OSError) as exc:
        return None, ids, counts, fills, [f"rich SVG source is malformed: {exc}"]


def _density_issues(role: str, counts: dict[str, int], fills: set[str]) -> list[str]:
    if role == "method":
        contract = (
            (counts["text"], 5, "rich method figure has too little scientific explanation"),
            (counts["glyph"], 5, "rich method figure lacks scientific visual encoding"),
            (len(fills), 3, "rich method figure lacks restrained visual differentiation"),
        )
    elif role in {"evaluation_design", "evaluation", "protocol"}:
        contract = (
            (counts["text"], 5, "evaluation figure lacks a substantive scientific explanation"),
            (counts["glyph"], 3, "evaluation figure lacks scientific relationship encoding"),
            (len(fills), 2, "evaluation figure lacks restrained visual differentiation"),
        )
    else:
        contract = (
            (counts["text"], 16, "rich scientific figure is under-specified: fewer than 16 text elements"),
            (counts["rect"], 8, "rich scientific figure lacks visible hierarchy: fewer than 8 panels/modules"),
            (counts["glyph"], 6, "rich scientific figure lacks explanatory visual glyphs"),
            (len(fills), 4, "rich scientific figure lacks sufficient restrained visual differentiation"),
        )
    issues = [message for actual, minimum, message in contract if actual < minimum]
    return issues


def _method_semantic_issues(root: Any, metadata: dict[str, Any], registry: Any) -> list[str]:
    text = " ".join(
        " ".join(element.itertext()) for element in root.iter()
        if element.tag.rsplit("}", 1)[-1].casefold() in {"text", "title", "desc"}
    )
    patterns = {
        "pending/planned implementation status": r"\b(?:pending|planned\s+(?:inference|implementation|component)|design\s+scaffold|runtime[- ]verified)\b",
        "internal provenance implementation": r"\b(?:sha-?256|canonical\s+hash|build\s+(?:the\s+)?ledger(?:\s+record)?|persist\s+(?:the\s+)?evidence\s+bundle|event\s+logger|source[_ -]?run[_ -]?id)\b",
        "evidence-mode disclaimer": r"\b(?:no\s+empirical\s+(?:ranking\s+)?outcome|not\s+experimental\s+results|synthetic\s+preview|simulation\s+disclosure)\b",
    }
    issues = [
        "method rich SVG exposes " + label + "; replace it with publication-facing scientific concepts"
        for label, pattern in patterns.items() if re.search(pattern, text, re.IGNORECASE)
    ]
    issues.extend(registry.predictive_architecture_semantic_issues(metadata, text))
    return issues


def _mapping_issues(
    metadata: dict[str, Any], ids: set[str], root: Path, verify: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    mappings = [dict(item) for item in metadata.get("element_mappings") or [] if isinstance(item, dict)]
    role = str(metadata.get("scientific_role") or "")
    if role not in {"method", "evaluation_design", "evaluation", "protocol"}:
        return mappings, []
    if not mappings:
        return mappings, [f"{role} rich SVG requires element_mappings to real project sources"]
    issues = []
    mapped_ids = {str(item.get("element_id") or "").strip() for item in mappings if str(item.get("element_id") or "").strip()}
    from .model_composed_svg import required_element_mapping_count

    minimum_groups = required_element_mapping_count({
        **metadata, "scientific_role": role,
    })
    if len(mapped_ids) < minimum_groups:
        issues.append(f"{role} rich SVG requires at least {minimum_groups} source-mapped scientific groups")
    issues.extend(verify({"elements": [{"id": value} for value in sorted(ids)]}, mappings, root))
    return mappings, issues


def _failure(
    error: str, *, source: Path | None = None, code: str = "",
    rounds: Any = None, independent_review: dict[str, Any] | None = None,
) -> FigureResult:
    metadata = {"visual_review_rounds": rounds} if rounds is not None else {}
    if independent_review:
        metadata["independent_visual_review"] = independent_review
    return FigureResult(
        False, FigureType.RICH_SVG,
        source_path=str(source) if source else None, code=code or None, error=error,
        metadata=metadata or None,
    )


def _success(
    source: Path, pdf: Path, png: Path, svg: str, metadata: dict[str, Any],
    mappings: list[dict[str, Any]], ids: set[str], rounds: Any,
    source_hash: str, render_hash: str, visual_review: dict[str, Any],
) -> FigureResult:
    deterministic_runtime_template = (
        metadata.get("producer_kind") == "deterministic"
        and metadata.get("skill_invocation_verified") is True
        and str(metadata.get("skill_invocation_verified_by") or "").startswith(
            "deterministic-runtime-"
        )
    )
    generator = (
        "deterministic-runtime-rich-svg"
        if deterministic_runtime_template else "model-authored-rich-svg"
    )
    return FigureResult(
        True, FigureType.RICH_SVG, output_path=str(pdf), source_path=str(source),
        code=svg, svg_content=svg, install_hint=f"IDE preview: {png}",
        metadata={
            "generator": generator,
            "skill": metadata.get("generator_skill") or metadata.get("skill") or "",
            "generator_skill": metadata.get("generator_skill") or "",
            "skill_invocation_verified": bool(metadata.get("skill_invocation_verified")),
            "renderer": "rich-svg-vector-v1", "render_status": "rendered",
            "source_faithful": (
                "runtime-template-svg-same-source-variants"
                if deterministic_runtime_template
                else "model-authored-svg-same-source-variants"
            ),
            "model_authored": not deterministic_runtime_template,
            "scientific_svg_compiler": (
                "deterministic-runtime-template-v1"
                if deterministic_runtime_template else "model-authored-svg-v1"
            ),
            "model_authored_blueprint": (
                not deterministic_runtime_template
                and isinstance(metadata.get("visual_blueprint"), dict)
            ),
            "element_mappings": mappings, "visual_element_ids": sorted(ids),
            "visual_review_rounds": rounds,
            "visual_review_source_sha256": source_hash,
            "visual_review_render_sha256": render_hash,
            "independent_visual_review": (
                {} if deterministic_runtime_template else visual_review
            ),
            "deterministic_visual_review": (
                visual_review if deterministic_runtime_template else {}
            ),
            "_rendered_variant_paths": {
                "svg": str(source), "pdf": str(pdf), "png": str(png),
            },
        },
    )


def _finish_local_candidate(
    *, source: Path, pdf: Path, png: Path, svg: str,
    value: dict[str, Any], mappings: list[dict[str, Any]], ids: set[str],
    review: Path, append_review: AppendReview,
    source_hash: str, render_hash: str,
) -> FigureResult:
    from .rich_svg_visual_review import local_review_issues, local_review_record

    local_review = local_review_record(value, source, pdf, png)
    local_issues = local_review_issues(
        {**value, "deterministic_visual_review": local_review,
         "independent_visual_review": {}}, source, pdf, png,
        require_round=False,
    )
    if local_issues:
        rounds = _review(
            append_review, review, value, "failed", local_issues,
            source_hash, render_hash,
        )
        return _failure(
            "Rich SVG local-pixel review failed: " + "; ".join(local_issues),
            source=source, code=svg, rounds=rounds,
        )
    rounds = _review(
        append_review, review, value, "passed", [], source_hash, render_hash,
    )
    return _success(
        source, pdf, png, svg, value, mappings, ids,
        rounds, source_hash, render_hash, local_review,
    )


async def _finish_rendered_candidate(
    *, registry: Any, root_path: Path, artifact_stem: str,
    source: Path, pdf: Path, png: Path, svg: str, value: dict[str, Any],
    mappings: list[dict[str, Any]], ids: set[str], review: Path,
    append_review: AppendReview, sha256_path: Any,
) -> FigureResult:
    raster_issues = [
        *registry.raster_visual_quality_issues(png),
        *registry.rich_svg_render_issues(png),
    ]
    source_hash, render_hash = sha256_path(source), sha256_path(png)
    if raster_issues:
        rounds = _review(
            append_review, review, value, "failed", raster_issues,
            source_hash, render_hash,
        )
        return _failure(
            "Rich SVG render review failed; revise the same artifact_name and retry: "
            + "; ".join(raster_issues), source=source, code=svg, rounds=rounds,
        )
    if value.get("production_strategy") == "deterministic_template":
        return _finish_local_candidate(
            source=source, pdf=pdf, png=png, svg=svg, value=value,
            mappings=mappings, ids=ids, review=review,
            append_review=append_review, source_hash=source_hash,
            render_hash=render_hash,
        )
    from .rich_svg_visual_review import native_review_issues, review_candidate

    staged_review = value.get("independent_visual_review")
    staged_review = staged_review if isinstance(staged_review, dict) else {}
    reuse_issues = native_review_issues(value, root_path, source, png)
    if (
        value.get("production_strategy") == "model_composed_full_svg"
        and staged_review
        and not reuse_issues
    ):
        # The source and rendered pixels exactly match the accepted preflight.
        # Reuse its attested trace instead of paying for a duplicate model call.
        native_review, native_issues = staged_review, []
    else:
        native_review, native_issues = await review_candidate(
            root=root_path, artifact_id=artifact_stem, metadata=value,
            source=source, pdf=pdf, png=png, source_sha256=source_hash,
        )
    if native_issues:
        rounds = _review(
            append_review, review, value, "failed", native_issues,
            source_hash, render_hash,
        )
        archive = native_review.get("candidate_path") or "review invocation trace"
        return _failure(
            "Rich SVG native-image review failed; revise the same artifact_name: "
            + "; ".join(native_issues) + f"; candidate: {archive}",
            source=source, code=svg, rounds=rounds,
            independent_review=native_review,
        )
    rounds = _review(
        append_review, review, value, "passed", [], source_hash, render_hash,
    )
    return _success(
        source, pdf, png, svg, value, mappings, ids,
        rounds, source_hash, render_hash, native_review,
    )


def _generation_blueprint(value: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Keep runtime templates distinct from model-owned semantic blueprints."""
    from .rich_svg_blueprint import validate_visual_blueprint

    raw_blueprint = value.get("visual_blueprint")
    from .rich_svg_visual_review import is_deterministic_template

    deterministic_runtime_template = is_deterministic_template(value)
    # visual_blueprint is the semantic index for model-authored SVGs. Runtime
    # templates already own fixed, typed groups plus element_mappings and must
    # not be forced to impersonate the model-authored compiler. They still pass
    # source mapping, print, raster, and hash-bound local-pixel review below.
    if deterministic_runtime_template:
        return {}, []
    source_spec = (
        value if value.get("production_strategy") == "model_composed_full_svg"
        else None
    )
    return validate_visual_blueprint(raw_blueprint, source_spec=source_spec)


def _source_review(
    svg: str, value: dict[str, Any], blueprint: dict[str, Any],
    root_path: Path, artifact_stem: str, registry: Any, verify: Any,
) -> tuple[set[str], list[dict[str, Any]], list[str]]:
    """Collect semantic, print, and source-mapping findings in their original order."""
    from .rich_svg_blueprint import blueprint_svg_issues

    root, ids, counts, fills, issues = _parse_svg(svg)
    if root is not None and blueprint:
        issues.extend(blueprint_svg_issues(blueprint, root))
    role = re.sub(r"[^a-z0-9]+", "_", str(value.get("scientific_role") or artifact_stem).casefold()).strip("_")
    if root is not None:
        from .figure_print_policy import svg_print_contract_issues
        issues.extend(_density_issues(role, counts, fills))
        issues.extend(svg_print_contract_issues(svg, root, value))
        if role == "method":
            issues.extend(_method_semantic_issues(root, value, registry))
    mappings, mapping_issues = _mapping_issues(value, ids, root_path, verify)
    issues.extend(mapping_issues)
    return ids, mappings, issues


async def generate_rich_svg(
    code: str, output_dir: str, artifact_stem: str, metadata: Optional[dict],
    *, normalize_svg: Any,
    convert_variants: Any, append_review: AppendReview, sha256_path: Any,
) -> FigureResult:
    from .excalidraw_renderer import verify_element_mappings
    from .figure_artifacts import figure_artifact_registry

    value = dict(metadata or {})
    from .rich_svg_visual_review import is_deterministic_template

    if (
        value.get("production_strategy") == "deterministic_template"
        and not is_deterministic_template(value)
    ):
        return _failure(
            "Rich SVG deterministic template requires verified runtime producer provenance."
        )
    blueprint, early_blueprint_issues = _generation_blueprint(value)
    if early_blueprint_issues:
        return _failure(
            "Rich SVG visual blueprint failed: " + "; ".join(early_blueprint_issues)
        )
    svg = normalize_svg(code.strip())
    if not svg:
        return _failure(
            "Rich SVG generation requires complete <svg> source; prose is not renderable."
        )
    svg += "" if svg.endswith("\n") else "\n"
    source_hash = hashlib.sha256(svg.encode("utf-8")).hexdigest()
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    root_path = figure_artifact_registry.project_root(directory)
    review = root_path / ".merak" / "figure-reviews" / f"{artifact_stem}.json"
    review.parent.mkdir(parents=True, exist_ok=True)
    source, pdf, png = (
        directory / f"{artifact_stem}{suffix}" for suffix in (".svg", ".pdf", ".png")
    )
    ids, mappings, issues = _source_review(
        svg, value, blueprint, root_path, artifact_stem,
        figure_artifact_registry, verify_element_mappings,
    )
    if issues:
        rejected = review.parent / f"{artifact_stem}.rejected.svg"
        atomic_write_text(rejected, svg)
        rounds = _review(append_review, review, value, "failed", issues, source_hash)
        return _failure(
            "Rich SVG source review failed; revise the same artifact_name and retry: "
            + "; ".join(list(dict.fromkeys(issues))) + f"; rejected candidate: {rejected}",
            code=svg, rounds=rounds,
        )
    atomic_write_text(source, svg)
    converted, conversion_error = convert_variants(source, pdf, png)
    if not converted:
        rounds = _review(append_review, review, value, "failed", [conversion_error], source_hash)
        return _failure(conversion_error, source=source, code=svg, rounds=rounds)
    return await _finish_rendered_candidate(
        registry=figure_artifact_registry, root_path=root_path,
        artifact_stem=artifact_stem, source=source, pdf=pdf, png=png,
        svg=svg, value=value, mappings=mappings, ids=ids, review=review,
        append_review=append_review, sha256_path=sha256_path,
    )
