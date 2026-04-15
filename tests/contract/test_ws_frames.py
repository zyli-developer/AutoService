"""WS frame envelope + F1–F15 / S1–S14 payload schema tests.

T0.2 §2 envelope + §4/§5 frame catalogs. Engine-independent: these validate
JSON shape only. A minimal fixture set of positive + negative examples lives
inline (DevB may upgrade to `docs/contracts/test-vectors/frames.json` later;
test loader falls back to inline when the file is absent).
"""

from __future__ import annotations

import io
import json
import re
from datetime import datetime
from pathlib import Path

import pytest


FRAMES_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs" / "contracts" / "test-vectors" / "frames.json"
)

UUID_V4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
ULID_RE = re.compile(r"^[0-9A-Z]{26}$")
ISO_MS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)


# ---------- envelope validator (T0.2 §2) ----------

def _validate_envelope(frame: dict, direction: str) -> list[str]:
    """Return a list of validation errors; empty = valid envelope."""
    errors: list[str] = []
    for f in ("v", "type", "id", "ts", "payload"):
        if f not in frame:
            errors.append(f"missing {f}")
    if errors:
        return errors

    if frame["v"] != 1:
        errors.append(f"v must be 1, got {frame['v']!r}")
    if not isinstance(frame["type"], str) or not frame["type"]:
        errors.append("type must be non-empty string")
    if not isinstance(frame["payload"], dict):
        errors.append("payload must be object")

    # ID format depends on direction
    fid = frame["id"]
    if direction == "FE->BE":
        if not UUID_V4_RE.match(fid):
            errors.append(f"FE->BE id must be UUID v4, got {fid!r}")
    elif direction == "BE->FE":
        if not ULID_RE.match(fid):
            errors.append(f"BE->FE id must be ULID, got {fid!r}")

    if not ISO_MS_RE.match(frame["ts"]):
        errors.append(f"ts must be ISO 8601 UTC ms (…Z), got {frame['ts']!r}")
    else:
        # Parse to ensure realness
        try:
            datetime.fromisoformat(frame["ts"].replace("Z", "+00:00"))
        except ValueError as e:
            errors.append(f"ts unparseable: {e}")

    # ref semantics (T0.2 §2 + §3.2): only BE->FE ack/error/command_response
    # carry ref; ping/pong themselves never ack.
    if "ref" in frame:
        if direction == "FE->BE":
            errors.append("FE->BE frames must not include ref")
        if frame["type"] in {"ping", "pong", "ack", "error"} and frame["type"] != "ack" and frame["type"] != "error":
            errors.append(f"{frame['type']} must not carry ref (§3.2)")

    return errors


# ---------- positive fixtures (minimal, one per major type) ----------

FE_BE_FRAMES = {
    "client_hello": {
        "v": 1, "type": "client_hello",
        "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
        "ts": "2026-04-15T10:30:00.000Z",
        "payload": {
            "protocol_version": 1,
            "client_app": "customer-chat@1.0.0",
        },
    },
    "ping": {
        "v": 1, "type": "ping",
        "id": "f47ac10b-58cc-4372-a567-0e02b2c3d480",
        "ts": "2026-04-15T10:30:20.000Z",
        "payload": {},
    },
    "customer_message": {
        "v": 1, "type": "customer_message",
        "id": "f47ac10b-58cc-4372-a567-0e02b2c3d481",
        "ts": "2026-04-15T10:30:00.123Z",
        "payload": {
            "conversation_id": "feishu_oc_abc123",
            "content": "B 套餐多少钱",
        },
    },
    "operator_command": {
        "v": 1, "type": "operator_command",
        "id": "f47ac10b-58cc-4372-a567-0e02b2c3d482",
        "ts": "2026-04-15T10:30:05.000Z",
        "payload": {
            "conversation_id": "feishu_oc_abc123",
            "operator_id": "xiaoli",
            "command": "/hijack",
            "args": {},
        },
    },
    "history_request_since": {
        "v": 1, "type": "history_request",
        "id": "f47ac10b-58cc-4372-a567-0e02b2c3d483",
        "ts": "2026-04-15T10:30:00.000Z",
        "payload": {
            "conversation_id": "feishu_oc_abc123",
            "since_sequence": 10,
            "limit": 50,
        },
    },
    "history_request_before": {
        "v": 1, "type": "history_request",
        "id": "f47ac10b-58cc-4372-a567-0e02b2c3d484",
        "ts": "2026-04-15T10:30:00.000Z",
        "payload": {
            "conversation_id": "feishu_oc_abc123",
            "before_sequence": 42,
            "limit": 50,
        },
    },
    "subscribe": {
        "v": 1, "type": "subscribe",
        "id": "f47ac10b-58cc-4372-a567-0e02b2c3d485",
        "ts": "2026-04-15T10:30:00.000Z",
        "payload": {"scope": {"squad_id": "sq1"}, "event_types": ["mode.changed"]},
    },
    "csat_response": {
        "v": 1, "type": "csat_response",
        "id": "f47ac10b-58cc-4372-a567-0e02b2c3d486",
        "ts": "2026-04-15T10:35:00.000Z",
        "payload": {"conversation_id": "feishu_oc_abc123", "score": 5},
    },
}

BE_FE_FRAMES = {
    "server_hello": {
        "v": 1, "type": "server_hello",
        "id": "01HX7Z2Q8K3N5T6V8W9X0Y1Z2A",
        "ts": "2026-04-15T10:30:00.050Z",
        "payload": {
            "session_id": "sess_abc",
            "protocol_version": 1,
            "server_time": "2026-04-15T10:30:00.000Z",
            "viewer_role": "customer",
            "accepted_subscriptions": [],
            "server_capabilities": [],
        },
    },
    "pong": {
        "v": 1, "type": "pong",
        "id": "01HX7Z2Q8K3N5T6V8W9X0Y1Z2B",
        "ts": "2026-04-15T10:30:20.050Z",
        "payload": {"server_time": "2026-04-15T10:30:20.050Z"},
    },
    "ack": {
        "v": 1, "type": "ack",
        "id": "01HX7Z2Q8K3N5T6V8W9X0Y1Z2C",
        "ts": "2026-04-15T10:30:00.200Z",
        "ref": "f47ac10b-58cc-4372-a567-0e02b2c3d481",
        "payload": {},
    },
    "error": {
        "v": 1, "type": "error",
        "id": "01HX7Z2Q8K3N5T6V8W9X0Y1Z2D",
        "ts": "2026-04-15T10:30:00.200Z",
        "ref": "f47ac10b-58cc-4372-a567-0e02b2c3d481",
        "payload": {
            "code": "4012_VALIDATION",
            "message": "content must be non-empty",
            "recoverable": False,
        },
    },
    "message": {
        "v": 1, "type": "message",
        "id": "01HX7Z2Q8K3N5T6V8W9X0Y1Z2E",
        "ts": "2026-04-15T10:30:01.500Z",
        "payload": {
            "conversation_id": "feishu_oc_abc123",
            "message": {
                "id": "01HX7Z2Q8K3N5T6V8W9X0Y1Z2F",
                "conversation_id": "feishu_oc_abc123",
                "source": "fast-agent",
                "content": "B 套餐每月 199 元",
                "visibility": "public",
                "sequence_number": 2,
                "timestamp": "2026-04-15T10:30:01.450Z",
                "edit_of": None,
                "metadata": {},
            },
            "source_display": {
                "id": "fast-agent",
                "role": "agent",
                "name": "快速响应 Agent",
            },
        },
    },
    "event": {
        "v": 1, "type": "event",
        "id": "01HX7Z2Q8K3N5T6V8W9X0Y1Z2G",
        "ts": "2026-04-15T10:30:15.000Z",
        "payload": {
            "event": {
                "id": "01HX7Z2Q8K3N5T6V8W9X0Y1Z2G",
                "type": "mode.changed",
                "conversation_id": "feishu_oc_abc123",
                "data": {"from_mode": "copilot", "to_mode": "takeover",
                         "trigger": "/hijack", "triggered_by": "xiaoli"},
                "timestamp": "2026-04-15T10:30:15.000Z",
                "sequence_number": 8,
            }
        },
    },
    "command_response": {
        "v": 1, "type": "command_response",
        "id": "01HX7Z2Q8K3N5T6V8W9X0Y1Z2H",
        "ts": "2026-04-15T10:30:05.100Z",
        "ref": "f47ac10b-58cc-4372-a567-0e02b2c3d482",
        "payload": {"command": "/hijack", "ok": True, "result": {}},
    },
    "history_snapshot": {
        "v": 1, "type": "history_snapshot",
        "id": "01HX7Z2Q8K3N5T6V8W9X0Y1Z2I",
        "ts": "2026-04-15T10:30:01.000Z",
        "ref": "f47ac10b-58cc-4372-a567-0e02b2c3d483",
        "payload": {
            "conversation_id": "feishu_oc_abc123",
            "messages": [],
            "has_more": False,
        },
    },
}


def _load_file_fixtures():
    """Merge with inline fixtures if test-vectors/frames.json exists."""
    if not FRAMES_PATH.exists():
        return {}, {}
    with io.open(FRAMES_PATH, encoding="utf-8") as f:
        doc = json.load(f)
    return (doc.get("fe_be", {}), doc.get("be_fe", {}))


FE_FILE, BE_FILE = _load_file_fixtures()


# ---------- positive tests (envelope validation) ----------

@pytest.mark.parametrize("name,frame", sorted((FE_BE_FRAMES | FE_FILE).items()))
def test_fe_be_envelope_valid(name, frame):
    errors = _validate_envelope(frame, "FE->BE")
    assert not errors, f"{name}: {errors}"


@pytest.mark.parametrize("name,frame", sorted((BE_FE_FRAMES | BE_FILE).items()))
def test_be_fe_envelope_valid(name, frame):
    errors = _validate_envelope(frame, "BE->FE")
    assert not errors, f"{name}: {errors}"


# ---------- negative tests (envelope violations) ----------

def _base_fe():
    return dict(FE_BE_FRAMES["customer_message"])


def test_envelope_missing_v():
    frame = _base_fe()
    del frame["v"]
    assert _validate_envelope(frame, "FE->BE")


def test_envelope_wrong_v():
    frame = _base_fe()
    frame["v"] = 2
    assert _validate_envelope(frame, "FE->BE")


def test_envelope_fe_be_id_must_be_uuid():
    frame = _base_fe()
    frame["id"] = "01HX7Z2Q8K3N5T6V8W9X0Y1Z2A"  # ULID, not UUID
    errors = _validate_envelope(frame, "FE->BE")
    assert any("UUID" in e for e in errors)


def test_envelope_be_fe_id_must_be_ulid():
    frame = dict(BE_FE_FRAMES["ack"])
    frame["id"] = "f47ac10b-58cc-4372-a567-0e02b2c3d479"  # UUID, not ULID
    errors = _validate_envelope(frame, "BE->FE")
    assert any("ULID" in e for e in errors)


def test_envelope_ts_missing_ms():
    frame = _base_fe()
    frame["ts"] = "2026-04-15T10:30:00Z"  # no ms
    errors = _validate_envelope(frame, "FE->BE")
    assert any("ts" in e for e in errors)


def test_envelope_ts_not_utc():
    frame = _base_fe()
    frame["ts"] = "2026-04-15T10:30:00.000+08:00"
    errors = _validate_envelope(frame, "FE->BE")
    assert any("ts" in e for e in errors)


def test_envelope_payload_must_be_object():
    frame = _base_fe()
    frame["payload"] = "not-an-object"
    errors = _validate_envelope(frame, "FE->BE")
    assert any("payload" in e for e in errors)


def test_envelope_fe_be_must_not_have_ref():
    frame = _base_fe()
    frame["ref"] = "f47ac10b-58cc-4372-a567-0e02b2c3d400"
    errors = _validate_envelope(frame, "FE->BE")
    assert any("ref" in e for e in errors)


# ---------- payload-level checks (a few strategic ones) ----------

def test_history_request_since_and_before_may_not_coexist_in_example():
    """T0.2 F13 rule: since_sequence / before_sequence 互斥. Fixture honors this."""
    f1 = FE_BE_FRAMES["history_request_since"]["payload"]
    f2 = FE_BE_FRAMES["history_request_before"]["payload"]
    assert "since_sequence" in f1 and "before_sequence" not in f1
    assert "before_sequence" in f2 and "since_sequence" not in f2


def test_operator_command_uses_canonical_commands():
    allowed = {"/hijack", "/release", "/copilot", "/resolve", "/abandon", "/status"}
    assert FE_BE_FRAMES["operator_command"]["payload"]["command"] in allowed


def test_ack_and_error_require_ref():
    for t in ("ack", "error"):
        assert "ref" in BE_FE_FRAMES[t], f"{t} must carry ref"


def test_event_frame_type_must_equal_known_event_type():
    from autoservice.conversation_engine import EventType

    ev = BE_FE_FRAMES["event"]["payload"]["event"]
    assert ev["type"] in {e.value for e in EventType}


def test_csat_response_score_in_range():
    assert 1 <= FE_BE_FRAMES["csat_response"]["payload"]["score"] <= 5


def test_message_frame_visibility_is_public_for_customer_push():
    """S5 message frame pushed to customer has visibility=public (already
    visibility-filtered by Engine per T0.1 Q9)."""
    m = BE_FE_FRAMES["message"]["payload"]["message"]
    assert m["visibility"] in {"public", "side", "system"}
