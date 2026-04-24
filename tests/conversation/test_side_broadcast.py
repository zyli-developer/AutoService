"""TRIAGE SIDE messages: operator sees, customer doesn't."""
from __future__ import annotations

import asyncio
import pytest
import pytest_asyncio

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import (
    MessageVisibility, Participant, ParticipantRole,
)
from datetime import datetime, timezone


@pytest_asyncio.fixture()
async def engine():
    return LocalEngine()


async def _join_triage_participant(engine: LocalEngine, conv_id: str) -> None:
    await engine.join(
        conv_id,
        Participant(
            id="triage",
            role=ParticipantRole.TRIAGE,
            joined_at=datetime.now(timezone.utc),
        ),
    )


@pytest.mark.asyncio
async def test_operator_sees_triage_side(engine):
    conv = await engine.create_conversation(channel="web", external_id="v1")
    await _join_triage_participant(engine, conv.id)
    await engine.send_message(
        conv.id, source="triage", content="[分流] ...",
        requested_visibility=MessageVisibility.SIDE,
        metadata={"type": "triage_decision"},
    )
    msgs = await engine.get_messages(
        conv.id, viewer_role=ParticipantRole.OPERATOR, limit=50,
    )
    assert any(m.source == "triage" for m in msgs)


@pytest.mark.asyncio
async def test_customer_does_not_see_triage_side(engine):
    conv = await engine.create_conversation(channel="web", external_id="v2")
    await _join_triage_participant(engine, conv.id)
    await engine.send_message(
        conv.id, source="triage", content="[分流] ...",
        requested_visibility=MessageVisibility.SIDE,
        metadata={"type": "triage_decision"},
    )
    msgs = await engine.get_messages(
        conv.id, viewer_role=ParticipantRole.CUSTOMER, limit=50,
    )
    assert not any(m.source == "triage" for m in msgs)
