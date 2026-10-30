"""Route manuscript length corrections to authors, never the read-only consistency reviewer."""

import math

from .manuscript_text import word_count


def length_findings(specs, sections: dict[str, str], profile: dict) -> list[dict]:
    from .paper_consistency_findings import _finding
    bounds = profile.get('main_text_words') or []
    if len(bounds) != 2:
        return []
    counts = {spec.id: word_count(sections.get(spec.id, '')) for spec in specs}
    total, maximum = sum(counts.values()), int(bounds[1])
    if total <= maximum:
        return []
    issue = f'main text is too verbose for the selected profile ({total} words; maximum {maximum})'
    capacity = {spec.id: max(0, counts[spec.id] - spec.minimum_words) for spec in specs}
    available = sum(capacity.values())
    if not available:
        return []
    # Allocate a concrete shared reduction; section minima and all science stay in force.
    reduction = min(available, total - maximum + 50)
    findings = []
    for spec in specs:
        if not capacity[spec.id]:
            continue
        target = max(spec.minimum_words, counts[spec.id] - math.ceil(reduction * capacity[spec.id] / available))
        findings.append(_finding(
            'manuscript_length', 'main-text-limit', spec.id, f'paper/sections/{spec.filename}', issue,
            f'Condense this section from {counts[spec.id]} to at most {target} words through focused edits '
            'removing repetition. Preserve mechanisms, definitions, evidence, citations, limits and required '
            'figure/table interpretation. Do not alter the profile or reviewer report. Other implicated '
            'authors receive their own share of the reduction.',
            validation_issue=issue, current_section_words=counts[spec.id], target_section_words=target,
        ))
    return findings
