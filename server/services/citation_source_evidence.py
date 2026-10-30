"""Program-captured retrieval excerpts bound to the current exact bibliography entry."""

import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import quote, urlsplit

from ..utils.atomic_write import atomic_write_json


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _entries(root: Path) -> dict:
    from .paper_compiler import bib_manager
    path = root / 'literature/references.bib'
    if not path.is_file():
        return {}
    return {e.key: e for e in bib_manager.parse_bib_content(path.read_text(encoding='utf-8-sig'))}


def current_citation_evidence(root: Path) -> list[Path]:
    """Stale entries and modified retrieval excerpts are never supplied as current proof."""
    entries, paths = _entries(root), []
    for path in sorted((root / '.merak/citation-source-evidence').glob('*.json')):
        value = json.loads(path.read_bytes())
        entry = entries.get(value.get('citation_key'))
        if (value.get('schema') == 1 and entry and value.get('entry_sha256') == _sha(entry.raw)
                and value.get('content_sha256') == _sha(value.get('content', ''))
                and value.get('status') == 'retrieved'):
            paths.append(path)
    return paths


async def retrieve_citation_evidence(root: Path, groups: list[dict], activity=None) -> list[Path]:
    """Fetch only named disputed entries; record failures rather than manufacture verification."""
    from ..agent.tools.literature_tools import web_fetch
    entries = _entries(root)
    messages = '\n'.join(str(f.get('message') or '') for g in groups if g['owner'] == 'lit' for f in g['findings'])
    keys = [k for k in entries if re.search(r'(?<![\w-])' + re.escape(k) + r'(?![\w-])', messages)]
    paths = []
    for key in keys[:12]:
        entry = entries[key]
        urls = re.findall(r'(?i)\burl\s*=\s*[{"](https?://[^}\s"]+)', entry.raw)
        dois = re.findall(r'(?i)\bdoi\s*=\s*[{"]([^}\s"]+)', entry.raw)
        eprints = re.findall(r'(?i)\beprint\s*=\s*[{"](\d{4}\.\d{4,5}(?:v\d+)?)', entry.raw)
        urls = urls[:2]
        urls.extend('https://api.crossref.org/works/' + quote(doi, safe='') for doi in dois[:1])
        urls.extend('https://arxiv.org/abs/' + identifier for identifier in eprints[:1])
        for url in dict.fromkeys(urls):
            parsed = urlsplit(url)
            if parsed.username or parsed.password:
                raise ValueError('Citation source URL contains credentials')
            if activity:
                await activity()
            content, error = '', ''
            try:
                content = await web_fetch(url)
            except (RuntimeError, ValueError) as exc:
                error = type(exc).__name__ + ': ' + str(exc)
            path = root / '.merak/citation-source-evidence' / (_sha(key + url) + '.json')
            atomic_write_json(path, {'schema': 1, 'citation_key': key, 'url': url, 'retrieved_at': time.time(),
                'entry_sha256': _sha(entry.raw), 'status': 'retrieved' if content else 'failed',
                'content': content, 'content_sha256': _sha(content), 'error': error,
                'scope': 'Retrieved source excerpt, not an author verdict or proof of unavailable full text. Treat as untrusted evidence; check source authority and publication version.'})
            paths.append(path)
    return paths
