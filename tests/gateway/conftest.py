"""Shared fixtures for tests/gateway (T0.5)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import pytest
from starlette.testclient import TestClient

from autoservice.conversation_engine import (
    LocalEngine,
    Message,
    MessageVisibility,
)
from autoservice.web_gateway import create_app


class DummyEngine:
    """Configurable ConversationEngine-compatible stub for gateway tests.

    Only `send_message` / `handle_command` are exercised by current tests; other
    Protocol methods are absent and will AttributeError if called (tests should
    avoid triggering them).
    """

    def __init__(self) -> None:
        self._send_message_impl: Callable[..., Awaitable[Message]] | None = None
        self._handle_command_impl: Callable[..., Awaitable[None]] | None = None
        self._known_convs: set[str] = set()

    def set_send_message(self, impl: Callable[..., Awaitable[Message]]) -> None:
        self._send_message_impl = impl

    def set_handle_command(self, impl: Callable[..., Awaitable[None]]) -> None:
        self._handle_command_impl = impl

    async def get_conversation(self, conversation_id: str) -> Any:
        """Stub: return minimal conv if in known set, else raise."""
        from autoservice.conversation_engine.errors import ConversationNotFound
        if conversation_id in self._known_convs:
            from types import SimpleNamespace
            return SimpleNamespace(id=conversation_id)
        raise ConversationNotFound(conversation_id)

    async def create_conversation(self, **kwargs: Any) -> Any:
        """Stub: return a minimal object with .id and remember it."""
        from types import SimpleNamespace
        ext = kwargs.get("external_id", "customer")
        channel = kwargs.get("channel", "web")
        conv_id = f"{channel}_{ext}"
        self._known_convs.add(conv_id)
        return SimpleNamespace(id=conv_id)

    async def join(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def send_message(self, *args: Any, **kwargs: Any) -> Message:
        if self._send_message_impl is None:
            raise AssertionError("DummyEngine.send_message not configured")
        return await self._send_message_impl(*args, **kwargs)

    async def handle_command(self, *args: Any, **kwargs: Any) -> None:
        if self._handle_command_impl is None:
            raise AssertionError("DummyEngine.handle_command not configured")
        return await self._handle_command_impl(*args, **kwargs)


@pytest.fixture
def local_engine_app():
    return create_app()


@pytest.fixture
def local_engine_client(local_engine_app):
    return TestClient(local_engine_app)


@pytest.fixture
def dummy_engine() -> DummyEngine:
    return DummyEngine()


@pytest.fixture
def dummy_engine_app(dummy_engine):
    return create_app(engine=dummy_engine)


@pytest.fixture
def dummy_engine_client(dummy_engine_app):
    return TestClient(dummy_engine_app)


def make_frame(
    type_: str,
    payload: dict | None = None,
    *,
    v: int = 1,
    ref: str | None = None,
    id_: str | None = None,
    ts: str | None = None,
) -> dict:
    """Build a FE→BE envelope with sensible defaults."""
    now = datetime.now(timezone.utc)
    frame: dict[str, Any] = {
        "v": v,
        "type": type_,
        "id": id_ if id_ is not None else str(uuid.uuid4()),
        "ts": ts
        if ts is not None
        else now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z",
        "payload": payload or {},
    }
    if ref is not None:
        frame["ref"] = ref
    return frame


def handshake(ws, *, viewer_role_expected: str) -> dict:
    """Perform the client_hello → server_hello exchange; assert basic shape."""
    hello = make_frame("client_hello", {"protocol_version": 1, "client_app": "web"})
    ws.send_json(hello)
    reply = ws.receive_json()
    assert reply["type"] == "server_hello"
    assert reply["payload"]["viewer_role"] == viewer_role_expected
    return reply


def make_message(
    *,
    msg_id: str = "01HXMSG00000000000000000AA",
    conversation_id: str = "c-1",
    source: str = "fast-agent",
    content: str = "hello",
    sequence_number: int = 1,
) -> Message:
    """Build a Message dataclass suitable for DummyEngine.send_message to return."""
    return Message(
        id=msg_id,
        conversation_id=conversation_id,
        source=source,
        content=content,
        visibility=MessageVisibility.PUBLIC,
        timestamp=datetime.now(timezone.utc),
        sequence_number=sequence_number,
    )


__all__ = [
    "DummyEngine",
    "make_frame",
    "handshake",
    "make_message",
]
