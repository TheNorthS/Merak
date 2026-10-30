"""Propagate child activity without attributing child writes or private text to its parent."""

from contextvars import ContextVar
import inspect
from typing import Any

from .session_models import AgentEvent


delegate_observer: ContextVar[Any] = ContextVar("delegate_activity_observer", default=None)


async def run_observed_delegate(handler: Any, arguments: dict, observer: Any) -> Any:
    token = delegate_observer.set(observer)
    try:
        return await handler(**arguments)
    finally:
        delegate_observer.reset(token)


def parent_activity_callback(skill: str):
    observer = delegate_observer.get()
    if observer is None:
        return None

    async def notify(event: Any) -> None:
        kind = str(getattr(event, "type", ""))
        data = event.data if isinstance(getattr(event, "data", None), dict) else {}
        if kind not in {"tool_call", "tool_result", "text", "done", "error"}:
            return
        if kind == "text" and not str(data.get("text") or data.get("content") or "").strip():
            return
        summary = {"kind": "delegate_activity", "title": f"子技能活动：{skill}",
            "detail": f"{kind}: {str(data.get('name') or '')[:80]}", "skill": skill, "event_kind": kind}
        result = observer(AgentEvent(type="step", data=summary))
        if inspect.isawaitable(result):
            await result
    return notify
