"""Focused literature tools for the MERAK agent surface."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from typing import Any

import structlog
from ..remote_errors import RemoteCallError, read_only_get



logger = structlog.get_logger()
FILE_READ_MAX_CHARS = 128_000


def _arxiv_params(query: str, limit: int) -> dict[str, Any]:
    identifier = re.fullmatch(
        r"(?:arxiv:)?(\d{4}\.\d{4,5})(?:v\d+)?", query, re.IGNORECASE,
    )
    if identifier:
        return {"max_results": limit, "id_list": identifier.group(1)}
    has_operator = bool(re.search(
        r"(?:^|\s)(?:all|ti|au|abs|co|jr|cat|rn|id):", query, re.IGNORECASE,
    ))
    return {
        "max_results": limit,
        "search_query": query if has_operator else f"all:{query}",
    }


async def _arxiv_response(params: dict[str, Any]) -> Any:
    import httpx

    headers = {
        "Accept": "application/atom+xml",
        "User-Agent": "Merak/0.1 (research workflow; local installation)",
    }
    async with httpx.AsyncClient(
        follow_redirects=True, headers=headers,
        timeout=httpx.Timeout(12.0, connect=6.0),
    ) as client:
        return await read_only_get(client, "https://export.arxiv.org/api/query", service="arxiv", params=params)


def _arxiv_results(response_text: str, limit: int) -> str:
    root = ET.fromstring(response_text)
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    results: list[str] = []
    for entry in root.findall("atom:entry", namespace)[:limit]:
        title = entry.findtext("atom:title", default="", namespaces=namespace)
        entry_url = entry.findtext("atom:id", default="", namespaces=namespace)
        summary = entry.findtext("atom:summary", default="", namespaces=namespace)
        identifier = entry_url.rsplit("/", 1)[-1].strip()
        clean_title = " ".join(title.split())
        if clean_title and identifier:
            results.append(f"[{identifier}] {clean_title}")
            clean_summary = " ".join(summary.split())
            if clean_summary:
                results.append(f"  {clean_summary[:200]}")
    return "\n".join(results) if results else "No results"


async def arxiv_search(query: str, max_results: int = 10) -> str:
    """Search arXiv with bounded retries and structured Atom parsing."""

    try:

        normalized_query = str(query or "").strip()
        if not normalized_query:
            raise ValueError("arXiv query error: empty query")
        limit = max(1, min(25, int(max_results or 10)))
        response = await _arxiv_response(_arxiv_params(normalized_query, limit))
        try:
            return _arxiv_results(response.text, limit)
        except ET.ParseError as exc:
            raise RuntimeError(f"arXiv response parse error: {type(exc).__name__}: {exc}") from exc
    except RemoteCallError:
        raise
    except Exception as exc:
        raise RuntimeError(f"arXiv search failed: {type(exc).__name__}: {exc}") from exc

async def openalex_search(query: str, max_results: int = 10) -> str:
    """Search OpenAlex with open citation and venue metadata."""
    try:
        import httpx

        limit = max(1, min(25, int(max_results or 10)))
        params = {"search": query, "per-page": limit}
        email = os.environ.get("OPENALEX_EMAIL", "").strip()
        if email:
            params["mailto"] = email
        api_key = os.environ.get("OPENALEX_API_KEY", "").strip()
        if api_key:
            params["api_key"] = api_key
        async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
            response = await client.get("https://api.openalex.org/works", params=params)
        if response.status_code != 200:
            raise RuntimeError(f"OpenAlex API error: {response.status_code}")
        records = response.json().get("results", [])
        lines: list[str] = []
        for record in records[:limit]:
            title = str(record.get("display_name") or record.get("title") or "Untitled")
            year = record.get("publication_year") or "n.d."
            cited = int(record.get("cited_by_count") or 0)
            venue = (
                ((record.get("primary_location") or {}).get("source") or {}).get("display_name")
                or ""
            )
            authors = [
                str((item.get("author") or {}).get("display_name") or "")
                for item in record.get("authorships", [])[:5]
                if (item.get("author") or {}).get("display_name")
            ]
            identifier = str(record.get("doi") or record.get("id") or "")
            suffix = f" | {venue}" if venue else ""
            lines.append(
                f"[{year}] {title}{suffix} | cited_by={cited} | "
                f"authors={', '.join(authors) or 'unknown'} | {identifier}"
            )
        return "\n".join(lines) if lines else "No results"
    except Exception as exc:
        raise RuntimeError(f"OpenAlex search failed: {exc}") from exc


async def pubmed_search(query: str, max_results: int = 10) -> str:
    """Search PubMed through NCBI E-utilities and return structured summaries."""
    try:
        import httpx

        limit = max(1, min(25, int(max_results or 10)))
        common = {"db": "pubmed", "retmode": "json"}
        api_key = os.environ.get("NCBI_API_KEY", "").strip()
        if api_key:
            common["api_key"] = api_key
        async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
            search_response = await client.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params={**common, "term": query, "retmax": limit, "sort": "relevance"},
            )
            if search_response.status_code != 200:
                raise RuntimeError(f"PubMed API error: {search_response.status_code}")
            identifiers = search_response.json().get("esearchresult", {}).get("idlist", [])
            if not identifiers:
                return "No results"
            summary_response = await client.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                params={**common, "id": ",".join(identifiers)},
            )
        if summary_response.status_code != 200:
            raise RuntimeError(f"PubMed API error: {summary_response.status_code}")
        payload = summary_response.json().get("result", {})
        lines: list[str] = []
        for pmid in identifiers:
            record = payload.get(str(pmid), {})
            title = str(record.get("title") or "Untitled").strip()
            publication = str(record.get("fulljournalname") or record.get("source") or "")
            date = str(record.get("pubdate") or "n.d.")
            authors = [
                str(item.get("name") or "")
                for item in record.get("authors", [])[:5]
                if item.get("name")
            ]
            doi = next((
                str(item.get("value") or "")
                for item in record.get("articleids", [])
                if str(item.get("idtype") or "").casefold() == "doi"
            ), "")
            suffix = f" | DOI:{doi}" if doi else ""
            lines.append(
                f"[PMID:{pmid}] {title} | {publication} | {date} | "
                f"authors={', '.join(authors) or 'unknown'}{suffix}"
            )
        return "\n".join(lines) if lines else "No results"
    except Exception as exc:
        raise RuntimeError(f"PubMed search failed: {exc}") from exc


async def web_search(query: str, max_results: int = 5) -> str:
    """网络搜索（通用）"""
    # 使用 Exa API 或其他搜索引擎
    exa_key = os.environ.get("EXA_API_KEY", "")
    if exa_key:
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.exa.ai/search",
                    headers={"x-api-key": exa_key},
                    json={"query": query, "numResults": max_results, "type": "neural"},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                results = []
                for r in data.get("results", []):
                    results.append(f"[{r['title']}]({r['url']})")
                    if r.get("text"):
                        results.append(f"  {r['text'][:200]}")
                return '\n'.join(results) if results else "No results"
        except Exception as e:
            raise RuntimeError(f"Exa search failed: {e}") from e
    raise RuntimeError("No search API configured. Set EXA_API_KEY.")


async def web_fetch(url: str) -> str:
    """Fetch readable evidence while retaining structured transport failures."""
    import asyncio
    import httpx
    from .web_fetch_content import extract_web_content

    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        response = await read_only_get(client, url, service='WebFetch')
    return await asyncio.to_thread(extract_web_content, response)


# ==================== Agent / Skill / MCP 替代实现 ====================
