"""Reject substantial Beamer frame overflow before claiming a readable delivery."""
import re
from pathlib import Path


def slide_overflow_findings(root: Path) -> list[dict]:
    from .risk_artifact_support import _finding
    path = root / 'slides/main.log'
    if not path.is_file():
        return []
    matches = re.findall(r'Overfull \\vbox \(([0-9.]+)pt too high\) detected at line\s+(\d+)',
                         path.read_text(encoding='utf8', errors='replace'))
    evidence = [{'points': float(points), 'line': int(line)} for points, line in matches if float(points) > 10]
    if not evidence:
        return []
    finding = _finding('PPT-OVERFLOW-001', 'blocker', 'layout',
        'Compiled slide frames overflow vertically: ' + ', '.join(f"line {x['line']} ({x['points']:.1f}pt)" for x in evidence),
        '演示页内容超出页面高度，需要拆分内容或调整图文布局。', ['slides/main.tex', 'slides/main.log'],
        'Repair the indicated frames in slides/main.tex: split content or reduce unused spacing/image size. '
        'Preserve scientific content; do not shrink all text or suppress overflow reporting.', target_files=['slides/main.tex'])
    finding['overflow_evidence'] = evidence
    return [finding]
