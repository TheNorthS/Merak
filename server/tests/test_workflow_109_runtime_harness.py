"""Fault injection at tool boundaries, using fake processes/services only."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from server.agent import ToolCall
from server.agent.engine import AgentEngine
from server.agent.session_models import AgentSession, AgentStatus
from server.agent.agent_loop import AgentLoopCoordinator, LoopState
from server.agent.tool_harness import FailureBudget
from server.agent.tools.remote_tools import ssh_exec, terminal_exec
from server.agent.tool_deadline import run_with_deadline, ToolCancellationUnconfirmed


@pytest.mark.asyncio
async def test_ssh_nonzero_exit_is_a_failure_receipt(monkeypatch):
    from server.services.ssh_manager import ssh_manager
    async def fake_execute(*args, **kwargs):
        return "output", "traceback", 2
    monkeypatch.setattr(ssh_manager, "execute", fake_execute)
    engine = AgentEngine(None)
    result = await engine._call_tool_handler(ssh_exec, ToolCall("ssh", "ssh_exec", {
        "server_id": "fake", "command": "never executed"}), None, 0)
    assert not result.success and "exit code: 2" in result.error


@pytest.mark.asyncio
async def test_compile_failure_is_not_successful_tool_output(monkeypatch):
    from server.services.paper_compiler import paper_compiler
    from server.agent.tools.review_and_domain_tools import latex_compile
    async def fake_compile(*args):
        return SimpleNamespace(success=False, errors=[SimpleNamespace(line=3, message="invalid syntax")])
    monkeypatch.setattr(paper_compiler, "compile", fake_compile)
    result = await AgentEngine(None)._call_tool_handler(latex_compile, ToolCall("compile", "latex_compile", {
        "project_dir": "not accessed"}), None, 0)
    assert not result.success and "invalid syntax" in result.error


@pytest.mark.asyncio
async def test_search_configuration_error_is_failed_not_empty_evidence(monkeypatch):
    from server.agent.tools.literature_tools import web_search
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="No search API configured"):
        await web_search("offline")


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_local_command_timeout_and_cancellation_clean_owned_process(monkeypatch, cancel):
    import server.agent.tool_process as processes
    entered = asyncio.Event()
    cleaned = []
    proc = SimpleNamespace()
    async def fake_spawn(*args, **kwargs):
        assert kwargs.get("start_new_session") or kwargs.get("creationflags")
        return proc
    async def hanging_read(*args):
        entered.set()
        await asyncio.Event().wait()
    async def cleanup(value):
        cleaned.append(value)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_spawn)
    monkeypatch.setattr(processes, "read_process_tail", hanging_read)
    monkeypatch.setattr(processes, "stop_process_tree", cleanup)
    task = asyncio.create_task(terminal_exec("never executed", timeout=0.01))
    await entered.wait()
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
        await task
    assert cleaned == [proc]


@pytest.mark.asyncio
async def test_process_output_is_bounded_before_decoding():
    from server.agent.tool_process import read_process_tail
    chunks = [b"a" * 16_384 for _ in range(100)] + [b"END", b""]
    async def read(size):
        return chunks.pop(0)
    async def wait():
        return 0
    result = await read_process_tail(SimpleNamespace(stdout=SimpleNamespace(read=read), wait=wait), 1000)
    assert len(result) == 1000 and result.endswith(b"END")


@pytest.mark.asyncio
async def test_failed_tree_kill_cannot_claim_cleanup_confirmed(monkeypatch):
    import server.agent.tool_process as processes
    async def wait():
        return 1
    killer = SimpleNamespace(returncode=1, wait=wait)
    async def spawn(*args, **kwargs):
        return killer
    process = SimpleNamespace(pid=123, returncode=None, wait=wait)
    process.kill = lambda: setattr(process, "returncode", -1)
    monkeypatch.setattr(processes, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(processes.subprocess, "CREATE_NO_WINDOW", 0, raising=False)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(ToolCancellationUnconfirmed):
        await processes.stop_process_tree(process)


@pytest.mark.asyncio
async def test_async_deadline_waits_for_cancellation_cleanup(monkeypatch):
    import server.agent.tool_deadline as deadlines
    monkeypatch.setattr(deadlines, "TOOL_WALL_TIMEOUT", 0.01)
    cleaned = []
    async def operation():
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.append(True)
    with pytest.raises(TimeoutError, match="TOOL_TIMEOUT"):
        await run_with_deadline(operation())
    assert cleaned == [True]


@pytest.mark.asyncio
async def test_ignored_cancellation_is_fatal_instead_of_retryable_failure(monkeypatch):
    import server.agent.tool_deadline as deadlines
    monkeypatch.setattr(deadlines, "TOOL_WALL_TIMEOUT", 0.01)
    monkeypatch.setattr(deadlines, "TOOL_CANCEL_GRACE", 0.01)
    release, stopped = asyncio.Event(), asyncio.Event()
    async def operation():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
        finally:
            stopped.set()
    try:
        with pytest.raises(ToolCancellationUnconfirmed):
            await AgentEngine(None)._call_tool_handler(operation, ToolCall("x", "fake", {}), None, 0)
    finally:
        release.set()
        await asyncio.wait_for(stopped.wait(), 1)


@pytest.mark.asyncio
async def test_iteration_exhaustion_never_emits_success(monkeypatch):
    engine = AgentEngine(None)
    events = []
    monkeypatch.setattr(engine, "_persist_session_transcript", lambda *_: None)
    session = AgentSession(iterations=1, max_iterations=1)
    loop = AgentLoopCoordinator(engine, session.id, "offline", events.append, None, 64, None, None)
    state = LoopState(session, [], False, [], "offline", None)
    with pytest.raises(RuntimeError, match="AGENT_ITERATION_LIMIT"):
        await loop._complete(state)
    assert session.status == AgentStatus.ERROR
    assert not any(event.type == "done" for event in events)


def test_receipts_and_failure_budget_survive_session_restore(tmp_path):
    from server.agent.session_persistence import persist_session_transcript, restore_session
    from server.agent import Message
    session = AgentSession(project_path=str(tmp_path), messages=[Message(role="user", content="offline")],
                           tool_failure_counts={"fingerprint:TOOL_SCHEMA_ERROR": 3},
                           tool_receipts=[{"error_code": "TOOL_SCHEMA_ERROR", "tool_call_id": "x"}])
    persist_session_transcript(session)
    restored = restore_session({}, session.id, str(tmp_path))
    assert restored.tool_receipts == session.tool_receipts
    assert FailureBudget(restored.tool_failure_counts).exhausted("fingerprint")


@pytest.mark.asyncio
async def test_unconfirmed_cancellation_cannot_enter_workflow_repair_or_text_fallback(monkeypatch):
    from server.workflows.engine import WorkflowEngine
    from server.workflows.node_execution_invocation import _other_failure
    import server.workflows.node_execution_invocation as invocation

    error = ToolCancellationUnconfirmed("TOOL_CLEANUP_UNCONFIRMED: timeout")
    assert not WorkflowEngine._is_recoverable_research_error(error)
    assert not WorkflowEngine._is_transport_research_error(error)
    async def noop(*args):
        return None
    async def forbidden(**kwargs):
        pytest.fail("fatal cancellation must not generate fallback text")
    context = SimpleNamespace(host=SimpleNamespace(
        _can_text_fallback=lambda *args: True,
        _is_transport_research_error=lambda *args: False,
        _persist_search_evidence=lambda *args: None,
        _execute_node_text_fallback=forbidden,
    ), node=None, run=None, opts={}, enabled_tools=[], search_tool_trace=[])
    monkeypatch.setattr(invocation, "_mark_failed", lambda *args: None)
    monkeypatch.setattr(invocation, "_failure_event", noop)
    monkeypatch.setattr(invocation, "_persist_partial", noop)
    with pytest.raises(ToolCancellationUnconfirmed):
        await _other_failure(context, error)
