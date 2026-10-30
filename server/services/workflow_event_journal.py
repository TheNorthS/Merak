"""Backend-owned workflow event and display-log persistence."""

from __future__ import annotations

import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json, path_lock
from .workflow_event_display import format_display_entry


class WorkflowEventJournal:
    """Persist every workflow event even when no UI client is connected."""

    max_display_entries = 1000

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._submission_lock = threading.Lock()
        self._writer: ThreadPoolExecutor | None = None

    async def record_async(self, project_path: str | Path, run_id: str,
                           event_type: str, data: dict[str, Any] | None) -> None:
        """One ordered writer keeps disk locks/fsync outside the event loop.

        Awaiting the receipt preserves durable-before-broadcast behavior. A
        cancelled producer cannot cancel a write already queued for persistence.
        """
        payload = self._serializable(data or {})
        with self._submission_lock:
            if self._writer is None:
                self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="merak-journal")
            future = self._writer.submit(self.record, project_path, run_id, event_type, payload)
        await asyncio.shield(asyncio.wrap_future(future))

    async def close(self) -> None:
        """Drain outstanding persistence work before shutdown; reusable on restart."""
        with self._submission_lock:
            writer, self._writer = self._writer, None
        if writer is not None:
            await asyncio.to_thread(writer.shutdown, wait=True)

    @staticmethod
    def _serializable(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))

    @staticmethod
    def _compact(value: Any, limit: int = 1200) -> str:
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False, default=str)
        else:
            text = str(value or "")
        return " ".join(text.replace("\r", " ").split())[:limit]

    def _display_entry(
        self,
        event_type: str,
        data: dict[str, Any],
        timestamp: float,
    ) -> dict[str, str] | None:
        return format_display_entry(event_type, data, self._compact, timestamp)


    def record(
        self,
        project_path: str | Path,
        run_id: str,
        event_type: str,
        data: dict[str, Any] | None,
    ) -> None:
        root = Path(project_path).expanduser().resolve()
        safe_data = self._serializable(data or {})
        runs_dir = root / ".merak" / "runs"
        events_path = runs_dir / f"{run_id}.events.jsonl"
        display_path = root / ".merak" / "workflow_logs.json"
        timestamp = time.time()
        event_record = {
            "schema": 1,
            "timestamp": timestamp,
            "run_id": run_id,
            "event": event_type,
            "data": safe_data,
        }
        display_entry = self._display_entry(event_type, safe_data, timestamp)

        with self._lock:
            runs_dir.mkdir(parents=True, exist_ok=True)
            with path_lock(events_path):
                with events_path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(event_record, ensure_ascii=False) + "\n")

            if display_entry is None:
                return
            with path_lock(display_path):
                existing: list[dict[str, Any]] = []
                if display_path.is_file():
                    try:
                        loaded = json.loads(
                            display_path.read_text(encoding="utf-8-sig")
                        )
                        if isinstance(loaded, list):
                            existing = [
                                item for item in loaded if isinstance(item, dict)
                            ]
                    except (OSError, UnicodeError, json.JSONDecodeError):
                        existing = []
                if existing and all(
                    existing[-1].get(key) == display_entry.get(key)
                    for key in ("source", "message", "level")
                ):
                    return
                existing.append(display_entry)
                existing = existing[-self.max_display_entries :]
                atomic_write_json(
                    display_path,
                    existing,
                    indent=None,
                    separators=(",", ":"),
                )


workflow_event_journal = WorkflowEventJournal()
