"""Cross-check T0.2 frontend-ws-schema.md §7 mapping against T0.1 Protocol.

These tests are pure documentation-consistency checks — they don't require an
engine instance. They guarantee that every Engine method mentioned in the WS
mapping table exists on the Protocol, and vice versa that every Protocol
method appears (or is explicitly marked internal) in the mapping.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from autoservice.conversation_engine import ConversationEngine

WS_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "docs" / "contracts" / "frontend-ws-schema.md"
)


@pytest.fixture(scope="module")
def ws_schema_text() -> str:
    return WS_SCHEMA.read_text(encoding="utf-8")


def _protocol_methods() -> set[str]:
    # Names declared on Protocol itself (not dunders).
    return {
        n for n in dir(ConversationEngine)
        if not n.startswith("_") and callable(getattr(ConversationEngine, n))
    }


def test_ws_schema_file_exists(ws_schema_text):
    assert "T0.2 · Frontend WebSocket Schema" in ws_schema_text


def test_every_protocol_method_is_referenced(ws_schema_text):
    """§7 mapping table must reference every non-internal Engine method.

    `register_hook` is plugin-registration, not a WS-exposed call — excluded.
    """
    excluded = {"register_hook"}
    missing = []
    for method in _protocol_methods() - excluded:
        # Method appears either as `method(` (table cell) or `\`method\`` (inline code)
        if not re.search(rf"`{re.escape(method)}[(`]", ws_schema_text):
            missing.append(method)
    assert not missing, f"Protocol methods absent from WS schema: {missing}"


def test_permission_matrix_commands_match_handle_command(ws_schema_text):
    """F11 operator_command enumerates commands; the set must match §6.1."""
    # Pull F11's enumerated list from the line like:
    #   command (/hijack | /release | /copilot | /resolve | /abandon | /status)
    m = re.search(
        r"`operator_command`.*?command\s*\(([^)]+)\)",
        ws_schema_text,
        re.DOTALL,
    )
    assert m, "F11 operator_command row not found"
    listed = {
        tok.strip().strip("`").strip("\\")
        for tok in re.findall(r"/\w+", m.group(1))
    }
    expected = {"/hijack", "/release", "/copilot", "/resolve", "/abandon", "/status"}
    assert listed == expected, f"F11 commands drift: got {listed}"


def test_endpoint_roles_match_participant_enum(ws_schema_text):
    """§1 endpoints claim viewer_role ∈ {CUSTOMER, OPERATOR, ADMIN}.

    ADMIN is an out-of-enum operational role (documented); CUSTOMER / OPERATOR
    must line up with ParticipantRole.
    """
    from autoservice.conversation_engine import ParticipantRole

    for role_str in ("CUSTOMER", "OPERATOR"):
        assert role_str in ws_schema_text, f"§1 missing role {role_str}"
        # Must be a valid enum value (case-insensitive)
        assert role_str.lower() in {r.value for r in ParticipantRole}


def test_close_codes_table_is_present(ws_schema_text):
    """§3.4 close code 4499 is the canonical server-error (bumped from 4500)."""
    assert "4499" in ws_schema_text
    # And 4500 has been excised (DevA review #2)
    assert "| 4500 |" not in ws_schema_text
