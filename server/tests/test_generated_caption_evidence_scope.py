"""Public generated captions preserve evidence boundaries and selected figure scope."""

import pytest

from server.services.simulation_interval_caption import scenario_interval_caption
from server.services.paper_figure_outputs import _publication_caption


@pytest.mark.parametrize('original,expected,forbidden', [
    ('Task manifest selected balanced accuracy or auroc task normalized (higher is better) [95% interval].',
     'Generator-labelled task-normalized balanced-accuracy-or-AUROC field', 'Task manifest selected'),
    ('Cross-shift generalization. Stress-response trajectories with uncertainty bands.',
     'do not establish cross-shift generalization or executed perturbation responses', 'Cross-shift generalization.'),
    ('Task calibration and risk coverage. Retained-coverage versus risk curves with uncertainty bands.',
     'do not establish calibration or a within-population risk-coverage relationship', 'versus risk curves'),
])
def test_generated_caption_boundary_is_explicit_and_idempotent(original, expected, forbidden):
    updated = scenario_interval_caption(original)
    assert expected in updated and forbidden not in updated
    assert scenario_interval_caption(updated) == updated


def test_evaluation_caption_describes_selected_inventory_without_claiming_exhaustiveness():
    metadata = {'caption': 'Evaluation design preserving every declared study condition.',
        'method_brief': {'evaluation_conditions': {'mode': 'declared_conditions',
            'conditions': ['No-remapping', 'Generic dropout']}}}
    result = _publication_caption({}, metadata, 'evaluation_design', 1)
    assert 'selected prospective evaluation conditions' in result
    assert 'does not enumerate the complete mechanism-test family' in result
    assert all(name in result for name in ['No-remapping', 'Generic dropout'])
    assert 'every declared' not in result
