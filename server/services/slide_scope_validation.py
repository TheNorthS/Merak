"""Recognize visible bounded scenario descriptions and preserve slide repair ownership."""

import re

from .risk_constants import SIMULATION_SCOPE_RE


def has_bounded_slide_scope(text: str) -> bool:
    """Evidence scope may be expressed without one preferred benchmark keyword."""
    text = re.sub(r'(?m)(?<!\\)%.*$', '', text)
    body = re.search(r'\\begin\{document\}(.*?)\\end\{document\}', text, re.S)
    if body:
        text = body.group(1)
    text = re.sub(r'\\(?:input|include|includegraphics)(?:\[[^]]*\])?\{[^}]*\}', '', text)
    text = re.sub(r'\\[A-Za-z@]+\*?', ' ', text)
    text = ' '.join(re.sub(r'[{}]', ' ', text).split())
    if SIMULATION_SCOPE_RE.search(text):
        return True
    return bool(re.search(
        r'\b(?:deterministic|generated|assigned|synthetic)(?:[\s-]+[\w-]+){0,4}[\s-]+scenario\b'
        r'|\bscenario[\s-]+(?:coordinates|labels|bounds)\b|确定性场景|生成场景|合成场景',
        text, re.I))


def bind_slide_repair_owners(findings: list[dict]) -> list[dict]:
    """Inspected manuscript/figure evidence does not authorize edits to its producer."""
    consumer_ids = {'PPT-SIM-002', 'PPT-FIG-001', 'PPT-FIG-002', 'PPT-FIG-003', 'PPT-CONTRAST-001',
                    'PPT-SOURCE-001', 'PPT-CLAIM-001', 'PPT-CITE-001', 'PPT-MODE-001'}
    result = []
    for item in findings:
        if item.get('id') in consumer_ids:
            result.append({**item, 'owner_node': 'ppt', 'upstream_node': 'ppt',
                           'target_files': ['slides/main.tex'], 'legal_write_targets': ['slides/main.tex']})
        else:
            result.append(item)
    return result
