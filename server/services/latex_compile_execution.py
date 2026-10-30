"""Bounded execution transaction for one LaTeX manuscript build."""

from __future__ import annotations

import subprocess
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol


class CompilePort(Protocol):
    def _compile_lock_for(self, project_path: Path): ...
    def repair_bibliography_text_fields(self, project_dir: str | Path) -> list[dict[str, object]]: ...
    async def _run_command(self, command: list[str], *, cwd: str | None = None, timeout: int, stderr: int = subprocess.STDOUT): ...
    def _decode_process_output(self, value: bytes | None) -> str: ...
    def _parse_errors(self, log: str) -> list[Any]: ...
    def _parse_warnings(self, log: str) -> list[Any]: ...
    async def _get_page_count(self, pdf_path: str) -> int: ...


def _elapsed_ms(start: datetime) -> int:
    return int((datetime.utcnow() - start).total_seconds() * 1000)


def _resolve_tex(project_dir: str, main_tex: str) -> tuple[Path, Path, str | None]:
    project = Path(project_dir).expanduser().resolve()
    tex = (project / main_tex).resolve()
    try:
        tex.relative_to(project)
    except ValueError:
        return project, tex, "Main TeX file must stay inside the paper project directory"
    if not tex.is_file():
        return project, tex, "Main TeX file not found"
    return project, tex, None


def _clear_stale_bibliography(
    compiler: CompilePort, project: Path, main_tex: str,
) -> list[dict[str, object]]:
    repairs = compiler.repair_bibliography_text_fields(project)
    stem = Path(main_tex).stem
    bbl = project / f"{stem}.bbl"
    changed = bool(repairs)
    if bbl.is_file():
        changed = changed or any(
            path.stat().st_mtime > bbl.stat().st_mtime
            for path in project.glob("*.bib") if path.is_file()
        )
    if changed:
        for suffix in (".bbl", ".blg"):
            (project / f"{stem}{suffix}").unlink(missing_ok=True)
    return repairs


def _compile_command(project: Path, tex: Path) -> list[str]:
    content = tex.read_text(encoding="utf-8", errors="replace")
    mode = "-xelatex" if "ctex" in content or any(ord(char) > 127 for char in content) else "-pdf"
    return [
        "latexmk", mode, "-interaction=nonstopmode", "-halt-on-error",
        "-file-line-error", f"-outdir={project}", str(tex),
    ]


async def _clean_if_requested(
    compiler: CompilePort, project_dir: str, project: Path, tex: Path,
    main_tex: str, clean: bool, start: datetime, repairs: list[dict[str, object]],
    result_type: Any, error_type: Any,
) -> Any | None:
    if not clean:
        return None
    command = ["latexmk", "-C", f"-outdir={project}", str(tex)]
    try:
        result = await compiler._run_command(command, cwd=project_dir, timeout=30)
    except subprocess.TimeoutExpired as exc:
        return result_type(
            success=False,
            errors=[error_type(main_tex, 0, "LaTeX cleanup timed out (30s)", "error")],
            log_output=compiler._decode_process_output(exc.output)[-5000:],
            compile_time_ms=_elapsed_ms(start), source_repairs=repairs,
        )
    if result.returncode == 0:
        return None
    return result_type(
        success=False,
        errors=[error_type(main_tex, 0, "LaTeX cleanup failed before compilation", "error")],
        log_output=compiler._decode_process_output(result.stdout)[-5000:],
        compile_time_ms=_elapsed_ms(start), source_repairs=repairs,
    )


def _final_log(project: Path, main_tex: str, fallback: str) -> str:
    path = project / Path(main_tex).with_suffix(".log")
    if not path.is_file():
        return fallback
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return fallback


async def _result_from_process(
    compiler: CompilePort, process: Any, project: Path, tex: Path,
    main_tex: str, start: datetime, repairs: list[dict[str, object]],
    result_type: Any,
) -> Any:
    log = compiler._decode_process_output(process.stdout)
    pdf = project / tex.with_suffix(".pdf").name
    if pdf.exists() and process.returncode == 0:
        pages = await compiler._get_page_count(str(pdf))
        warning_log = _final_log(project, main_tex, log)
        return result_type(
            success=True, pdf_path=str(pdf), warnings=compiler._parse_warnings(warning_log),
            log_output=log[-5000:], compile_time_ms=_elapsed_ms(start),
            pages=pages, source_repairs=repairs,
        )
    errors = compiler._parse_errors(log)
    final_log = _final_log(project, main_tex, "")
    if final_log:
        # TeX wraps long absolute paths; restore a split line number before
        # parsing so the source error is not hidden by latexmk's exit code.
        source_log = re.sub(r'(\.tex:\d+)\r?\n(\d+:)', r'\1\2', final_log)
        source_errors = compiler._parse_errors(source_log)
        errors = source_errors + [item for item in errors if not any(
            item.file == prior.file and item.line == prior.line and item.message == prior.message
            for prior in source_errors)]
        log = f"{log}\n{final_log[-5000:]}"
    return result_type(
        success=False, errors=errors, warnings=compiler._parse_warnings(log),
        log_output=log[-5000:], compile_time_ms=_elapsed_ms(start),
        source_repairs=repairs,
    )


async def _locked_compile(
    compiler: CompilePort, project_dir: str, project: Path, tex: Path,
    main_tex: str, clean: bool, start: datetime, result_type: Any, error_type: Any,
) -> Any:
    repairs: list[dict[str, object]] = []
    try:
        repairs = _clear_stale_bibliography(compiler, project, main_tex)
        clean_failure = await _clean_if_requested(
            compiler, project_dir, project, tex, main_tex, clean, start,
            repairs, result_type, error_type,
        )
        if clean_failure is not None:
            return clean_failure
        process = await compiler._run_command(
            _compile_command(project, tex), cwd=project_dir, timeout=120,
        )
        return await _result_from_process(
            compiler, process, project, tex, main_tex, start, repairs, result_type,
        )
    except subprocess.TimeoutExpired as exc:
        return result_type(
            success=False,
            errors=[error_type(main_tex, 0, "Compilation timed out (120s)", "error")],
            log_output=compiler._decode_process_output(exc.output)[-5000:],
            compile_time_ms=_elapsed_ms(start), source_repairs=repairs,
        )
    except FileNotFoundError:
        return result_type(
            success=False,
            errors=[error_type("", 0, "latexmk not found. Install TeX Live.", "error")],
            source_repairs=repairs,
        )
    except OSError as exc:
        return result_type(
            success=False,
            errors=[error_type(main_tex, 0, f"Local compiler process failed: {exc}", "error")],
            compile_time_ms=_elapsed_ms(start), source_repairs=repairs,
        )


async def compile_paper(
    compiler: CompilePort,
    result_type: Any,
    error_type: Any,
    project_dir: str,
    main_tex: str = "main.tex",
    clean: bool = False,
) -> Any:
    start = datetime.utcnow()
    project, tex, path_error = _resolve_tex(project_dir, main_tex)
    if path_error:
        return result_type(
            success=False,
            errors=[error_type(main_tex, 0, path_error, "error")],
        )
    async with compiler._compile_lock_for(project):
        return await _locked_compile(
            compiler, project_dir, project, tex, main_tex, clean,
            start, result_type, error_type,
        )
