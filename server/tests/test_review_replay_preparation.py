"""A restored accepted result still obtains missing reproducibility evidence before review."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.workflows.models import WorkflowNode, WorkflowRun
from server.workflows import review_execution
from server.services import simulation_replay_capsule


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,training', [('synthetic_preview', False), ('executed', True), ('design_only', False)])
async def test_real_review_entry_prepares_only_authorized_synthetic_capsule_before_model(tmp_path, monkeypatch, mode, training):
    observed = []

    def prepare(root, direction):
        observed.append(('capsule', str(root), direction))

    async def review(**kwargs):
        observed.append(('review',))
        return SimpleNamespace()

    monkeypatch.setattr(simulation_replay_capsule, 'ensure_simulation_replay_capsule', prepare)
    monkeypatch.setattr(review_execution.cross_model_reviewer, 'run_review_loop', review)
    monkeypatch.setattr(review_execution, '_bind_reconciled_state', AsyncMock(return_value={}))
    monkeypatch.setattr(review_execution, '_review_payload', lambda *_: {})
    options = {'run_experiment': training, 'non_experiment_evidence_mode': mode, 'research_direction': 'EEG'}
    run = WorkflowRun(project_path=str(tmp_path), options=options)
    await review_execution._run_review(SimpleNamespace(), WorkflowNode('review', 'Review', 'domain-review-loop'),
                                       run, options, None)
    assert observed == ([('capsule', str(tmp_path), 'EEG'), ('review',)]
                        if mode == 'synthetic_preview' and not training else [('review',)])
