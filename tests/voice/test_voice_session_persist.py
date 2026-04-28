"""Engine-sync persistence tests for VoiceSession (and parallel coverage
for VoiceSplitSession).

Verifies that ASR finals and agent text from voice sessions write to
the conversation engine and push a message frame to the customer's
/ws/customer registry entry, so voice utterances appear in chat history.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from channels.web.voice.session import VoiceSession
from channels.web.voice.session_split import VoiceSplitSession


class _FakeEngine:
    def __init__(self):
        self.calls: list[dict] = []

    async def send_message(
        self, conv_id, *, source, content, metadata=None,
        requested_visibility=None,
    ):
        self.calls.append({
            "conv_id": conv_id, "source": source,
            "content": content, "metadata": metadata,
        })
        return SimpleNamespace(
            id=f"m{len(self.calls)}",
            conversation_id=conv_id,
            source=source,
            content=content,
            visibility=SimpleNamespace(value="public"),
            sequence_number=len(self.calls),
            timestamp=datetime.now(timezone.utc),
            edit_of=None,
            metadata=dict(metadata or {}),
        )


class _FakeCustomerWs:
    def __init__(self):
        self.frames: list[dict] = []

    async def send_json(self, frame):
        self.frames.append(frame)


def _fake_browser_ws(engine):
    """Stand-in for a FastAPI WebSocket — only the `.app.state.engine`
    path is used by _persist_to_engine."""
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(engine=engine)),
    )


@pytest.fixture
def conv_id():
    return "conv_voice_persist"


@pytest.fixture
def fake_engine():
    return _FakeEngine()


@pytest.fixture
def fake_cust_ws(conv_id):
    from autoservice.gateway.message_router import _customer_ws_by_conv
    ws = _FakeCustomerWs()
    _customer_ws_by_conv[conv_id] = ws
    yield ws
    _customer_ws_by_conv.pop(conv_id, None)


async def test_voice_session_persists_user_text_with_voice_metadata(
    fake_engine, fake_cust_ws, conv_id,
):
    sess = VoiceSession(
        _fake_browser_ws(fake_engine),
        conversation_id=conv_id, tenant_id="tnt_a",
    )
    sess._customer_source = "cust_test_user"
    await sess._persist_user_text("我想问个问题")

    # User voice text MUST hit the engine (history / operator visibility)…
    assert len(fake_engine.calls) == 1
    call = fake_engine.calls[0]
    assert call["conv_id"] == conv_id
    assert call["source"] == "cust_test_user"
    assert call["content"] == "我想问个问题"
    assert call["metadata"] == {"voice": True}

    # …but MUST NOT push back to the customer's own chat WS — frontend
    # already inserted an optimistic right-side bubble on the ASR final.
    # A push would render a duplicate bubble next to the optimistic one.
    assert fake_cust_ws.frames == []


async def test_voice_session_persists_agent_text_with_voice_metadata(
    fake_engine, fake_cust_ws, conv_id,
):
    sess = VoiceSession(
        _fake_browser_ws(fake_engine),
        conversation_id=conv_id, tenant_id="tnt_a",
    )
    await sess._persist_agent_text("好的，请稍等")

    assert len(fake_engine.calls) == 1
    assert fake_engine.calls[0]["source"] == "agent"
    assert fake_engine.calls[0]["metadata"] == {"voice": True}
    assert fake_cust_ws.frames[0]["payload"]["message"]["content"] == "好的，请稍等"


async def test_voice_session_greeting_persist_carries_voice_greeting_flag(
    fake_engine, fake_cust_ws, conv_id,
):
    """The connect_and_greet path tags the greeting with voice_greeting:True
    so the frontend's voice-forward useEffect can dedupe it."""
    sess = VoiceSession(
        _fake_browser_ws(fake_engine),
        conversation_id=conv_id, tenant_id="tnt_a",
    )
    await sess._persist_agent_text(
        "你好，请问有什么可以帮你？",
        extra_metadata={"voice_greeting": True},
    )
    assert fake_engine.calls[0]["metadata"] == {
        "voice": True, "voice_greeting": True,
    }


async def test_voice_session_skips_persist_without_conversation_id(fake_engine):
    """Running with no conv_id (e.g. user opened voice before the chat
    session was assigned) should silently no-op — voice still works,
    just without chat-history sync."""
    sess = VoiceSession(
        _fake_browser_ws(fake_engine),
        conversation_id=None,
    )
    await sess._persist_user_text("hi")
    await sess._persist_agent_text("hello")
    assert fake_engine.calls == []


async def test_voice_session_skips_persist_when_engine_missing():
    """If app.state lacks engine (smoke test / minimal mount), do nothing."""
    ws = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    sess = VoiceSession(ws, conversation_id="conv_x")
    # Must not raise.
    await sess._persist_user_text("hi")


async def test_voice_split_session_persists_with_voice_metadata(
    fake_engine, fake_cust_ws, conv_id,
):
    """Same persistence contract for split mode."""
    sess = VoiceSplitSession(
        _fake_browser_ws(fake_engine),
        conversation_id=conv_id, tenant_id="tnt_a",
    )
    sess._customer_source = "cust_split_user"
    await sess._persist_user_text("split hello")
    await sess._persist_agent_text("split reply")

    # Engine sees both messages; chat WS only sees the agent one
    # (user text relies on the frontend's optimistic bubble).
    assert len(fake_cust_ws.frames) == 1
    assert fake_cust_ws.frames[0]["payload"]["message"]["content"] == "split reply"

    sources = [c["source"] for c in fake_engine.calls]
    assert sources == ["cust_split_user", "agent"]
    metadatas = [c["metadata"] for c in fake_engine.calls]
    assert all(m == {"voice": True} for m in metadatas)
