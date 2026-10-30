"""Scenario provenance cannot imply actual held-out subjects or primary-grid pairing."""

import pytest

from server.services.simulation_claim_evidence import claim_evidence_rows
from server.services.simulation_ranking_evidence import _axis_seed_values, _paired_row


@pytest.mark.parametrize('outcome,planned', [('subject generalization', 'subject_held_out'),
                                         ('dataset transfer', 'dataset_held_out'),
                                         ('robustness', 'registered_protocol')])
def test_constructed_claim_discloses_planned_not_executed_split(outcome, planned):
    rows = claim_evidence_rows(claim_ids=['C1'],
        method_contract={'claim_evidence_plan': [{'idea_claim_id': 'C1', 'outcomes': [outcome]}]},
        selected_contract={'claims': [{'id': 'C1', 'statement': 'Unexecuted hypothesis'}]}, paired_rows=[],
        anchor=.6, maximize_primary=True, primary_metric='score', metric_direction='maximize', simulate=dict)
    row, = rows
    assert row['split_protocol'] == 'not_applicable_deterministic_scenario'
    assert row['planned_split_protocol'] == planned
    assert row['analysis_unit'] == 'random_seed'
    assert row['supports_claim'] == 'false'
    assert (row['value'], row['ci_low'], row['ci_high']) == ('0.600', '0.590', '0.610')


def test_pair_provenance_exposes_separate_projection_without_altering_values():
    axis = {'axis_id': 'accuracy', 'direction': 'maximize'}
    ref = _axis_seed_values(0, 'ref', axis, [13,42,73], {'ref':.547125}, True)
    candidate = _axis_seed_values(1, 'candidate', axis, [13,42,73], {'candidate':.580250}, True)
    effects = [c-r for c,r in zip(candidate,ref)]
    assert effects == pytest.approx([.013125,.043125,.033125])
    mean = sum(effects)/3
    item = {'mean_effect':mean, 'ci_low':-.0082, 'ci_high':.0677, 'mpid':.01,
        'effects':effects, 'axis_id':'accuracy','metric':'score','metric_direction':'maximize',
        'reference_method':'Reference','reference_model_id':'ref','candidate_method':'Candidate',
        'candidate_model_id':'candidate','reference_values':ref,'candidate_values':candidate,'paired_n':3,'p_value':.2}
    row = _paired_row(1,item,item,1,.05,0,True,[13,42,73],dict)
    assert row['oriented_mean_effect'] == '+0.029792'
    assert row['not_primary_grid_contrast'] == 'true'
    assert row['source_table'].endswith('registered_axis_results.csv')
    assert 'model-index/configuration perturbation' in row['construction_note']


def test_generated_analysis_explains_why_paired_mean_differs_from_main_table():
    from server.services.simulation_interval_semantics import interval_semantics
    text = '\n'.join(interval_semantics({}))
    assert 'registered_axis_results.csv' in text
    assert '0.020 * model_index' in text
    assert 'shared offsets cancel' in text
    assert 'not directly from the displayed primary-table replicates' in text
