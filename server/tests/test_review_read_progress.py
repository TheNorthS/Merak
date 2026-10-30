"""Long static reviews retain exact missing ranges without asserting scientific acceptance."""

from types import SimpleNamespace
import json

import pytest

from server.agent import Message
from server.agent.engine import AgentEngine
from server.agent.review_read_progress import review_read_progress
from server.agent.session_models import AgentSession
from server.workflows.primary_session_resume import restore_primary_session


def fixture(tmp_path):
    path = tmp_path / "test_pipeline.py"
    lines = [f"# code line {i}" for i in range(1, 1440)]
    path.write_text("\n".join(lines), encoding="utf-8")
    session = AgentSession(project_path=str(tmp_path), context_key="skill-chain:workflow>training-check",
                           tool_policy="workflow_artifacts")
    for index, (start, end) in enumerate([(1, 650), (650, 1250)]):
        session.messages.extend([
            Message(role="assistant", content="", tool_calls=[{"id": str(index), "name": "Read", "arguments": {
                "path": str(path), "start_line": start, "end_line": end}}]),
            Message(role="tool", tool_call_id=str(index), content="\n".join(lines[start-1:end])),
        ])
    return session, path


def test_overlapping_reads_leave_exact_unread_tail(tmp_path):
    session, _ = fixture(tmp_path)
    progress = review_read_progress(session)
    records = json.loads(progress.split('\n')[-1])
    assert records[0]["delivered_ranges"] == [[1, 1250]]
    assert records[0]["undelivered_ranges"] == [[1251, 1439]]
    assert "not proof of review or correctness" in progress


@pytest.mark.parametrize("change", ["source", "truncated", "failed", "missing-result"])
def test_untrusted_read_does_not_attest_coverage(tmp_path, change):
    session, path = fixture(tmp_path)
    session.messages = session.messages[:2]
    if change == "source": path.write_text("changed", encoding="utf-8")
    elif change == "truncated": session.messages[-1].content += "\n[MERAK Read truncated this file]"
    elif change == "failed": session.messages[-1].content = "TOOL_ERROR: missing"
    else: session.messages.pop()
    assert review_read_progress(session) == ""


@pytest.mark.asyncio
async def test_line_cursor_survives_compaction_without_mutating_transcript(tmp_path):
    session, _ = fixture(tmp_path)
    engine = AgentEngine(None)
    session.context_token_limit = 1800
    session.messages.insert(0, Message(role="system", content="Review source honestly."))
    before = list(session.messages)
    view = await engine._prepare_messages_for_model(session=session,
        provider=SimpleNamespace(max_context=100000), system_prompt_override=None, max_tokens=1024, on_event=None)
    assert any('"undelivered_ranges": [[1251, 1439]]' in (m.content or "") for m in view)
    assert session.messages == before


def test_resume_removes_old_budget_commands_but_retains_evidence(tmp_path):
    engine = AgentEngine(None)
    session = engine.create_session("Old system")
    session.project_path = str(tmp_path)
    session.messages.extend([Message(role="user", content="Runtime read-only closeout: old attempt"),
        Message(role="user", content="Runtime budget notice: old attempt"),
        Message(role="assistant", content='{"review_complete":false}'),
        Message(role="user", content="Preserve the research design")])
    restored = restore_primary_session(engine, session.id, str(tmp_path), system_prompt="Current system")
    assert not any(str(m.content).startswith("Runtime ") for m in restored.messages)
    assert restored.messages[-1].content == "Preserve the research design"
    assert restored.messages[-2].content == '{"review_complete":false}'
