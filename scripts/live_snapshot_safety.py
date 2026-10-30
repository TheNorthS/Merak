"""Readonly configuration and reversible tool guards for authorized live snapshots.

This helper does not run a model, a workflow, a simulator, or an experiment.
Runtime/subprocess/network guards and external notification suppression remain
the runner's responsibility; denied tools always fail rather than fake success.
"""

from __future__ import annotations

import inspect
import json
import shutil
import sqlite3
import tempfile
from contextlib import closing, contextmanager
from functools import wraps
from pathlib import Path
from typing import Any, Iterator

from pydantic import ValidationError

from server.services.settings_models import ModelConfig, UserSettings
from server.services.settings_repository import snapshot_order


class SnapshotSafetyError(RuntimeError):
    """An operation exceeded the explicitly authorized snapshot scope."""


def _database_payload(path: Path) -> dict[str, Any]:
    """Read a private SQLite shadow so even WAL bookkeeping cannot touch users."""
    companions = [candidate for candidate in (path, Path(str(path) + "-wal")) if candidate.is_file()]
    before = {candidate: (candidate.stat().st_mtime_ns, candidate.stat().st_size) for candidate in companions}
    with tempfile.TemporaryDirectory(prefix="merak-live-settings-read-") as directory:
        shadow = Path(directory) / path.name
        for candidate in companions:
            shutil.copyfile(candidate, Path(directory) / candidate.name)
        if any((candidate.stat().st_mtime_ns, candidate.stat().st_size) != state for candidate, state in before.items()):
            raise SnapshotSafetyError("Settings changed while creating the readonly validation snapshot")
        with closing(sqlite3.connect(shadow.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.execute("PRAGMA query_only = ON")
            rows = connection.execute("SELECT key, value FROM user_settings WHERE user_id = ?", ("default",)).fetchall()
    result: dict[str, Any] = {}
    for key, value in rows:
        section, separator, field = str(key).partition(".")
        if separator:
            result.setdefault(section, {})[field] = value
        else:
            result[section] = value
    return result


def load_current_model_config_readonly(repository: str | Path) -> ModelConfig:
    """Select the newest valid UserSettings snapshot without syncing or exposing keys."""
    root = Path(repository).expanduser().resolve()
    json_path, database = root / "user_settings.json", root / "merak_ide.db"
    candidates: list[tuple[float, str, dict[str, Any]]] = []
    for path, source in ((json_path, "json"), (database, "sqlite")):
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig")) if source == "json" else _database_payload(path)
            freshness_paths = [path, *(candidate for candidate in [Path(str(path) + "-wal")]
                                       if source == "sqlite" and candidate.is_file())]
            modified = max(candidate.stat().st_mtime for candidate in freshness_paths)
        except (OSError, UnicodeError, json.JSONDecodeError, sqlite3.Error, SnapshotSafetyError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("models"), dict) and payload["models"]:
            candidates.append((modified, source, payload))
    for _modified, _source, payload in sorted(
        candidates, key=lambda item: (snapshot_order(item[2], item[0]), item[1]), reverse=True,
    ):
        try:
            return UserSettings.model_validate(payload).models
        except ValidationError:
            continue
    raise SnapshotSafetyError("No valid durable model configuration is available for the authorized snapshot")


def _exact_readonly_session(session: Any, root: Path) -> bool:
    readonly = getattr(session, "readonly_roots", []) or []
    return getattr(session, "allowed_write_paths", None) is None and any(
        isinstance(value, str) and Path(value).expanduser().resolve() == root for value in readonly
    )


def check_snapshot_session(session: Any, snapshot_root: str | Path) -> None:
    """Reject foreign projects and any declared write target outside this snapshot."""
    root = Path(snapshot_root).expanduser().resolve()
    project = str(getattr(session, "project_path", "") or "")
    if not project or Path(project).expanduser().resolve() != root:
        raise SnapshotSafetyError("Model session does not belong to the authorized snapshot")
    scope = getattr(session, "allowed_write_paths", None)
    if scope is None:
        if getattr(session, "tool_policy", "") != "workflow_artifacts" and not _exact_readonly_session(session, root):
            raise SnapshotSafetyError("Model session has no enforced snapshot artifact write policy")
        return
    if not isinstance(scope, list) or any(not isinstance(value, str) or not value for value in scope):
        raise SnapshotSafetyError("Model session write scope is invalid")
    for relative in scope:
        if not (root / relative).resolve().is_relative_to(root):
            raise SnapshotSafetyError("Model session write scope leaves the authorized snapshot")


def blocked_snapshot_tool(name: str) -> bool:
    """Deny command execution, remote mutation, autonomous agents and cloud compute."""
    normalized = name.casefold().replace("-", "_")
    return normalized in {"bash", "terminal_exec", "spawnagent", "spawn_agent", "agent"} or any(
        token in normalized for token in ("ssh", "overleaf", "wiki_write", "meta_opt", "gpu", "vastai", "modal",
                                          "run_experiment", "deploy_experiment", "cloud_compute", "cloud_instance")
    )


def _guarded_handler(name: str, handler: Any, blocked_attempts: list[str]) -> Any:
    @wraps(handler)
    async def guarded(*args: Any, **kwargs: Any) -> Any:
        cloud_image = name.casefold() == "generate_figure" and str(kwargs.get("figure_type") or "").casefold() in {
            "gpt_image", "nano_banana", "gemini_image",
        }
        if blocked_snapshot_tool(name) or cloud_image:
            blocked_attempts.append(name)
            raise SnapshotSafetyError(f"LIVE_SNAPSHOT_BLOCKED: {name} is outside the authorized local validation scope")
        result = handler(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result
    return guarded


@contextmanager
def blocked_snapshot_tools(
    engine: Any, snapshot_root: str | Path, blocked_attempts: list[str] | None = None,
) -> Iterator[list[str]]:
    """Temporarily guard existing/re-registered tools and check every tool session.

Only handlers/methods are replaced. Existing production schemas, file policies,
scientific gates and provenance checks continue to run unchanged.
"""
    attempts = blocked_attempts if blocked_attempts is not None else []
    original_tools = dict(engine._tools)
    original_definitions = list(engine._tool_definitions)
    original_register, original_execute = engine.register_tool, engine._execute_tool
    attributes = {name: vars(engine).get(name) for name in ("register_tool", "_execute_tool")}

    def register(name: str, description: str, parameters: dict, handler: Any) -> None:
        original_register(name, description, parameters, _guarded_handler(name, handler, attempts))

    async def execute(session: Any, tool_call: Any, *args: Any, **kwargs: Any) -> Any:
        check_snapshot_session(session, snapshot_root)
        if _exact_readonly_session(session, Path(snapshot_root).resolve()) and tool_call.name not in {
            "Read", "Glob", "Grep", "file_read", "file_list", "file_search", "WebSearch", "WebFetch",
            "web_search", "web_fetch", "arxiv_search", "semantic_scholar_search", "openalex_search", "pubmed_search",
            "verify_citation", "zotero_search", "obsidian_read", "wiki_read", "audit_status", "figure_manifest",
        }:
            attempts.append(str(tool_call.name))
            raise SnapshotSafetyError("LIVE_SNAPSHOT_BLOCKED: readonly reviewer cannot invoke a mutating or execution tool")
        return await original_execute(session, tool_call, *args, **kwargs)

    try:
        engine._tools.update({name: _guarded_handler(name, handler, attempts) for name, handler in original_tools.items()})
        engine.register_tool, engine._execute_tool = register, execute
        yield attempts
    finally:
        engine._tools.clear()
        engine._tools.update(original_tools)
        engine._tool_definitions[:] = original_definitions
        for name, previous in attributes.items():
            if previous is None:
                vars(engine).pop(name, None)
            else:
                setattr(engine, name, previous)
