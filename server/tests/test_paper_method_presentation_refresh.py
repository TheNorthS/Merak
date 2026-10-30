"""Source changes require a real author response before method-table rebinding."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from server.services.api_visual_reviewer import ApiVisualReviewer
from server.services.method_table_presentation import PRESENTATION, _hashes, write_method_presentation
from server.tests.test_method_table_presentation import ready
from server.workflows.paper_method_presentation import refresh_method_presentation


def setup(root):
    _evidence, rows = ready(root)
    write_method_presentation(root, rows, author='original-author')
    return SimpleNamespace(project_path=str(root)), rows


@pytest.mark.asyncio
async def test_current_presentation_needs_no_model_and_changes_no_files(tmp_path, monkeypatch):
    run, _rows = setup(tmp_path)
    async def forbidden(*_args, **_kwargs):
        raise AssertionError('Current table should not call a model')
    monkeypatch.setattr(ApiVisualReviewer, 'invoke', forbidden)
    before = (tmp_path / PRESENTATION).read_bytes()
    assert not await refresh_method_presentation(run)
    assert (tmp_path / PRESENTATION).read_bytes() == before


@pytest.mark.asyncio
async def test_changed_chapter_is_reviewed_then_producer_rebuilds_without_rewriting_science(tmp_path, monkeypatch):
    run, rows = setup(tmp_path)
    (tmp_path / 'paper/sections/03_method.tex').write_text('Revised input requires finite supplied coordinates')
    before = (tmp_path / PRESENTATION).read_bytes()
    calls = []
    async def invoke(_self, **kwargs):
        calls.append(kwargs)
        assert tmp_path / 'paper/sections/03_method.tex' in kwargs['evidence_paths']
        assert kwargs['schema']['properties'].keys() == {'rows'}
        return SimpleNamespace(text=json.dumps({'rows': rows}), invocation_id='model-api:fixture', trace_path='fixture-trace')
    monkeypatch.setattr(ApiVisualReviewer, 'invoke', invoke)
    from server.services import paper_preparation_errors
    def prepare(root):
        assert json.loads((root / PRESENTATION).read_bytes())['source_sha256'] == _hashes(root)
    monkeypatch.setattr(paper_preparation_errors, 'prepare_paper_evidence', prepare)
    assert await refresh_method_presentation(run)
    assert len(calls) == 1
    assert json.loads((tmp_path / PRESENTATION).read_bytes())['author'] == 'model-api:fixture'
    assert next((tmp_path / '.merak/method-table-authoring').glob('*/before.json')).read_bytes() == before
    assert (tmp_path / 'paper/sections/03_method.tex').read_text().startswith('Revised input')


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['cancel', 'rename', 'source_change'])
async def test_cancel_invalid_rows_or_concurrent_edit_preserve_presentation(tmp_path, monkeypatch, mode):
    run, rows = setup(tmp_path)
    chapter = tmp_path / 'paper/sections/03_method.tex'
    chapter.write_text('Changed input')
    before = (tmp_path / PRESENTATION).read_bytes()
    async def invoke(_self, **_kwargs):
        if mode == 'cancel':
            raise asyncio.CancelledError()
        if mode == 'rename':
            rows[0]['component'] = 'A foreign component'
        if mode == 'source_change':
            chapter.write_text('Concurrent change')
        return SimpleNamespace(text=json.dumps({'rows': rows}), invocation_id='model-api:fixture', trace_path='fixture')
    monkeypatch.setattr(ApiVisualReviewer, 'invoke', invoke)
    with pytest.raises(asyncio.CancelledError if mode == 'cancel' else ValueError):
        await refresh_method_presentation(run)
    assert (tmp_path / PRESENTATION).read_bytes() == before
