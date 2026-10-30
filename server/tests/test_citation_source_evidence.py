"""Disputed spelling is resolved from source evidence, not forced edits or model intuition."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.services.citation_source_evidence import current_citation_evidence, retrieve_citation_evidence
from server.workflows.report_revision_recovery import reopen_missing_source_review


def bibliography(root):
    p = root / 'literature/references.bib'
    p.parent.mkdir()
    p.write_text('@article{ref1,author={Unusual Name},title={Study},url={https://example.test/study}}\n'
                 '@article{ref2,title={Unrelated},url={https://example.test/unrelated}}', encoding='utf-8')
    return p


@pytest.mark.asyncio
async def test_fetch_only_disputed_entry_and_reject_stale_or_tampered_evidence(tmp_path, monkeypatch):
    bib = bibliography(tmp_path)
    fetch = AsyncMock(return_value='Official publication: Unusual Name')
    monkeypatch.setattr('server.agent.tools.literature_tools.web_fetch', fetch)
    paths = await retrieve_citation_evidence(tmp_path, [{'owner':'lit','findings':[{'message':'Check `ref1` author'}]}])
    fetch.assert_awaited_once_with('https://example.test/study')
    assert paths == current_citation_evidence(tmp_path)
    value = json.loads(paths[0].read_bytes())
    assert value['content'] == 'Official publication: Unusual Name'
    original = bib.read_text()
    bib.write_text(original.replace('Unusual Name','Changed Author'))
    assert current_citation_evidence(tmp_path) == []
    bib.write_text(original)
    value['content'] = 'A model says change the name'
    paths[0].write_text(json.dumps(value))
    assert current_citation_evidence(tmp_path) == []


@pytest.mark.asyncio
async def test_failed_fetch_is_visible_but_not_valid_citation_evidence(tmp_path, monkeypatch):
    bibliography(tmp_path)
    monkeypatch.setattr('server.agent.tools.literature_tools.web_fetch', AsyncMock(side_effect=RuntimeError('HTTP 404')))
    paths = await retrieve_citation_evidence(tmp_path,[{'owner':'lit','findings':[{'message':'ref1 is disputed'}]}])
    assert json.loads(paths[0].read_bytes())['status'] == 'failed'
    assert current_citation_evidence(tmp_path) == []


def test_explicit_source_review_recovery_does_not_reset_rounds_or_replay_edits(tmp_path):
    import hashlib
    bib=bibliography(tmp_path)
    record={'status':'needs_attention','round':2,'completed_owners':['lit'],'targets':['literature/references.bib'],
        'expected':{'literature/references.bib':hashlib.sha256(bib.read_bytes()).hexdigest()},
        'groups':[{'owner':'lit'}],'impact':{'scope':'local','unresolved':['Spelling dispute']}}
    saved={'status':'incomplete','report_revisions':{'r':record}}
    state=SimpleNamespace(project_path=tmp_path,update_state=lambda update:update(saved))
    reopen_missing_source_review(state)
    assert record['status']=='verifying' and record['round']==2
    assert record['completed_owners']==['lit'] and len(record['impact_history'])==1
    record['status']='needs_attention'
    reopen_missing_source_review(state)
    assert record['status']=='needs_attention' and len(record['impact_history'])==1


@pytest.mark.asyncio
async def test_doi_block_does_not_prevent_registry_and_preprint_evidence(tmp_path, monkeypatch):
    bib = bibliography(tmp_path)
    bib.write_text('@inproceedings{ref1,title={Study},doi={10.1234/test},eprint={2512.05442},url={https://doi.org/10.1234/test}}')
    async def fetch(url):
        if url.startswith('https://doi.org/'):
            raise RuntimeError('HTTP 403')
        return 'Registry metadata' if 'crossref' in url else 'Corresponding preprint abstract'
    mocked = AsyncMock(side_effect=fetch)
    monkeypatch.setattr('server.agent.tools.literature_tools.web_fetch', mocked)
    paths = await retrieve_citation_evidence(tmp_path, [{'owner': 'lit', 'findings': [{'message': 'Check ref1'}]}])
    assert len(paths) == 3 and len(current_citation_evidence(tmp_path)) == 2
    assert [c.args[0] for c in mocked.await_args_list] == ['https://doi.org/10.1234/test',
        'https://api.crossref.org/works/10.1234%2Ftest', 'https://arxiv.org/abs/2512.05442']
