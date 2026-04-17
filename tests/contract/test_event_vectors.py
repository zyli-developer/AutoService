"""Validate docs/contracts/test-vectors/events.json against T0.1 Event shape.

This file is engine-agnostic — it pins the T0.2 event-vector fixtures to the
T0.1 Event structure so drift between the two contracts is caught early.
"""

from __future__ import annotations

import io
import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from autoservice.conversation_engine import EventType

VECTORS_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs" / "contracts" / "test-vectors" / "events.json"
)

## ULID is Crockford base32 (excludes I L O U). test-vectors may use placeholder
## IDs for docs, so relax to structural-only (26 alphanumeric chars) here.
## Strict Crockford validation belongs in LocalEngine implementation tests.
ULID_RE = re.compile(r"^[0-9A-Z]{26}$")
CONV_ID_RE = re.compile(r"^(feishu|web)_.+")


@pytest.fixture(scope="module")
def vectors() -> list[dict]:
    with io.open(VECTORS_PATH, encoding="utf-8") as f:
        doc = json.load(f)
    return doc["vectors"]


def test_vectors_file_parses():
    # Redundant w/ fixture but makes the failure mode explicit.
    with io.open(VECTORS_PATH, encoding="utf-8") as f:
        json.load(f)


def test_every_event_type_has_at_least_one_vector(vectors):
    covered = {v["type"] for v in vectors}
    missing = {e.value for e in EventType} - covered
    assert not missing, f"Event types without vectors: {sorted(missing)}"


def test_no_unknown_event_types(vectors):
    """Every vector type must be a valid EventType (no drift)."""
    valid = {e.value for e in EventType}
    for v in vectors:
        assert v["type"] in valid, f"Unknown event type: {v['type']!r}"


@pytest.mark.parametrize("vec_idx", range(22))
def test_vector_envelope_shape(vectors, vec_idx):
    """Each vector's `example` conforms to T0.1 Event dataclass shape."""
    v = vectors[vec_idx]
    assert "type" in v
    assert "example" in v, f"{v['type']}: missing example"
    ex = v["example"]

    # Required fields per T0.1 §2.2 Event dataclass
    for field in ("id", "type", "conversation_id", "data", "timestamp", "sequence_number"):
        assert field in ex, f"{v['type']}: example missing field {field!r}"

    # Type must match envelope
    assert ex["type"] == v["type"], f"outer/inner type mismatch for {v['type']}"

    # ULID format (Q1)
    assert ULID_RE.match(ex["id"]), f"{v['type']}: id not ULID: {ex['id']!r}"

    # conversation_id format (Q1): {channel}_{external_id}
    assert CONV_ID_RE.match(ex["conversation_id"]), (
        f"{v['type']}: conversation_id format: {ex['conversation_id']!r}"
    )

    # Timestamp parseable ISO 8601
    ts = ex["timestamp"].replace("Z", "+00:00")
    datetime.fromisoformat(ts)  # raises on invalid

    # sequence_number is int (Q3 per-conversation monotonic)
    assert isinstance(ex["sequence_number"], int)
    assert ex["sequence_number"] >= 1

    # data is an object
    assert isinstance(ex["data"], dict), f"{v['type']}: data must be object"


# --- Type-specific data-field invariants (spot checks) ---

def _find(vectors, t):
    return [v for v in vectors if v["type"] == t][0]["example"]


VALID_MODES = {"auto", "copilot", "takeover"}
VALID_VISIBILITIES = {"public", "side", "system"}
VALID_ROLES = {"customer", "agent", "operator", "observer"}


def test_mode_changed_data_fields(vectors):
    d = _find(vectors, "mode.changed")["data"]
    assert {"from_mode", "to_mode", "trigger", "triggered_by"} <= d.keys()
    assert d["from_mode"] in VALID_MODES
    assert d["to_mode"] in VALID_MODES
    assert d["from_mode"] != d["to_mode"]  # actual change; target==current → mode.noop


def test_mode_noop_data_fields(vectors):
    """Q4: target == current → mode.noop."""
    d = _find(vectors, "mode.noop")["data"]
    assert {"current_mode", "requested_mode", "trigger", "triggered_by"} <= d.keys()
    assert d["current_mode"] == d["requested_mode"]  # defining property of noop
    assert d["current_mode"] in VALID_MODES


def test_message_gated_data_fields(vectors):
    """§4 + Q5: Gate only downgrades PUBLIC → SIDE."""
    d = _find(vectors, "message.gated")["data"]
    assert {"message_id", "requested_visibility", "final_visibility"} <= d.keys()
    assert d["requested_visibility"] == "public"
    assert d["final_visibility"] == "side"
    assert d["current_mode"] in VALID_MODES


def test_hook_failed_data_fields(vectors):
    """§7.1 #7: hook exceptions surfaced with hook + exception info."""
    d = _find(vectors, "hook.failed")["data"]
    assert "hook_class" in d
    assert "callback" in d
    assert "exception_type" in d
    assert "exception_message" in d


def test_participant_joined_has_role(vectors):
    d = _find(vectors, "participant.joined")["data"]
    p = d["participant"]
    assert p["role"] in VALID_ROLES


def test_timer_set_has_duration_ms(vectors):
    """Q2: Timer internal ms."""
    d = _find(vectors, "timer.set")["data"]
    assert isinstance(d["duration_ms"], int) and d["duration_ms"] > 0


def test_csat_recorded_score_in_range(vectors):
    d = _find(vectors, "conversation.csat_recorded")["data"]
    assert isinstance(d["score"], int)
    assert 1 <= d["score"] <= 5


def test_message_sent_wraps_message_object(vectors):
    """S5 frame and message.sent event share the same Message payload."""
    d = _find(vectors, "message.sent")["data"]
    m = d["message"]
    for field in ("id", "conversation_id", "source", "content", "visibility", "sequence_number"):
        assert field in m, f"message.sent: missing {field}"
    assert m["visibility"] in VALID_VISIBILITIES
