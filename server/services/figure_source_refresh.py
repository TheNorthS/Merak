"""Re-render one editable figure source without changing its semantic identity."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Protocol

from PIL import Image, ImageOps

from .figure_models import FigureResult, FigureType


ElectronRenderer = Callable[[str, Path, Path, Path], Awaitable[tuple[bool, str]]]


class FigureEnginePort(Protocol):
    async def _generate_rich_svg(self, *args: Any, **kwargs: Any) -> FigureResult: ...
    async def _generate_matplotlib(self, *args: Any, **kwargs: Any) -> FigureResult: ...
    async def _generate_figurespec(self, *args: Any, **kwargs: Any) -> FigureResult: ...
    async def _generate_excalidraw(self, *args: Any, **kwargs: Any) -> FigureResult: ...


@dataclass
class RefreshContext:
    engine: FigureEnginePort
    registry: Any
    source: Path
    figures_root: Path
    project_root: Path
    description: str
    metadata: dict[str, Any]
    figure_type: FigureType
    code: str
    output: Path
    render_mermaid: ElectronRenderer
    render_drawio: ElectronRenderer
    sha256_path: Callable[[Path], str]
    rendered: bool = False
    error: str = ""


def _figure_type(suffix: str, recorded_type: str) -> FigureType:
    if suffix == ".svg" or recorded_type == FigureType.RICH_SVG.value:
        return FigureType.RICH_SVG
    if suffix == ".py":
        return FigureType.MATPLOTLIB
    if suffix == ".json":
        return FigureType.FIGURESPEC
    if suffix in {".mmd", ".mermaid"}:
        return FigureType.MERMAID
    if suffix == ".excalidraw":
        return FigureType.EXCALIDRAW
    return FigureType.DRAWIO


def _manifest_context(
    registry: Any, figures_root: Path, project_root: Path, source: Path,
    description_override: str, metadata_override: Optional[dict],
) -> tuple[str, dict[str, Any], str]:
    try:
        source_relative = source.relative_to(project_root).as_posix()
    except ValueError:
        source_relative = source.as_posix()
    description = description_override.strip() or source.stem
    metadata: dict[str, Any] = {}
    recorded_type = ""
    for item in registry.load(figures_root).get("figures", []):
        if item.get("source_path") == source_relative:
            description = str(item.get("description") or description)
            metadata = dict(item.get("metadata") or {})
            recorded_type = str(item.get("type") or "").strip().casefold()
            break
    metadata.update(dict(metadata_override or {}))
    metadata.setdefault("semantic_key", source.stem)
    metadata.setdefault("managed_by", "merak")
    role = {
        "method_architecture": "method",
        "evaluation_design": "evaluation_design",
    }.get(source.stem.casefold())
    if role and not str(metadata.get("scientific_role") or "").strip():
        metadata.update({
            "scientific_role": role, "paper_selected": True,
            "manuscript_eligible": True, "evidence_status": "planned_design",
        })
    return description, metadata, recorded_type


def _context(
    engine: FigureEnginePort, registry: Any, source: Path,
    metadata_override: Optional[dict], description_override: str,
    render_mermaid: ElectronRenderer, render_drawio: ElectronRenderer,
    sha256_path: Callable[[Path], str],
) -> RefreshContext:
    figures_root = registry.figures_root(source.parent)
    project_root = registry.project_root(figures_root)
    description, metadata, recorded_type = _manifest_context(
        registry, figures_root, project_root, source,
        description_override, metadata_override,
    )
    figure_type = _figure_type(source.suffix.casefold(), recorded_type)
    return RefreshContext(
        engine, registry, source, figures_root, project_root, description,
        metadata, figure_type,
        source.read_text(encoding="utf-8", errors="replace"),
        source.with_suffix(".pdf"), render_mermaid, render_drawio, sha256_path,
    )


def _apply_generated(context: RefreshContext, generated: FigureResult) -> None:
    context.rendered = bool(generated.success and generated.output_path)
    context.error = str(generated.error or "")
    if generated.output_path:
        context.output = Path(generated.output_path).resolve()
    context.metadata.update(dict(generated.metadata or {}))


async def _native_backend(context: RefreshContext) -> bool:
    engine, source = context.engine, context.source
    if context.figure_type == FigureType.RICH_SVG:
        generated = await engine._generate_rich_svg(
            context.code, str(source.parent), artifact_stem=source.stem,
            metadata=context.metadata,
        )
    elif context.figure_type == FigureType.MATPLOTLIB:
        generated = await engine._generate_matplotlib(
            context.description, str(source.parent), "academic",
            code=context.code, artifact_stem=source.stem,
        )
    elif context.figure_type == FigureType.FIGURESPEC:
        generated = await engine._generate_figurespec(
            context.code, str(source.parent), artifact_stem=source.stem,
            metadata=context.metadata,
        )
    elif context.figure_type == FigureType.EXCALIDRAW:
        generated = await engine._generate_excalidraw(
            context.code, str(source.parent), artifact_stem=source.stem,
            metadata=context.metadata, enforce_mappings=False,
        )
    else:
        return False
    _apply_generated(context, generated)
    return True


def _temporary_variants(source: Path) -> tuple[Path, Path, Path]:
    return tuple(source.with_name(f"{source.stem}.refresh{suffix}") for suffix in (
        ".svg", ".pdf", ".png",
    ))


def _clear(paths: tuple[Path, ...]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def _pad_mermaid_preview(path: Path) -> None:
    try:
        with Image.open(path) as opened:
            preview = opened.convert("RGB")
        inset = max(48, round(min(preview.size) * 0.035))
        ImageOps.expand(preview, border=inset, fill="#FFFFFF").save(
            path, format="PNG", optimize=True,
        )
    except OSError:
        pass


def _adopt_rendered_variants(
    context: RefreshContext, temporary: tuple[Path, Path, Path],
) -> None:
    targets = tuple(context.source.with_suffix(suffix) for suffix in (
        ".svg", ".pdf", ".png",
    ))
    if context.figure_type == FigureType.MERMAID:
        _pad_mermaid_preview(temporary[2])
    for source, target in zip(temporary, targets):
        source.replace(target)
    context.output = targets[1]
    context.metadata["_rendered_variant_paths"] = {
        context.source.suffix.casefold().lstrip("."): str(context.source),
        "svg": str(targets[0]), "pdf": str(targets[1]), "png": str(targets[2]),
    }


def _adopt_current_variants(context: RefreshContext) -> bool:
    variants = tuple(context.source.with_suffix(suffix) for suffix in (
        ".svg", ".pdf", ".png",
    ))
    source_mtime = context.source.stat().st_mtime
    current = all(
        path.is_file() and path.stat().st_size > 0 and path.stat().st_mtime >= source_mtime
        for path in variants
    )
    if not current:
        return False
    context.rendered, context.error, context.output = True, "", variants[1]
    context.metadata.update({
        "reused_current_variants": True,
        "_rendered_variant_paths": {
            context.source.suffix.casefold().lstrip("."): str(context.source),
            "svg": str(variants[0]), "pdf": str(variants[1]), "png": str(variants[2]),
        },
    })
    return True


async def _electron_backend(context: RefreshContext) -> None:
    temporary = _temporary_variants(context.source)
    _clear(temporary)
    renderer = (
        context.render_mermaid
        if context.figure_type == FigureType.MERMAID else context.render_drawio
    )
    context.rendered, context.error = await renderer(
        context.code, temporary[0], temporary[1], temporary[2],
    )
    if context.rendered:
        _adopt_rendered_variants(context, temporary)
    _clear(temporary)
    if not context.rendered:
        _adopt_current_variants(context)


def _bind_variants(context: RefreshContext) -> None:
    paths = dict(context.metadata.pop("_rendered_variant_paths", {}) or {})
    if not paths:
        return
    rendered: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for variant, raw_path in paths.items():
        candidate = Path(str(raw_path)).resolve()
        if not candidate.is_file():
            continue
        try:
            relative = candidate.relative_to(context.project_root).as_posix()
        except ValueError:
            relative = candidate.as_posix()
        rendered[str(variant)] = relative
        hashes[str(variant)] = context.sha256_path(candidate)
    context.metadata.update({
        "rendered_variants": rendered, "rendered_variant_sha256": hashes,
        "preview_path": rendered.get("png", ""),
        "paper_vector_path": rendered.get("pdf", ""),
    })


def _renderer_name(context: RefreshContext) -> str:
    if not context.rendered:
        return "unavailable"
    return {
        FigureType.MATPLOTLIB: "matplotlib-python",
        FigureType.RICH_SVG: "rich-svg-vector-v1",
        FigureType.FIGURESPEC: "figurespec-v2",
        FigureType.EXCALIDRAW: "roughjs-excalidraw",
        FigureType.MERMAID: "electron-bundled-mermaid",
        FigureType.DRAWIO: "electron-bundled-drawio",
    }[context.figure_type]


def _record(context: RefreshContext) -> dict[str, Any]:
    _bind_variants(context)
    context.metadata.update({
        "render_status": "rendered" if context.rendered else "source_only",
        "renderer": _renderer_name(context),
        "source_faithful": (
            "same-source-geometry-style-and-labels"
            if context.rendered else context.metadata.get("source_faithful", "")
        ),
    })
    manifest_path, entry = context.registry.record(
        output_dir=context.source.parent, figure_type=context.figure_type.value,
        description=context.description,
        output_path=str(context.output) if context.rendered else None,
        source_path=str(context.source), metadata=context.metadata,
    )
    return {
        "success": context.rendered,
        "output_path": str(context.output) if context.rendered else None,
        "source_path": str(context.source), "manifest_path": str(manifest_path),
        "entry": entry, "error": context.error if not context.rendered else "",
    }


async def refresh_editable_source(
    engine: FigureEnginePort, source_path: str | Path,
    *, metadata_override: Optional[dict] = None, description_override: str = "",
    render_mermaid: ElectronRenderer, render_drawio: ElectronRenderer,
    sha256_path: Callable[[Path], str],
) -> dict[str, Any]:
    from .figure_artifacts import figure_artifact_registry

    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        return {"success": False, "error": f"Figure source not found: {source}"}
    allowed = {".py", ".svg", ".json", ".mmd", ".mermaid", ".drawio", ".dio", ".excalidraw"}
    if source.suffix.casefold() not in allowed:
        return {"success": False, "error": f"Unsupported editable figure source: {source.suffix.lower()}"}
    context = _context(
        engine, figure_artifact_registry, source, metadata_override,
        description_override, render_mermaid, render_drawio, sha256_path,
    )
    if not await _native_backend(context):
        await _electron_backend(context)
    return _record(context)
