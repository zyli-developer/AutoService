"""Envelope validation (T0.5 skeleton).

Per docs/contracts/frontend-ws-schema.md §2: every frame has
  v / type / id / ts / ref? / payload
FE→BE id must be UUIDv4; ts must be ISO8601 UTC with millisecond precision.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator


PROTOCOL_VERSION = 1
ACCEPTED_VERSIONS = frozenset({1})

# ISO8601 UTC with millisecond precision, ending in Z
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


class Envelope(BaseModel):
    """FE→BE frame envelope (T0.2 §2)."""

    v: int = Field(description="protocol version; currently only 1 is accepted")
    type: str = Field(min_length=1)
    id: str = Field(min_length=1, description="UUIDv4 for FE→BE frames")
    ts: str = Field(description="ISO8601 UTC with millisecond precision (...Z)")
    ref: str | None = None
    payload: dict[str, Any] = Field(description="type-specific payload; must be explicit (possibly {})")

    @field_validator("id")
    @classmethod
    def _id_is_uuid4(cls, v: str) -> str:
        try:
            parsed = uuid.UUID(v)
        except (ValueError, AttributeError, TypeError) as exc:  # noqa: BLE001
            raise ValueError("id must be a UUIDv4 string") from exc
        if parsed.version != 4:
            raise ValueError("id must be a UUIDv4 (version 4)")
        return v

    @field_validator("ts")
    @classmethod
    def _ts_utc_ms(cls, v: str) -> str:
        if not _TS_RE.match(v):
            raise ValueError(
                "ts must be ISO8601 UTC with ms precision, e.g. 2026-04-15T10:30:00.123Z"
            )
        return v


def parse_envelope(raw: Any) -> tuple[Envelope | None, dict[str, Any] | None]:
    """Parse a raw JSON object as an Envelope.

    Returns (envelope, None) on success, or (None, error_details) on failure,
    where error_details is a dict suitable for `error.payload.details`.
    """
    if not isinstance(raw, dict):
        return None, {"reason": "frame_not_object"}

    try:
        env = Envelope.model_validate(raw)
    except ValidationError as exc:
        missing: list[str] = []
        reasons: list[str] = []
        for err in exc.errors():
            loc = err.get("loc", ())
            field = loc[0] if loc else "?"
            if err.get("type") == "missing":
                missing.append(str(field))
            else:
                reasons.append(f"{field}: {err.get('msg', 'invalid')}")
        details: dict[str, Any] = {}
        if missing:
            details["missing"] = missing
        if reasons:
            details["reasons"] = reasons
        return None, details

    return env, None
