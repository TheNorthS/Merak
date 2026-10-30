"""Attribute compiled-page layout defects to editable artifact producers."""

import json
import re
from pathlib import Path
from typing import Any


def _json_records(path: Path, key: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    return [dict(item) for item in payload.get(key) or []
            if isinstance(payload, dict) and isinstance(item, dict)]


def _page_labels(paper: Path) -> dict[int, list[str]]:
    labels: dict[int, list[str]] = {}
    for path in paper.rglob('*.aux'):
        try:
            text = path.read_text(encoding='utf-8-sig', errors='replace')
        except OSError:
            continue
        for match in re.finditer(r'\\newlabel\{(?P<label>[^}]+)\}\{\{.*?\}\{(?P<page>\d+)\}', text):
            labels.setdefault(int(match.group('page')), []).append(match.group('label'))
    return labels


def _figure_for_label(figures: list[dict[str, Any]], label: str) -> dict[str, Any] | None:
    for item in figures:
        metadata = item.get('metadata') if isinstance(item.get('metadata'), dict) else {}
        if str(item.get('label') or metadata.get('label') or '') == label:
            return item
    return None


def _table_for_label(tables: list[dict[str, Any]], label: str) -> dict[str, Any] | None:
    """A prose-note page belongs to the table producer owning its complete text."""
    for item in tables:
        if item.get('label') == label:
            return item
        projection = item.get('publication_projection')
        if not isinstance(projection, dict):
            continue
        if any(label == f"note:{note.get('note_id')}" for note in projection.get('notes') or []
               if isinstance(note, dict) and note.get('note_id')):
            return item
    return None


def layout_repair_findings(
    project_root: str | Path, issues: list[str], report_path: str,
    *, layout: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    root = Path(project_root).resolve()
    paper = root / 'paper'
    labels = _page_labels(paper)
    figures = _json_records(root / 'figures/FIGURE_MANIFEST.json', 'figures')
    tables = _json_records(paper / 'tables/TABLE_MANIFEST.json', 'tables')
    findings = []
    for index, issue in enumerate(issues, start=1):
        match = re.match(r'page\s+(\d+)[: ]', issue, re.I)
        page = int(match.group(1)) if match else 0
        page_labels = labels.get(page) or ['']
        if layout is not None:
            page_labels = _evidence_labels(root, page, issue, layout, figures, page_labels)
        for label in page_labels:
            figure = _figure_for_label(figures, label)
            table = _table_for_label(tables, label)
            if figure:
                source = str(figure.get('source_path') or figure.get('output_path') or '')
                target_files, owner, assets = ([source] if source else ['figures/FIGURE_MANIFEST.json']), 'figure', [str(figure.get('id') or '')]
            elif table:
                target_files, owner, assets = [str(table.get('latex_path') or 'paper/main.tex')], 'paper', [str(table.get('id') or '')]
            else:
                target_files, owner, assets = ['paper/main.tex'], 'paper', []
            findings.append({
                'id': f'PAPER-LAYOUT-{page or 0}-{index}-{owner.upper()}',
                'severity': 'blocker', 'category': 'visual_layout',
                'message': issue, 'plain_message': issue, 'owner_node': owner,
                'target_files': target_files, 'asset_ids': [item for item in assets if item],
                'page': page, 'label': label, 'layout_report_path': report_path,
                'location_evidence': _issue_evidence(page, layout),
                'remediation': ('Repair and re-render the attributed figure source.' if owner == 'figure'
                                else 'Repair the attributed LaTeX table or page layout.'),
            })
    return findings


def _issue_evidence(page: int, layout: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not layout:
        return []
    item = next((row for row in layout.get('pages') or [] if row.get('page') == page), {})
    return [row for row in item.get('readable_font_findings') or [] if isinstance(row, dict)]


def _evidence_labels(root: Path, page: int, issue: str, layout: dict[str, Any],
                     figures: list[dict[str, Any]], labels: list[str]) -> list[str]:
    """Page labels are candidates, never proof that a prose defect belongs to a figure."""
    evidence = _issue_evidence(page, layout)
    if 'below 8.0' not in issue or not evidence:
        return ['']
    matches: set[str] = set()
    for label in labels:
        entry = _figure_for_label(figures, label)
        if entry and _figure_text_matches(root, entry, evidence):
            matches.add(label)
    return sorted(matches) if len(matches) == 1 else ['']


def _figure_text_matches(root: Path, entry: dict[str, Any], evidence: list[dict[str, Any]]) -> bool:
    """Match source PDF glyph identity, not coincidental page-level asset presence."""
    path = (root / str(entry.get('output_path') or '')).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() != '.pdf' or not path.is_file():
        return False
    try:
        import fitz
        with fitz.open(path) as document:
            spans = [span for page in document for block in page.get_text('dict').get('blocks') or []
                     for line in block.get('lines') or [] for span in line.get('spans') or []]
        def font(value: Any) -> str:
            return re.sub(r'^[A-Z]{6}\+', '', str(value or '')).casefold()
        matches = []
        for item in evidence:
            for span in spans:
                text = str(item.get('text') or '').strip()
                measured, native = float(item.get('size_bp') or 0), float(span.get('size') or 0)
                box, source_box = item.get('bbox') or [], span.get('bbox') or []
                if (len(text) < 3 or text != str(span.get('text') or '').strip()
                        or font(item.get('font')) != font(span.get('font')) or not 0 < measured < native
                        or len(box) != 4 or len(source_box) != 4):
                    continue
                scale = measured / native
                matches.append((text, scale, box[0] - source_box[0] * scale, box[1] - source_box[1] * scale))
        return any(first[0] != second[0] and abs(first[1] - second[1]) < 0.001
                   and abs(first[2] - second[2]) < 1.0 and abs(first[3] - second[3]) < 1.0
                   for index, first in enumerate(matches) for second in matches[index + 1:])
    except (OSError, ValueError, ImportError):
        return False
