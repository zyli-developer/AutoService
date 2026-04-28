"""Tests for the jambonz audio_fork WebSocket adapter (sip_audio_route).

The adapter is a THIN translator: parse start frame, build a
SipVoiceController, run it, guarantee shutdown. Unit-level tests
patch SipVoiceController out so we can drive the adapter through
all its branches without spinning up real ASR/TTS/CC.
"""
import json
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from channels.web.voice.sip_audio_route import sip_audio_endpoint


class _FakeController:
    """Records constructor args; run/shutdown record calls."""

    instances: list["_FakeController"] = []

    def __init__(self, *, call_sid, caller, callee, ws):
        self.call_sid = call_sid
        self.caller = caller
        self.callee = callee
        self.ws = ws
        self.run_called = False
        self.shutdown_called = False
        _FakeController.instances.append(self)

    async def run(self):
        self.run_called = True

    async def shutdown(self):
        self.shutdown_called = True


class _ExplodingController(_FakeController):
    async def run(self):
        self.run_called = True
        raise RuntimeError("controller crashed mid-call")


def _build_app():
    app = FastAPI()
    app.add_api_websocket_route("/sip-audio", sip_audio_endpoint)
    return app


def _reset_fakes():
    _FakeController.instances.clear()


def test_constructs_controller_from_start_event_and_runs_it():
    _reset_fakes()
    with patch(
        "channels.web.voice.sip_audio_route.SipVoiceController",
        _FakeController,
    ):
        app = _build_app()
        with TestClient(app) as client:
            with client.websocket_connect("/sip-audio") as ws:
                ws.send_text(json.dumps({
                    "event": "start",
                    "callSid": "abc-123",
                    "from": "+85212345678",
                    "to": "+85287654321",
                }))
                # Controller's run() returns immediately (fake), then adapter
                # closes the WS. Receive the close.
                # No further assertion on receive; we'll inspect _FakeController.

    assert len(_FakeController.instances) == 1
    inst = _FakeController.instances[0]
    assert inst.call_sid == "abc-123"
    assert inst.caller == "+85212345678"
    assert inst.callee == "+85287654321"
    assert inst.run_called
    assert inst.shutdown_called  # finally must run shutdown


def test_rejects_non_json_start_frame():
    _reset_fakes()
    with patch(
        "channels.web.voice.sip_audio_route.SipVoiceController",
        _FakeController,
    ):
        app = _build_app()
        with TestClient(app) as client:
            with client.websocket_connect("/sip-audio") as ws:
                ws.send_text("this is not json {")

    # No controller should have been built
    assert _FakeController.instances == []


def test_rejects_first_frame_without_event_start():
    _reset_fakes()
    with patch(
        "channels.web.voice.sip_audio_route.SipVoiceController",
        _FakeController,
    ):
        app = _build_app()
        with TestClient(app) as client:
            with client.websocket_connect("/sip-audio") as ws:
                ws.send_text(json.dumps({"event": "stop"}))  # wrong event

    assert _FakeController.instances == []


def test_uses_unknown_defaults_when_meta_fields_missing():
    """jambonz may send a minimal start frame; adapter must not crash."""
    _reset_fakes()
    with patch(
        "channels.web.voice.sip_audio_route.SipVoiceController",
        _FakeController,
    ):
        app = _build_app()
        with TestClient(app) as client:
            with client.websocket_connect("/sip-audio") as ws:
                ws.send_text(json.dumps({"event": "start"}))

    assert len(_FakeController.instances) == 1
    inst = _FakeController.instances[0]
    assert inst.call_sid == "unknown"
    assert inst.caller == "unknown"
    assert inst.callee == "unknown"


def test_shutdown_runs_even_if_controller_run_raises():
    """Adapter's finally must call shutdown so resources are released
    even when the controller crashes mid-call."""
    _reset_fakes()
    with patch(
        "channels.web.voice.sip_audio_route.SipVoiceController",
        _ExplodingController,
    ):
        app = _build_app()
        with TestClient(app) as client:
            with client.websocket_connect("/sip-audio") as ws:
                ws.send_text(json.dumps({
                    "event": "start", "callSid": "boom", "from": "x", "to": "y",
                }))

    assert len(_FakeController.instances) == 1
    inst = _FakeController.instances[0]
    assert inst.run_called
    assert inst.shutdown_called  # the critical assertion
