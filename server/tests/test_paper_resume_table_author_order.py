"""Changed prose must reach its table author before resume-side table preparation."""
from types import SimpleNamespace

import pytest

from server.workflows.engine import WorkflowEngine


@pytest.mark.asyncio
async def test_resume_paper_artifacts_refreshes_author_before_table_reader(tmp_path, monkeypatch):
    from server.workflows import paper_method_presentation
    from server.services import paper_preparation_errors, paper_print_projection
    calls = []
    async def author(run):
        calls.append('author')
    def prepare(*_args):
        assert calls == ['author']
        raise ValueError('fixture stops after ordered table author check')
    monkeypatch.setattr(paper_method_presentation, 'refresh_method_presentation', author)
    monkeypatch.setattr(paper_print_projection, 'restore_print_entrypoint', lambda *_: None)
    monkeypatch.setattr(paper_preparation_errors, 'prepare_paper_evidence', prepare)
    with pytest.raises(ValueError, match='ordered table author'):
        await WorkflowEngine()._ensure_paper_artifacts(SimpleNamespace(project_path=str(tmp_path), options={}), '', '')
