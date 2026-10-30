"""A new evaluation defect found during integration must invoke evaluation next."""

import json

import pytest

from server.tests.test_implementation_iteration_handoff import fixture_context
from server.tests.test_implementation_owner_reconciliation import DIRECTION
from server.workflows.implementation_model_invocation import StageModelInvocation
from server.workflows.staged_implementation_coordinator import StagedImplementationCoordinator


@pytest.mark.asyncio
async def test_new_declared_evaluation_blocker_routes_before_second_integration_attempt(tmp_path, monkeypatch):
    context, events = fixture_context(tmp_path)
    patch_path = tmp_path / 'experiments/IMPLEMENTATION_EVIDENCE_PATCH.json'
    patch = json.loads(patch_path.read_bytes())
    patch['checks'][0]['idea_mechanism_ids'] = ['M1']
    patch_path.unlink()
    spec_path = tmp_path / 'experiments/RUN_SPEC.json'
    target = next(stage.targets[0] for stage in context.stages if stage.id == 'evaluation')
    calls = []
    async def author(invocation):
        stage = invocation.state.stage.id
        calls.append(stage)
        if stage == 'integration':
            assert calls.count(stage) == 1, 'Wrong-owner repeat would consume an attempt without repairing source'
            patch_path.write_text(json.dumps(patch), encoding='utf-8')
            spec = json.loads(spec_path.read_bytes())
            spec.update(integration_readiness='blocked', integration_blockers=[{
                'id': 'evaluation-call', 'owner': 'evaluation', 'path': target,
                'description': 'Evaluation omits the new required target mapping argument.'}])
            spec_path.write_text(json.dumps(spec), encoding='utf-8')
        elif stage == 'evaluation':
            assert any('target mapping' in issue for issue in invocation.state.report['issues'])
            assert set(invocation.state.effective_targets) == set(invocation.state.stage.targets)
            raise InterruptedError('Fixture stops at verified correct author dispatch')
        else:
            pytest.fail(f'Unchanged owner must be reused: {stage}')
        return 'Declared evaluation defect without editing another owner source.'
    monkeypatch.setattr(StageModelInvocation, 'run', author)
    monkeypatch.setattr(StageModelInvocation, 'mark', lambda *_a, **_k: None)
    with pytest.raises(InterruptedError, match='correct author'):
        await StagedImplementationCoordinator(context.host, context.run, DIRECTION)._run_stages(context)
    assert calls == ['integration', 'evaluation']
    assert any(kind == 'implementation_owner_reconciliation_started' for kind, _ in events)
