"""Tests for LifecyclePlugin — CRM lifecycle hooks."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import (
    Conversation,
    ConversationMode,
    ConversationState,
    Outcome,
    Participant,
    ParticipantRole,
    Resolution,
)
from autoservice.plugins.lifecycle_plugin import LifecyclePlugin


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_crm_mock() -> MagicMock:
    crm = MagicMock()
    crm.upsert_contact.return_value = {"open_id": "cust-1", "name": "Alice"}
    crm.log_message.return_value = None
    return crm


def _make_conv(
    conv_id: str = "ch_ext1",
    *,
    state: ConversationState = ConversationState.CREATED,
    metadata: dict | None = None,
    resolution: Resolution | None = None,
) -> Conversation:
    now = _now()
    return Conversation(
        id=conv_id,
        state=state,
        mode=ConversationMode.AUTO,
        participants=(),
        created_at=now,
        updated_at=now,
        metadata=metadata or {"customer_id": "cust-1", "customer_name": "Alice"},
        resolution=resolution,
    )


# ---------- Unit tests ----------


@pytest.mark.asyncio
async def test_on_conversation_created_stores_crm_record():
    crm = _make_crm_mock()
    plugin = LifecyclePlugin(crm=crm)
    conv = _make_conv()

    await plugin.on_conversation_created(conv)

    crm.upsert_contact.assert_called_once_with(open_id="cust-1", name="Alice")
    assert conv.id in plugin._records
    assert plugin._records[conv.id]["contact"] == {"open_id": "cust-1", "name": "Alice"}


@pytest.mark.asyncio
async def test_on_conversation_closed_updates_record():
    crm = _make_crm_mock()
    plugin = LifecyclePlugin(crm=crm)
    conv = _make_conv()

    # Simulate create first so record exists
    await plugin.on_conversation_created(conv)

    # Close with resolution
    closed_conv = _make_conv(
        state=ConversationState.CLOSED,
        resolution=Resolution(
            outcome=Outcome.RESOLVED,
            resolved_by="op-1",
            csat_score=5,
        ),
    )
    await plugin.on_conversation_closed(closed_conv)

    record = plugin._records[conv.id]
    assert record["outcome"] == "resolved"
    assert record["csat"] == 5
    assert record["resolved_by"] == "op-1"
    assert "closed_at" in record

    crm.log_message.assert_called_once()
    call_kwargs = crm.log_message.call_args
    assert "closed" in call_kwargs.kwargs.get("text", call_kwargs[1].get("text", "")).lower() or \
           "closed" in str(call_kwargs).lower()


@pytest.mark.asyncio
async def test_on_conversation_closed_without_resolution():
    crm = _make_crm_mock()
    plugin = LifecyclePlugin(crm=crm)
    conv = _make_conv(state=ConversationState.CLOSED)

    await plugin.on_conversation_closed(conv)

    record = plugin._records[conv.id]
    assert record["outcome"] == ""
    assert record["csat"] is None


@pytest.mark.asyncio
async def test_on_event_is_noop():
    """on_event should not raise."""
    crm = _make_crm_mock()
    plugin = LifecyclePlugin(crm=crm)
    from autoservice.conversation_engine.types import Event

    ev = Event(
        id="e1",
        type="test",
        conversation_id="c1",
        data={},
        timestamp=_now(),
    )
    await plugin.on_event(ev)  # should not raise


# ---------- Integration test with LocalEngine ----------


@pytest.mark.asyncio
async def test_integration_create_and_close():
    """Register plugin with LocalEngine, create + close conversation, verify CRM calls."""
    crm = _make_crm_mock()
    plugin = LifecyclePlugin(crm=crm)

    engine = LocalEngine()
    engine.register_hook(plugin)

    # Create conversation
    conv = await engine.create_conversation(
        channel="web",
        external_id="ext-42",
        metadata={"customer_id": "cust-1", "customer_name": "Alice"},
    )
    assert conv.id == "web_ext-42"

    # Verify CRM upsert was called
    crm.upsert_contact.assert_called_once_with(open_id="cust-1", name="Alice")
    assert conv.id in plugin._records

    # Close conversation
    closed = await engine.close_conversation(
        conv.id,
        outcome=Outcome.RESOLVED,
        resolved_by="op-1",
    )
    assert closed.state == ConversationState.CLOSED

    # Verify CRM log_message was called on close
    crm.log_message.assert_called_once()
    record = plugin._records[conv.id]
    assert record["outcome"] == "resolved"
    assert record["resolved_by"] == "op-1"


@pytest.mark.asyncio
async def test_integration_metadata_without_customer_id():
    """When metadata has no customer_id, falls back to conv.id."""
    crm = _make_crm_mock()
    plugin = LifecyclePlugin(crm=crm)

    engine = LocalEngine()
    engine.register_hook(plugin)

    conv = await engine.create_conversation(
        channel="feishu",
        external_id="ext-99",
    )

    # Should use conv.id as fallback open_id
    call_args = crm.upsert_contact.call_args
    assert call_args.kwargs["open_id"] == conv.id
