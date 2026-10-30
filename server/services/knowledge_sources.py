"""Deterministic Zotero and Obsidian research-context ingestion."""

from __future__ import annotations

import os
import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json


@dataclass(slots=True)
class KnowledgeSourceResult:
    source: str
    query: str
    records: list[dict[str, Any]] = field(default_factory=list)
    artifact_path: str = ""
    status: str = "completed"
    limitations: list[str] = field(default_factory=list)


class KnowledgeSourceService:
    async def search_zotero(self, query: str, limit: int = 15) -> list[dict[str, Any]]:
        api_key = os.environ.get("ZOTERO_API_KEY", "")
        user_id = os.environ.get("ZOTERO_USER_ID", "")
        if not api_key or not user_id:
            raise RuntimeError("Zotero is not configured")
        import httpx

        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(
                f"https://api.zotero.org/users/{user_id}/items",
                params={
                    "q": query,
                    "limit": max(1, min(100, limit)),
                    "format": "json",
                    "sort": "dateModified",
                    "direction": "desc",
                    "itemType": "-attachment",
                },
                headers={"Zotero-API-Key": api_key},
            )
        if not response.is_success:
            raise RuntimeError(f"Zotero API failed: HTTP {response.status_code} {response.text[:300]}")

        records: list[dict[str, Any]] = []
        for item in response.json():
            data = item.get("data", {}) if isinstance(item, dict) else {}
            if not data.get("title"):
                continue
            creators = []
            for creator in data.get("creators", []):
                name = " ".join(
                    part for part in (creator.get("firstName", ""), creator.get("lastName", "")) if part
                ) or creator.get("name", "")
                if name:
                    creators.append(name)
            records.append({
                "item_key": item.get("key", ""),
                "version": item.get("version"),
                "item_type": data.get("itemType", ""),
                "title": data.get("title", ""),
                "creators": creators,
                "date": data.get("date", ""),
                "publication": data.get("publicationTitle", "") or data.get("conferenceName", ""),
                "doi": data.get("DOI", ""),
                "url": data.get("url", ""),
                "abstract": data.get("abstractNote", ""),
                "tags": [tag.get("tag", "") for tag in data.get("tags", []) if tag.get("tag")],
            })
        return records

    def search_obsidian(
        self,
        query: str,
        vault_path: str = "",
        limit: int = 15,
    ) -> list[dict[str, Any]]:
        raw_vault = vault_path or os.environ.get("OBSIDIAN_VAULT_PATH", "")
        if not raw_vault:
            raise RuntimeError("Obsidian vault is not configured")
        vault = Path(raw_vault).expanduser().resolve()
        if not vault.is_dir():
            raise RuntimeError(f"Obsidian vault does not exist: {vault}")

        terms = {
            token.lower()
            for token in re.findall(r"[A-Za-z0-9_\-\u4e00-\u9fff]{2,}", query)
            if len(token) >= 2
        }
        candidates: list[tuple[int, float, Path, list[str], list[str]]] = []
        scanned = 0
        for current_dir, dirnames, filenames in os.walk(vault, followlinks=False):
            if scanned >= 5000:
                break
            current = Path(current_dir)
            safe_directories = []
            for name in sorted(dirnames):
                candidate = current / name
                try:
                    resolved = candidate.resolve()
                    if (
                        name.startswith(".")
                        or candidate.is_symlink()
                        or not resolved.is_relative_to(vault)
                    ):
                        continue
                except OSError:
                    continue
                safe_directories.append(name)
            dirnames[:] = safe_directories

            for filename in sorted(filenames):
                if scanned >= 5000:
                    break
                if filename.startswith(".") or not filename.lower().endswith(".md"):
                    continue
                scanned += 1
                path = current / filename
                try:
                    resolved = path.resolve()
                    if path.is_symlink() or not resolved.is_relative_to(vault):
                        continue
                    stat = path.stat()
                    if stat.st_size > 2 * 1024 * 1024:
                        continue
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                lower = text.lower()
                matched = sorted(term for term in terms if term in lower)
                if terms and not matched:
                    continue
                snippets = []
                for line in text.splitlines():
                    if not matched or any(term in line.lower() for term in matched):
                        snippets.append(line.strip()[:500])
                    if len(snippets) >= 5:
                        break
                candidates.append((len(matched), stat.st_mtime, path, snippets, matched))
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [
            {
                "path": path.relative_to(vault).as_posix(),
                "matched_terms": matched,
                "snippets": snippets,
                "modified_at": modified,
                "score": score,
            }
            for score, modified, path, snippets, matched
            in candidates[:max(1, min(50, limit))]
        ]

    async def collect_for_project(
        self,
        project_path: str,
        query: str,
        *,
        zotero: bool,
        obsidian: bool,
        limit: int = 15,
    ) -> list[KnowledgeSourceResult]:
        root = Path(project_path).resolve()
        literature = root / "literature"
        literature.mkdir(parents=True, exist_ok=True)
        results: list[KnowledgeSourceResult] = []
        if zotero:
            records = await self.search_zotero(query, limit)
            results.append(self._write_artifact(
                literature / "zotero_context.json",
                "zotero",
                query,
                records,
                ["Personal-library coverage depends on the user's Zotero collection and metadata quality."],
            ))
        if obsidian:
            records = await asyncio.to_thread(self.search_obsidian, query, limit=limit)
            results.append(self._write_artifact(
                literature / "obsidian_context.json",
                "obsidian",
                query,
                records,
                [
                    "Only bounded matching snippets are exposed to the agent; full notes are not copied.",
                    "Personal notes are context, not independently verified scientific evidence.",
                ],
            ))
        return results

    @staticmethod
    def _write_artifact(
        path: Path,
        source: str,
        query: str,
        records: list[dict[str, Any]],
        limitations: list[str],
    ) -> KnowledgeSourceResult:
        payload = {
            "schema_version": 1,
            "source": source,
            "query": query,
            "status": "completed" if records else "completed_no_records",
            "records_returned": len(records),
            "records": records,
            "limitations": limitations,
            "created_at": time.time(),
        }
        if path.is_file():
            previous = json.loads(path.read_text(encoding="utf-8"))
            if {key: value for key, value in previous.items() if key != "created_at"} == {
                key: value for key, value in payload.items() if key != "created_at"
            }:
                payload = previous
            else:
                atomic_write_json(path, payload)
        else:
            atomic_write_json(path, payload)
        return KnowledgeSourceResult(
            source=source,
            query=query,
            records=records,
            artifact_path=str(path),
            status=payload["status"],
            limitations=limitations,
        )


knowledge_source_service = KnowledgeSourceService()
