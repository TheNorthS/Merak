"""Faithful Mermaid and Draw.io source/render backends."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from ..utils.atomic_write import atomic_write_text
from .figure_models import FigureResult, FigureType


def _compact_evaluation_mermaid(code: str) -> str:
    code = re.sub(r"^\s*topSpacer\[[^\n]*\]\s*\n", "", code, flags=re.MULTILINE)
    code = re.sub(r"^\s*topSpacer\s*[-.=]+>[^\n]*\n", "", code, flags=re.MULTILINE)
    for pattern, replacement in (
        (r"padding\s*:\s*240", "padding:18"),
        (r"nodeSpacing\s*:\s*54", "nodeSpacing:28"),
        (r"rankSpacing\s*:\s*78", "rankSpacing:44"),
        (r"useMaxWidth\s*:\s*false", "useMaxWidth:true"),
        (r"fontSize\s*:\s*'14px'", "fontSize:'20px'"),
    ):
        code = re.sub(pattern, replacement, code)
    return code


def _mermaid_source(description: str, artifact_stem: str, init: str) -> str:
    code = description.strip()
    if artifact_stem == "evaluation_design":
        code = _compact_evaluation_mermaid(code)
    without_init = re.sub(
        r"^\s*%%\{.*?\}%%\s*", "", code, count=1, flags=re.DOTALL,
    )
    valid = re.match(
        r"^(?:graph|flowchart|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|"
        r"erDiagram|gantt|pie|mindmap|timeline|quadrantChart|xychart)\b",
        without_init, flags=re.IGNORECASE,
    )
    if not valid:
        raise ValueError(
            "Mermaid generation requires complete Mermaid source code. A prose "
            "description cannot be converted without risking an unrelated template."
        )
    return code if code.lstrip().startswith("%%{init:") else init + "\n" + code


def _pad_preview(path: Path) -> None:
    try:
        with Image.open(path) as opened:
            preview = opened.convert("RGB")
        inset = max(48, round(min(preview.size) * 0.035))
        ImageOps.expand(preview, border=inset, fill="#FFFFFF").save(
            path, format="PNG", optimize=True,
        )
    except OSError:
        pass


async def _mermaid_cli(
    tool: str, source: Path, output: Path, run_process: Any,
    unavailable: set[str], electron_error: str,
) -> tuple[str | None, str]:
    try:
        process = await run_process([
            tool, "-i", str(source), "-o", str(output),
            "-t", "neutral", "-w", "1600",
        ], timeout=15)
        stderr = process.stderr or b""
        if process.returncode == 0 and output.is_file() and output.stat().st_size > 0:
            return str(output), "Rendered with Mermaid CLI using the neutral research theme."
        unavailable.add("mmdc")
        return None, f"{electron_error} Mermaid CLI failed: {stderr.decode('utf-8', errors='replace')[:240]}"
    except TimeoutError:
        unavailable.add("mmdc")
        return None, f"{electron_error} Mermaid CLI timed out after 15s."
    except Exception as exc:
        unavailable.add("mmdc")
        return None, f"{electron_error} Mermaid CLI unavailable: {exc}"


async def generate_mermaid(
    description: str, output_dir: str, artifact_stem: str, *, init: str,
    render_variants: Any, render_electron: Any, external_enabled: Any,
    find_tool: Any, run_process: Any, unavailable: set[str], install_hint: str,
) -> FigureResult:
    try:
        code = _mermaid_source(description, artifact_stem, init)
    except ValueError as exc:
        return FigureResult(False, FigureType.MERMAID, error=str(exc))
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / f"{artifact_stem}.mmd"
    svg, pdf, png = (directory / f"{artifact_stem}{suffix}" for suffix in (".svg", ".pdf", ".png"))
    atomic_write_text(source, code)
    for path in (svg, pdf, png):
        path.unlink(missing_ok=True)
    variants = {"mmd": str(source)}
    rendered, electron_error = await render_variants(render_electron, code, svg, pdf, png)
    output: str | None = None
    hint = electron_error
    if rendered:
        _pad_preview(png)
        variants.update({"svg": str(svg), "pdf": str(pdf), "png": str(png)})
        output = str(pdf)
        hint = "SVG, PDF, and PNG were exported natively from the same Electron-bundled Mermaid scene."
    external = external_enabled()
    tool = find_tool("mmdc") if external else None
    if not output and tool and "mmdc" not in unavailable:
        output, hint = await _mermaid_cli(
            tool, source, png, run_process, unavailable, electron_error,
        )
        if output:
            variants["png"] = output
    elif not output and external and not tool:
        hint = f"{electron_error} {install_hint}"
    return FigureResult(
        True, FigureType.MERMAID, output_path=output, source_path=str(source),
        code=code, install_hint=hint,
        metadata={
            "renderer": "electron-bundled-mermaid" if rendered else (
                "mermaid-cli" if output else "unavailable"
            ),
            "source_faithful": "same-source-geometry-style-and-labels",
            "_rendered_variant_paths": variants,
        },
    )


async def _drawio_cli(
    tool: str, source: Path, output: Path, run_process: Any, unavailable: set[str],
) -> tuple[str | None, str]:
    try:
        process = await run_process([
            tool, "--export", "--format", "png", "--output", str(output),
            "--no-sandbox", str(source),
        ], timeout=20)
        stderr = process.stderr or b""
        if process.returncode == 0 and output.is_file() and output.stat().st_size > 0:
            return str(output), ""
        unavailable.add("drawio")
        return None, (
            "Draw.io CLI failed; editable source retained and no degraded preview was created. "
            + stderr.decode("utf-8", errors="replace")[:240]
        )
    except TimeoutError:
        unavailable.add("drawio")
        return None, "Draw.io CLI timed out after 20s; editable source retained and no degraded preview was created."
    except Exception as exc:
        unavailable.add("drawio")
        return None, f"Draw.io CLI unavailable; editable source retained and no degraded preview was created. {exc}"


def _drawio_result(
    success: bool, output: str | None, source: Path, xml: str,
    hint: str, rendered: bool, adjustments: Any, variants: dict[str, str],
) -> FigureResult:
    metadata = {
        "renderer": "electron-bundled-drawio" if rendered else (
            "drawio-cli" if output else "unavailable"
        ),
        "source_faithful": "same-source-geometry-style-and-labels",
        "layout_autofit_adjustments": adjustments,
        "_rendered_variant_paths": variants,
    }
    return FigureResult(
        success, FigureType.DRAWIO, output_path=output, source_path=str(source),
        code=xml, install_hint=hint if success else None,
        error=None if success else hint or "Draw.io rendering did not produce the required SVG/PDF/PNG variants.",
        metadata=metadata,
    )


async def generate_drawio(
    description: str, output_dir: str, artifact_stem: str, *, registry: Any,
    render_electron: Any, convert_variants: Any, external_enabled: Any,
    find_tool: Any, run_process: Any, unavailable: set[str], install_hint: str,
) -> FigureResult:
    if not description.strip().startswith(("<?xml", "<mxfile")):
        return FigureResult(
            False, FigureType.DRAWIO,
            error="Draw.io generation requires complete mxfile XML; prose cannot define its components.",
        )
    xml, adjustments = registry.autofit_drawio_text(description.strip())
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / f"{artifact_stem}.drawio"
    svg, pdf, png = (directory / f"{artifact_stem}{suffix}" for suffix in (".svg", ".pdf", ".png"))
    atomic_write_text(source, xml)
    for path in (svg, pdf, png):
        path.unlink(missing_ok=True)
    variants = {"drawio": str(source)}
    rendered, electron_error = await render_electron(xml, svg)
    output: str | None = None
    hint = ""
    if rendered:
        converted, hint = convert_variants(svg, pdf, png)
        variants["svg"] = str(svg)
        if converted:
            variants.update({"pdf": str(pdf), "png": str(png)})
            output = str(pdf)
        else:
            output = str(svg)
    if not output:
        external = external_enabled()
        tool = find_tool("drawio", "draw.io") if external else None
        if tool and "drawio" not in unavailable:
            output, hint = await _drawio_cli(tool, source, png, run_process, unavailable)
            if output:
                variants["png"] = output
        elif not external:
            hint = "External Draw.io CLI rendering is disabled; editable source retained and no degraded preview was created."
        elif not tool:
            hint = install_hint
        else:
            hint = "Draw.io CLI disabled after an earlier failure; editable source retained and no degraded preview was created."
    complete = all(path.is_file() and path.stat().st_size > 0 for path in (svg, pdf, png))
    if not complete and not hint:
        hint = electron_error
    return _drawio_result(
        complete, output, source, xml, hint, rendered, adjustments, variants,
    )
