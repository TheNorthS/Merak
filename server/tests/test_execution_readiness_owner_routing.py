"""Unresolved execution declarations route to their producer without launching compute."""

import json
from types import SimpleNamespace

import pytest

from server.contracts.preparation import PreparationContractError
from server.contracts.implementation_readiness import readiness_instruction
from server.workflows.managed_experiment_execution import _run_contract


@pytest.mark.parametrize('description', [
    'Audited observations and external permission are not provided',
    'The runtime must run the registered preflight first',
])
def test_unresolved_declaration_blocks_and_identifies_design_owner(tmp_path, description):
    directory = tmp_path / 'experiments'
    directory.mkdir()
    (directory / 'RUN_SPEC.json').write_text(json.dumps({
        'execution_readiness': 'blocked', 'execution_prerequisites': [{
            'id': 'EP1', 'owner': 'integration', 'path': 'experiments/src/run.py', 'description': description}]}))
    with pytest.raises(PreparationContractError) as failure:
        _run_contract(None, SimpleNamespace(project_path=str(tmp_path)), {})
    assert failure.value.owner == 'exp-design'
    assert failure.value.paths == ('experiments/RUN_SPEC.json',)
    assert description in str(failure.value)
    assert 'preserve real missing external inputs' in str(failure.value)


def test_author_contract_distinguishes_external_readiness_from_runtime_execution():
    instruction = readiness_instruction()
    assert 'retain execution_status=not_executed' in instruction
    assert 'never grants authorization or skips the runtime preflight' in instruction


@pytest.mark.asyncio
async def test_acceptance_preparation_rechecks_and_preserves_producer_failure(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from server.workflows.revision_loop_phases import prepare_gate_artifacts
    from server.workflows import managed_experiment_execution
    host = SimpleNamespace(_prepare_node_for_gate=AsyncMock(return_value='prepared'))
    context = SimpleNamespace(host=host, node=SimpleNamespace(id='exp-run'),
        run=SimpleNamespace(project_path=str(tmp_path)), opts={'run_experiment': True},
        result='', research_direction='', assurance='draft')
    def blocked(*_args):
        raise PreparationContractError('Reconcile declared external readiness',
            owner='exp-design', paths=('experiments/RUN_SPEC.json',))
    monkeypatch.setattr(managed_experiment_execution, '_run_contract', blocked)
    await prepare_gate_artifacts(context)
    assert context.preparation_error == 'Reconcile declared external readiness'
    finding = context.preparation_failure_details['node_risk_audit']['findings'][0]
    assert finding['owner_node'] == 'exp-design'
    host._prepare_node_for_gate.assert_not_awaited()
    monkeypatch.setattr(managed_experiment_execution, '_run_contract', lambda *_args: None)
    await prepare_gate_artifacts(context)
    assert not context.preparation_error and context.result == 'prepared'
    host._prepare_node_for_gate.assert_awaited_once()
