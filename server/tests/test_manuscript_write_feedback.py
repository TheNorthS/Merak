"""Authors receive the same measured count as the validator, including candidate writes."""

import pytest

from server.agent.tools.file_tools import file_write, file_edit
from server.services.manuscript_text import word_count
from server.services.paper_candidate_transaction import PaperCandidate


@pytest.mark.asyncio
async def test_write_and_edit_report_exact_candidate_count_without_publishing(tmp_path):
    target = tmp_path / 'paper/sections/00_abstract.tex'
    target.parent.mkdir(parents=True)
    candidate = PaperCandidate(tmp_path, 'front_matter', [target], lambda: 'fixed')
    content = '\\textbf{Measured words} and 中文内容. % ignored comment\n' + 'word ' * 251
    with candidate:
        response = await file_write(str(target), content)
        assert f'count: {word_count(content)}.' in response
        response = await file_edit(str(target), 'word ' * 251, 'word ' * 180)
        assert f'count: {word_count(content.replace("word " * 251, "word " * 180))}.' in response
    assert not target.exists()


@pytest.mark.asyncio
async def test_non_manuscript_write_keeps_ordinary_response(tmp_path):
    response = await file_write(str(tmp_path / 'README.md'), 'Example text')
    assert 'Measured manuscript' not in response
