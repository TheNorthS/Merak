"""Keep incomplete text in the conversation without calling it a completed turn."""
from __future__ import annotations

from typing import Any

from . import Message


class ModelAttemptObservation:
    def __init__(self, engine: Any, session: Any, callback: Any):
        self.engine, self.session, self.callback = engine, session, callback
        self.text = ""

    async def emit(self, event: Any) -> None:
        if event.type == "text" and event.data:
            self.text = (self.text + str(event.data))[-16000:]
        await self.engine._emit(self.callback, event)

    def persist_interrupted(self) -> bool:
        if not self.text:
            return False
        self.session.messages.append(Message(role="assistant", content=self.text))
        self.session.messages.append(Message(role="user", content=(
            "The preceding response was interrupted and is not proof of delivery. "
            "On manual continuation inspect saved files and tool receipts before writing. "
            "Never replay deployments or scientific execution without checking their runtime state."
        )))
        self.engine._persist_session_transcript(self.session)
        return True
