"""Reserve a research project while Chat tools generate or compile artifacts."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import time
import uuid

from ..utils.atomic_write import atomic_write_json
from ..workflows.workflow_lease import ProjectRunLease
from .research_change_application import _invalidate_runs, affected_phases

_TARGETS = {
    "generate_figure": "figures/", "scaffold_paper": "paper/", "latex_compile": "paper/main.pdf",
}
_cleanup_monitors: set[asyncio.Task] = set()


async def _hold_for_cleanup(lease, token: str, run_id: str, session_id: str) -> None:
    from ..agent.tool_deadline import assert_session_quiescent

    while True:
        try:
            assert_session_quiescent(session_id)
        except ValueError:
            if not lease.renew(token, run_id=run_id, lease_seconds=120):
                raise RuntimeError("Research edit lost its cleanup lease")
            await asyncio.sleep(20)
        else:
            lease.release(token, run_id=run_id)
            return


async def _renew_lease(lease: ProjectRunLease, token: str, run_id: str, owner: asyncio.Task) -> None:
    while True:
        await asyncio.sleep(20)
        try:
            if not lease.renew(token, run_id=run_id, lease_seconds=120):
                owner.cancel()
                return
        except Exception:
            owner.cancel()
            raise


@asynccontextmanager
async def chat_runtime_revision(session, tool_name: str, arguments: dict | None = None):
    """Invalidate before possible writes, including partial writes on failure."""
    if session.tool_policy != "research_artifacts" or tool_name not in _TARGETS:
        yield None
        return
    root = Path(session.project_path).resolve()
    identity = uuid.uuid4().hex[:12]
    run_id = f"chat-edit-{identity}"
    lease = ProjectRunLease(str(root))
    token = lease.claim(run_id=run_id, owner_id=session.id, source="chat", lease_seconds=120)
    if not token:
        raise RuntimeError("A workflow or research edit is active; retry after it finishes or is paused")
    receipt = {"schema_version": 1, "id": identity, "status": "prepared", "source": "chat_tool",
               "tool": tool_name, "path": _TARGETS[tool_name], "created_at": time.time()}
    receipt["affected_phases"] = (["compile", "ppt"] if tool_name == "latex_compile"
                                  else affected_phases(receipt["path"]))
    if tool_name == "latex_compile" and (arguments or {}).get("project_dir"):
        target = Path(arguments["project_dir"]).resolve()
        if target.is_relative_to(root / "slides"):
            receipt.update(path="slides/", affected_phases=["ppt"])
    path = root / ".merak/research-edits" / f"{identity}.json"
    heartbeat = asyncio.create_task(_renew_lease(lease, token, run_id, asyncio.current_task()))
    try:
        atomic_write_json(path, receipt)
        receipt["affected_runs"] = _invalidate_runs(root, receipt["affected_phases"], receipt)
        atomic_write_json(path, receipt)
        yield receipt
    except Exception as exc:
        from ..agent.tool_deadline import ToolCancellationUnconfirmed
        if isinstance(exc, ToolCancellationUnconfirmed):
            receipt["cleanup_unconfirmed"] = True
        receipt["status"] = "interrupted"
        raise
    except BaseException:
        receipt["status"] = "interrupted"
        raise
    finally:
        try:
            atomic_write_json(path, {**receipt, "finished_at": time.time()})
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            if not receipt.get("cleanup_unconfirmed"):
                lease.release(token, run_id=run_id)
            else:
                cleanup = asyncio.create_task(_hold_for_cleanup(lease, token, run_id, session.id))
                _cleanup_monitors.add(cleanup)
                cleanup.add_done_callback(_cleanup_monitors.discard)
