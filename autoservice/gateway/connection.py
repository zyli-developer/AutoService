"""Connection helpers for the WS gateway (T0.5 skeleton).

Owns: session_id generation, server_hello construction, server-side frame
building (ULID-ish id, UTC ms ts). ULID is approximated with a random string
for the skeleton — Phase 1 may swap for a real ULID implementation.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any


SERVER_CAPABILITIES = ["v1"]


def now_iso_ms() -> str:
    """Return UTC ISO8601 timestamp with millisecond precision."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def generate_session_id() -> str:
    """Return a ULID-ish (26-char, Crockford-base32-ish) session id.

    Skeleton uses token_hex for simplicity; real ULID comes in Phase 1.
    """
    return secrets.token_hex(13)  # 26 hex chars


def generate_frame_id() -> str:
    """Server-side BE→FE frame id (ULID-ish)."""
    return secrets.token_hex(13)


def build_frame(
    frame_type: str, payload: dict[str, Any], *, ref: str | None = None
) -> dict[str, Any]:
    """Build a BE→FE frame with envelope filled in."""
    frame = {
        "v": 1,
        "type": frame_type,
        "id": generate_frame_id(),
        "ts": now_iso_ms(),
        "payload": payload,
    }
    if ref is not None:
        frame["ref"] = ref
    return frame


def build_server_hello(
    *,
    viewer_role: str,
    session_id: str,
) -> dict[str, Any]:
    """Build the server_hello payload per T0.2 §3.1."""
    return {
        "session_id": session_id,
        "protocol_version": 1,
        "server_time": now_iso_ms(),
        "viewer_role": viewer_role,
        "accepted_subscriptions": [],
        "server_capabilities": SERVER_CAPABILITIES,
    }
