"""ConversationEngine Protocol signature compliance.

These tests verify the Protocol's method signatures match T0.1 §3 exactly.
They're engine-independent — they reflect the shape of the Protocol itself,
not any implementation. Break on any silent change to the contract surface.
"""

from __future__ import annotations

import inspect
from typing import get_type_hints

import pytest

from autoservice.conversation_engine import ConversationEngine, PluginHook


PROTOCOL_METHODS = {
    # name -> (required_params, kw_only_params_with_defaults)
    "create_conversation": (set(), {"channel", "external_id", "metadata"}),
    "get_conversation": ({"conversation_id"}, set()),
    "list_active_conversations": (set(), {"operator_id", "squad_id"}),
    "close_conversation": ({"conversation_id"}, {"outcome", "resolved_by", "reason"}),
    "set_csat": ({"conversation_id", "score"}, set()),
    "join": ({"conversation_id", "participant"}, set()),
    "leave": ({"conversation_id", "participant_id"}, set()),
    "switch_mode": ({"conversation_id", "target"}, {"triggered_by", "trigger"}),
    "send_message": (
        {"conversation_id"},
        {"source", "content", "requested_visibility", "metadata"},
    ),
    "edit_message": (
        {"conversation_id", "message_id"},
        {"new_content", "edited_by"},
    ),
    "delete_message": (
        {"conversation_id", "message_id"},
        {"deleted_by"},
    ),
    "get_messages": (
        {"conversation_id"},
        {"since_sequence", "before_sequence", "until", "viewer_role", "limit"},
    ),
    "handle_command": (
        {"conversation_id"},
        {"actor_id", "command", "args"},
    ),
    "set_timer": (
        {"conversation_id", "name", "duration_ms"},
        {"on_expire"},
    ),
    "cancel_timer": ({"conversation_id", "name"}, set()),
    "subscribe": (
        set(),
        {
            "conversation_id",
            "squad_id",
            "event_types",
            "since_sequence",
            "viewer_role",
        },
    ),
    "query_events": (
        {"conversation_id"},
        {"since_sequence", "until", "types", "limit"},
    ),
    "register_hook": ({"hook"}, set()),
}


HOOK_METHODS = {
    "on_conversation_created",
    "on_conversation_closed",
    "on_mode_changed",
    "on_participant_joined",
    "on_timer_expired",
    "on_event",
}


def _sig(cls, name):
    return inspect.signature(getattr(cls, name))


def _params(sig):
    positional: set[str] = set()
    kw_only: set[str] = set()
    for n, p in sig.parameters.items():
        if n == "self":
            continue
        if p.kind is inspect.Parameter.KEYWORD_ONLY:
            kw_only.add(n)
        elif p.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.POSITIONAL_ONLY,
        ):
            positional.add(n)
    return positional, kw_only


@pytest.mark.parametrize("method", sorted(PROTOCOL_METHODS.keys()))
def test_protocol_method_exists(method):
    assert hasattr(ConversationEngine, method), (
        f"ConversationEngine missing method: {method}"
    )


@pytest.mark.parametrize("method", sorted(PROTOCOL_METHODS.keys()))
def test_protocol_method_signature(method):
    expected_pos, expected_kw = PROTOCOL_METHODS[method]
    sig = _sig(ConversationEngine, method)
    actual_pos, actual_kw = _params(sig)
    assert actual_pos == expected_pos, (
        f"{method}: positional params drift "
        f"(expected {expected_pos}, got {actual_pos})"
    )
    assert actual_kw == expected_kw, (
        f"{method}: kw-only params drift "
        f"(expected {expected_kw}, got {actual_kw})"
    )


def test_no_extra_protocol_methods():
    """New Protocol methods must be added to PROTOCOL_METHODS in this test file.

    Forces spec/test co-evolution: adding a method without updating this test
    yields a clear signal at review time.
    """
    declared = {
        n for n in vars(ConversationEngine)
        if not n.startswith("_") and callable(getattr(ConversationEngine, n))
    }
    undocumented = declared - set(PROTOCOL_METHODS.keys())
    assert not undocumented, (
        f"Protocol methods not covered by signature test: {undocumented}"
    )


def test_async_methods_are_coroutines():
    """All Engine methods except register_hook must be `async def`."""
    sync_only = {"register_hook"}
    for name in PROTOCOL_METHODS:
        if name in sync_only:
            continue
        fn = getattr(ConversationEngine, name)
        assert inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn), (
            f"{name}: must be async (T0.1 §3 header: 'All methods async')"
        )


def test_subscribe_returns_async_iterator():
    """§3 subscribe -> AsyncIterator[Event]."""
    sig = _sig(ConversationEngine, "subscribe")
    ret = sig.return_annotation
    # Accept AsyncIterator[Event] in any stringified or typing form.
    s = str(ret)
    assert "AsyncIterator" in s, f"subscribe return annotation: {ret}"


def test_plugin_hook_has_all_required_callbacks():
    declared = {
        n for n in vars(PluginHook)
        if not n.startswith("_") and callable(getattr(PluginHook, n))
    }
    missing = HOOK_METHODS - declared
    assert not missing, f"PluginHook missing callbacks: {missing}"


def test_register_hook_is_sync():
    """register_hook registers a hook object — no I/O — must not be async."""
    fn = getattr(ConversationEngine, "register_hook")
    assert not inspect.iscoroutinefunction(fn)


def test_get_messages_exclusive_params_both_present():
    """DevB #1: both since_sequence AND before_sequence must be parameters
    (mutual exclusion enforced at runtime; here we only assert presence)."""
    _, kw = _params(_sig(ConversationEngine, "get_messages"))
    assert "since_sequence" in kw
    assert "before_sequence" in kw


def test_subscribe_accepts_three_scopes():
    """§3 subscribe supports conv_id / squad_id / global (both None)."""
    _, kw = _params(_sig(ConversationEngine, "subscribe"))
    assert "conversation_id" in kw
    assert "squad_id" in kw


def test_list_active_accepts_operator_and_squad_filters():
    _, kw = _params(_sig(ConversationEngine, "list_active_conversations"))
    assert "operator_id" in kw
    assert "squad_id" in kw


def test_handle_command_signature_matches_ws_f11():
    """T0.2 §7 maps operator_command/admin_command → handle_command(actor_id, command, args)."""
    _, kw = _params(_sig(ConversationEngine, "handle_command"))
    assert {"actor_id", "command", "args"} <= kw
