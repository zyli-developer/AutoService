"""Verify _arm_takeover_timer is a no-op for passive_channel conversations."""
from __future__ import annotations

import pytest

from autoservice.conversation_engine import LocalEngine


@pytest.mark.asyncio
async def test_passive_channel_skips_takeover_arm():
    """Passive-channel conv: _arm_takeover_timer should NOT register any state."""
    engine = LocalEngine()
    conv = await engine.create_conversation(
        channel="cinnox", external_id="tA:inq1",
        metadata={"tenant_id": "tA", "passive_channel": True},
    )
    engine._arm_takeover_timer(conv.id, operator_id="op1")
    # Internal state container is _takeover_tasks (verified at line 160 / 827)
    assert conv.id not in engine._takeover_tasks


@pytest.mark.asyncio
async def test_active_channel_still_arms_takeover():
    """Regression: web/feishu conversations (no passive_channel) still arm normally."""
    engine = LocalEngine()
    conv = await engine.create_conversation(
        channel="web", external_id="cust1", metadata={},
    )
    engine._arm_takeover_timer(conv.id, operator_id="op1")
    assert conv.id in engine._takeover_tasks
    # Clean up the scheduled tasks so test teardown doesn't leak warnings
    engine._cancel_takeover_timer(conv.id)
