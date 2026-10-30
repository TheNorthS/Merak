"""
画图引擎 — 多后端路由

支持：
- Matplotlib/Seaborn（数据图表）— Agent 生成 Python 代码并执行
- Mermaid（流程图/序列图/类图）— 生成语法，前端渲染
- TikZ（数学图/算法图）— 生成 LaTeX 代码编译
- GPT Image2 (DALL-E)（照片级示意图）— OpenAI API
- Nano Banana 2（快速风格化）— API 调用
- Draw.io XML（架构图）— 生成 XML，前端内嵌编辑器
"""

import asyncio
import base64
import hashlib
import importlib.util
import os
import json
import re
import shutil
import threading
import time
import weakref
from typing import Any, Optional
from pathlib import Path

import structlog

from .process_runner import run_process
from .figure_generation_transaction import generate_serialized
from .figure_models import FigureResult as FigureResult, FigureType as FigureType
from .figure_result_finalizer import finalize_figure_result
from .matplotlib_figure_backend import generate_matplotlib
from .image_figure_backends import generate_gpt_image, generate_nano_banana
from .excalidraw_figure_backend import generate_excalidraw
from .diagram_figure_backends import generate_drawio, generate_mermaid
from .figurespec_backend import generate_figurespec
from .tikz_figure_backend import generate_tikz
from .rich_svg_backend import generate_rich_svg
from .svg_variant_conversion import convert_svg_variants as _convert_svg_variants
from .figure_svg_sources import (
    _benchmark_model_suite_svg,  # noqa: F401 - compatibility re-export
    _evaluation_design_svg,  # noqa: F401 - compatibility re-export
    _inline_svg_vector_class_styles,
    _raise_svg_connectors,
    _normalize_svg_marker_viewports,
)
from ..utils.atomic_write import (
    atomic_replace_file,
    atomic_write_bytes,
    atomic_write_json,
    path_lock,
)

logger = structlog.get_logger()
_UNAVAILABLE_TOOLS: set[str] = set()
_FIGURESPEC_RENDERER: Any = None
_ARTIFACT_ASYNC_LOCKS: "weakref.WeakKeyDictionary[Any, dict[str, asyncio.Lock]]" = (
    weakref.WeakKeyDictionary()
)
_ARTIFACT_ASYNC_LOCKS_GUARD = threading.Lock()
PUBLICATION_STYLE_PROFILE = "merak-publication-v1"
MATPLOTLIB_STYLE_PREAMBLE = """# MERAK_PUBLICATION_STYLE
import matplotlib as _merak_mpl
from cycler import cycler as _merak_cycler
_merak_mpl.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 8,
    "axes.labelsize": 8,
    "axes.titlesize": 9,
    "axes.linewidth": 0.8,
    "axes.edgecolor": "#374151",
    "axes.labelcolor": "#111827",
    "axes.prop_cycle": _merak_cycler(color=["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9", "#222222"]),
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "xtick.color": "#374151",
    "ytick.color": "#374151",
    "legend.fontsize": 7,
    "legend.frameon": False,
    "axes.grid": False,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
    "savefig.dpi": 450,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})
"""
MERMAID_PUBLICATION_INIT = (
    '%%{init: {"theme": "base", "themeVariables": {'
    '"fontFamily": "Arial, Helvetica, sans-serif", "fontSize": "18px", '
    '"primaryColor": "#EDF2F7", "primaryTextColor": "#111827", '
    '"primaryBorderColor": "#334155", "lineColor": "#475569", '
    '"secondaryColor": "#E6F4F1", "tertiaryColor": "#FFF4D6", '
    '"clusterBkg": "#F8FAFC", "clusterBorder": "#94A3B8"}, '
    '"flowchart": {"curve": "basis", "htmlLabels": true}}}%%'
)


def _sha256_path(path: Path) -> str:
    """Hash figure inputs/variants without loading large result files in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_async_lock(path: str | Path) -> asyncio.Lock:
    """Return one event-loop-local lock for a canonical figure artifact.

    Stable semantic filenames are intentionally reused across revisions.  The
    lock prevents two agent sessions in the same server process from rendering
    and registering the same semantic artifact at the same time.  Manifest
    read-modify-write operations retain their separate cross-process lock.
    """

    loop = asyncio.get_running_loop()
    key = str(Path(path).expanduser().resolve()).replace("\\", "/").casefold()
    with _ARTIFACT_ASYNC_LOCKS_GUARD:
        locks = _ARTIFACT_ASYNC_LOCKS.setdefault(loop, {})
        return locks.setdefault(key, asyncio.Lock())


def _append_visual_review(
    review_path: Path,
    record: dict[str, Any],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Append one review without losing concurrent rounds for the same artifact."""

    with path_lock(review_path):
        try:
            loaded = json.loads(review_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            loaded = []
        rounds = [
            dict(item)
            for item in loaded
            if isinstance(item, dict)
        ] if isinstance(loaded, list) else []
        entry = dict(record)
        round_numbers: list[int] = []
        for item in rounds:
            try:
                round_numbers.append(int(item.get("round") or 0))
            except (TypeError, ValueError):
                continue
        entry["round"] = max(round_numbers, default=0) + 1
        rounds.append(entry)
        rounds = rounds[-max(1, int(limit)):]
        atomic_write_json(review_path, rounds)
        return [dict(item) for item in rounds]


def _semantic_figure_stem(
    description: str,
    figure_type: "FigureType",
    artifact_name: str = "",
    metadata: Optional[dict] = None,
) -> str:
    """Return a stable, readable filename instead of a random UUID."""
    metadata = dict(metadata or {})
    raw = str(artifact_name or metadata.get("semantic_key") or description or "")
    words = re.findall(r"[A-Za-z0-9]+", raw.lower())
    generic = {"figure", "generated", "academic", "research", "illustration", "drawio"}
    words = [word for word in words if word not in generic]
    if not words:
        role = str(metadata.get("scientific_role") or "research").lower()
        role = re.sub(r"[^a-z0-9]+", "_", role).strip("_") or "research"
        defaults = {
            "matplotlib": "result_plot",
            "figurespec": "method_architecture",
            "rich_svg": "method_architecture",
            "mermaid": "claim_evidence_workflow",
            "tikz": "method_diagram",
            "gpt_image": "qualitative_illustration",
            "nano_banana": "qualitative_illustration",
            "drawio": "method_architecture",
            "excalidraw": "method_architecture",
        }
        return f"{role}_{defaults.get(figure_type.value, 'figure')}"[:72]
    stem = "_".join(words[:10]).strip("_")
    if stem in {"plot", "diagram", "image", "workflow", "architecture"}:
        stem = f"{str(metadata.get('scientific_role') or 'research').lower()}_{stem}"
    return stem[:72] or f"research_{figure_type.value}"


def _external_renderers_enabled() -> bool:
    """External renderer CLIs are opt-in because browser child processes can stall on Windows."""
    return os.environ.get("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _candidate_electron_ports() -> list[int]:
    """Return explicit and discoverable IDE renderer ports in priority order.

    Electron may reuse an MERAK backend that was started before the desktop app.
    That process cannot inherit ``MERAK_ELECTRON_API_PORT`` retroactively even
    though the renderer endpoint is live.  The desktop endpoint intentionally
    binds only to localhost and chooses from this small fixed range, so probing
    it is both bounded and more reliable than treating a missing environment
    variable as a permanent renderer failure.
    """
    ports: list[int] = []
    explicit = os.environ.get("MERAK_ELECTRON_API_PORT", "").strip()
    try:
        explicit_port = int(explicit) if explicit else 0
    except ValueError:
        explicit_port = 0
    if 1 <= explicit_port <= 65535:
        ports.append(explicit_port)
    if os.environ.get("MERAK_DISABLE_ELECTRON_RENDERER_DISCOVERY", "").strip().lower() not in {
        "1", "true", "yes", "on",
    }:
        ports.extend(port for port in range(18765, 18785) if port not in ports)
    return ports


async def _render_mermaid_with_bundled_electron(
    code: str,
    output_path: str | Path,
) -> tuple[bool, str]:
    """Render Mermaid in a hidden one-shot Electron process."""
    root = Path(__file__).resolve().parents[2]
    output = Path(output_path).expanduser().resolve()
    electron_candidates = [
        Path(os.environ.get("MERAK_ELECTRON_EXECUTABLE", "")),
        root / "node_modules" / "electron" / "dist" / "electron.exe",
    ]
    discovered = shutil.which("electron")
    if discovered:
        electron_candidates.append(Path(discovered))
    electron = next(
        (candidate for candidate in electron_candidates if str(candidate) and candidate.is_file()),
        None,
    )
    script = root / "scripts" / "render-mermaid-electron.cjs"
    renderer_candidates = [
        Path(os.environ.get("MERAK_MERMAID_RENDERER", "")),
        root / "dist-electron" / "mermaid-renderer.js",
    ]
    renderer = next(
        (candidate for candidate in renderer_candidates if str(candidate) and candidate.is_file()),
        None,
    )
    if not electron or not script.is_file() or not renderer:
        return False, "Bundled one-shot Mermaid renderer is unavailable."
    env = os.environ.copy()
    env.pop("ELECTRON_RUN_AS_NODE", None)
    try:
        process = await run_process(
            [str(electron), str(script), str(output), str(renderer)],
            env=env,
            stdin=code.encode("utf-8"),
            timeout=45,
        )
    except Exception as exc:
        return False, f"Bundled one-shot Mermaid renderer failed: {exc}"
    if process.returncode == 0 and output.is_file() and output.stat().st_size > 0:
        return True, ""
    detail = (process.stderr or process.stdout or b"").decode(
        "utf-8", errors="replace"
    )[:1200]
    return False, f"Bundled one-shot Mermaid renderer failed: {detail}"


async def _render_mermaid_with_electron(code: str, output_path: str | Path) -> tuple[bool, str]:
    """Render Mermaid through the live IDE or its bundled one-shot fallback."""
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    requested_format = output.suffix.casefold().lstrip(".")
    if requested_format not in {"svg", "pdf", "png"}:
        requested_format = "svg"
    errors: list[str] = []
    electron_ports = _candidate_electron_ports()
    if electron_ports:
        try:
            import httpx

            timeout = httpx.Timeout(35.0, connect=0.5)
            async with httpx.AsyncClient(timeout=timeout) as client:
                for electron_port in electron_ports:
                    try:
                        response = await client.post(
                            f"http://127.0.0.1:{electron_port}/mermaid-export",
                            json={
                                "code": code,
                                "format": requested_format,
                            },
                        )
                        payload = response.json()
                        encoded = str(payload.get("data") or "")
                        if response.status_code == 200 and payload.get("success") and encoded:
                            rendered = base64.b64decode(encoded, validate=True)
                            if rendered:
                                atomic_write_bytes(output, rendered)
                                os.environ["MERAK_ELECTRON_API_PORT"] = str(electron_port)
                                return True, ""
                        errors.append(
                            f"{electron_port}: HTTP {response.status_code} {response.text[:120]}"
                        )
                    except Exception as exc:
                        errors.append(f"{electron_port}: {exc}")
        except Exception as exc:
            errors.append(str(exc))
    rendered, fallback_error = await _render_mermaid_with_bundled_electron(
        code, output
    )
    if rendered:
        return True, ""
    errors.append(fallback_error)
    return False, "Electron Mermaid renderer failed: " + "; ".join(errors[-3:])


async def _render_drawio_with_electron(xml: str, output_path: str | Path) -> tuple[bool, str]:
    """Export Draw.io XML through the Electron integration."""
    electron_ports = _candidate_electron_ports()
    if not electron_ports:
        return False, "Electron Draw.io renderer is not available."
    errors: list[str] = []
    try:
        import httpx

        output = Path(output_path).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        requested_format = output.suffix.casefold().lstrip(".")
        if requested_format not in {"svg", "pdf", "png"}:
            requested_format = "svg"
        timeout = httpx.Timeout(40.0, connect=0.5)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for electron_port in electron_ports:
                try:
                    response = await client.post(
                        f"http://127.0.0.1:{electron_port}/drawio-export",
                        json={
                            "xml": xml,
                            "format": requested_format,
                        },
                    )
                    payload = response.json()
                    encoded = str(payload.get("data") or "")
                    if response.status_code == 200 and payload.get("success") and encoded:
                        rendered = base64.b64decode(encoded, validate=True)
                        if rendered:
                            atomic_write_bytes(output, rendered)
                            os.environ["MERAK_ELECTRON_API_PORT"] = str(electron_port)
                            return True, ""
                    errors.append(f"{electron_port}: HTTP {response.status_code} {response.text[:120]}")
                except Exception as exc:
                    errors.append(f"{electron_port}: {exc}")
        detail = "; ".join(errors[-3:])
        return False, f"Electron Draw.io renderer failed: {detail}"
    except Exception as exc:
        return False, f"Electron Draw.io renderer failed: {exc}"


async def _render_electron_variants(
    renderer,
    source: str,
    svg_path: str | Path,
    pdf_path: str | Path,
    png_path: str | Path,
) -> tuple[bool, str]:
    """Export each format in its native Electron path.

    Mermaid SVG commonly contains foreignObject HTML labels that PDF libraries
    cannot convert faithfully. Rendering each requested format in Chromium
    preserves the same scene while avoiding a lossy cross-renderer conversion.
    """
    for output in (svg_path, pdf_path, png_path):
        final_path = Path(output).expanduser().resolve()
        temporary = final_path.with_name(
            f".{final_path.name}.{os.getpid()}.{threading.get_ident()}"
            f".{time.time_ns()}.merak-part{final_path.suffix}"
        )
        temporary.unlink(missing_ok=True)
        rendered, error = await renderer(source, temporary)
        if not rendered:
            temporary.unlink(missing_ok=True)
            return False, error
        try:
            atomic_replace_file(temporary, final_path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            return False, f"Atomic figure variant commit failed: {exc}"
    return True, ""


def _load_figurespec_renderer() -> Any:
    """Load the canonical renderer shipped by the /figure-spec skill."""

    global _FIGURESPEC_RENDERER
    if _FIGURESPEC_RENDERER is not None:
        return _FIGURESPEC_RENDERER
    app_root = Path(__file__).resolve().parents[2]
    configured = os.environ.get("MERAK_FIGURESPEC_RENDERER", "").strip()
    skills_root = os.environ.get("MERAK_SKILLS_PATH", "").strip()
    candidates = [
        Path(configured) if configured else None,
        Path(skills_root) / "figure-spec" / "scripts" / "figure_renderer.py"
        if skills_root else None,
        app_root / "merak-skills" / "figure-spec" / "scripts" / "figure_renderer.py",
    ]
    renderer_path = next(
        (candidate for candidate in candidates if candidate and candidate.is_file()),
        None,
    )
    if renderer_path is None:
        raise RuntimeError(
            "Canonical figure-spec renderer is missing from merak-skills/figure-spec/scripts."
        )
    module_spec = importlib.util.spec_from_file_location(
        "merak_native_figurespec_renderer",
        renderer_path,
    )
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"Cannot load FigureSpec renderer: {renderer_path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    _FIGURESPEC_RENDERER = module
    return module


def _find_tool(*names: str) -> Optional[str]:
    """查找工具路径：PATH → MERAK_TOOLS_DIR（安装包携带）→ drawio-path.txt"""
    for name in names:
        p = shutil.which(name)
        if p:
            return p

    # 安装包携带路径：由 Electron 主进程通过 MERAK_TOOLS_DIR 环境变量告知
    tools_dir = os.environ.get("MERAK_TOOLS_DIR", "")
    if tools_dir:
        tools_path = Path(tools_dir)
        for name in names:
            for suffix in ("", ".cmd", ".exe"):
                candidate = tools_path / "node_modules" / ".bin" / (name + suffix)
                if candidate.exists():
                    return str(candidate)
        # drawio desktop 路径由 install-tools.js 写入
        drawio_txt = tools_path / "drawio-path.txt"
        if drawio_txt.exists() and any(n in ("drawio", "draw.io") for n in names):
            p = drawio_txt.read_text(encoding="utf-8").strip()
            if p and Path(p).exists():
                return p

    return None


INSTALL_HINT = {
    "mmdc": (
        "Mermaid CLI 未安装。\n"
        "安装方法: npm install -g @mermaid-js/mermaid-cli\n"
        "或: npx -y @mermaid-js/mermaid-cli\n"
        "（Merak 安装包会自动携带，无需手动安装）"
    ),
    "drawio": (
        "Draw.io PNG 导出失败（仅保存了可编辑的 .drawio 源文件）。\n"
        "Merak 内置了基于 Electron 的 Draw.io 导出，通常无需额外安装。\n"
        "若此提示出现，请确认 Merak 主进程已启动。"
    ),
}


class FigureEngine:
    """画图引擎"""

    def _resolve_figure_type(
        self,
        description: str,
        figure_type: Optional[FigureType],
        metadata: Optional[dict],
    ) -> FigureType:
        if figure_type:
            return figure_type
        routed_backend = str(dict(metadata or {}).get("recommended_backend") or "")
        if routed_backend:
            try:
                return FigureType(routed_backend)
            except ValueError:
                pass
        return self._detect_type(description)

    async def generate(
        self,
        description: str,
        figure_type: Optional[FigureType] = None,
        output_dir: str = "./figures",
        style: str = "academic",
        code: str = "",
        image_size: str = "1024x1024",
        image_quality: str = "high",
        metadata: Optional[dict] = None,
        artifact_name: str = "",
    ) -> FigureResult:
        """Serialize generation of one stable semantic artifact.

        Figure sessions deliberately reuse readable semantic filenames.  A
        per-artifact async lock therefore covers reuse lookup, rendering, and
        manifest registration as one local transaction.  Different semantic
        figures can still render concurrently.
        """

        resolved_type = self._resolve_figure_type(
            description,
            figure_type,
            metadata,
        )
        semantic_key = _semantic_figure_stem(
            description,
            resolved_type,
            artifact_name,
            dict(metadata or {}),
        )
        generation_key = (
            Path(output_dir).expanduser().resolve()
            / f".{semantic_key}.generation"
        )
        async with _artifact_async_lock(generation_key):
            return await self._generate_serialized(
                description=description,
                figure_type=resolved_type,
                output_dir=output_dir,
                style=style,
                code=code,
                image_size=image_size,
                image_quality=image_quality,
                metadata=metadata,
                artifact_name=artifact_name,
            )

    async def _generate_serialized(
        self,
        description: str,
        figure_type: FigureType,
        output_dir: str = "./figures",
        style: str = "academic",
        code: str = "",
        image_size: str = "1024x1024",
        image_quality: str = "high",
        metadata: Optional[dict] = None,
        artifact_name: str = "",
    ) -> FigureResult:
        return await generate_serialized(
            self, description, figure_type, output_dir, style, code,
            image_size, image_quality, metadata, artifact_name,
            semantic_stem=_semantic_figure_stem,
            sha256_path=_sha256_path,
        )

    def _finalize_result(
        self,
        result: FigureResult,
        description: str,
        output_dir: str,
        metadata: dict,
    ) -> FigureResult:
        return finalize_figure_result(
            result, description, output_dir, metadata, sha256_path=_sha256_path,
        )

    async def refresh_editable_source(
        self,
        source_path: str | Path,
        *,
        metadata_override: Optional[dict] = None,
        description_override: str = "",
    ) -> dict:
        """Serialize refreshes with generation for the same semantic stem."""

        source = Path(source_path).expanduser().resolve()
        generation_key = source.parent / f".{source.stem}.generation"
        async with _artifact_async_lock(generation_key):
            return await self._refresh_editable_source_serialized(
                source,
                metadata_override=metadata_override,
                description_override=description_override,
            )

    async def _refresh_editable_source_serialized(
        self,
        source_path: str | Path,
        *,
        metadata_override: Optional[dict] = None,
        description_override: str = "",
    ) -> dict:
        from .figure_source_refresh import refresh_editable_source

        async def render_mermaid(
            code: str, svg: Path, pdf: Path, png: Path,
        ) -> tuple[bool, str]:
            return await _render_electron_variants(
                _render_mermaid_with_electron, code, svg, pdf, png,
            )

        async def render_drawio(
            code: str, svg: Path, pdf: Path, png: Path,
        ) -> tuple[bool, str]:
            return await _render_electron_variants(
                _render_drawio_with_electron, code, svg, pdf, png,
            )

        return await refresh_editable_source(
            self, source_path,
            metadata_override=metadata_override,
            description_override=description_override,
            render_mermaid=render_mermaid,
            render_drawio=render_drawio,
            sha256_path=_sha256_path,
        )

    @staticmethod
    def _detect_type(description: str) -> FigureType:
        from .figure_type_detection import detect_figure_type

        return detect_figure_type(description)

    async def _generate_matplotlib(
        self,
        description: str,
        output_dir: str,
        style: str,
        code: str = "",
        artifact_stem: str = "result_plot",
    ) -> FigureResult:
        return await generate_matplotlib(
            description, output_dir, style, code, artifact_stem,
            preamble=MATPLOTLIB_STYLE_PREAMBLE, run_process=run_process,
        )

    async def _generate_rich_svg(
        self,
        code: str,
        output_dir: str = "./figures/diagrams",
        artifact_stem: str = "method_architecture",
        metadata: Optional[dict] = None,
    ) -> FigureResult:
        def normalize_svg(value: str) -> str:
            if (
                isinstance(metadata, dict)
                and metadata.get("production_strategy") == "model_composed_full_svg"
            ):
                # The reviewed full-canvas source is canonical.  Renderer-only
                # compatibility transforms happen inside variant conversion;
                # never rewrite the editable SVG that the model and reviewer saw.
                return value
            return _raise_svg_connectors(
                _inline_svg_vector_class_styles(
                    _normalize_svg_marker_viewports(value)
                )
            )

        return await generate_rich_svg(
            code, output_dir, artifact_stem, metadata,
            normalize_svg=normalize_svg,
            convert_variants=_convert_svg_variants,
            append_review=_append_visual_review,
            sha256_path=_sha256_path,
        )

    async def _generate_figurespec(
        self,
        code: str,
        output_dir: str = "./figures/diagrams",
        artifact_stem: str = "method_architecture",
        metadata: Optional[dict] = None,
    ) -> FigureResult:
        return await generate_figurespec(
            code, output_dir, artifact_stem, metadata,
            load_renderer=_load_figurespec_renderer,
            convert_variants=_convert_svg_variants,
            append_review=_append_visual_review,
        )

    async def _generate_mermaid(
        self,
        description: str,
        output_dir: str = "./figures/diagrams",
        artifact_stem: str = "claim_evidence_workflow",
    ) -> FigureResult:
        return await generate_mermaid(
            description, output_dir, artifact_stem,
            init=MERMAID_PUBLICATION_INIT,
            render_variants=_render_electron_variants,
            render_electron=_render_mermaid_with_electron,
            external_enabled=_external_renderers_enabled,
            find_tool=_find_tool,
            run_process=run_process,
            unavailable=_UNAVAILABLE_TOOLS,
            install_hint=INSTALL_HINT["mmdc"],
        )

    async def _generate_tikz(
        self,
        description: str,
        output_dir: str,
        artifact_stem: str = "method_diagram",
    ) -> FigureResult:
        return await generate_tikz(
            description, output_dir, artifact_stem, run_process=run_process,
        )

    @staticmethod
    def _build_tikz_from_description(description: str) -> str:
        if "\\begin{tikzpicture}" not in description:
            raise ValueError(
                "Complete tikzpicture source is required; generic templates are disabled."
            )
        return description

    async def _generate_gpt_image(
        self,
        description: str,
        output_dir: str,
        *,
        size: str,
        quality: str,
        artifact_stem: str = "qualitative_illustration",
    ) -> FigureResult:
        return await generate_gpt_image(
            description, output_dir, size=size, quality=quality,
            artifact_stem=artifact_stem,
        )

    async def _generate_nano_banana(
        self,
        description: str,
        output_dir: str,
        *,
        artifact_stem: str = "qualitative_illustration",
        metadata: Optional[dict] = None,
    ) -> FigureResult:
        return await generate_nano_banana(
            description, output_dir, artifact_stem=artifact_stem,
            metadata=metadata,
        )

    async def _generate_excalidraw(
        self,
        code: str,
        output_dir: str = "./figures/diagrams",
        artifact_stem: str = "method_architecture",
        metadata: Optional[dict] = None,
        *,
        enforce_mappings: bool = True,
    ) -> FigureResult:
        return await generate_excalidraw(
            code, output_dir, artifact_stem, metadata,
            enforce_mappings=enforce_mappings,
            append_review=_append_visual_review,
        )

    async def _generate_drawio(
        self,
        description: str,
        output_dir: str = "./figures/diagrams",
        artifact_stem: str = "method_architecture",
    ) -> FigureResult:
        from .figure_artifacts import figure_artifact_registry

        return await generate_drawio(
            description, output_dir, artifact_stem,
            registry=figure_artifact_registry,
            render_electron=_render_drawio_with_electron,
            convert_variants=_convert_svg_variants,
            external_enabled=_external_renderers_enabled,
            find_tool=_find_tool,
            run_process=run_process,
            unavailable=_UNAVAILABLE_TOOLS,
            install_hint=INSTALL_HINT["drawio"],
        )


# 全局实例
figure_engine = FigureEngine()
