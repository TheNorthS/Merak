"""HTTP failures, PDF bodies and access checks must not masquerade as source text."""

import httpx
import pymupdf
import pytest

from server.agent.remote_errors import RemoteCallError
from server.agent.tools.literature_tools import web_fetch
from server.agent.tools.web_fetch_content import extract_web_content


@pytest.mark.asyncio
async def test_404_is_structured_failure_and_does_not_retry(monkeypatch):
    calls = []
    async def get(_client, url, **kwargs):
        calls.append(url)
        return httpx.Response(404, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    with pytest.raises(RemoteCallError) as failed:
        await web_fetch('https://example.test/missing')
    assert failed.value.status == 404 and not failed.value.retryable
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_fetch_pdf_returns_readable_title_and_author_text(monkeypatch):
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), 'Research Title\nAuthor One and Author Two')
        raw = document.tobytes()
    async def get(_client, url, **kwargs):
        return httpx.Response(200, content=raw, headers={'content-type': 'application/pdf'})
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    text = await web_fetch('https://example.test/paper.pdf')
    assert 'Research Title' in text and 'Author One and Author Two' in text
    assert '%PDF' not in text and '[Page 1]' in text


@pytest.mark.parametrize('body', [
    '<html><title>Verifying your browser | OpenReview</title>Complete the check</html>',
    '<html><title>Just a moment...</title>Browser challenge</html>',
])
def test_browser_challenge_is_not_semantic_evidence(body):
    with pytest.raises(RuntimeError, match='access-verification'):
        extract_web_content(httpx.Response(200, text=body))


def test_html_entities_scripts_and_explicit_excerpt():
    text = '<HTML><title>A &amp; B</title><SCRIPT>Secret script</SCRIPT><body>' + 'Scientific text ' * 1000 + '</body></HTML>'
    result = extract_web_content(httpx.Response(200, text=text))
    assert 'A & B' in result and 'Secret script' not in result
    assert '[EXCERPT:' in result


def test_blank_pdf_requires_text_source_instead_of_false_success():
    with pymupdf.open() as document:
        document.new_page()
        raw = document.tobytes()
    with pytest.raises(RuntimeError, match='no extractable text'):
        extract_web_content(httpx.Response(200, content=raw))


def test_crossref_metadata_after_large_reference_list_remains_complete():
    record = {'DOI': '10.1234/study', 'type': 'proceedings-article', 'title': ['Study'],
              'reference': [{'unstructured': 'x' * 6000}], 'container-title': ['Exact proceedings title'],
              'publisher-location': 'New York', 'author': [{'given': 'A', 'family': 'Researcher'}]}
    response = httpx.Response(200, json={'message-type': 'work', 'message': record},
                              request=httpx.Request('GET', 'https://api.crossref.org/works/10.1234%2Fstudy'))
    text = extract_web_content(response)
    assert 'Exact proceedings title' in text and 'Researcher' in text
    assert 'x' * 100 not in text and 'METADATA PROJECTION' in text
    assert 'not publisher-page or full-text access' in text
