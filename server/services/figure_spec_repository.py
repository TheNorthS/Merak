"""Persist the complete runtime-owned figure contract before model authoring."""

from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json
from .figure_producer_policy import figure_production_issues
from .publication_figure_labels import validate_publication_labels


def persist_figure_specs(project_path: str | Path, asset_plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Project all active figure assets, never a targeted repair subset.

    Validate producer/label contracts before writing. Invalid plans must fail at
    the owner boundary rather than leaving an apparently usable partial spec.
    """
    figures = [{**item, 'caption': str(item.get('caption') or item.get('scientific_question')
                or f"Scientific figure: {item.get('id') or 'unnamed asset'}.")}
               for item in asset_plan.get('assets', []) if isinstance(item, dict)
               and item.get('kind') == 'figure' and item.get('generation_policy') != 'skip']
    issues = []
    for item in figures:
        identity = str(item.get('id') or '')
        if item.get('producer_kind') not in {'model', 'deterministic'}:
            issues.append(f'{identity}: missing figure producer')
        issues.extend(
            f'{identity}: {issue}' for issue in figure_production_issues(item)
        )
        _, label_issues = validate_publication_labels(item.get('publication_labels'))
        issues.extend(f'{identity}: {issue}' for issue in label_issues)
    if issues:
        raise ValueError('Figure plan contract failed: ' + '; '.join(issues))
    style = asset_plan.get('publication_style') or {}
    payload = {
        'schema': 4, 'publication_label_schema': 1,
        'style_profile': style.get('visual_standard') or 'field-adaptive-accessible-vector-v3',
        'style_profile_path': style.get('path') or '',
        'research_family': style.get('family'), 'study_archetype': style.get('study_archetype'),
        'target_venue': style.get('target_venue'), 'evidence_mode': asset_plan.get('evidence_mode'),
        'illustration_mode': asset_plan.get('illustration_mode') or 'auto',
        'production_policy_schema': 1,
        'generator_policy': 'figure-nature-routing-v2', 'figures': figures,
    }
    atomic_write_json(Path(project_path).resolve() / 'figures/FIGURE_SPECS.json', payload)
    return figures
