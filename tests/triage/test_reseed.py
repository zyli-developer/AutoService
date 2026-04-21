"""History re-seed on role switch — §2.5 of the spec."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import (
    MessageVisibility,
    Participant,
    ParticipantRole,
)
from autoservice.triage_dispatch import _build_reseeded_prompt, _estimate_tokens


@pytest_asyncio.fixture()
async def seeded_engine():
    engine = LocalEngine()
    conv = await engine.create_conversation(channel="web", external_id="r1")
    now = datetime.now(timezone.utc)
    await engine.join(
        conv.id,
        Participant(id="customer", role=ParticipantRole.CUSTOMER, joined_at=now),
    )
    await engine.join(
        conv.id,
        Participant(id="agent", role=ParticipantRole.AGENT, joined_at=now),
    )
    for source, text in [
        ("customer", "你好"),
        ("agent", "你好,有什么可以帮你"),
        ("customer", "产品怎么用"),
    ]:
        await engine.send_message(conv.id, source=source, content=text)
    return engine, conv.id


@pytest.mark.asyncio
async def test_no_reseed_on_same_role(seeded_engine):
    engine, conv_id = seeded_engine
    prompt = await _build_reseeded_prompt(
        engine, conv_id, "再问一个问题",
        previous_role="customer", new_role="customer",
        token_limit=2000,
    )
    assert prompt == "再问一个问题"


@pytest.mark.asyncio
async def test_reseed_includes_history_on_switch(seeded_engine):
    engine, conv_id = seeded_engine
    prompt = await _build_reseeded_prompt(
        engine, conv_id, "我想买",
        previous_role="customer", new_role="lead",
        token_limit=2000,
    )
    assert "<conversation_history>" in prompt
    assert "你好" in prompt
    assert "产品怎么用" in prompt
    assert "我想买" in prompt
    assert "You are now the lead agent" in prompt


@pytest.mark.asyncio
async def test_reseed_truncates_when_token_limit_hit(seeded_engine):
    engine, conv_id = seeded_engine
    prompt = await _build_reseeded_prompt(
        engine, conv_id, "再问",
        previous_role="customer", new_role="lead",
        token_limit=5,
    )
    assert "产品怎么用" in prompt
