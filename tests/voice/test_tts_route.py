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
    with patch("channels.web.voice.tts_route.TTSClient", return_value=FakeTTSClient()):
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

    with patch("channels.web.voice.tts_route.TTSClient", return_value=SlowTTS()):
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

    with patch("channels.web.voice.tts_route.TTSClient", return_value=ExplodingTTS()):
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
