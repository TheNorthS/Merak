"""Per-backend publication quality and provenance audit for figure artifacts."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from PIL import Image

from .figure_artifact_support import (
    MANUSCRIPT_FIGURE_ROLES,
    NON_SUBMISSION_EVIDENCE_STATUSES,
    PAPER_READY_EXTENSIONS,
    _sha256,
)


def _entries(registry: Any, path: str | Path, root: Path) -> list[dict[str, Any]]:
    entries = list(registry.paper_ready_entries(path))
    known = {str(item.get("id") or "") for item in entries}
    for item in registry.load(path).get("figures", []):
        if not isinstance(item, dict):
            continue
        metadata = dict(item.get("metadata") or {})
        if metadata.get("evidence_status") != "synthetic_preview" or str(item.get("id") or "") in known:
            continue
        output = (root / str(item.get("output_path") or "")).resolve()
        if output.is_file() and output.stat().st_size > 0 and output.suffix.casefold() in PAPER_READY_EXTENSIONS:
            entries.append(item)
            known.add(str(item.get("id") or ""))
    return entries


def _source(root: Path, item: dict[str, Any]) -> Path | None:
    value = str(item.get("source_path") or "").strip()
    if not value:
        return None
    path = Path(value)
    return (path if path.is_absolute() else root / path).resolve()


def _resolve(root: Path, value: Any, fallback: Path | None = None) -> Path | None:
    if not str(value or "").strip():
        return fallback
    path = Path(str(value)).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def _metadata_issues(
    figure_id: str, item: dict[str, Any], metadata: dict[str, Any], root: Path,
) -> list[str]:
    role = str(metadata.get("scientific_role") or "")
    issues: list[str] = []
    if role not in MANUSCRIPT_FIGURE_ROLES:
        issues.append(f"{figure_id}: unsupported or missing scientific_role metadata ({role or 'empty'})")
    requirements = (
        (metadata.get("style_profile"), "missing publication style profile"),
        (len(str(item.get("caption") or "").strip()) >= 20, "caption is too generic"),
        (str(metadata.get("scientific_question") or "").strip(), "missing scientific_question metadata"),
        (str(metadata.get("intended_comparison") or "").strip(), "missing intended_comparison metadata"),
        (str(metadata.get("visual_encoding") or "").strip(), "missing visual_encoding metadata"),
    )
    issues.extend(f"{figure_id}: {message}" for condition, message in requirements if not condition)
    sources = metadata.get("source_data")
    if not isinstance(sources, list) or not sources:
        issues.append(f"{figure_id}: missing source_data provenance")
    else:
        for raw in sources:
            candidate = _resolve(root, raw)
            try:
                candidate.relative_to(root)
            except (AttributeError, OSError, ValueError):
                issues.append(f"{figure_id}: source_data escapes project: {raw}")
                continue
            if not candidate.is_file() or candidate.stat().st_size == 0:
                issues.append(f"{figure_id}: source_data is missing or empty: {raw}")
    if role in {"result", "ablation", "robustness"}:
        if not metadata.get("source_data"):
            issues.append(f"{figure_id}: quantitative figure has no source_data provenance")
        if not metadata.get("claim_ids"):
            issues.append(f"{figure_id}: quantitative figure is not linked to a claim")
        if not str(metadata.get("uncertainty_encoding") or "").strip():
            issues.append(f"{figure_id}: quantitative figure has no uncertainty encoding")
    return issues


def _diagram_issues(
    registry: Any, figure_id: str, item: dict[str, Any],
    metadata: dict[str, Any], root: Path, source: Path | None,
) -> list[str]:
    if not source or not source.is_file():
        return []
    issues: list[str] = []
    if source.suffix.casefold() in {".drawio", ".dio"}:
        issues.extend(f"{figure_id}: {value}" for value in registry.drawio_text_layout_issues(source))
        variants = dict(metadata.get("rendered_variants") or {})
        pdf_value = variants.get("pdf") or (
            item.get("output_path") if str(item.get("output_path") or "").casefold().endswith(".pdf") else ""
        )
        pdf = _resolve(root, pdf_value, source.with_suffix(".pdf"))
        issues.extend(f"{figure_id}: {value}" for value in registry.drawio_render_text_issues(source, pdf))
    elif source.suffix.casefold() in {".mmd", ".mermaid"}:
        issues.extend(f"{figure_id}: {value}" for value in registry.mermaid_layout_issues(source))
        pdf = _resolve(root, item.get("output_path"), source.with_suffix(".pdf"))
        issues.extend(f"{figure_id}: {value}" for value in registry.mermaid_render_text_issues(pdf))
    return issues


def _review_contract(
    figure_id: str, metadata: dict[str, Any], source: Path,
    preview: Path | None, required_variants: set[str],
) -> tuple[list[str], dict[str, Any]]:
    variants = dict(metadata.get("rendered_variants") or {})
    missing = sorted(required_variants - set(variants))
    issues = [f"{figure_id}: missing rendered variants " + ", ".join(missing)] if missing else []
    rounds = [item for item in metadata.get("visual_review_rounds") or [] if isinstance(item, dict)]
    last = rounds[-1] if rounds else {}
    if last.get("status") != "passed":
        issues.append(f"{figure_id}: no passing hash-bound visual review")
    if last.get("content_sha256") != _sha256(source):
        issues.append(f"{figure_id}: visual review is stale for editable source")
    if not preview or not preview.is_file():
        issues.append(f"{figure_id}: PNG preview is missing")
    elif last.get("render_sha256") != _sha256(preview):
        issues.append(f"{figure_id}: visual review is stale for rendered preview")
    return issues, last


def _rich_svg_provenance_issues(
    figure_id: str, metadata: dict[str, Any],
) -> list[str]:
    """Require the renderer's truthful provenance for the declared producer."""
    strategy = str(metadata.get("production_strategy") or "").strip()
    producer = str(metadata.get("producer_kind") or "").strip()
    if strategy == "deterministic_template":
        expected_producer = "deterministic"
        skill = "deterministic-figure-template"
        values = {
            "generator": "deterministic-runtime-rich-svg",
            "source_faithful": "runtime-template-svg-same-source-variants",
            "model_authored": False,
            "model_authored_blueprint": False,
            "scientific_svg_compiler": "deterministic-runtime-template-v1",
            "skill_invocation_verified_by": "deterministic-runtime-figure-builder",
        }
    elif strategy in {"", "model_composed_full_svg"}:
        expected_producer = "model"
        skill = "model-svg-figure" if strategy else "rich-svg-figure"
        values = {
            "generator": "model-authored-rich-svg",
            "source_faithful": "model-authored-svg-same-source-variants",
            "model_authored": True,
            "model_authored_blueprint": True,
            "scientific_svg_compiler": "model-authored-svg-v1",
            "skill_invocation_verified_by": "agent-runtime",
        }
    else:
        return [f"{figure_id}: unsupported rich SVG production_strategy ({strategy})"]
    issues = []
    if producer != expected_producer and (strategy or producer):
        issues.append(
            f"{figure_id}: {strategy or 'legacy rich SVG'} requires "
            f"producer_kind={expected_producer}"
        )
    values.update({
        "renderer": "rich-svg-vector-v1",
        "render_status": "rendered",
        "skill": skill,
        "generator_skill": skill,
        "skill_invocation_verified": True,
    })
    if not strategy:
        # The legacy rich-SVG route predates explicit producer attestation;
        # preserve its prior checks rather than retroactively rejecting it.
        for key in (
            "source_faithful", "model_authored", "render_status",
            "generator_skill", "skill_invocation_verified",
            "skill_invocation_verified_by",
        ):
            values.pop(key)
    issues.extend(
        f"{figure_id}: {key} provenance does not match {strategy or 'legacy rich SVG'}"
        for key, expected in values.items() if metadata.get(key) != expected
    )
    return issues


def _rich_svg_issues(
    registry: Any, figure_id: str, metadata: dict[str, Any],
    root: Path, source: Path, role: str,
) -> list[str]:
    from .excalidraw_renderer import verify_element_mappings
    from .rich_svg_visual_review import local_review_issues, native_review_issues

    issues = [f"{figure_id}: {value}" for value in registry.rich_svg_source_issues(source)]
    try:
        svg = ET.fromstring(source.read_bytes())
        ids = sorted({str(item.attrib.get("id") or "").strip() for item in svg.iter() if str(item.attrib.get("id") or "").strip()})
    except ET.ParseError:
        ids = []
        issues.append(f"{figure_id}: rich SVG source is malformed")
    mappings = [dict(item) for item in metadata.get("element_mappings") or [] if isinstance(item, dict)]
    if role in {"method", "evaluation_design", "evaluation", "protocol"}:
        if not mappings:
            issues.append(f"{figure_id}: missing element-to-source mappings")
        else:
            from .model_composed_svg import required_element_mapping_count

            minimum = required_element_mapping_count({
                **metadata, "scientific_role": role,
            })
            mapped = {
                str(item.get("element_id") or "").strip()
                for item in mappings if str(item.get("element_id") or "").strip()
            }
            if len(mapped) < minimum:
                issues.append(
                    f"{figure_id}: rich SVG requires at least {minimum} "
                    "independently source-mapped major groups"
                )
            issues.extend(f"{figure_id}: {value}" for value in verify_element_mappings(
                {"elements": [{"id": value} for value in ids]}, mappings, root,
            ))
    issues.extend(_rich_svg_provenance_issues(figure_id, metadata))
    preview = _resolve(root, dict(metadata.get("rendered_variants") or {}).get("png"))
    contract, _last = _review_contract(figure_id, metadata, source, preview, {"svg", "pdf", "png"})
    issues.extend(contract)
    output = _resolve(root, dict(metadata.get("rendered_variants") or {}).get("pdf"))
    review_issues = (
        local_review_issues(metadata, source, output, preview)
        if metadata.get("production_strategy") == "deterministic_template"
        else native_review_issues(metadata, root, source, preview)
    )
    issues.extend(f"{figure_id}: {issue}" for issue in review_issues)
    if preview and preview.is_file():
        issues.extend(f"{figure_id}: {value}" for value in registry.raster_visual_quality_issues(preview))
        issues.extend(f"{figure_id}: {value}" for value in registry.rich_svg_render_issues(preview))
    return issues


def _figurespec_issues(
    registry: Any, figure_id: str, metadata: dict[str, Any],
    root: Path, source: Path, role: str,
) -> list[str]:
    from .excalidraw_renderer import verify_element_mappings

    issues = [f"{figure_id}: {value}" for value in registry.figurespec_layout_issues(source)]
    try:
        spec = json.loads(source.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        spec = {}
    spec = spec if isinstance(spec, dict) else {}
    mappings = [dict(item) for item in metadata.get("element_mappings") or [] if isinstance(item, dict)]
    if role == "method":
        if not mappings:
            issues.append(f"{figure_id}: missing element-to-source mappings")
        else:
            scene = {"elements": [{"id": str(node.get("id") or "")} for node in spec.get("nodes") or [] if isinstance(node, dict) and str(node.get("id") or "")]}
            issues.extend(f"{figure_id}: {value}" for value in verify_element_mappings(scene, mappings, root))
    deterministic = metadata.get("production_strategy") == "deterministic_architecture"
    for key, expected, message in (
        ("generator", "deterministic-figurespec", "FigureSpec generator provenance is missing"),
        ("skill", "figure-spec", "FigureSpec skill provenance is missing"),
        ("renderer", "figurespec-v2", "unapproved FigureSpec renderer"),
        ("model_authored", not deterministic, "FigureSpec authorship provenance is incorrect"),
    ):
        if metadata.get(key) != expected:
            issues.append(f"{figure_id}: {message}")
    if deterministic and (
        metadata.get("producer_kind") != "deterministic"
        or metadata.get("skill_invocation_verified_by")
        != "deterministic-runtime-figure-builder"
    ):
        issues.append(f"{figure_id}: deterministic architecture producer provenance is missing")
    preview = _resolve(root, dict(metadata.get("rendered_variants") or {}).get("png"))
    contract, last = _review_contract(figure_id, metadata, source, preview, {"json", "svg", "pdf", "png"})
    issues.extend(contract)
    if metadata.get("visual_review_policy") == "enhanced_local_pixels_required" and last.get("review_kind") != "enhanced_local_pixels":
        issues.append(f"{figure_id}: enhanced local pixel/layout review is missing")
    if preview and preview.is_file():
        issues.extend(f"{figure_id}: {value}" for value in registry.raster_visual_quality_issues(preview))
    return issues


def _implementation_sources(root: Path) -> set[str]:
    directory = root / "experiments" / "src"
    extensions = {".py", ".r", ".jl", ".m", ".c", ".cc", ".cpp", ".h", ".java", ".kt", ".rs", ".go", ".ts", ".tsx", ".js"}
    return {
        path.relative_to(root).as_posix() for path in directory.rglob("*")
        if path.is_file() and path.suffix.casefold() in extensions
    } if directory.is_dir() else set()


def _excalidraw_issues(
    registry: Any, figure_id: str, metadata: dict[str, Any],
    root: Path, source: Path, role: str,
) -> list[str]:
    from .excalidraw_renderer import scene_layout_issues, scene_text, verify_element_mappings

    issues: list[str] = []
    try:
        scene = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        scene = {}
        issues.append(f"{figure_id}: Excalidraw source is not valid JSON")
    mappings = [dict(item) for item in metadata.get("element_mappings") or [] if isinstance(item, dict)]
    if scene:
        issues.extend(f"{figure_id}: {value}" for value in scene_layout_issues(scene))
        labels = {" ".join(line.casefold().split()) for line in scene_text(scene).splitlines() if line.strip()}
        generic = {"input", "data", "model", "method", "process", "output", "result", "input data", "model architecture", "proposed method"}
        if labels and labels <= generic:
            issues.append(f"{figure_id}: scene uses only generic Input/Model/Output labels")
        issues.extend(f"{figure_id}: {value}" for value in verify_element_mappings(scene, mappings, root)) if mappings else issues.append(f"{figure_id}: missing element-to-source mappings")
    for key, expected, message in (
        ("generator", "model-excalidraw", "Excalidraw source was not authored by the figure model"),
        ("skill", "excalidraw-skill", "Excalidraw skill provenance is missing"),
        ("renderer", "roughjs-excalidraw", "unapproved Excalidraw renderer"),
        ("model_authored", True, "model_authored provenance is not true"),
    ):
        if metadata.get(key) != expected:
            issues.append(f"{figure_id}: {message}")
    variants = dict(metadata.get("rendered_variants") or {})
    missing = sorted({"excalidraw", "svg", "pdf", "png"} - set(variants))
    if missing:
        issues.append(f"{figure_id}: missing Excalidraw variants {', '.join(missing)}")
    rounds = [item for item in metadata.get("visual_review_rounds") or [] if isinstance(item, dict)]
    if not rounds or rounds[-1].get("status") != "passed":
        issues.append(f"{figure_id}: no passing render-review round")
    preview = _resolve(root, variants.get("png"))
    if preview and preview.is_file():
        try:
            with Image.open(preview) as image:
                width, height = image.size
            if width < 1000 or height < 450:
                issues.append(f"{figure_id}: Excalidraw preview is too small ({width}x{height})")
        except OSError:
            issues.append(f"{figure_id}: Excalidraw PNG preview cannot be decoded")
        issues.extend(f"{figure_id}: {value}" for value in registry.raster_layout_issues(preview))
    implementation = _implementation_sources(root)
    mapped = {str(item.get("source_path") or "").replace("\\", "/") for item in mappings}
    if role == "method" and implementation:
        if not mapped & implementation:
            issues.append(f"{figure_id}: method scene does not map any element to implementation code")
        if not metadata.get("code_symbols"):
            issues.append(f"{figure_id}: method scene has no verified code_symbols")
    return issues


def _preview_issues(
    registry: Any, figure_id: str, item: dict[str, Any],
    metadata: dict[str, Any], root: Path, source: Path | None,
) -> list[str]:
    output = _resolve(root, item.get("output_path"))
    candidates = []
    if item.get("preview_path"):
        candidates.append(_resolve(root, item["preview_path"]))
    if output and output.suffix.casefold() in {".png", ".jpg", ".jpeg"}:
        candidates.append(output)
    if source:
        candidates.append(source.with_suffix(".png"))
    if output:
        candidates.append(output.with_suffix(".png"))
    preview = next((path for path in candidates if path and path.is_file()), None)
    if not preview:
        return []
    issues: list[str] = []
    try:
        with Image.open(preview) as image:
            width, height = image.size
        if width < 1000 or height < 450:
            issues.append(f"{figure_id}: raster preview is too small ({width}x{height})")
        ratio = width / max(1, height)
        if ratio < 0.7 or ratio > 4.2:
            issues.append(f"{figure_id}: extreme aspect ratio {ratio:.2f}")
    except OSError:
        issues.append(f"{figure_id}: raster output cannot be decoded")
    quarantined = metadata.get("evidence_status") == "synthetic_preview" and metadata.get("paper_selected") is False and metadata.get("manuscript_eligible") is False
    if not quarantined:
        issues.extend(f"{figure_id}: {value}" for value in registry.raster_layout_issues(preview))
    return issues


def _item_issues(registry: Any, item: dict[str, Any], root: Path) -> list[str]:
    figure_id = str(item.get("id") or "unknown")
    metadata = dict(item.get("metadata") or {})
    status = str(metadata.get("evidence_status") or "").casefold()
    if status in NON_SUBMISSION_EVIDENCE_STATUSES and status != "synthetic_preview":
        return []
    role, source = str(metadata.get("scientific_role") or ""), _source(root, item)
    issues = _metadata_issues(figure_id, item, metadata, root)
    if str(item.get("type") or "").casefold() == "nano_banana":
        issues.extend(registry.gemini_protocol_issues(item, root))
    issues.extend(_diagram_issues(registry, figure_id, item, metadata, root, source))
    if source and source.is_file():
        kind = str(item.get("type") or "").casefold()
        if kind == "rich_svg" and source.suffix.casefold() == ".svg":
            issues.extend(_rich_svg_issues(registry, figure_id, metadata, root, source, role))
        elif kind == "figurespec" and source.suffix.casefold() == ".json":
            issues.extend(_figurespec_issues(registry, figure_id, metadata, root, source, role))
        elif source.suffix.casefold() == ".excalidraw":
            issues.extend(_excalidraw_issues(registry, figure_id, metadata, root, source, role))
    issues.extend(_preview_issues(registry, figure_id, item, metadata, root, source))
    return issues


def scientific_quality_issues(registry: Any, path: str | Path) -> list[str]:
    root = registry.project_root(path)
    return [
        issue for item in _entries(registry, path, root)
        for issue in _item_issues(registry, item, root)
    ]
