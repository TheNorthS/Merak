"""Hard publication-layout gate over the freshly compiled manuscript PDF."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import json

from ..utils.atomic_write import atomic_write_json


def pdf_quality_implementation_signature() -> str:
    from ..utils.runtime_source_root import server_source_root
    root = server_source_root() / 'services'
    digest = hashlib.sha256()
    for name in ('paper_pdf_quality.py', 'pdf_review_inspection.py', 'pdf_overlap_pixels.py', 'publication_pdf_fonts.py',
                 'paper_layout_attribution.py', 'paper_print_projection.py'):
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def pdf_layout_issues(layout: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    pages = [item for item in layout.get("pages") or [] if isinstance(item, dict)]
    if not pages:
        return ['publication PDF geometry inspection produced no verified pages']
    page_count = len(pages)
    for index, page in enumerate(pages, start=1):
        number = int(page.get("page") or index)
        minimum = float(page.get('minimum_readable_font_pt', page.get("minimum_font_pt")) or 0.0)
        visible = int(page.get("visible_text_chars") or 0)
        findings = [str(item) for item in page.get("possible_layout_findings") or []]
        if visible >= 30 and minimum and minimum < 8.0:
            issues.append(f"page {number} has publication text below 8.0 pt ({minimum:.1f} pt)")
        for finding in findings:
            lowered = finding.casefold()
            if any(marker in lowered for marker in (
                "overlapping text-block", "physical page edge", "orphaned heading",
            )):
                issues.append(f"page {number}: {finding}")
            if "blank or nearly blank" in lowered and number not in {1, page_count}:
                issues.append(f"page {number}: {finding}")
    issues.extend(str(item) for item in layout.get("document_findings") or [])
    return list(dict.fromkeys(issues))


def inspect_compiled_paper(
    compiler: Any, project_root: str | Path, pdf_path: str | Path,
) -> tuple[dict[str, Any], list[str]]:
    root = Path(project_root).expanduser().resolve()
    report = compiler.inspect_pdf_for_review(
        pdf_path, preview_dir=root / ".merak/quality/paper-previews",
    )
    issues = pdf_layout_issues(report)
    from .latex_bundle import latex_source_bundle
    source_hash, _ = latex_source_bundle(root / 'paper')
    from .paper_layout_attribution import layout_repair_findings
    repairs = layout_repair_findings(root, issues, '.merak/quality/paper-layout.json', layout=report)
    atomic_write_json(root / ".merak/quality/paper-layout.json", {
        "schema": 1, "pdf_path": str(Path(pdf_path).resolve()),
        'pdf_sha256': hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest(),
        'source_bundle_sha256': source_hash,
        'inspection_implementation_sha256': pdf_quality_implementation_signature(),
        "accepted": not issues, "issues": issues, "layout": report,
        'repair_findings': repairs,
    })
    return report, issues


def validate_persisted_pdf_quality(project_root: str | Path) -> list[str]:
    """Accept only a fresh passing layout report bound to current PDF and sources."""
    root = Path(project_root).resolve()
    report_path = root / '.merak/quality/paper-layout.json'
    pdf = root / 'paper/main.pdf'
    try:
        payload = json.loads(report_path.read_text(encoding='utf-8-sig'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ['compiled-paper publication layout report is missing or invalid']
    if not isinstance(payload, dict) or payload.get('schema') != 1:
        return ['compiled-paper publication layout report schema is unsupported']
    if payload.get('inspection_implementation_sha256') != pdf_quality_implementation_signature():
        return ['publication layout report requires inspection under the current validator']
    from .paper_print_projection import validate_print_projection
    projection_issues = validate_print_projection(root)
    if projection_issues:
        return projection_issues
    if not pdf.is_file():
        return ['compiled manuscript PDF is missing']
    from .latex_bundle import latex_source_bundle
    source_hash, _ = latex_source_bundle(root / 'paper')
    if payload.get('source_bundle_sha256') != source_hash:
        return ['publication layout report is stale for the current manuscript sources']
    if payload.get('pdf_sha256') != hashlib.sha256(pdf.read_bytes()).hexdigest():
        return ['publication layout report is stale for the current manuscript PDF']
    issues = pdf_layout_issues(payload.get('layout') or {})
    if payload.get('accepted') is not True or issues:
        return issues or ['compiled manuscript publication layout was not accepted']
    return []
