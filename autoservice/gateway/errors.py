"""WS error codes + EngineError → WS code mapping (T0.5 skeleton).

Per docs/contracts/frontend-ws-schema.md §6.
"""

from __future__ import annotations

from typing import Any


# T0.2 §6 error code table
ERR_AUTH_FAILED = "4001_AUTH_FAILED"
ERR_PERMISSION_DENIED = "4003_PERMISSION_DENIED"
ERR_NOT_FOUND = "4004_NOT_FOUND"
ERR_CONFLICT = "4009_CONFLICT"
ERR_VALIDATION = "4012_VALIDATION"
ERR_ILLEGAL_STATE = "4013_ILLEGAL_STATE"
ERR_RATE_LIMIT = "4029_RATE_LIMIT"
ERR_VERSION_INCOMPATIBLE = "4040_VERSION_INCOMPATIBLE"
ERR_REPLAY_GAP = "4041_REPLAY_GAP"
ERR_INTERNAL = "5000_INTERNAL"
ERR_OVERLOAD = "5003_OVERLOAD"


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
