"""Bounded document-part persistence and deterministic assembly."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ...utils.atomic_write import atomic_write_json, atomic_write_text, path_lock


MAX_DOCUMENT_PART_CHARS = 16_000
MAX_ASSEMBLED_DOCUMENT_CHARS = 512_000
_PART_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


def _target(project_path: str, target_path: str) -> tuple[Path, Path, str]:
    root = Path(project_path).expanduser().resolve()
    target = Path(target_path).expanduser().resolve()
    try:
        relative = target.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("document target must be project-local") from error
    if target.suffix.casefold() not in {".md", ".tex", ".bib", ".json"}:
        raise ValueError("document target must be Markdown, LaTeX, BibTeX, or JSON")
    key = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]
    return root, target, key


def write_document_part(
    target_path: str, part_id: str, content: str, *, project_path: str = "",
) -> str:
    """Write one bounded part without mutating the canonical document."""
    root, target, key = _target(project_path, target_path)
    identity = str(part_id or "").strip()
    if not _PART_ID.fullmatch(identity):
        raise ValueError("part_id must match [A-Za-z0-9][A-Za-z0-9_.-]{0,79}")
    body = str(content or "")
    if not body.strip():
        raise ValueError("document part content must be non-empty")
    if len(body) > MAX_DOCUMENT_PART_CHARS:
        raise ValueError(
            f"document part exceeds {MAX_DOCUMENT_PART_CHARS} characters; split it"
        )
    directory = root / ".merak" / "composition" / key
    part = directory / f"{identity}.part"
    index = directory / "index.json"
    directory.mkdir(parents=True, exist_ok=True)
    with path_lock(index):
        payload = _load_index(index)
        payload.update({
            "schema": 1,
            "target_path": target.relative_to(root).as_posix(),
        })
        payload.setdefault("parts", {})[identity] = {
            "path": part.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(body.rstrip().encode("utf-8")).hexdigest(),
            "chars": len(body),
        }
        atomic_write_text(part, body.rstrip() + "\n")
        atomic_write_json(index, payload)
    return f"Stored document part {identity} ({len(body)} chars) for {target}"


def assemble_document(
    target_path: str, part_ids: list[str], *, project_path: str = "",
) -> str:
    """Atomically assemble the exact ordered parts into the canonical target."""
    root, target, key = _target(project_path, target_path)
    identities = [str(value).strip() for value in part_ids if str(value).strip()]
    if not identities or len(identities) != len(set(identities)):
        raise ValueError("part_ids must be a non-empty ordered list without duplicates")
    directory = root / ".merak" / "composition" / key
    payload = _load_index(directory / "index.json")
    if payload.get("target_path") != target.relative_to(root).as_posix():
        raise ValueError("document composition target does not match its part index")
    records = payload.get("parts") if isinstance(payload.get("parts"), dict) else {}
    bodies: list[str] = []
    for identity in identities:
        record = records.get(identity)
        if not isinstance(record, dict):
            raise ValueError(f"document part is missing from index: {identity}")
        part = (root / str(record.get("path") or "")).resolve()
        if not part.is_relative_to(directory.resolve()):
            raise ValueError("document part escapes its composition directory")
        body = part.read_text(encoding="utf-8").rstrip()
        if hashlib.sha256(body.encode("utf-8")).hexdigest() != record.get("sha256"):
            raise ValueError(f"document part hash mismatch: {identity}")
        bodies.append(body)
    assembled = "\n\n".join(bodies).rstrip() + "\n"
    if len(assembled) > MAX_ASSEMBLED_DOCUMENT_CHARS:
        raise ValueError("assembled document exceeds the runtime safety limit")
    from ...contracts.writers import versioned_artifact_write_error
    from ...services.artifact_contract import artifact_write_error
    if target.suffix.casefold() == ".json":
        json.loads(assembled)
    issue = artifact_write_error(root, target) or versioned_artifact_write_error(
        root, target, assembled, model_authored=True,
    )
    if issue:
        raise ValueError(issue)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, assembled)
    return f"Assembled {len(identities)} parts ({len(assembled)} chars) into {target}"


def _load_index(path: Path) -> dict:
    if not path.is_file():
        return {"schema": 1, "parts": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"document composition index is invalid: {path}") from error
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise ValueError(f"document composition index has unsupported schema: {path}")
    return payload
