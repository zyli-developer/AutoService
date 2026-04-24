"""FastAPI WebSocket test for /asr route.

Ported from cc-openclaw/voice_gateway/tests/test_asr_route.py — aiohttp
TestClient replaced with fastapi.testclient.TestClient.websocket_connect.
Uses a FakeASRClient to avoid hitting the real Doubao service.
"""
import json
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from channels.web.voice.asr_route import asr_endpoint


class FakeASRClient:
    def __init__(self):
        self.connected = False
        self.audio_chunks = []
        self._events = []

    async def connect(self):
        self.connected = True

    async def send_audio(self, data: bytes):
        self.audio_chunks.append(data)

    async def receive(self):
        for ev in self._events:
            yield ev

    async def close(self):
        self.connected = False

    def enqueue(self, event: dict):
        self._events.append(event)


def _build_app(fake_cls):
    app = FastAPI()
    # asr_endpoint uses channels.web.voice.asr_route.ASRClient symbol,
    # which we patch to the fake class.
    app.add_api_websocket_route("/asr", asr_endpoint)
    return app


def test_asr_route_forwards_final_event_as_simple_frame():
    fake = FakeASRClient()
    fake.enqueue({
        "type": "conversation.item.input_audio_transcription.completed",
        "transcript": "hello world",
    })

    with patch("channels.web.voice.asr_route.ASRClient", return_value=fake):
        app = _build_app(FakeASRClient)
        with TestClient(app) as client:
            with client.websocket_connect("/asr") as ws:
                ws.send_json({"type": "start"})
                raw = ws.receive_text()
                data = json.loads(raw)
                assert data == {"type": "final", "text": "hello world"}


def test_asr_route_forwards_partial_and_speech_started():
    fake = FakeASRClient()
    fake.enqueue({"type": "input_audio_buffer.speech_started"})
    fake.enqueue({
        "type": "conversation.item.input_audio_transcription.result",
        "transcript": "hel",
    })

    with patch("channels.web.voice.asr_route.ASRClient", return_value=fake):
        app = _build_app(FakeASRClient)
        with TestClient(app) as client:
            with client.websocket_connect("/asr") as ws:
                ws.send_json({"type": "start"})
                got = [json.loads(ws.receive_text()) for _ in range(2)]
                assert {"type": "speech_started"} in got
                assert {"type": "partial", "text": "hel"} in got


def test_asr_route_surfaces_backend_exception_to_browser():
    """Proves that an exception raised from ASRClient.receive() gets forwarded
    to the browser as an error frame instead of being silently dropped."""
    class ExplodingASR:
        async def connect(self):
            return None

        async def send_audio(self, data: bytes):
            return None

        async def receive(self):
            raise RuntimeError("upstream died")
            yield  # pragma: no cover — makes this an async generator

        async def close(self):
            return None

    with patch("channels.web.voice.asr_route.ASRClient", return_value=ExplodingASR()):
        app = FastAPI()
        app.add_api_websocket_route("/asr", asr_endpoint)
        with TestClient(app) as client:
            with client.websocket_connect("/asr") as ws:
                ws.send_json({"type": "start"})
                raw = ws.receive_text()
                data = json.loads(raw)
                assert data["type"] == "error"
                assert "upstream died" in data["message"]


def test_asr_route_rejects_invalid_start_frame_without_instantiating_client():
    """Proves that a malformed start frame fails fast — ASRClient() is not
    instantiated, so its close() is not called on a never-connected client."""
    instantiated = []

    class TrackingASR:
        def __init__(self):
            instantiated.append(self)

        async def connect(self):
            raise AssertionError("connect() must not be called for invalid start frame")

        async def close(self):
            raise AssertionError("close() must not be called on a client that never connected")

    with patch("channels.web.voice.asr_route.ASRClient", TrackingASR):
        app = FastAPI()
        app.add_api_websocket_route("/asr", asr_endpoint)
        with TestClient(app) as client:
            with client.websocket_connect("/asr") as ws:
                ws.send_text("not json")
                raw = ws.receive_text()
                data = json.loads(raw)
                assert data["type"] == "error"
                assert data["message"] == "invalid start frame"

    assert instantiated == [], "ASRClient should not be instantiated on invalid start frame"
