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
