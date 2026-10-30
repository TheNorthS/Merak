"""Extract readable web evidence; error and browser challenge pages are not sources."""

import html
import json
import re


MAX_FETCH_CHARS = 5000


def _excerpt(text: str) -> str:
    if len(text) <= MAX_FETCH_CHARS:
        return text
    return text[:MAX_FETCH_CHARS] + '\n[EXCERPT: remaining source content is not included; do not claim full-text review.]'


def _pdf_text(raw: bytes) -> str:
    import pymupdf

    try:
        with pymupdf.open(stream=raw, filetype='pdf') as document:
            if document.needs_pass:
                raise ValueError('PDF is encrypted')
            pages, size = [], 0
            for index, page in enumerate(document):
                text = page.get_text()
                pages.append(f'[Page {index + 1}]\n{text}')
                size += len(pages[-1])
                if size > MAX_FETCH_CHARS:
                    break
            if not any(re.search(r'\S', part.split('\n', 1)[-1]) for part in pages):
                raise ValueError('PDF has no extractable text; OCR or a text source is required')
            return _excerpt('\n'.join(pages))
    except (RuntimeError, ValueError) as error:
        raise RuntimeError(f'WebFetch PDF extraction failed: {error}') from error


def extract_web_content(response) -> str:
    """Return explicit excerpts, never decoded PDF bytes or access-check HTML."""
    kind = response.headers.get('content-type', '').lower()
    raw = response.content
    if 'application/pdf' in kind or raw.lstrip().startswith(b'%PDF-'):
        return _pdf_text(raw)
    if b'\x00' in raw[:8192]:
        raise RuntimeError('WebFetch returned unsupported binary content')
    text = response.text
    try:
        host = response.url.host
    except RuntimeError:
        host = ''
    if 'json' in kind and host == 'api.crossref.org':
        parsed = json.loads(text)
        if isinstance(parsed, dict) and parsed.get('message-type') == 'work':
            work = parsed.get('message')
            if isinstance(work, dict):
                fields = ('DOI', 'type', 'title', 'author', 'container-title', 'short-container-title',
                          'publisher', 'publisher-location', 'published', 'published-print', 'published-online',
                          'page', 'volume', 'issue', 'ISBN', 'ISSN', 'URL', 'link', 'source', 'member')
                metadata = {key: work[key] for key in fields if key in work}
                return ('Crossref DOI registry metadata (publisher-deposited record; not publisher-page or full-text access).\n'
                        + json.dumps(metadata, ensure_ascii=False, indent=2)
                        + '\n[METADATA PROJECTION: unrelated reference lists and administrative fields omitted.]')
    if re.search(r'<title[^>]*>[^<]*(?:verifying your browser|just a moment|access denied)', text, re.I):
        raise RuntimeError('WebFetch returned an access-verification page, not research evidence; use another official source')
    if re.search(r'<(?:html|body|head)\b', text, re.I):
        text = re.sub(r'<(?:script|style)\b[^>]*>.*?</(?:script|style)>', '', text, flags=re.I | re.S)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', html.unescape(text)).strip()
    if not text.strip():
        raise RuntimeError('WebFetch returned an empty source')
    return _excerpt(text)
