"""Downstream plot projection changes cannot invalidate their upstream measurements."""
import pytest

from server.services.workflow_inputs import snapshot_paths
from server.workflows.engine import WorkflowEngine


@pytest.mark.parametrize('node', ['exp-run', 'results'])
def test_plot_projection_does_not_hide_changes_to_scientific_results(tmp_path, node):
    root = tmp_path.resolve()
    result = root / 'experiments/results'
    (result / 'aggregates').mkdir(parents=True)
    measured = result / 'aggregate/summary_by_seed.csv'
    measured.parent.mkdir()
    measured.write_text('seed,metric,value\n1,MAE,0.2\n')
    derived = result / 'aggregates/main_comparison.csv'
    derived.write_text('old plotted rows')
    engine = WorkflowEngine()
    snapshot = snapshot_paths(str(root), [result],
                              directory_exclusions=engine._artifact_directory_exclusions(node))
    derived.write_text('new plotted rows')
    assert engine._artifact_snapshot_issues(str(root), snapshot) == []
    measured.write_text('seed,metric,value\n1,MAE,0.9\n')
    assert engine._artifact_snapshot_issues(str(root), snapshot)


def test_result_snapshot_still_binds_authored_analysis_and_unknown_aggregate_files(tmp_path):
    root = tmp_path.resolve(); result = root / 'experiments/results'
    (result / 'aggregates').mkdir(parents=True)
    analysis = result / 'analysis.md'; analysis.write_text('Original scientific interpretation')
    engine = WorkflowEngine()
    snapshot = snapshot_paths(str(root), [result], directory_exclusions=engine._artifact_directory_exclusions('results'))
    analysis.write_text('Changed scientific interpretation')
    assert engine._artifact_snapshot_issues(str(root), snapshot)
    analysis.write_text('Original scientific interpretation')
    (result / 'aggregates/custom_measurement.csv').write_text('unexpected new measured evidence')
    assert engine._artifact_snapshot_issues(str(root), snapshot)
