"""Real route-entrypoint contracts, with no model or workflow execution."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.agent import ModelRole, ModelRouter
from server.services import api_visual_review_invocation
from server.workflows import review_loop


def _router(shared: bool) -> tuple[ModelRouter, object]:
    writer = SimpleNamespace(name='openai', model='writer')
    reviewer = writer if shared else SimpleNamespace(name='openai', model='reviewer')
    router = ModelRouter()
    router._providers = {'writer': writer, 'reviewer': reviewer}
    router.set_strategy(ModelRole.EXECUTOR, 'writer')
    router.set_strategy(ModelRole.REVIEWER, 'reviewer')
    return router, reviewer


@pytest.mark.parametrize('shared', [False, True])
def test_manuscript_review_initialization_resolves_real_reviewer_role(
    tmp_path: Path, monkeypatch, shared: bool,
) -> None:
    router, reviewer = _router(shared)
    monkeypatch.setattr(review_loop, 'model_router', router)
    context = review_loop.ReviewContext(
        reviewer=SimpleNamespace(_load_state=lambda *_args, **_kwargs: None),
        paper_path=str(tmp_path / 'paper/main.tex'), project_path=str(tmp_path),
        max_rounds=3, difficulty='hard', on_progress=None, run_id='entrypoint-test',
        researcher_feedback='', evidence_mode='design_only', transport_retry=None,
    )

    state, cached = review_loop._initialize_state(context)

    assert context.reviewer_name == 'reviewer'
    assert context.reviewer_identity == router.provider_identity(reviewer)
    assert state.run_id == 'entrypoint-test'
    assert cached is False


@pytest.mark.parametrize('shared', [False, True])
def test_visual_review_entrypoint_resolves_real_reviewer_role(monkeypatch, shared):
    router, reviewer = _router(shared)
    monkeypatch.setattr(api_visual_review_invocation, 'model_router', router)

    route = api_visual_review_invocation._route()

    assert route.executor_name == 'writer'
    assert route.provider_name == 'reviewer'
    assert route.provider is reviewer
    assert route.model_identity == router.provider_identity(reviewer)


def test_all_production_isolated_route_calls_bind_the_current_signature():
    """Catch missing roles/retired keywords even on unexecuted feature paths."""
    root = Path(__file__).resolve().parents[1]
    signature = inspect.signature(ModelRouter.get_isolated_provider_route)
    checked = []
    for path in root.rglob('*.py'):
        if 'tests' in path.relative_to(root).parts:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != 'get_isolated_provider_route':
                continue
            arguments = [object() for _ in node.args]
            keywords = {keyword.arg: object() for keyword in node.keywords}
            try:
                signature.bind(object(), *arguments, **keywords)
            except TypeError as exc:
                pytest.fail(f'{path.relative_to(root)}:{node.lineno}: {exc}')
            checked.append(path)
    assert len(checked) >= 5
