"""Pure guards for authorized model validation without external mutations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.live_snapshot_safety import (
    SnapshotSafetyError, blocked_snapshot_tools, check_snapshot_session,
    load_current_model_config_readonly,
)


def _settings_json(root: Path, model: str, *, modified: float = 2000) -> Path:
    path = root / "user_settings.json"
    path.write_text(json.dumps({"models": {"openai_api_key": "fixture-secret-never-print", "openai_model": model}}), encoding="utf-8")
    os.utime(path, (modified, modified))
    return path


def _settings_database(root: Path, model: str, *, modified: float = 1000) -> Path:
    path = root / "merak_ide.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE user_settings (user_id TEXT, key TEXT, value TEXT)")
        connection.executemany("INSERT INTO user_settings VALUES ('default', ?, ?)",
                               [("models.openai_api_key", "fixture-db-secret-never-print"), ("models.openai_model", model)])
    os.utime(path, (modified, modified))
    return path


def test_newest_valid_json_is_used_without_db_sync_or_secret_output(tmp_path: Path, capsys) -> None:
    json_path = _settings_json(tmp_path, "new-model")
    database = _settings_database(tmp_path, "old-model")
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (json_path, database)}
    config = load_current_model_config_readonly(tmp_path)
    assert config.openai_model == "new-model"
    assert config.openai_api_key == "fixture-secret-never-print"
    assert before == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (json_path, database)}
    assert capsys.readouterr().out == capsys.readouterr().err == ""


def test_newest_database_is_opened_in_ro_shadow_not_user_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _settings_json(tmp_path, "old-model", modified=1000)
    database = _settings_database(tmp_path, "new-db-model", modified=2000)
    source_hash = hashlib.sha256(database.read_bytes()).hexdigest()
    original_connect = sqlite3.connect
    paths = []

    def readonly_connect(path, *args, **kwargs):
        paths.append(str(path))
        assert "mode=ro" in str(path)
        assert kwargs.get("uri") is True
        assert not str(path).startswith(tmp_path.as_uri())
        return original_connect(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", readonly_connect)
    assert load_current_model_config_readonly(tmp_path).openai_model == "new-db-model"
    assert paths
    assert hashlib.sha256(database.read_bytes()).hexdigest() == source_hash
    assert not (tmp_path / "merak_ide.db-journal").exists()


def test_invalid_new_snapshot_uses_older_valid_settings_without_logging_payload(tmp_path: Path, capsys) -> None:
    database = _settings_database(tmp_path, "valid-db-model")
    _settings_json(tmp_path, "invalid", modified=2000).write_text(json.dumps({
        "models": {"openai_api_key": ["private invalid field"], "openai_model": "invalid"},
    }), encoding="utf-8")
    before = database.read_bytes()
    assert load_current_model_config_readonly(tmp_path).openai_model == "valid-db-model"
    assert database.read_bytes() == before
    captured = capsys.readouterr()
    assert "private invalid field" not in captured.out + captured.err


def test_missing_or_unsupported_settings_fail_without_default_secret_fallback(tmp_path: Path) -> None:
    with pytest.raises(SnapshotSafetyError, match="No valid durable model configuration"):
        load_current_model_config_readonly(tmp_path)
    assert list(tmp_path.iterdir()) == []
    (tmp_path / "user_settings.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SnapshotSafetyError, match="No valid durable model configuration"):
        load_current_model_config_readonly(tmp_path)


def test_uncheckpointed_wal_settings_are_current_and_original_sidecars_do_not_change(tmp_path: Path) -> None:
    path = tmp_path / "merak_ide.db"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE user_settings (user_id TEXT, key TEXT, value TEXT)")
        connection.commit()
        connection.execute("INSERT INTO user_settings VALUES ('default','models.openai_model','wal-current-model')")
        connection.commit()
        before = {candidate.name: candidate.read_bytes() for candidate in tmp_path.iterdir()}
        assert load_current_model_config_readonly(tmp_path).openai_model == "wal-current-model"
        assert before == {candidate.name: candidate.read_bytes() for candidate in tmp_path.iterdir()}


class _Engine:
    def __init__(self):
        self._tools = {}
        self._tool_definitions = []

    def register_tool(self, name, description, parameters, handler):
        self._tools[name] = handler
        self._tool_definitions.append(SimpleNamespace(name=name, description=description, parameters=parameters))

    async def _execute_tool(self, session, call):
        result = self._tools[call.name](**call.arguments)
        return await result if asyncio.iscoroutine(result) else result


def _session(root: Path, **overrides):
    return SimpleNamespace(project_path=str(root), allowed_write_paths=[], tool_policy="workflow_artifacts", **overrides)


@pytest.mark.parametrize("name", ["Bash", "terminal_exec", "ssh_exec", "ssh_sync", "ssh_deploy", "overleaf_sync",
                                  "wiki_write", "meta_optimize_propose", "SpawnAgent", "gpu_status", "vastai_create",
                                  "modal_deploy", "run_experiment", "cloud_compute", "cloud_instance_create"])
def test_forbidden_tools_fail_explicitly_without_invoking_handlers(tmp_path: Path, name: str) -> None:
    engine = _Engine()
    calls = []
    original = lambda **_kwargs: calls.append("unauthorized operation")
    engine.register_tool(name, "fixture", {}, original)
    session = _session(tmp_path)
    with blocked_snapshot_tools(engine, tmp_path) as denied:
        with pytest.raises(SnapshotSafetyError, match="LIVE_SNAPSHOT_BLOCKED"):
            asyncio.run(engine._execute_tool(session, SimpleNamespace(name=name, arguments={})))
        assert denied == [name]
    assert engine._tools[name] is original
    assert calls == []


def test_registering_new_or_replacing_tools_during_guard_cannot_reenable_execution(tmp_path: Path) -> None:
    engine = _Engine()
    calls = []
    original = lambda **_kwargs: "ordinary"
    engine.register_tool("Read", "fixture", {}, original)
    definitions = list(engine._tool_definitions)
    with blocked_snapshot_tools(engine, tmp_path):
        engine.register_tool("ssh_exec", "new registration", {}, lambda **_kwargs: calls.append("remote"))
        with pytest.raises(SnapshotSafetyError):
            asyncio.run(engine._execute_tool(_session(tmp_path), SimpleNamespace(name="ssh_exec", arguments={})))
        engine.register_tool("Read", "new registration", {}, lambda **_kwargs: "safe current snapshot read")
        assert asyncio.run(engine._execute_tool(_session(tmp_path), SimpleNamespace(name="Read", arguments={}))) == "safe current snapshot read"
    assert calls == []
    assert engine._tools == {"Read": original}
    assert engine._tool_definitions == definitions
    assert "register_tool" not in vars(engine) and "_execute_tool" not in vars(engine)


def test_tool_guard_checks_foreign_session_and_write_scope_before_call(tmp_path: Path) -> None:
    root = tmp_path / "snapshot"
    root.mkdir()
    engine = _Engine()
    calls = []
    engine.register_tool("Write", "fixture", {}, lambda **_kwargs: calls.append("write"))
    with blocked_snapshot_tools(engine, root):
        session = SimpleNamespace(project_path=str(tmp_path), tool_policy="workflow_artifacts", allowed_write_paths=[])
        with pytest.raises(SnapshotSafetyError, match="does not belong"):
            asyncio.run(engine._execute_tool(session, SimpleNamespace(name="Write", arguments={})))
        session.project_path = str(root)
        session.allowed_write_paths = ["../original/analysis.md"]
        with pytest.raises(SnapshotSafetyError, match="write scope leaves"):
            asyncio.run(engine._execute_tool(session, SimpleNamespace(name="Write", arguments={})))
    assert calls == []


def test_current_bounded_session_is_valid_and_unbounded_unsafe_policy_is_not(tmp_path: Path) -> None:
    check_snapshot_session(_session(tmp_path), tmp_path)
    session = SimpleNamespace(project_path=str(tmp_path), allowed_write_paths=["paper/sections/03_method.tex"], tool_policy="workflow_artifacts")
    check_snapshot_session(session, tmp_path)
    session.allowed_write_paths = None
    session.tool_policy = "ordinary"
    with pytest.raises(SnapshotSafetyError, match="enforced snapshot artifact write policy"):
        check_snapshot_session(session, tmp_path)


def test_exact_snapshot_readonly_reviewer_is_valid_but_foreign_readonly_root_is_not(tmp_path: Path) -> None:
    session = SimpleNamespace(project_path=str(tmp_path), allowed_write_paths=None, tool_policy="research_artifacts",
                              readonly_roots=[str(tmp_path)])
    check_snapshot_session(session, tmp_path)
    session.readonly_roots = [str(tmp_path / "foreign-project")]
    with pytest.raises(SnapshotSafetyError, match="enforced snapshot artifact write policy"):
        check_snapshot_session(session, tmp_path)


def test_readonly_observer_cannot_write_even_when_production_policy_allows_project_artifacts(tmp_path: Path) -> None:
    engine = _Engine()
    writes = []
    engine.register_tool("Read", "fixture", {}, lambda: "readonly evidence")
    engine.register_tool("Write", "fixture", {}, lambda: writes.append("unsafe write"))
    session = SimpleNamespace(project_path=str(tmp_path), allowed_write_paths=None, tool_policy="workflow_artifacts",
                              readonly_roots=[str(tmp_path)])
    with blocked_snapshot_tools(engine, tmp_path):
        assert asyncio.run(engine._execute_tool(session, SimpleNamespace(name="Read", arguments={}))) == "readonly evidence"
        with pytest.raises(SnapshotSafetyError, match="readonly reviewer"):
            asyncio.run(engine._execute_tool(session, SimpleNamespace(name="Write", arguments={})))
    assert writes == []


def test_cloud_image_generation_is_denied_but_local_rendering_preserves_handler_signature(tmp_path: Path) -> None:
    engine = _Engine()
    calls = []

    def render(figure_type, generator_skill=""):
        calls.append((figure_type, generator_skill))
        return "local source result"

    engine.register_tool("generate_figure", "fixture", {}, render)
    with blocked_snapshot_tools(engine, tmp_path):
        with pytest.raises(SnapshotSafetyError):
            asyncio.run(engine._execute_tool(_session(tmp_path), SimpleNamespace(name="generate_figure", arguments={"figure_type": "gpt_image"})))
        assert asyncio.run(engine._execute_tool(_session(tmp_path), SimpleNamespace(name="generate_figure", arguments={"figure_type": "rich_svg", "generator_skill": "figure-spec"}))) == "local source result"
    assert calls == [("rich_svg", "figure-spec")]


def test_guard_restores_original_registry_even_when_validation_raises(tmp_path: Path) -> None:
    engine = _Engine()
    original = lambda: "read"
    engine.register_tool("Read", "fixture", {}, original)
    with pytest.raises(ValueError, match="fixture failure"):
        with blocked_snapshot_tools(engine, tmp_path):
            raise ValueError("fixture failure")
    assert engine._tools["Read"] is original
    assert "register_tool" not in vars(engine)
