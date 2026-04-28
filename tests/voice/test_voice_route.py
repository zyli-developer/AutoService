"""Tests for /ws/voice mode dispatch.

The route reads a JSON `start` frame and instantiates VoiceSession
(default / e2e) or VoiceSplitSession (split) accordingly. We patch the
two session classes so the test doesn't pull in Doubao networking.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from channels.web.voice.voice_route import voice_endpoint


def _build_app():
    app = FastAPI()
    app.add_api_websocket_route("/ws/voice", voice_endpoint)
    return app


def _make_session_factory():
    """Return (cls_mock, instances) where instances captures created
    session-like objects so the test can assert constructor args + that
    .run() was awaited."""
    instances: list = []

    class _StubSession:
        def __init__(self, ws, *, start_config, conversation_id, tenant_id):
            self.ws = ws
            self.start_config = start_config
            self.conversation_id = conversation_id
            self.tenant_id = tenant_id
            self.run = AsyncMock()
            instances.append(self)

    return _StubSession, instances


def test_voice_route_dispatches_default_to_e2e_session():
    e2e_cls, e2e_instances = _make_session_factory()
    split_cls, split_instances = _make_session_factory()

    with patch("channels.web.voice.session.VoiceSession", e2e_cls), \
         patch("channels.web.voice.session_split.VoiceSplitSession", split_cls):
        app = _build_app()
        with TestClient(app) as client:
            with client.websocket_connect(
                "/ws/voice?conversation_id=conv_e2e&tenant=tnt_a",
            ) as ws:
                ws.send_text(json.dumps({"type": "start"}))

    assert len(e2e_instances) == 1
    assert len(split_instances) == 0
    inst = e2e_instances[0]
    assert inst.conversation_id == "conv_e2e"
    assert inst.tenant_id == "tnt_a"
    assert inst.start_config == {"type": "start"}
    inst.run.assert_awaited_once()


def test_voice_route_dispatches_explicit_e2e_session():
    e2e_cls, e2e_instances = _make_session_factory()
    split_cls, split_instances = _make_session_factory()
    with patch("channels.web.voice.session.VoiceSession", e2e_cls), \
         patch("channels.web.voice.session_split.VoiceSplitSession", split_cls):
        app = _build_app()
        with TestClient(app) as client:
            with client.websocket_connect("/ws/voice") as ws:
                ws.send_text(json.dumps({
                    "type": "start", "mode": "e2e_session",
                }))
    assert len(e2e_instances) == 1
    assert len(split_instances) == 0


def test_voice_route_dispatches_e2e_alias():
    """cc-openclaw used `mode:"e2e"` historically — accept it as alias."""
    e2e_cls, e2e_instances = _make_session_factory()
    split_cls, split_instances = _make_session_factory()
    with patch("channels.web.voice.session.VoiceSession", e2e_cls), \
         patch("channels.web.voice.session_split.VoiceSplitSession", split_cls):
        app = _build_app()
        with TestClient(app) as client:
            with client.websocket_connect("/ws/voice") as ws:
                ws.send_text(json.dumps({"type": "start", "mode": "e2e"}))
    assert len(e2e_instances) == 1
    assert len(split_instances) == 0


def test_voice_route_dispatches_split_mode():
    e2e_cls, e2e_instances = _make_session_factory()
    split_cls, split_instances = _make_session_factory()
    with patch("channels.web.voice.session.VoiceSession", e2e_cls), \
         patch("channels.web.voice.session_split.VoiceSplitSession", split_cls):
        app = _build_app()
        with TestClient(app) as client:
            with client.websocket_connect("/ws/voice") as ws:
                ws.send_text(json.dumps({
                    "type": "start", "mode": "split",
                }))
    assert len(e2e_instances) == 0
    assert len(split_instances) == 1
    split_instances[0].run.assert_awaited_once()


def test_voice_route_rejects_unknown_mode():
    e2e_cls, _ = _make_session_factory()
    split_cls, _ = _make_session_factory()
    with patch("channels.web.voice.session.VoiceSession", e2e_cls), \
         patch("channels.web.voice.session_split.VoiceSplitSession", split_cls):
        app = _build_app()
        with TestClient(app) as client:
            with client.websocket_connect("/ws/voice") as ws:
                ws.send_text(json.dumps({
                    "type": "start", "mode": "telepathy",
                }))
                err = json.loads(ws.receive_text())
                assert err["type"] == "error"
                assert "unknown mode" in err["message"]


def test_voice_route_rejects_non_start_first_frame():
    app = _build_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/voice") as ws:
            ws.send_text(json.dumps({"type": "speak", "text": "hi"}))
            err = json.loads(ws.receive_text())
            assert err["type"] == "error"
            assert "type=start" in err["message"]


def test_voice_route_rejects_invalid_json_first_frame():
    app = _build_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/voice") as ws:
            ws.send_text("not-json{{{")
            err = json.loads(ws.receive_text())
            assert err["type"] == "error"
            assert "invalid start frame" in err["message"]
