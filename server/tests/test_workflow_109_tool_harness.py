"""Offline replay of 109 tool failures plus protocol fault injection; no providers."""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from server.agent import LLMResponse, ToolCall
from server.agent.engine import AgentEngine
from server.agent.agent_loop import AgentLoopCoordinator, LoopState
from server.agent.session_models import AgentSession, ToolResult
from server.agent.tool_harness import FailureBudget, argument_fingerprint, classify_result
from server.agent.tool_schema import argument_issues, prepare_tool_schema
from server.agent.tools.file_tools import file_edit
from server.agent.tools.tool_registration import TOOL_SPECS, register_tool_specs


def _engine(monkeypatch):
    engine = AgentEngine(None)
    monkeypatch.setattr(engine, "_log_tool_event", lambda *_: None)
    monkeypatch.setattr(engine, "_record_execution_provenance", lambda *_: None)
    monkeypatch.setattr(engine, "_persist_session_transcript", lambda *_: None)
    return engine


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", ["", "\n"])
async def test_109_edit_delete_reaches_handler_without_schema_error(tmp_path, monkeypatch, replacement):
    engine = _engine(monkeypatch)
    spec = next(item for item in TOOL_SPECS if item[0] == "Edit")
    engine.register_tool(*spec[:3], file_edit)
    target = tmp_path / "references.bib"
    target.write_text("keep\nremove\n", encoding="utf-8")
    session = AgentSession(project_path=str(tmp_path))
    result = await engine._execute_tool(session, ToolCall("delete", "Edit", {
        "path": str(target), "old_text": "remove\n", "new_text": replacement,
    }))
    assert result.success and result.error_code == ""
    assert target.read_text(encoding="utf-8") == "keep\n" + replacement
    assert result.argument_fingerprint and result.duration_ms >= 0


@pytest.mark.asyncio
async def test_ambiguous_edit_preserves_file(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("same same", encoding="utf-8")
    with pytest.raises(ValueError, match="ambiguous"):
        await file_edit(str(target), "same", "new")
    assert target.read_text(encoding="utf-8") == "same same"


@pytest.mark.parametrize("arguments,rule", [
    ({}, "required"), ({"count": True}, "type"), ({"count": "2"}, "type"),
    ({"count": -1}, "minimum"), ({"count": 1, "unexpected": 0}, "additionalProperties"),
    ({"count": 1, "items": ["a", 2]}, "type"), ({"count": 1, "items": []}, "minItems"),
    ({"count": 1, "mode": "invalid"}, "enum"),
])
def test_nested_schema_constraints_are_validated_without_coercion(arguments, rule):
    schema = {"type": "object", "properties": {
        "count": {"type": "integer", "minimum": 0},
        "items": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "mode": {"type": "string", "enum": ["read", "write"]}},
        "required": ["count"], "additionalProperties": False}
    before = copy.deepcopy(arguments)
    assert rule in {issue["rule"] for issue in argument_issues(schema, arguments)}
    assert arguments == before


def test_schema_alternatives_validate_types_and_nullability():
    schema = {"type": "object", "anyOf": [
        {"properties": {"id": {"type": "integer"}}, "required": ["id"]},
        {"properties": {"name": {"type": ["string", "null"]}}, "required": ["name"]}]}
    assert argument_issues(schema, {"id": "wrong"})
    assert not argument_issues(schema, {"name": None})


def test_diagnostics_do_not_echo_argument_secrets():
    errors = argument_issues({"type": "object", "properties": {"x": {"type": "integer"}}}, {"x": "private-token"})
    assert errors[0]["path"] == "/x"
    assert "private-token" not in str(errors)


def test_full_production_registry_schema_and_handler_conformance():
    import server.agent.tools as handlers
    engine = AgentEngine(None)
    register_tool_specs(engine, vars(handlers))
    assert len(engine._tool_definitions) == len(TOOL_SPECS)
    assert all(d.parameters["additionalProperties"] is False for d in engine._tool_definitions)
    with pytest.raises(ValueError, match="unsupported handler"):
        prepare_tool_schema({"type": "object", "properties": {"typo": {"type": "string"}}}, lambda path: None)


@pytest.mark.asyncio
async def test_schema_rejections_have_receipts_without_handler_execution(monkeypatch, tmp_path):
    engine = _engine(monkeypatch)
    recorded = []
    monkeypatch.setattr(engine, "_record_execution_provenance", lambda *args: recorded.append(args))
    engine.register_tool("Edit", "edit", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
                         lambda **_: pytest.fail("invalid call executed"))
    result = await engine._execute_tool(AgentSession(project_path=str(tmp_path)), ToolCall("bad", "Edit", {}))
    assert result.error_code == "TOOL_SCHEMA_ERROR" and result.phase == "validation"
    assert result.retryable and len(recorded) == 1


@pytest.mark.asyncio
async def test_runtime_arguments_never_leak_into_original_call(monkeypatch, tmp_path):
    engine = _engine(monkeypatch)
    calls = []
    async def handler(**kwargs):
        calls.append(kwargs)
        return "done"
    engine.register_tool("Skill", "skill", {"type": "object", "properties": {}}, handler)
    call = ToolCall("delegate", "Skill", {})
    assert (await engine._execute_tool(AgentSession(project_path=str(tmp_path)), call)).success
    assert call.arguments == {} and calls[0]["project_path"] == str(tmp_path)


def test_repeated_failure_budget_survives_intervening_reads():
    budget = FailureBudget()
    fingerprint = argument_fingerprint("Write", {"path": "x", "content": 1})
    for attempt in range(3):
        bad = ToolResult("id", False, "", "TOOL_SCHEMA_ERROR: wrong type")
        classify_result(bad)
        assert budget.observe(fingerprint, bad) == (attempt == 2)
        assert not budget.observe("unrelated-read", ToolResult("r", True, "ok"))


def _loop(engine, session, available=()):
    coordinator = AgentLoopCoordinator(engine, session.id, "test", None, None, 64, None, None)
    state = LoopState(session, [], False, list(available), "offline", None)
    return coordinator, state


@pytest.mark.asyncio
async def test_model_cannot_invoke_an_unadvertised_registered_tool(monkeypatch):
    engine = _engine(monkeypatch)
    engine.register_tool("Write", "write", {"type": "object", "properties": {}}, lambda: pytest.fail("unadvertised tool executed"))
    loop, state = _loop(engine, AgentSession())
    result = await loop._execute_one_tool(state, ToolCall("x", "Write", {}))
    assert result.error_code == "TOOL_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_duplicate_tool_ids_reject_entire_batch_before_effects(monkeypatch):
    engine = _engine(monkeypatch)
    loop, state = _loop(engine, AgentSession())
    response = SimpleNamespace(content="", tool_calls=[ToolCall("x", "Write", {}), ToolCall("x", "Read", {})])
    with pytest.raises(RuntimeError, match="TOOL_CALL_ID_INVALID"):
        await loop._execute_tool_calls(state, response)
    assert state.session.messages == []
