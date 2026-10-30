"""Exact stage write scopes protect upstream inputs before tool execution."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.agent import Message, ToolCall
from server.agent.engine import AgentEngine
from server.agent.tools import skill_tool
from server.agent.write_scope import normalize_allowed_write_paths, scoped_write_error


def _engine(root: Path, scope: list[str] | None):
    engine = AgentEngine(SimpleNamespace(_providers={}, _strategy={}))
    session = engine.create_session()
    session.project_path = str(root)
    session.tool_policy = "workflow_artifacts"
    session.allowed_write_paths = scope
    return engine, session


@pytest.mark.parametrize("raw", ["", "   "])
@pytest.mark.parametrize("tool", ["Glob", "Grep"])
def test_empty_search_directory_is_project_scoped_and_keeps_chat_restrictions(tmp_path, raw, tool):
    engine, session = _engine(tmp_path, [])
    call = ToolCall("search", tool, {"directory": raw, "pattern": "NARRATIVE_REPORT.md"})
    assert engine._apply_tool_policy(session, call) is None
    assert call.arguments["directory"] == str(tmp_path.resolve())
    session.tool_policy = "research_artifacts"
    denied = engine._apply_tool_policy(session, ToolCall("chat", tool, {"directory": raw, "pattern": "*"}))
    assert denied is not None and not denied.success


@pytest.mark.parametrize("declaration", [
    ["../escape.py"], ["experiments/../outside.py"], ["experiments/"],
    ["experiments/*.py"], ["C:/outside.py"], ["C:outside.py"],
    ["experiments/src.py:stream"], [""], [None], "experiments/src.py",
])
def test_scope_declarations_require_exact_project_relative_files(tmp_path, declaration) -> None:
    with pytest.raises(ValueError, match="allowed_write_paths"):
        normalize_allowed_write_paths(tmp_path, declaration)


def test_scope_preserves_none_and_empty_and_normalizes_separators(tmp_path) -> None:
    assert normalize_allowed_write_paths(tmp_path, None) is None
    assert normalize_allowed_write_paths(tmp_path, []) == []
    assert normalize_allowed_write_paths(tmp_path, ["experiments\\src\\data.py"]) == [
        "experiments/src/data.py",
    ]


@pytest.mark.parametrize("tool_name,key", [
    ("Write", "path"), ("Edit", "path"),
    ("WritePart", "target_path"), ("AssembleDocument", "target_path"),
])
@pytest.mark.asyncio
async def test_undeclared_file_is_rejected_before_handler_and_budget(
    tmp_path, tool_name, key, monkeypatch,
) -> None:
    engine, session = _engine(tmp_path, ["experiments/src/data.py"])
    seen = []
    engine.register_tool(tool_name, "fixture mutation", {"type": "object", "properties": {key: {"type": "string"}, "content": {"type": "string"}}, "required": [key]},
                         lambda **arguments: seen.append(arguments))
    result = await engine._execute_tool(session, ToolCall("call", tool_name, {
        key: "experiments/src/models.py", "content": "not authorized",
    }))
    assert result.success is False and "not owned" in result.error
    assert seen == []
    assert session.tool_call_counts == {}
    assert not (tmp_path / ".merak" / "composition").exists()


@pytest.mark.asyncio
async def test_declared_file_reaches_handler_with_canonical_absolute_path(tmp_path, monkeypatch) -> None:
    engine, session = _engine(tmp_path, ["experiments/src/data.py"])
    seen = []
    engine.register_tool("Write", "fixture mutation", {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
                         lambda **arguments: seen.append(arguments) or "written")
    monkeypatch.setattr(engine, "_log_tool_event", lambda *_: None)
    monkeypatch.setattr(engine, "_record_execution_provenance", lambda *_: None)
    result = await engine._execute_tool(session, ToolCall("call", "Write", {
        "path": "experiments\\src\\data.py", "content": "complete data code",
    }))
    assert result.success is True
    assert seen[0]["path"] == str((tmp_path / "experiments/src/data.py").resolve())
    assert session.tool_call_counts == {"Write": 1}


@pytest.mark.asyncio
async def test_scoped_read_of_other_stage_remains_allowed(tmp_path, monkeypatch) -> None:
    engine, session = _engine(tmp_path, [])
    seen = []
    engine.register_tool("Read", "fixture read", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
                         lambda **arguments: seen.append(arguments) or "source")
    monkeypatch.setattr(engine, "_log_tool_event", lambda *_: None)
    monkeypatch.setattr(engine, "_record_execution_provenance", lambda *_: None)
    result = await engine._execute_tool(session, ToolCall("call", "Read", {
        "path": "experiments/src/models.py",
    }))
    assert result.success is True and seen


@pytest.mark.parametrize("target", [
    "experiments/src/../src/data.py", "../experiments/src/data.py", "experiments/src/data.py/",
])
def test_lexical_traversal_or_directory_target_cannot_expand_scope(tmp_path, target) -> None:
    if target.endswith("/"):
        (tmp_path / "experiments/src/data.py").mkdir(parents=True)
    error = scoped_write_error(tmp_path, ["experiments/src/data.py"], "Write", {"path": target})
    assert error and error.startswith("BLOCKED:")


@pytest.mark.skipif(os.name != "nt", reason="Windows case-insensitive path identity")
def test_windows_case_and_separator_normalization_match_exact_owned_file(tmp_path) -> None:
    target = str(tmp_path / "EXPERIMENTS/SRC/DATA.PY").replace("\\", "/")
    assert scoped_write_error(tmp_path, ["experiments/src/data.py"], "Write", {
        "path": target,
    }) is None


def test_resolved_symlink_escape_is_blocked_even_when_lexically_owned(tmp_path, monkeypatch) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.py"
    resolve = Path.resolve

    def redirected(path, *args, **kwargs):
        if path.name == "data.py":
            return outside
        return resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", redirected)
    with pytest.raises(ValueError, match="outside"):
        normalize_allowed_write_paths(root, ["experiments/src/data.py"])
    assert scoped_write_error(root, ["experiments/src/data.py"], "Write", {
        "path": "experiments/src/data.py",
    }) is not None


def test_in_project_symlink_cannot_convert_stage_scope_into_upstream_permission(tmp_path, monkeypatch) -> None:
    root = tmp_path / "project"
    root.mkdir()
    upstream = root / "experiments/src/models.py"
    resolve = Path.resolve

    def redirected(path, *args, **kwargs):
        if path.name == "data.py":
            return upstream
        return resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", redirected)
    with pytest.raises(ValueError, match="symlink"):
        normalize_allowed_write_paths(root, ["experiments/src/data.py"])
    for target in ("experiments/src/data.py", "experiments/src/models.py"):
        assert scoped_write_error(root, ["experiments/src/data.py"], "Write", {
            "path": target,
        }) is not None


def test_runtime_owned_file_remains_blocked_even_when_in_scope(tmp_path) -> None:
    engine, session = _engine(tmp_path, [".merak/runs/state.json"])
    result = engine._apply_tool_policy(session, ToolCall("call", "Write", {
        "path": ".merak/runs/state.json", "content": "{}",
    }))
    assert result is not None and "runtime-owned" in result.error


def test_ordinary_sessions_without_scope_keep_previous_policy_behavior(tmp_path) -> None:
    engine, session = _engine(tmp_path, None)
    assert engine._apply_tool_policy(session, ToolCall("call", "Write", {
        "path": "experiments/src/models.py", "content": "ordinary owned code",
    })) is None


@pytest.mark.parametrize("scope", [None, [], ["experiments/src/data.py"]])
def test_session_scope_survives_restart_without_widening(tmp_path, scope) -> None:
    first, session = _engine(tmp_path, scope)
    session.messages.append(Message(role="user", content="fixture task"))
    first._persist_session_transcript(session)
    second = AgentEngine(SimpleNamespace(_providers={}, _strategy={}))
    restored = second.restore_session(session.id, str(tmp_path))
    assert restored is not None and restored.allowed_write_paths == scope
    payload = json.loads((tmp_path / ".merak/agent-sessions" / f"{session.id}.json").read_text())
    assert payload["allowed_write_paths"] == scope


@pytest.mark.asyncio
async def test_skill_scope_is_validated_before_delegate_execution(tmp_path, monkeypatch) -> None:
    session = SimpleNamespace(max_iterations=40, tool_call_limits={})
    loaded = SimpleNamespace(root=tmp_path, name="fixture-skill", lineage=["fixture-skill"])
    monkeypatch.setattr(skill_tool, "_load_skill", lambda *_: loaded)
    monkeypatch.setattr(skill_tool, "_system_prompt", lambda *_: ("fixture prompt", []))
    from server.agent.engine import agent_engine
    monkeypatch.setattr(agent_engine, "create_session", lambda **_: session)
    monkeypatch.setattr(skill_tool, "_allowed_tools", lambda *_: ["Read", "Write"])
    monkeypatch.setattr(skill_tool, "_new_trace", lambda *_: (None, {}))
    monkeypatch.setattr(skill_tool, "atomic_write_json", lambda *args, **kwargs: None)

    async def run_traced(*_):
        assert session.allowed_write_paths == ["experiments/src/data.py"]
        return "bounded"

    monkeypatch.setattr(skill_tool, "_run_traced", run_traced)
    assert await skill_tool.invoke_skill(
        "fixture-skill", allowed_write_paths=["experiments/src/data.py"],
    ) == "bounded"
    with pytest.raises(ValueError, match="traversal"):
        await skill_tool.invoke_skill("fixture-skill", allowed_write_paths=["../data.py"])
