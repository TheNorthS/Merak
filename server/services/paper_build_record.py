"""Hash-bound build-record updates for compiled manuscript PDFs."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json, path_lock
from .latex_bundle import latex_source_bundle


def _load_record(path: Path, *, changed: bool = False) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        state = "changed into unreadable state" if changed else "is unreadable or corrupt"
        raise RuntimeError(
            f"Compile build record {state}; refusing to overwrite it: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Compile build record root must be a JSON object; refusing to overwrite it: {path}"
        )
    return payload


def _compile_record(
    source_root: Path,
    pdf_path: Path,
    source_bundle_sha256: str,
    source_paths: list[Path],
    *,
    pages: int | None,
    compile_time_ms: int | None,
    warning_count: int | None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "success": True, "pdf_path": str(pdf_path),
        "pdf_sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        "source_bundle_sha256": source_bundle_sha256,
        "source_files": [
            path.relative_to(source_root.parent).as_posix()
            if path.is_relative_to(source_root.parent) else path.as_posix()
            for path in source_paths
        ],
        "verified_at": time.time(),
    }
    if pages is not None:
        record["pages"] = max(0, int(pages))
    if compile_time_ms is not None:
        record["compile_time_ms"] = max(0, int(compile_time_ms))
    if warning_count is not None:
        record["warning_count"] = max(0, int(warning_count))
    return record


def _update_page_contract(
    payload: dict[str, Any], pages: int | None,
) -> dict[str, Any] | None:
    contract = payload.get("page_contract")
    if not isinstance(contract, dict) or pages is None:
        return contract if isinstance(contract, dict) else None
    actual = max(0, int(pages))
    contract["actual_pages"] = actual
    minimum = int(contract.get("minimum_pages") or 0)
    maximum = int(contract.get("maximum_pages") or 0)
    if minimum > 0 and maximum >= minimum:
        within_range = minimum <= actual <= maximum
        contract["within_preferred_range"] = within_range
        contract["warning"] = "" if within_range else (
            f"Compiled paper has {actual} pages; the preferred range is {minimum}-{maximum}. "
            "Scientific completeness takes priority, so this soft target does not block the workflow."
        )
    return contract


def _merge_and_write(
    path: Path, compile_record: dict[str, Any], page_contract: dict[str, Any] | None,
) -> None:
    with path_lock(path):
        payload = _load_record(path, changed=True)
        latest_compile = payload.get("compile")
        if not isinstance(latest_compile, dict):
            latest_compile = {}
        latest_compile.update(compile_record)
        if page_contract is not None:
            latest_contract = payload.get("page_contract")
            if not isinstance(latest_contract, dict):
                latest_contract = {}
            latest_contract.update(page_contract)
            payload["page_contract"] = latest_contract
        payload.update({
            "schema": 1, "generated_at": time.time(), "compile": latest_compile,
        })
        atomic_write_json(path, payload)


def refresh_build_record(
    source_root: str | Path,
    record_name: str,
    pdf_name: str,
    *,
    pages: int | None = None,
    compile_time_ms: int | None = None,
    warning_count: int | None = None,
) -> bool:
    root = Path(source_root).expanduser().resolve()
    pdf_path = root / pdf_name
    bundle_hash, source_paths = latex_source_bundle(root)
    if (
        not source_paths or not pdf_path.is_file() or pdf_path.stat().st_size == 0
        or pdf_path.read_bytes()[:5] != b"%PDF-"
    ):
        return False
    if pdf_path.stat().st_mtime + 1.0 < max(path.stat().st_mtime for path in source_paths):
        return False
    record_path = root / record_name
    payload = _load_record(record_path)
    compile_record = _compile_record(
        root, pdf_path, bundle_hash, source_paths,
        pages=pages, compile_time_ms=compile_time_ms, warning_count=warning_count,
    )
    page_contract = _update_page_contract(payload, pages)
    _merge_and_write(record_path, compile_record, page_contract)
    return True
