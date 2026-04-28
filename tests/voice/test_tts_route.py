"""FastAPI WebSocket test for /tts route.

Ported from cc-openclaw/voice_gateway/tests/test_tts_route.py — aiohttp
TestClient replaced with fastapi.testclient.TestClient.websocket_connect.
Uses FakeTTSClient / SlowTTS doubles to avoid hitting real Doubao.
"""
import asyncio
import json
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from channels.web.voice.tts_route import tts_endpoint


class FakeTTSClient:
    def __init__(self):
        self.connected = False

    async def connect(self):
        self.connected = True

    async def synthesize(self, text: str):
        yield b"\x00\x01" * 100
        yield b"\x02\x03" * 100

    async def close(self):
        self.connected = False


def _build_app():
    app = FastAPI()
    app.add_api_websocket_route("/tts", tts_endpoint)
    return app


def test_tts_route_streams_audio_then_done():
    # Disable auto-greet so this test exercises the client-driven speak path
    # without interleaved greeting frames.
    with patch("channels.web.voice.tts_route.GREETING_TEXT", ""), \
         patch("channels.web.voice.tts_route.TTSClient", return_value=FakeTTSClient()):
        app = _build_app()
        with TestClient(app) as client:
            with client.websocket_connect("/tts") as ws:
                ws.send_json({"type": "speak", "text": "hi"})

                binary_chunks = 0
                got_done = False
                for _ in range(10):
                    msg = ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    if "bytes" in msg and msg["bytes"] is not None:
                        binary_chunks += 1
                    elif "text" in msg and msg["text"] is not None:
                        data = json.loads(msg["text"])
                        if data.get("type") == "done":
                            got_done = True
                            break

                assert binary_chunks == 2
                assert got_done


def test_tts_route_auto_greets_after_connect():
    """Backend-driven greeting: connecting the /tts WS triggers a speak
    of GREETING_TEXT immediately after the upstream is ready, without any
    client frame."""
    seen_texts: list[str] = []

    class RecordingTTS:
        async def connect(self):
            return None

        async def synthesize(self, text: str):
            seen_texts.append(text)
            yield b"G" * 50

        async def close(self):
            return None

    with patch("channels.web.voice.tts_route.GREETING_TEXT", "你好欢迎"), \
         patch("channels.web.voice.tts_route.TTSClient", return_value=RecordingTTS()):
        app = _build_app()
        with TestClient(app) as client:
            with client.websocket_connect("/tts") as ws:
                # Do NOT send any client frame — the greeting must arrive
                # purely from the backend's post-connect auto-fire.
                got_audio = False
                got_done = False
                for _ in range(10):
                    msg = ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    if "bytes" in msg and msg["bytes"] is not None:
                        got_audio = True
                    elif "text" in msg and msg["text"] is not None:
                        data = json.loads(msg["text"])
                        if data.get("type") == "done":
                            got_done = True
                            break

                assert got_audio, "no greeting audio arrived"
                assert got_done, "greeting did not emit done"
                assert seen_texts == ["你好欢迎"], (
                    f"expected synthesize called once with greeting text, "
                    f"got {seen_texts!r}"
                )


def test_tts_route_abort_then_speak_no_interleaved_audio():
    class SlowTTS:
        async def connect(self):
            pass

        async def synthesize(self, text: str):
            if text == "first":
                yield b"A" * 100
                await asyncio.sleep(0.2)
                yield b"A" * 100  # should never reach the browser
            else:
                yield b"B" * 100

        async def close(self):
            pass

    with patch("channels.web.voice.tts_route.GREETING_TEXT", ""), \
         patch("channels.web.voice.tts_route.TTSClient", return_value=SlowTTS()):
        app = _build_app()
        with TestClient(app) as client:
            with client.websocket_connect("/tts") as ws:
                ws.send_json({"type": "speak", "text": "first"})

                msg = ws.receive()
                assert "bytes" in msg and msg["bytes"] == b"A" * 100

                ws.send_json({"type": "abort"})
                ws.send_json({"type": "speak", "text": "second"})

                stray_A = 0
                got_done = False
                for _ in range(10):
                    msg = ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    if "bytes" in msg and msg["bytes"] is not None:
                        if b"A" in msg["bytes"]:
                            stray_A += 1
                        else:
                            assert msg["bytes"] == b"B" * 100
                    elif "text" in msg and msg["text"] is not None:
                        data = json.loads(msg["text"])
                        if data.get("type") == "done":
                            got_done = True
                            break

                assert stray_A == 0, "post-abort PCM from cancelled task leaked"
                assert got_done


async def test_persist_greeting_writes_chat_message_with_metadata():
    """Issue #1 fix: backend auto-greet also persists an `agent` message
    into the conversation engine and pushes the frame to the customer's
    chat WS so the greeting appears as a bubble in chat history."""
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from channels.web.voice.tts_route import _persist_greeting_in_chat
    from autoservice.gateway.message_router import _customer_ws_by_conv

    sent: list[dict] = []

    class FakeEngine:
        async def send_message(
            self, conv_id, *, source, content, metadata=None,
            requested_visibility=None,
        ):
            sent.append({
                "conv_id": conv_id, "source": source,
                "content": content, "metadata": metadata,
            })
            return SimpleNamespace(
                id="msg_g1",
                conversation_id=conv_id,
                source=source,
                content=content,
                visibility=SimpleNamespace(value="public"),
                sequence_number=1,
                timestamp=datetime.now(timezone.utc),
                edit_of=None,
                metadata=dict(metadata or {}),
            )

    pushed: list[dict] = []

    class FakeCustomerWs:
        async def send_json(self, frame):
            pushed.append(frame)

    fake_app = SimpleNamespace(
        state=SimpleNamespace(engine=FakeEngine()),
    )
    _customer_ws_by_conv["conv_test_persist"] = FakeCustomerWs()
    try:
        await _persist_greeting_in_chat(
            fake_app, "conv_test_persist", "你好欢迎",
        )
        # Engine receives the agent message with voice_greeting metadata so
        # frontend can dedupe (App.tsx skips voice_greeting bubbles in the
        # voice-forward useEffect).
        assert len(sent) == 1
        assert sent[0] == {
            "conv_id": "conv_test_persist",
            "source": "agent",
            "content": "你好欢迎",
            "metadata": {"voice_greeting": True},
        }
        # Frame pushed to customer WS so bubble appears immediately,
        # without waiting for engine subscription fan-out.
        assert len(pushed) == 1
        frame = pushed[0]
        assert frame["type"] == "message"
        assert frame["payload"]["message"]["content"] == "你好欢迎"
        assert frame["payload"]["message"]["metadata"]["voice_greeting"] is True
    finally:
        _customer_ws_by_conv.pop("conv_test_persist", None)


async def test_persist_greeting_no_engine_in_app_state_is_safe():
    """If the helper is invoked on an app whose state lacks `engine` (e.g.
    /tts mounted standalone without web_gateway init), it logs and returns
    without raising."""
    from types import SimpleNamespace
    from channels.web.voice.tts_route import _persist_greeting_in_chat

    fake_app = SimpleNamespace(state=SimpleNamespace())
    # Should not raise.
    await _persist_greeting_in_chat(fake_app, "conv_x", "你好")


async def test_persist_greeting_no_customer_ws_persists_but_skips_push():
    """If no customer WS is registered for this conversation (e.g. user
    opens voice before chat server_hello finalised), the message is still
    persisted; the frame just isn't pushed."""
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from channels.web.voice.tts_route import _persist_greeting_in_chat
    from autoservice.gateway.message_router import _customer_ws_by_conv

    sent: list[str] = []

    class FakeEngine:
        async def send_message(
            self, conv_id, *, source, content, metadata=None,
            requested_visibility=None,
        ):
            sent.append(content)
            return SimpleNamespace(
                id="m", conversation_id=conv_id, source=source,
                content=content,
                visibility=SimpleNamespace(value="public"),
                sequence_number=1, timestamp=datetime.now(timezone.utc),
                edit_of=None, metadata=dict(metadata or {}),
            )

    fake_app = SimpleNamespace(state=SimpleNamespace(engine=FakeEngine()))
    _customer_ws_by_conv.pop("conv_no_ws", None)
    await _persist_greeting_in_chat(fake_app, "conv_no_ws", "你好")
    assert sent == ["你好"]


def test_tts_route_surfaces_backend_exception_to_browser():
    """Proves an exception raised mid-synthesize is forwarded as {type: error}."""
    class ExplodingTTS:
        async def connect(self):
            return None

        async def synthesize(self, text: str):
            yield b"X" * 10
            raise RuntimeError("upstream died")

        async def close(self):
            return None

    with patch("channels.web.voice.tts_route.GREETING_TEXT", ""), \
         patch("channels.web.voice.tts_route.TTSClient", return_value=ExplodingTTS()):
        app = _build_app()
        with TestClient(app) as client:
            with client.websocket_connect("/tts") as ws:
                ws.send_json({"type": "speak", "text": "hello"})

                saw_error = False
                for _ in range(10):
                    msg = ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    if "text" in msg and msg["text"] is not None:
                        data = json.loads(msg["text"])
                        if data.get("type") == "error":
                            saw_error = True
                            assert "upstream died" in data["message"]
                            break

                assert saw_error
