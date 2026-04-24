"""Triage state on Conversation.metadata + TRIAGE participant role.

Spec: docs/superpowers/specs/2026-04-21-multi-role-triage-dispatch-design.md §3
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import ParticipantRole


def test_triage_role_exists():
    assert ParticipantRole.TRIAGE.value == "triage"


@pytest_asyncio.fixture()
async def engine() -> "LocalEngine":
    return LocalEngine()


@pytest.mark.asyncio
async def test_triage_state_defaults_to_empty(engine):
    conv = await engine.create_conversation(channel="web", external_id="c1")
    state = await engine.get_triage_state(conv.id)
    assert state == {
        "active_role": None,
        "cc_instance_id": None,
        "detected_language": None,
        "drift_counter": 0,
        "triage_mode": "drift",
    }


@pytest.mark.asyncio
async def test_update_triage_state_merges(engine):
    conv = await engine.create_conversation(channel="web", external_id="c2")
    await engine.update_triage_state(
        conv.id, active_role="lead", cc_instance_id="cc-042",
    )
    state = await engine.get_triage_state(conv.id)
    assert state["active_role"] == "lead"
    assert state["cc_instance_id"] == "cc-042"
    assert state["drift_counter"] == 0  # unchanged fields preserved


@pytest.mark.asyncio
async def test_incr_and_reset_drift(engine):
    conv = await engine.create_conversation(channel="web", external_id="c3")
    assert await engine.incr_drift(conv.id) == 1
    assert await engine.incr_drift(conv.id) == 2
    await engine.reset_drift(conv.id)
    assert (await engine.get_triage_state(conv.id))["drift_counter"] == 0


@pytest.mark.asyncio
async def test_triage_state_survives_unrelated_metadata(engine):
    conv = await engine.create_conversation(
        channel="web", external_id="c4", metadata={"squad_id": "S1"},
    )
    await engine.update_triage_state(conv.id, active_role="customer")
    conv2 = await engine.get_conversation(conv.id)
    assert conv2.metadata["squad_id"] == "S1"
    assert conv2.metadata["triage"]["active_role"] == "customer"


@pytest.mark.asyncio
async def test_update_triage_state_rejects_unknown_field(engine):
    conv = await engine.create_conversation(channel="web", external_id="c5")
    with pytest.raises(KeyError, match="unknown_field"):
        await engine.update_triage_state(conv.id, unknown_field="x")
