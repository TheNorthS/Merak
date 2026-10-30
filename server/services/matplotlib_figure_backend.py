"""Execute a project-grounded Matplotlib source and adopt its fresh variants."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..utils.atomic_write import atomic_write_text
from .figure_models import FigureResult, FigureType


ProcessRunner = Callable[..., Awaitable[Any]]


def _paths(output_dir: str, stem: str) -> tuple[Path, Path, Path, Path, Path]:
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return (
        directory,
        directory / f"{stem}.py",
        directory / f"{stem}.pdf",
        directory / f"{stem}.svg",
        directory / f"{stem}.png",
    )


def _executable_code(
    code: str, preamble: str, pdf: Path, svg: Path, png: Path,
) -> str:
    value = code.rstrip()
    if "# MERAK_PUBLICATION_STYLE" not in value:
        lines = value.splitlines()
        insertion = 0
        while insertion < len(lines) and lines[insertion].startswith("from __future__ import"):
            insertion += 1
        lines[insertion:insertion] = [preamble.rstrip(), ""]
        value = "\n".join(lines)
    saved = bool(
        re.search(r"\b(?:plt|fig)\.savefig\s*\(", value)
        or re.search(r"\b(?:save_all|save_figure|save_plot|export_figure)\s*\(", value)
    )
    if not saved:
        value += (
            f'\nplt.tight_layout()\nplt.savefig(r"{pdf}", bbox_inches="tight")'
            f'\nplt.savefig(r"{svg}", bbox_inches="tight")'
            f'\nplt.savefig(r"{png}", dpi=450, bbox_inches="tight")'
            "\nplt.close()\n"
        )
    return value


def _fresh_candidates(directory: Path, started_at: float) -> list[Path]:
    candidates: list[Path] = []
    for suffix in (".pdf", ".png", ".jpg", ".jpeg", ".svg"):
        candidates.extend(
            path for path in directory.glob(f"*{suffix}")
            if path.is_file() and path.stat().st_size > 0
            and path.stat().st_mtime >= started_at - 1.0
        )
    return candidates


def _success_result(
    actual: Path, source: Path, pdf: Path, svg: Path, png: Path,
    directory: Path, stem: str, code: str,
) -> FigureResult:
    desired = directory / f"{stem}{actual.suffix.lower()}"
    if actual.resolve() != desired.resolve():
        desired.unlink(missing_ok=True)
        actual.replace(desired)
        actual = desired
    variants = {"py": str(source)}
    for name, candidate in (("pdf", pdf), ("svg", svg), ("png", png)):
        if candidate.is_file() and candidate.stat().st_size > 0:
            variants[name] = str(candidate)
    variants.setdefault(actual.suffix.lower().lstrip("."), str(actual))
    return FigureResult(
        True, FigureType.MATPLOTLIB, output_path=str(actual),
        source_path=str(source), code=code,
        metadata={"renderer": "matplotlib-python", "_rendered_variant_paths": variants},
    )


async def generate_matplotlib(
    description: str, output_dir: str, style: str, code: str,
    artifact_stem: str, *, preamble: str, run_process: ProcessRunner,
) -> FigureResult:
    del description, style
    if not code.strip():
        return FigureResult(
            False, FigureType.MATPLOTLIB,
            error="Matplotlib figures require executable code backed by project data; MERAK will not fabricate sample metrics.",
        )
    from .figure_artifacts import figure_artifact_registry
    from .backend_python_command import local_figure_script_command

    directory, source, pdf, svg, png = _paths(output_dir, artifact_stem)
    started_at = time.time()
    executable = _executable_code(code, preamble, pdf, svg, png)
    atomic_write_text(source, executable + "\n")
    environment = os.environ.copy()
    environment.setdefault("MPLBACKEND", "Agg")
    try:
        process = await run_process(
            local_figure_script_command(source),
            cwd=str(figure_artifact_registry.project_root(directory)),
            env=environment, timeout=90,
        )
    except TimeoutError:
        return FigureResult(
            False, FigureType.MATPLOTLIB, source_path=str(source), code=executable,
            error="Python figure process timed out after 90 seconds.",
        )
    except Exception as exc:
        return FigureResult(
            False, FigureType.MATPLOTLIB, source_path=str(source),
            code=executable, error=str(exc),
        )
    candidates = _fresh_candidates(directory, started_at)
    actual = pdf if pdf.is_file() and pdf.stat().st_size > 0 else (
        max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None
    )
    if process.returncode == 0 and actual:
        return _success_result(actual, source, pdf, svg, png, directory, artifact_stem, executable)
    stderr, stdout = process.stderr or b"", process.stdout or b""
    error = stderr.decode("utf-8", errors="replace") or stdout.decode("utf-8", errors="replace")
    if process.returncode == 0:
        error = "Python figure code completed but produced no PDF/PNG/SVG in the requested output directory."
    return FigureResult(
        False, FigureType.MATPLOTLIB, source_path=str(source), code=executable,
        error=error,
    )
