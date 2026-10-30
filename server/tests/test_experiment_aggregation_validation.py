"""Completed cells cannot hide failed or missing aggregation."""
import json
import pytest

from server.contracts.preparation import PreparationContractError
from server.services.experiment_aggregation_validation import aggregation_issues


def test_missing_aggregate_receipt_remains_blocking(tmp_path):
    assert aggregation_issues(tmp_path, {'aggregation_command': 'python aggregate.py'}, 'matrix')


def test_failed_aggregate_routes_to_exact_producer_and_preserves_outputs(tmp_path):
    root = tmp_path.resolve()
    manifest = root / '.merak/experiments/matrix-aggregate/run.json'
    manifest.parent.mkdir(parents=True)
    log = manifest.parent / 'train.log'
    log.write_text('refusing to overwrite existing aggregate artifacts')
    manifest.write_text(json.dumps({'status': 'failed', 'current_attempt': 1, 'attempts': [
        {'attempt': 1, 'status': 'failed', 'local_log_path': str(log)}]}))
    before = manifest.read_bytes()
    with pytest.raises(PreparationContractError) as caught:
        aggregation_issues(root, {'aggregation_command': 'python aggregate.py', 'entrypoint': 'experiments/src/aggregate.py',
                                 'outputs': {'aggregate_files': ['experiments/results/summary.csv']}}, 'matrix')
    assert caught.value.owner == 'exp-design'
    assert caught.value.paths == ('experiments/src/aggregate.py',)
    assert 'refusing to overwrite' in str(caught.value)
    assert manifest.read_bytes() == before


def test_preparation_keeps_aggregate_producer_owner_before_scheduler_can_run(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from server.workflows.managed_experiment_execution import _run_contract
    import server.services.experiment_aggregation_validation as validation
    root = tmp_path.resolve()
    (root / 'experiments').mkdir()
    (root / 'experiments/RUN_SPEC.json').write_text('{"aggregation_command":"python aggregate.py"}')
    manifest = root / '.merak/experiments/matrix-aggregate/run.json'
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"status":"failed","attempts":[]}')
    monkeypatch.setattr('server.services.experiment_output_failure.source_bound_experiment_id', lambda *_: 'matrix')
    with pytest.raises(PreparationContractError) as caught:
        _run_contract(None, SimpleNamespace(project_path=str(root), id='workflow'), {})
    assert caught.value.owner == 'exp-design'
    assert caught.value.details()['node_risk_audit']['findings'][0]['owner_node'] == 'exp-design'


def test_subsequent_clear_risk_audit_cannot_erase_producer_routing(tmp_path):
    from types import SimpleNamespace
    from server.services.risk_audit_coordinator import apply_gate
    from server.workflows.engine import WorkflowEngine
    from server.workflows.models import WorkflowRun
    from server.workflows.revision_owner_policy import revision_owner_for_gate
    error = PreparationContractError('Aggregation output failed', owner='exp-design',
                                     paths=('experiments/src/run_analysis.py',))
    gate = {'accepted': False, 'reason': 'producer failed', 'details': error.details()}
    service = SimpleNamespace(audit_node=lambda *a, **k: {'findings': [], 'passed': True})
    checked = apply_gate(service, gate, tmp_path, 'exp-run', {})
    engine = WorkflowEngine()
    nodes = engine._get_default_nodes()
    run = WorkflowRun(id='test', project_path=str(tmp_path), nodes=nodes)
    current = next(node for node in nodes if node.id == 'exp-run')
    assert revision_owner_for_gate(engine, current, run, checked).id == 'exp-design'
