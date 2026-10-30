"""Non-compatible compiled-review snapshot request contract regressions."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.workflows import review_execution
from server.workflows.review_visuals import (
    ReviewSnapshotRequest,
    ReviewVisualsMixin,
)


@pytest.mark.asyncio
async def test_final_review_binding_is_readonly_and_does_not_recompile_reviewed_pixels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = SimpleNamespace(
        run_id='review-run', final_score=2, final_verdict='major_revision',
        rounds=[], is_complete=True, threshold_met=False, bounded_complete=True,
        reviewer_model='reviewer/model', executor_model='executor/model',
        pdf_snapshots=[{'round': 1}], current_round=1,
        source_bundle_sha256='', publication_ready=False,
    )
    run = SimpleNamespace(project_path=str(tmp_path), options={})
    progress: list[tuple[str, dict]] = []

    class Host:
        async def _emit(self, _run, event: str, data: dict) -> None:
            progress.append((event, data))

        @staticmethod
        def _review_visual_evidence_gate(*_args):
            return {'required': False, 'verified': True}

    captured: list[ReviewSnapshotRequest] = []

    async def compile_snapshot(_state, request):
        captured.append(request)
        if request.on_progress:
            await request.on_progress('snapshot compiled')
        return {'snapshot_path': 'paper/main_round1.pdf'}

    monkeypatch.setattr(
        review_execution.paper_drafting_service,
        'reconcile_reviewed_artifacts',
        lambda *_args, **_kwargs: pytest.fail('Final review consumer must not reassemble reviewed sources'),
    )
    monkeypatch.setattr(review_execution.paper_drafting_service, 'gate_report',
                        lambda *_args, **_kwargs: {'passed': True, 'issues': []})
    monkeypatch.setattr(
        review_execution.cross_model_reviewer,
        '_compile_review_snapshot',
        compile_snapshot,
    )

    await review_execution._bind_reconciled_state(
        Host(), run, state, str(tmp_path / 'paper/main.tex'),
    )

    assert captured == []
    assert progress == []


def test_every_production_snapshot_call_uses_one_complete_request_object() -> None:
    root = Path(__file__).resolve().parents[1]
    request_signature = inspect.signature(ReviewSnapshotRequest)
    calls = 0
    requests = 0
    for path in root.rglob('*.py'):
        if 'tests' in path.relative_to(root).parts:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr == '_compile_review_snapshot':
                assert len(node.args) == 2, f'{path}:{node.lineno} must pass state and request'
                assert not node.keywords, f'{path}:{node.lineno} uses the removed keyword API'
                calls += 1
            if isinstance(node.func, ast.Name) and node.func.id == 'ReviewSnapshotRequest':
                request_signature.bind(
                    *[object() for _ in node.args],
                    **{keyword.arg: object() for keyword in node.keywords},
                )
                requests += 1
    assert calls == requests == 2


def test_removed_keyword_snapshot_api_is_not_accepted() -> None:
    with pytest.raises(TypeError, match='unexpected keyword'):
        ReviewVisualsMixin()._compile_review_snapshot(
            SimpleNamespace(), project_path='project', paper_path='paper/main.tex',
            round_number=1, original=False, reason='legacy', on_progress=None,
        )


@pytest.mark.parametrize(
    ('field', 'value'),
    [('project_path', ''), ('paper_path', ''), ('round_number', -1), ('reason', '')],
)
def test_snapshot_request_rejects_incomplete_values(field: str, value) -> None:
    values = {
        'project_path': 'project', 'paper_path': 'paper/main.tex',
        'round_number': 1, 'original': False, 'reason': 'review',
        'on_progress': None,
    }
    values[field] = value
    with pytest.raises(ValueError):
        ReviewSnapshotRequest(**values)
