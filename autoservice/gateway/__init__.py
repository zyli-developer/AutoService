"""WebSocket gateway (T0.5 skeleton)."""

from autoservice.gateway.connection import (
    build_frame,
    build_server_hello,
    generate_frame_id,
    generate_session_id,
    now_iso_ms,
)
from autoservice.gateway.envelope import (
    ACCEPTED_VERSIONS,
    PROTOCOL_VERSION,
    Envelope,
    parse_envelope,
)
from autoservice.gateway.errors import (
    ERR_AUTH,
    ERR_AUTH_FAILED,  # deprecated alias
    ERR_ENGINE,
    ERR_INTERNAL,
    ERR_PERMISSION,
    ERR_PERMISSION_DENIED,  # deprecated alias
    ERR_SCHEMA,
    ERR_VALIDATION,
    ERR_VERSION_INCOMPATIBLE,
    make_error_payload,
)
from autoservice.gateway.message_router import dispatch

__all__ = [
    "ACCEPTED_VERSIONS",
    "PROTOCOL_VERSION",
    "Envelope",
    "parse_envelope",
    "build_frame",
    "build_server_hello",
    "generate_frame_id",
    "generate_session_id",
    "now_iso_ms",
    "ERR_AUTH",
    "ERR_AUTH_FAILED",
    "ERR_ENGINE",
    "ERR_INTERNAL",
    "ERR_PERMISSION",
    "ERR_PERMISSION_DENIED",
    "ERR_SCHEMA",
    "ERR_VALIDATION",
    "ERR_VERSION_INCOMPATIBLE",
    "make_error_payload",
    "dispatch",
]
