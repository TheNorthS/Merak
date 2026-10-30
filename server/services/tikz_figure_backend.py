"""Persist and optionally compile an explicitly authored TikZ figure."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

import structlog

from ..utils.atomic_write import atomic_write_bytes, atomic_write_text
from .figure_models import FigureResult, FigureType


logger = structlog.get_logger()


def _document(body: str) -> str:
    return f"""\\documentclass[border=5pt]{{standalone}}
\\usepackage{{tikz}}
\\usetikzlibrary{{arrows.meta,positioning,shapes,calc,decorations.pathreplacing}}
\\usepackage{{amsmath}}

\\begin{{document}}
{body}
\\end{{document}}
"""


async def _compile(
    latex: str, directory: Path, filename: str, run_process: Any,
) -> str | None:
    compiler = shutil.which("pdflatex") or shutil.which("xelatex")
    if not compiler:
        return None
    try:
        with tempfile.TemporaryDirectory() as temporary:
            tex = Path(temporary) / f"{filename}.tex"
            tex.write_text(latex, encoding="utf-8")
            await run_process([
                compiler, "-interaction=nonstopmode", "-halt-on-error", str(tex),
            ], cwd=temporary, timeout=30)
            pdf = Path(temporary) / f"{filename}.pdf"
            if pdf.is_file() and pdf.stat().st_size > 0:
                output = directory / f"{filename}.pdf"
                atomic_write_bytes(output, pdf.read_bytes())
                return str(output)
    except Exception as exc:
        logger.debug("TikZ compilation failed", error=str(exc))
    return None


async def generate_tikz(
    code: str, output_dir: str, artifact_stem: str, *, run_process: Any,
) -> FigureResult:
    if "\\begin{tikzpicture}" not in code or "\\end{tikzpicture}" not in code:
        return FigureResult(
            False, FigureType.TIKZ,
            error=(
                "TikZ generation requires complete tikzpicture source grounded in "
                "the project; MERAK will not substitute a generic diagram template."
            ),
        )
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / f"{artifact_stem}.tex"
    latex = _document(code)
    atomic_write_text(source, latex)
    output = await _compile(latex, directory, artifact_stem, run_process)
    return FigureResult(
        True, FigureType.TIKZ, output_path=output,
        source_path=str(source), code=code,
    )
