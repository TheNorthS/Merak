"""Read-only validation for the compiled manuscript build record."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def paper_build_issues(
    root: Path,
    paper_build: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    from .latex_bundle import latex_source_bundle

    issues: list[str] = []
    compile_record = paper_build.get("compile")
    compile_record = compile_record if isinstance(compile_record, dict) else {}
    source_hash, source_paths = latex_source_bundle(root / "paper")
    pdf_path = root / "paper" / "main.pdf"
    expected_source_hash = str(compile_record.get("source_bundle_sha256") or "")
    expected_pdf_hash = str(compile_record.get("pdf_sha256") or "")
    if compile_record.get("success") is not True:
        issues.append("paper build does not record a successful compile")
    if not source_paths:
        issues.append("paper build has no current LaTeX source bundle")
    elif not expected_source_hash:
        issues.append("paper build is missing its source bundle hash")
    elif expected_source_hash != source_hash:
        issues.append("paper build is stale relative to current LaTeX sources")
    pdf_is_current = (
        pdf_path.is_file()
        and pdf_path.stat().st_size > 0
        and pdf_path.read_bytes()[:5] == b"%PDF-"
    )
    current_pdf_hash = ""
    if not pdf_is_current:
        issues.append("compiled paper/main.pdf is missing, empty, or invalid")
    else:
        current_pdf_hash = _sha256(pdf_path)
        if not expected_pdf_hash:
            issues.append("paper build is missing its PDF hash")
        elif expected_pdf_hash != current_pdf_hash:
            issues.append("paper/main.pdf does not match PAPER_BUILD.json")
    return issues, {
        "source_bundle_sha256": source_hash,
        "pdf_sha256": current_pdf_hash,
        "source_count": len(source_paths),
    }
