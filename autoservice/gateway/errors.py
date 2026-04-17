"""WS error codes + EngineError → WS code mapping (T0.5 skeleton).

Per docs/contracts/frontend-ws-schema.md §6.
Aligned to frontend ERROR_CODES (frontend/packages/ws-client/src/types.ts).
"""

from __future__ import annotations

from typing import Any


# T0.2 §6 error code table — aligned to frontend types.ts ERROR_CODES
ERR_SCHEMA = "4010_SCHEMA"
ERR_AUTH = "4011_AUTH"
ERR_VALIDATION = "4012_VALIDATION"
ERR_PERMISSION = "4013_PERMISSION"
ERR_ILLEGAL_MODE = "4014_ILLEGAL_MODE_TRANSITION"
ERR_TIMER_NOT_FOUND = "4015_TIMER_NOT_FOUND"
ERR_PARTICIPANT_NOT_FOUND = "4016_PARTICIPANT_NOT_FOUND"
ERR_RATE_LIMIT = "4017_RATE_LIMIT"
ERR_SEQ_GAP = "4018_SEQUENCE_GAP"
ERR_VERSION_INCOMPATIBLE = "4040_VERSION_INCOMPATIBLE"
ERR_INTERNAL = "5010_INTERNAL"
ERR_ENGINE = "5011_ENGINE"

# ── Backward-compatible aliases (deprecated, remove after full migration) ──
ERR_AUTH_FAILED = ERR_AUTH
ERR_PERMISSION_DENIED = ERR_PERMISSION
ERR_ILLEGAL_STATE = ERR_ILLEGAL_MODE
ERR_NOT_FOUND = "4004_NOT_FOUND"          # kept for gateway internals
ERR_CONFLICT = "4009_CONFLICT"            # kept for gateway internals
ERR_REPLAY_GAP = ERR_SEQ_GAP
ERR_OVERLOAD = "5003_OVERLOAD"            # kept for gateway internals


def make_error_payload(
    code: str,
    message: str,
    *,
    recoverable: bool = False,
    retry_after: int | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the payload of an S4 `error` frame."""
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
        "recoverable": recoverable,
    }
    if retry_after is not None:
        payload["retry_after"] = retry_after
    if details:
        payload["details"] = details
    return payload
