"""T0.4 LocalEngine skeleton tests (test-plan-001 · TC-001 ~ TC-025).

TC-026 (tests/contract/ regression gate) is not covered here — it is
executed by skill-4-test-runner as a separate pytest invocation.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from autoservice.conversation_engine import (
    ConversationMode,
    LocalEngine,
    Outcome,
)


# ----------------------------------------------------------------------------
# Shared data for parametrized hint checks (TC-022)
# ----------------------------------------------------------------------------

HINT_RE = re.compile(r"T[12]A\.\d+")

# (method_name, is_async, call_kwargs)
PROTOCOL_METHOD_CALLS: list[tuple[str, bool, dict]] = [
    ("create_conversation", True, dict(channel="web", external_id="c1")),
    ("get_conversation", True, {}),
    ("list_active_conversations", True, {}),
    ("close_conversation", True, dict(outcome=Outcome.RESOLVED, resolved_by="op1")),
    ("set_csat", True, {}),
    ("join", True, {}),
    ("leave", True, {}),
    ("switch_mode", True, dict(target=ConversationMode.COPILOT, triggered_by="op1", trigger="manual")),
    ("send_message", True, dict(source="u1", content="hi")),
    ("edit_message", True, dict(new_content="edited", edited_by="u1")),
    ("delete_message", True, dict(deleted_by="u1")),
    ("get_messages", True, {}),
    ("handle_command", True, dict(actor_id="op1", command="/hijack")),
    ("set_timer", True, dict(on_expire={"action": "noop"})),
    ("cancel_timer", True, {}),
    ("query_events", True, {}),
    # subscribe / register_hook handled separately below
]

PROTOCOL_METHOD_NAMES = [
    "create_conversation",
    "get_conversation",
    "list_active_conversations",
    "close_conversation",
    "set_csat",
    "join",
    "leave",
    "switch_mode",
    "send_message",
    "edit_message",
    "delete_message",
    "get_messages",
    "handle_command",
    "set_timer",
    "cancel_timer",
    "subscribe",
    "query_events",
    "register_hook",
]


# ----------------------------------------------------------------------------
# Group A · Import / instantiation / Protocol structure
# ----------------------------------------------------------------------------


def test_tc001_import_local_engine() -> None:
    """TC-001: LocalEngine importable from the package __init__."""
    from autoservice.conversation_engine import LocalEngine as LE

    assert LE is LocalEngine


def test_tc002_instantiate_local_engine() -> None:
    """TC-002: LocalEngine() returns an instance without error."""
    e = LocalEngine()
    assert isinstance(e, LocalEngine)


def test_tc003_protocol_structural_check(engine: LocalEngine) -> None:
    """TC-003: LocalEngine has every Protocol method (callable)."""
    for name in PROTOCOL_METHOD_NAMES:
        assert hasattr(engine, name), f"LocalEngine missing method: {name}"
        assert callable(getattr(engine, name)), f"{name} is not callable"


# ----------------------------------------------------------------------------
# Group B · Each Protocol method raises NotImplementedError with T1A.x hint
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tc004_create_conversation_raises(engine: LocalEngine) -> None:
    """TC-004: create_conversation raises NotImplementedError with T1A.1 hint."""
    with pytest.raises(NotImplementedError) as exc:
        await engine.create_conversation(channel="web", external_id="c1")
    msg = str(exc.value)
    assert "T1A.1" in msg
    assert "lifecycle" in msg.lower()


@pytest.mark.asyncio
async def test_tc005_get_conversation_raises(engine: LocalEngine) -> None:
    """TC-005: get_conversation raises NotImplementedError with T1A.1 hint."""
    with pytest.raises(NotImplementedError) as exc:
        await engine.get_conversation("conv-x")
    assert "T1A.1" in str(exc.value)


@pytest.mark.asyncio
async def test_tc006_list_active_conversations_raises(engine: LocalEngine) -> None:
    """TC-006: list_active_conversations raises on all filter combos."""
    with pytest.raises(NotImplementedError):
        await engine.list_active_conversations()
    with pytest.raises(NotImplementedError):
        await engine.list_active_conversations(operator_id="op1")
    with pytest.raises(NotImplementedError) as exc:
        await engine.list_active_conversations(squad_id="sq1")
    assert "T1A.1" in str(exc.value)


@pytest.mark.asyncio
async def test_tc007_close_conversation_raises(engine: LocalEngine) -> None:
    """TC-007: close_conversation raises NotImplementedError with T1A.1 hint."""
    with pytest.raises(NotImplementedError) as exc:
        await engine.close_conversation(
            "conv-1", outcome=Outcome.RESOLVED, resolved_by="op1"
        )
    msg = str(exc.value)
    assert "T1A.1" in msg
    assert "lifecycle" in msg.lower()


@pytest.mark.asyncio
async def test_tc008_set_csat_raises(engine: LocalEngine) -> None:
    """TC-008: set_csat raises NotImplementedError with T1A.1 hint."""
    with pytest.raises(NotImplementedError) as exc:
        await engine.set_csat("conv-1", 5)
    assert "T1A.1" in str(exc.value)


@pytest.mark.asyncio
async def test_tc009_join_raises(engine: LocalEngine, participant_customer) -> None:
    """TC-009: join raises NotImplementedError with T1A.1 (participant) hint."""
    with pytest.raises(NotImplementedError) as exc:
        await engine.join("conv-1", participant_customer)
    msg = str(exc.value)
    assert "T1A.1" in msg
    assert "participant" in msg.lower()


@pytest.mark.asyncio
async def test_tc010_leave_raises(engine: LocalEngine) -> None:
    """TC-010: leave raises NotImplementedError with T1A.1 (participant) hint."""
    with pytest.raises(NotImplementedError) as exc:
        await engine.leave("conv-1", "u-customer-1")
    msg = str(exc.value)
    assert "T1A.1" in msg
    assert "participant" in msg.lower()


@pytest.mark.asyncio
async def test_tc011_switch_mode_raises(engine: LocalEngine) -> None:
    """TC-011: switch_mode(AUTO→COPILOT) raises with T1A.1 (mode) hint."""
    with pytest.raises(NotImplementedError) as exc:
        await engine.switch_mode(
            "conv-1",
            ConversationMode.COPILOT,
            triggered_by="op1",
            trigger="manual",
        )
    msg = str(exc.value)
    assert "T1A.1" in msg
    assert "mode" in msg.lower()


@pytest.mark.asyncio
async def test_tc012_send_message_raises(engine: LocalEngine) -> None:
    """TC-012: send_message raises with T1A.1 (messages) hint."""
    with pytest.raises(NotImplementedError) as exc:
        await engine.send_message("conv-1", source="u1", content="hi")
    msg = str(exc.value).lower()
    assert "t1a.1" in msg
    assert "message" in msg or "crud" in msg


@pytest.mark.asyncio
async def test_tc013_edit_message_raises(engine: LocalEngine) -> None:
    """TC-013: edit_message raises with T1A.1 (messages) hint."""
    with pytest.raises(NotImplementedError) as exc:
        await engine.edit_message(
            "conv-1", "msg-1", new_content="edited", edited_by="u1"
        )
    msg = str(exc.value).lower()
    assert "t1a.1" in msg
    assert "message" in msg or "crud" in msg


@pytest.mark.asyncio
async def test_tc014_delete_message_raises(engine: LocalEngine) -> None:
    """TC-014: delete_message raises with T1A.1 (messages) hint."""
    with pytest.raises(NotImplementedError) as exc:
        await engine.delete_message("conv-1", "msg-1", deleted_by="u1")
    msg = str(exc.value).lower()
    assert "t1a.1" in msg
    assert "message" in msg or "crud" in msg


@pytest.mark.asyncio
async def test_tc015_get_messages_raises(engine: LocalEngine) -> None:
    """TC-015: get_messages raises on all paging modes with T1A.1 hint."""
    with pytest.raises(NotImplementedError):
        await engine.get_messages("conv-1")
    with pytest.raises(NotImplementedError):
        await engine.get_messages("conv-1", since_sequence=10)
    with pytest.raises(NotImplementedError) as exc:
        await engine.get_messages("conv-1", before_sequence=10)
    assert "T1A.1" in str(exc.value)


@pytest.mark.asyncio
async def test_tc016_handle_command_raises(engine: LocalEngine) -> None:
    """TC-016: handle_command raises with T2A.1 hint."""
    with pytest.raises(NotImplementedError) as exc:
        await engine.handle_command("conv-1", actor_id="op1", command="/hijack")
    msg = str(exc.value).lower()
    assert "t2a.1" in msg
    assert "command" in msg


@pytest.mark.asyncio
async def test_tc017_set_timer_raises(engine: LocalEngine) -> None:
    """TC-017: set_timer raises with T1A.2 hint."""
    with pytest.raises(NotImplementedError) as exc:
        await engine.set_timer(
            "conv-1", "sla_first_reply", 60000, on_expire={"action": "noop"}
        )
    msg = str(exc.value).lower()
    assert "t1a.2" in msg
    assert "timer" in msg


@pytest.mark.asyncio
async def test_tc018_cancel_timer_raises(engine: LocalEngine) -> None:
    """TC-018: cancel_timer raises with T1A.2 hint."""
    with pytest.raises(NotImplementedError) as exc:
        await engine.cancel_timer("conv-1", "sla_first_reply")
    assert "T1A.2" in str(exc.value)


@pytest.mark.asyncio
async def test_tc019_subscribe_raises(engine: LocalEngine) -> None:
    """TC-019: subscribe iteration raises NotImplementedError with T1A.3 hint.

    LocalEngine.subscribe is implemented as `async def ... -> AsyncIterator`
    with an unreachable `yield` after `raise`, making it a valid async
    generator that raises immediately on iteration (not on the call itself).
    """
    agen = engine.subscribe(conversation_id="conv-1")
    with pytest.raises(NotImplementedError) as exc:
        async for _ in agen:
            break
    msg = str(exc.value).lower()
    assert "t1a.3" in msg
    assert "event" in msg or "bus" in msg


@pytest.mark.asyncio
async def test_tc020_query_events_raises(engine: LocalEngine) -> None:
    """TC-020: query_events raises with T1A.3 hint."""
    with pytest.raises(NotImplementedError) as exc:
        await engine.query_events("conv-1")
    assert "T1A.3" in str(exc.value)


def test_tc021_register_hook_raises(engine: LocalEngine) -> None:
    """TC-021: register_hook (sync) raises with T1A.3 (hooks) hint."""

    class DummyHook:
        pass

    with pytest.raises(NotImplementedError) as exc:
        engine.register_hook(DummyHook())  # type: ignore[arg-type]
    msg = str(exc.value).lower()
    assert "t1a.3" in msg
    assert "hook" in msg


# ----------------------------------------------------------------------------
# Group C · Skeleton boundary checks
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name,is_async,kwargs", PROTOCOL_METHOD_CALLS)
async def test_tc022_every_async_method_hint_matches_regex(
    engine: LocalEngine,
    method_name: str,
    is_async: bool,
    kwargs: dict,
) -> None:
    """TC-022 (async methods): every NotImplementedError hint matches T[12]A.\\d+."""
    method = getattr(engine, method_name)
    # Fill positional args the Protocol requires with placeholders
    positional = []
    if method_name in {
        "create_conversation",
        "list_active_conversations",
        "subscribe",
    }:
        pass  # keyword-only or no conv id
    elif method_name in {"get_conversation", "set_csat"}:
        positional = ["conv-x"] if method_name == "get_conversation" else ["conv-1", 5]
    elif method_name in {"close_conversation"}:
        positional = ["conv-1"]
    elif method_name in {"join"}:
        from datetime import datetime, timezone

        from autoservice.conversation_engine import Participant, ParticipantRole

        positional = [
            "conv-1",
            Participant(
                id="u1",
                role=ParticipantRole.CUSTOMER,
                joined_at=datetime.now(timezone.utc),
            ),
        ]
    elif method_name in {"leave"}:
        positional = ["conv-1", "u1"]
    elif method_name in {"switch_mode"}:
        positional = ["conv-1"]
    elif method_name in {"send_message"}:
        positional = ["conv-1"]
    elif method_name in {"edit_message"}:
        positional = ["conv-1", "msg-1"]
    elif method_name in {"delete_message"}:
        positional = ["conv-1", "msg-1"]
    elif method_name in {"get_messages", "query_events"}:
        positional = ["conv-1"]
    elif method_name in {"handle_command"}:
        positional = ["conv-1"]
    elif method_name in {"set_timer"}:
        positional = ["conv-1", "timer-x", 1000]
    elif method_name in {"cancel_timer"}:
        positional = ["conv-1", "timer-x"]

    with pytest.raises(NotImplementedError) as exc:
        await method(*positional, **kwargs)
    assert HINT_RE.search(str(exc.value)), (
        f"{method_name} hint missing T1A.x/T2A.1: {exc.value!r}"
    )


def test_tc022b_subscribe_hint_matches_regex(engine: LocalEngine) -> None:
    """TC-022 (subscribe variant): async-gen iteration hint matches regex.

    Runs via asyncio.run to keep this case out of the parametrized matrix,
    since subscribe's raise-on-iteration semantics differ from the other
    async methods.
    """
    import asyncio

    async def _iter() -> None:
        async for _ in engine.subscribe(conversation_id="conv-1"):
            break

    with pytest.raises(NotImplementedError) as exc:
        asyncio.run(_iter())
    assert HINT_RE.search(str(exc.value))


def test_tc022c_register_hook_hint_matches_regex(engine: LocalEngine) -> None:
    """TC-022 (sync register_hook): hint matches regex."""

    class DummyHook:
        pass

    with pytest.raises(NotImplementedError) as exc:
        engine.register_hook(DummyHook())  # type: ignore[arg-type]
    assert HINT_RE.search(str(exc.value))


def test_tc023_no_autoservice_engine_dir() -> None:
    """TC-023: the incorrect `autoservice/engine/` directory does not exist."""
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    wrong = repo_root / "autoservice" / "engine"
    assert not wrong.exists(), (
        f"unexpected directory exists: {wrong} — kickoff forbids this path"
    )


def test_tc024_no_enum_redefinition_in_local_engine() -> None:
    """TC-024: local_engine.py does not redefine any T0.1 enum."""
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    source = (
        repo_root / "autoservice" / "conversation_engine" / "local_engine.py"
    ).read_text(encoding="utf-8")
    forbidden = [
        "class Mode",
        "class Visibility",
        "class ConversationMode",
        "class MessageVisibility",
        "class EventType",
        "class ParticipantRole",
        "class Outcome",
        "class ConversationState",
    ]
    hits = [tok for tok in forbidden if tok in source]
    assert not hits, f"local_engine.py redefines enums: {hits}"


# ----------------------------------------------------------------------------
# Group D · __init__ export integrity
# ----------------------------------------------------------------------------


def test_tc025_init_exports_include_local_engine_without_regressing_t01() -> None:
    """TC-025: __init__ exposes LocalEngine and preserves T0.1 exports."""
    from autoservice import conversation_engine as ce

    assert "LocalEngine" in ce.__all__
    assert ce.LocalEngine is LocalEngine

    # T0.1 frozen exports must still resolve
    required_t01 = [
        "ConversationEngine",
        "PluginHook",
        "Conversation",
        "ConversationMode",
        "ConversationState",
        "Event",
        "EventType",
        "Message",
        "MessageVisibility",
        "Outcome",
        "Participant",
        "ParticipantRole",
        "Resolution",
        "Timer",
        "EngineError",
        "ConversationNotFound",
        "ConversationAlreadyClosed",
        "IllegalModeTransition",
        "PermissionDenied",
        "TimerNotFound",
        "UnknownParticipant",
        "ValidationError",
    ]
    missing = [name for name in required_t01 if not hasattr(ce, name)]
    assert not missing, f"T0.1 exports missing after LocalEngine add: {missing}"
    assert len(ce.__all__) >= len(required_t01) + 1
