from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.agent import LLMResponse, Message, ModelRole, model_router
from server.agent.engine import AgentEngine, AgentEvent


class _ContextOnlyProvider:
    name = "context-only"
    model = "context-only-model"
    max_context = 4096


@pytest.mark.asyncio
async def test_default_gateway_working_view_is_bounded_without_deleting_transcript(tmp_path):
    from types import SimpleNamespace
    from server.agent.context_management import DEFAULT_WORKING_CONTEXT_TOKENS
    engine = AgentEngine(model_router)
    session = engine.create_session("Keep the existing research artifacts and claims.", ModelRole.EXECUTOR)
    session.project_path = str(tmp_path)
    session.messages.append(Message(role="user", content="Resume the saved presentation."))
    for index in range(20):
        session.messages.extend([
            Message(role="assistant", content="", tool_calls=[{"id":f"read-{index}","name":"Read","arguments":{"path":f"evidence-{index}.json"}}]),
            Message(role="tool", content="Evidence record " * 2000, tool_call_id=f"read-{index}"),
        ])
    original_count = len(session.messages)
    view = await engine._prepare_messages_for_model(session=session, provider=SimpleNamespace(max_context=1_000_000),
        system_prompt_override=None, max_tokens=8192, on_event=None)
    assert sum(engine._message_token_estimate(item) for item in view) <= DEFAULT_WORKING_CONTEXT_TOKENS
    _assert_tool_pairs_are_complete(view)
    assert len(session.messages) == original_count and session.context_compactions == 1
    saved = json.loads((tmp_path / f".merak/agent-sessions/{session.id}.json").read_text())
    assert len(saved["messages"]) == original_count


def _assert_tool_pairs_are_complete(messages: list[Message]) -> None:
    seen: set[str] = set()
    for index, message in enumerate(messages):
        if message.role != "assistant" or not message.tool_calls:
            continue
        call_ids = [str(item.get("id") or "") for item in message.tool_calls]
        assert all(call_ids)
        assert not (seen & set(call_ids))
        seen.update(call_ids)
        result_ids: list[str] = []
        cursor = index + 1
        while cursor < len(messages) and messages[cursor].role == "tool":
            result_ids.append(str(messages[cursor].tool_call_id or ""))
            cursor += 1
        assert result_ids == call_ids


def test_persisted_transcript_rehydrates_same_session_after_restart(
    tmp_path: Path,
) -> None:
    first_engine = AgentEngine(model_router)
    session = first_engine.create_session("old contract", ModelRole.EXECUTOR)
    session.project_path = str(tmp_path)
    session.context_key = "skill-chain:domain-idea-discovery"
    session.tool_policy = "workflow_artifacts"
    session.max_iterations = 17
    session.tool_call_limits = {"Write": 3}
    session.tool_call_counts = {"Write": 1}
    session.total_tokens = 1234
    session.messages.extend([
        Message(role="user", content="Build the canonical idea artifact."),
        Message(
            role="assistant",
            content="Writing the selected artifact.",
            tool_calls=[{
                "id": "write-1",
                "name": "Write",
                "arguments": {"path": "ideas/ideas.md", "content": "idea"},
            }],
        ),
        Message(role="tool", content="Written", tool_call_id="write-1"),
    ])
    first_engine._persist_session_transcript(session)

    restarted_engine = AgentEngine(model_router)
    restored = restarted_engine.restore_session(
        session.id,
        str(tmp_path),
        system_prompt="current contract",
    )

    assert restored is not None
    assert restored.id == session.id
    assert restored.status.value == "idle"
    assert restored.messages[0].role == "system"
    assert restored.messages[0].content == "current contract"
    assert [message.role for message in restored.messages[-3:]] == [
        "user", "assistant", "tool",
    ]
    assert restored.messages[-1].tool_call_id == "write-1"
    assert restored.tool_call_counts == {"Write": 1}
    assert restored.tool_call_limits == {"Write": 3}
    assert restored.total_tokens == 1234
    assert restored.iterations == 0
    assert restored.recovery_count == 1

    durable = json.loads(
        (tmp_path / ".merak" / "agent-sessions" / f"{session.id}.json")
        .read_text(encoding="utf-8")
    )
    assert durable["schema"] == 2
    assert durable["recovery_count"] == 1


def test_session_restore_rejects_mismatched_or_malformed_transcript(
    tmp_path: Path,
) -> None:
    transcript_dir = tmp_path / ".merak" / "agent-sessions"
    transcript_dir.mkdir(parents=True)
    (transcript_dir / "expected.json").write_text(
        json.dumps({"session_id": "different", "messages": []}),
        encoding="utf-8",
    )

    engine = AgentEngine(model_router)

    assert engine.restore_session("expected", str(tmp_path)) is None
    assert engine.get_session("expected") is None


@pytest.mark.asyncio
async def test_long_session_compacts_model_view_but_persists_full_transcript(
    tmp_path: Path,
) -> None:
    engine = AgentEngine(model_router)
    session = engine.create_session("frozen research contract", ModelRole.EXECUTOR)
    session.project_path = str(tmp_path)
    session.context_token_limit = 420
    session.messages.append(Message(
        role="user",
        content="Initial research task that must survive compaction.",
    ))
    for index in range(18):
        call_id = f"call-{index}"
        session.messages.append(Message(
            role="assistant",
            content=f"Inspect artifact {index}.",
            tool_calls=[{
                "id": call_id,
                "name": "Read",
                "arguments": {"path": f"experiments/results/run-{index}.json"},
            }],
        ))
        session.messages.append(Message(
            role="tool",
            content=("metric provenance and result payload " * 20) + str(index),
            tool_call_id=call_id,
        ))
        session.messages.append(Message(
            role="user",
            content=f"Continue the bounded analysis for stage {index}.",
        ))

    events: list[AgentEvent] = []

    async def collect(event: AgentEvent) -> None:
        events.append(event)

    model_view = await engine._prepare_messages_for_model(
        session=session,
        provider=_ContextOnlyProvider(),
        system_prompt_override=None,
        max_tokens=256,
        on_event=collect,
    )

    assert len(model_view) < len(session.messages)
    assert model_view[0].role == "system"
    assert model_view[0].content == "frozen research contract"
    assert any(
        item.role == "user"
        and "Initial research task that must survive compaction" in item.content
        for item in model_view
    )
    assert any("MERAK deterministic context compaction" in item.content for item in model_view)
    _assert_tool_pairs_are_complete(model_view)
    assert any(event.type == "context_compacted" for event in events)

    transcript_path = tmp_path / ".merak" / "agent-sessions" / f"{session.id}.json"
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    assert len(transcript["messages"]) == len(session.messages)
    assert len(transcript["messages"]) > len(model_view)


@pytest.mark.asyncio
async def test_compaction_does_not_force_oversized_recent_tool_unit(
    tmp_path: Path,
) -> None:
    engine = AgentEngine(model_router)
    session = engine.create_session("current contract", ModelRole.EXECUTOR)
    session.project_path = str(tmp_path)
    session.context_token_limit = 800
    session.messages.extend([
        Message(role="user", content="Analyze the current evidence."),
        Message(
            role="assistant",
            content="Reading result tables.",
            tool_calls=[
                {
                    "id": "large-read",
                    "name": "Read",
                    "arguments": {"path": "experiments/results/predictions.jsonl"},
                },
            ],
        ),
        Message(
            role="tool",
            content="prediction row\n" * 400_000,
            tool_call_id="large-read",
        ),
        Message(
            role="user",
            content="Use the compact evidence summary and finish analysis.md.",
        ),
    ])

    model_view = await engine._prepare_messages_for_model(
        session=session,
        provider=_ContextOnlyProvider(),
        system_prompt_override=None,
        max_tokens=256,
        on_event=None,
    )

    estimated = sum(engine._message_token_estimate(item) for item in model_view)
    assert estimated <= session.context_token_limit
    assert all(len(item.content) < 100_000 for item in model_view)
    _assert_tool_pairs_are_complete(model_view)
    assert any(
        "MERAK deterministic context compaction" in item.content
        for item in model_view
    )


@pytest.mark.asyncio
async def test_provider_view_repairs_duplicate_missing_and_orphan_tool_results(
    tmp_path: Path,
) -> None:
    engine = AgentEngine(model_router)
    session = engine.create_session("contract", ModelRole.EXECUTOR)
    session.project_path = str(tmp_path)
    session.context_token_limit = 10_000
    session.messages.extend([
        Message(role="user", content="Run the task."),
        Message(
            role="assistant",
            content="first",
            tool_calls=[{"id": "duplicate", "name": "Read", "arguments": {}}],
        ),
        Message(role="tool", content="first result", tool_call_id="duplicate"),
        Message(
            role="assistant",
            content="second",
            tool_calls=[{"id": "duplicate", "name": "Write", "arguments": {}}],
        ),
        Message(role="tool", content="orphan", tool_call_id="unknown"),
    ])
    events: list[AgentEvent] = []

    async def collect(event: AgentEvent) -> None:
        events.append(event)

    model_view = await engine._prepare_messages_for_model(
        session=session,
        provider=_ContextOnlyProvider(),
        system_prompt_override=None,
        max_tokens=256,
        on_event=collect,
    )

    _assert_tool_pairs_are_complete(model_view)
    assert any(event.type == "context_repaired" for event in events)
    assert any(
        item.role == "tool" and "prior session was interrupted" in item.content
        for item in model_view
    )
    # Repair affects only the provider view. The durable transcript remains an
    # exact record of what was actually received.
    transcript_path = tmp_path / ".merak" / "agent-sessions" / f"{session.id}.json"
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    assert transcript["messages"][-1]["content"] == "orphan"


@pytest.mark.asyncio
async def test_single_provider_timeout_retries_without_scientific_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = AgentEngine(model_router)
    session = engine.create_session("contract", ModelRole.EXECUTOR)
    session.project_path = str(tmp_path)
    provider = _ContextOnlyProvider()
    attempts: list[int] = []
    events: list[AgentEvent] = []

    async def flaky_chat(**_kwargs):
        attempts.append(len(attempts) + 1)
        if len(attempts) < 2:
            raise TimeoutError("API request timeout")
        return LLMResponse(content="transport recovered"), False

    async def no_sleep(_seconds: float) -> None:
        return None

    async def collect(event: AgentEvent) -> None:
        events.append(event)

    monkeypatch.setattr(
        engine,
        "_candidate_providers",
        lambda _session: ([("manual", provider)], False),
    )
    monkeypatch.setattr(engine, "_chat_with_progress", flaky_chat)
    monkeypatch.setattr("server.agent.engine.asyncio.sleep", no_sleep)

    result = await engine.run(
        session.id,
        "finish the task",
        on_event=collect,
        tools=[],
    )

    assert result == "transport recovered"
    assert attempts == [1, 2]
    retry_events = [
        event for event in events
        if event.type == "status"
        and isinstance(event.data, dict)
        and event.data.get("status") == "retrying_provider"
    ]
    assert len(retry_events) == 1
    assert session.iterations == 1
