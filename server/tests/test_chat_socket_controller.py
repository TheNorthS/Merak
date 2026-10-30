from __future__ import annotations

import asyncio
import json

from server.api.chat_socket_controller import ChatSocketController


class FakeSocket:
    def __init__(self, messages: list[str] | None = None) -> None:
        self.messages = list(messages or [])
        self.sent: list[dict] = []

    async def receive_text(self) -> str:
        return self.messages.pop(0)

    async def send_text(self, payload: str) -> None:
        self.sent.append(json.loads(payload))


def test_invalid_json_is_reported_without_dispatching() -> None:
    socket = FakeSocket(["{broken"])
    controller = ChatSocketController(socket)

    message = asyncio.run(controller._receive_message())

    assert message is None
    assert socket.sent[0]["type"] == "protocol_error"
    assert "Invalid JSON" in socket.sent[0]["error"]


def test_unknown_message_type_fails_closed() -> None:
    socket = FakeSocket()
    controller = ChatSocketController(socket)

    asyncio.run(controller._dispatch({"type": "unexpected"}))

    assert socket.sent == [{
        "type": "protocol_error",
        "error": "Unsupported chat message type: unexpected",
    }]


def test_ping_uses_serialized_response_envelope() -> None:
    socket = FakeSocket()
    controller = ChatSocketController(socket)

    asyncio.run(controller._dispatch({"type": "ping"}))

    assert socket.sent == [{"type": "pong"}]


def test_connection_cleanup_cancels_every_owned_task() -> None:
    socket = FakeSocket()
    controller = ChatSocketController(socket)

    async def exercise() -> None:
        tasks = {
            asyncio.create_task(asyncio.Event().wait()),
            asyncio.create_task(asyncio.Event().wait()),
        }
        controller.tasks.update(tasks)
        await controller._cancel_connection_tasks()
        assert all(task.cancelled() for task in tasks)

    asyncio.run(exercise())
