"""Tests for CCChatClient — same-process direct cc_pool invocation
for the SIP voice path.

Naming follows 08 doc, but the implementation calls cc_pool.session_query()
directly instead of going through ws://127.0.0.1:8000/ws/chat (08 spec
is broken: /ws/chat lives in M1 legacy channels/web/app.py, not in
web_gateway where /sip-audio runs). See cc_chat_client.py docstring.
"""
from dataclasses import dataclass

import pytest

from channels.web.voice.cc_chat_client import CCChatClient


@dataclass
class _FakeTextBlock:
    text: str


@dataclass
class _FakeToolUseBlock:
    name: str
    input: dict


@dataclass
class _FakeAssistantMessage:
    content: list


class _FakePool:
    """Records session_query / end_session calls; returns canned messages."""

    def __init__(self, scripted_messages_per_query: list[list] | None = None):
        self._scripted = scripted_messages_per_query or []
        self.session_query_calls: list[dict] = []
        self.end_session_calls: list[str] = []
        self._end_session_raises: Exception | None = None

    def will_raise_on_end_session(self, exc: Exception) -> None:
        self._end_session_raises = exc

    def session_query(self, *, chat_id, prompt, tenant_id=None, tier=None, **_):
        self.session_query_calls.append(
            {"chat_id": chat_id, "prompt": prompt, "tenant_id": tenant_id, "tier": tier},
        )
        idx = len(self.session_query_calls) - 1
        msgs = self._scripted[idx] if idx < len(self._scripted) else []

        async def gen():
            for m in msgs:
                yield m

        return gen()

    async def end_session(self, chat_id: str) -> None:
        self.end_session_calls.append(chat_id)
        if self._end_session_raises is not None:
            raise self._end_session_raises


@pytest.mark.asyncio
async def test_send_concatenates_text_blocks_from_assistant_messages():
    pool = _FakePool(scripted_messages_per_query=[[
        _FakeAssistantMessage(content=[_FakeTextBlock(text="Hello, ")]),
        _FakeAssistantMessage(content=[_FakeTextBlock(text="how can I help?")]),
    ]])
    bridge = CCChatClient(call_sid="call-1", caller="+85212345678", pool=pool)
    await bridge.connect()

    reply = await bridge.send("hi")

    assert reply == "Hello, how can I help?"


@pytest.mark.asyncio
async def test_send_passes_call_sid_as_chat_id_with_fast_tier():
    pool = _FakePool(scripted_messages_per_query=[[]])
    bridge = CCChatClient(
        call_sid="abc-123", caller="+1", tenant_id="t1", pool=pool,
    )
    await bridge.connect()
    await bridge.send("question")

    assert pool.session_query_calls == [{
        "chat_id": "abc-123",
        "prompt": "question",
        "tenant_id": "t1",
        "tier": "fast",
    }]


@pytest.mark.asyncio
async def test_send_ignores_non_text_blocks():
    """ToolUse / unknown blocks must not appear in the audible reply."""
    pool = _FakePool(scripted_messages_per_query=[[
        _FakeAssistantMessage(content=[
            _FakeTextBlock(text="OK"),
            _FakeToolUseBlock(name="lookup", input={"q": "x"}),
            _FakeTextBlock(text=" done."),
        ]),
    ]])
    bridge = CCChatClient(call_sid="c", caller="+1", pool=pool)
    await bridge.connect()

    reply = await bridge.send("x")

    assert reply == "OK done."


@pytest.mark.asyncio
async def test_send_returns_empty_string_when_no_text_messages():
    """Pool yields tool-only messages → bridge returns empty (controller
    will handle with fallback message, not crash)."""
    pool = _FakePool(scripted_messages_per_query=[[
        _FakeAssistantMessage(content=[_FakeToolUseBlock(name="x", input={})]),
    ]])
    bridge = CCChatClient(call_sid="c", caller="+1", pool=pool)
    await bridge.connect()

    reply = await bridge.send("x")

    assert reply == ""


@pytest.mark.asyncio
async def test_close_calls_end_session_with_call_sid():
    pool = _FakePool()
    bridge = CCChatClient(call_sid="release-me", caller="+1", pool=pool)
    await bridge.connect()

    await bridge.close()

    assert pool.end_session_calls == ["release-me"]


@pytest.mark.asyncio
async def test_close_swallows_end_session_errors():
    """A failing end_session must not cascade into the controller cleanup
    (controller's shutdown() iterates multiple closes; one failure must
    not skip the others)."""
    pool = _FakePool()
    pool.will_raise_on_end_session(RuntimeError("pool gone"))
    bridge = CCChatClient(call_sid="c", caller="+1", pool=pool)
    await bridge.connect()

    # Must not raise
    await bridge.close()
    assert pool.end_session_calls == ["c"]


@pytest.mark.asyncio
async def test_close_before_connect_is_noop():
    """Defensive: shutdown path may run before connect succeeded."""
    bridge = CCChatClient(call_sid="c", caller="+1")
    # No pool injected, no connect called — close must be safe
    await bridge.close()


@pytest.mark.asyncio
async def test_send_propagates_pool_exception():
    """Cc_pool errors must propagate so controller's try/except can
    speak the fallback ('抱歉，我这边出了点问题')."""
    class ExplodingPool:
        def session_query(self, **_):
            async def gen():
                yield _FakeAssistantMessage(content=[_FakeTextBlock(text="partial")])
                raise RuntimeError("pool died mid-stream")
            return gen()

        async def end_session(self, chat_id):
            pass

    bridge = CCChatClient(call_sid="c", caller="+1", pool=ExplodingPool())
    await bridge.connect()

    with pytest.raises(RuntimeError, match="pool died"):
        await bridge.send("x")
