"""A pre-execution source review cannot demand completed downstream execution first."""
import pytest
from server.services.training_review_policy import current_review_findings, review_blocks


@pytest.mark.parametrize('targets,scope,blocks', [
    (['experiments/results/aggregate/summary.csv'], 'execution_evidence', False),
    (['experiments/results/analysis.md'], 'execution_evidence', False),
    (['experiments/src/run.py'], 'execution_evidence', True),
    (['experiments/results/x.csv', 'experiments/src/run.py'], 'execution_evidence', True),
    (['experiments/results/../src/run.py'], 'execution_evidence', True),
    (['experiments/src/run.py'], 'implementation_correctness', True),
    ([], 'execution_evidence', True),
])
def test_only_explicit_runtime_output_findings_are_deferred(targets, scope, blocks):
    finding = {'severity': 'blocker', 'scope': scope, 'target_files': targets,
               'message': 'Old outputs do not reflect the current source'}
    assessment = {'blocking': True, 'verdict': 'FAIL', 'findings': [finding]}
    assert review_blocks(assessment, {'run_experiment': True}) is blocks
    assert bool(current_review_findings(assessment, {'run_experiment': True})) is blocks
    assert assessment['findings'] == [finding] and assessment['verdict'] == 'FAIL'
