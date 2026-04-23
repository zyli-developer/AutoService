"""In-session model upgrade via ``ClaudeSDKClient.set_model`` (plan C).

The SDK supports runtime model switching without tearing down the
subprocess, so the customer sticky pool can default to haiku (fast /
cheap for keyword-like turns) and escalate to sonnet the first time
the router flags a turn as slow-tier. Escalation is one-way per sticky
session — once upgraded, we don't switch back, matching the old demo's
`_sdk_ensure` semantics (no model thrashing mid-conversation).

Contract pinned here:

  1. CCClient.set_model → SDK.set_model (thin passthrough)
  2. session_query(..., tier="fast") uses fast_model; no set_model call
     when instance already matches that tier.
  3. session_query(..., tier="slow") on an instance currently at fast
     triggers exactly one set_model(slow_model) before querying.
  4. After an upgrade to slow, subsequent session_query(..., tier="fast")
     on the same sticky key DOES NOT downgrade — the instance stays on
     slow for the session's lifetime (sticky release resets it).
  5. tier=None (legacy callers) leaves the current model alone.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoservice.cc_pool import CCClient, CCPool, PoolConfig


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def _fake_sdk_client():
    """Mock of ClaudeSDKClient — tracks set_model + connect/disconnect."""
    sdk = MagicMock()
    sdk.connect = AsyncMock()
    sdk.disconnect = AsyncMock()
    sdk.query = AsyncMock()
    sdk.set_model = AsyncMock()

    async def _noop_stream():
        return
        yield  # pragma: no cover
    sdk.receive_response = _noop_stream

    # is_healthy inspects _transport._process — give it a living one.
    sdk._transport = MagicMock()
    sdk._transport._process = MagicMock(returncode=None)
    return sdk


def _fake_cc_client():
    """Build a CCClient wrapping a mocked SDK."""
    sdk = _fake_sdk_client()
    return CCClient(sdk)


@pytest.fixture(autouse=True)
def _patch_create(monkeypatch):
    """Replace create_cc_client with a fake factory so no Claude CLI
    is spawned. Each returned client is a fresh mock."""
    async def _factory(config, *args, **kwargs):
        return _fake_cc_client()
    monkeypatch.setattr("autoservice.cc_pool.create_cc_client", _factory)


@pytest.fixture()
async def tiered_pool():
    cfg = PoolConfig(
        min_size=0, max_size=2, warmup_count=0,
        model=None,
        fast_model="claude-haiku-4-5",
        slow_model="claude-sonnet-4-6",
    )
    p = CCPool(cfg)
    await p.start()
    yield p
    await p.shutdown()


# ---------------------------------------------------------------------------
# CCClient.set_model — thin passthrough
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ccclient_set_model_passes_through_to_sdk():
    sdk = _fake_sdk_client()
    client = CCClient(sdk)
    await client.set_model("claude-sonnet-4-6")
    sdk.set_model.assert_awaited_once_with("claude-sonnet-4-6")


# ---------------------------------------------------------------------------
# session_query(tier=...) — upgrade-once semantics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_query_fast_tier_does_not_call_set_model(tiered_pool):
    """Customer instance starts on fast_model by default (_ROLE_TIER['customer']
    == 'fast'); a fast-tier turn should not re-set the model."""
    async for _ in tiered_pool.session_query("conv-1", "hi", tier="fast"):
        pass
    inst = tiered_pool._sticky_bindings["conv-1"].instance  # noqa: SLF001
    inst.client._sdk.set_model.assert_not_called()


@pytest.mark.asyncio
async def test_session_query_slow_tier_triggers_upgrade_once(tiered_pool):
    """First slow turn on a fast-default sticky instance triggers
    exactly one set_model call with the slow_model value."""
    # Turn 1: fast (baseline)
    async for _ in tiered_pool.session_query("conv-2", "hi", tier="fast"):
        pass
    # Turn 2: slow — must upgrade
    async for _ in tiered_pool.session_query("conv-2", "我要投诉", tier="slow"):
        pass
    inst = tiered_pool._sticky_bindings["conv-2"].instance  # noqa: SLF001
    inst.client._sdk.set_model.assert_awaited_once_with("claude-sonnet-4-6")


@pytest.mark.asyncio
async def test_session_query_slow_then_fast_stays_on_slow(tiered_pool):
    """Post-upgrade, a fast-tier turn must NOT downgrade — mirrors the
    old demo's 'stay on sonnet after gate cleared' policy."""
    # Upgrade
    async for _ in tiered_pool.session_query("conv-3", "问题", tier="slow"):
        pass
    inst = tiered_pool._sticky_bindings["conv-3"].instance  # noqa: SLF001
    assert inst.client._sdk.set_model.await_count == 1

    # A fast turn after upgrade — must not call set_model again.
    async for _ in tiered_pool.session_query("conv-3", "ok", tier="fast"):
        pass
    assert inst.client._sdk.set_model.await_count == 1, (
        "downgrade attempted — sticky instance should stay on slow tier"
    )


@pytest.mark.asyncio
async def test_session_query_repeated_slow_does_not_reupgrade(tiered_pool):
    """Two consecutive slow turns should trigger set_model only once
    (the first); the second recognizes the instance is already upgraded."""
    async for _ in tiered_pool.session_query("conv-4", "msg1", tier="slow"):
        pass
    async for _ in tiered_pool.session_query("conv-4", "msg2", tier="slow"):
        pass
    inst = tiered_pool._sticky_bindings["conv-4"].instance  # noqa: SLF001
    assert inst.client._sdk.set_model.await_count == 1


@pytest.mark.asyncio
async def test_session_query_without_tier_kwarg_is_legacy_noop(tiered_pool):
    """Callers that don't pass tier (existing M1/M2 code) see unchanged
    behavior — no set_model side-effect."""
    async for _ in tiered_pool.session_query("conv-5", "anything"):
        pass
    inst = tiered_pool._sticky_bindings["conv-5"].instance  # noqa: SLF001
    inst.client._sdk.set_model.assert_not_called()


@pytest.mark.asyncio
async def test_sticky_release_resets_upgrade_state(tiered_pool):
    """End-session returns the instance to the warm pool and a later
    session can start on fast again (upgrade state is per-sticky-session,
    not baked into the instance forever)."""
    # Upgrade conv-6 to slow
    async for _ in tiered_pool.session_query("conv-6", "complaint", tier="slow"):
        pass
    await tiered_pool.end_session("conv-6")

    # Same key rebinds — should start fresh (fast tier by default).
    async for _ in tiered_pool.session_query("conv-6", "hi again", tier="fast"):
        pass
    inst = tiered_pool._sticky_bindings["conv-6"].instance  # noqa: SLF001
    # If the stamp carried over, set_model would never have been called on
    # the "release", so the guard is: after release we DO NOT require
    # set_model for a subsequent fast turn; but a fresh slow turn on the
    # recycled instance must still trigger an upgrade.
    set_count_before = inst.client._sdk.set_model.await_count
    async for _ in tiered_pool.session_query("conv-6", "complex again", tier="slow"):
        pass
    assert inst.client._sdk.set_model.await_count == set_count_before + 1, (
        "sticky release should clear upgrade stamp; re-slow should re-upgrade"
    )


# ---------------------------------------------------------------------------
# Fast-only deployments (slow_model unset) must not crash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_slow_tier_without_slow_model_falls_back_silently():
    """If slow_model isn't configured, a slow-tier request should NOT
    raise — the pool degrades to the base model (whatever the instance
    was warmed with) and logs the skip.
    """
    cfg = PoolConfig(
        min_size=0, max_size=2, warmup_count=0,
        fast_model="claude-haiku-4-5",
        # slow_model intentionally unset
    )
    pool = CCPool(cfg)
    await pool.start()
    try:
        async for _ in pool.session_query("conv-fb", "msg", tier="slow"):
            pass
        inst = pool._sticky_bindings["conv-fb"].instance  # noqa: SLF001
        # No slow_model configured → we don't call set_model with None
        # (which would mean "reset to default" per SDK docs — undesired).
        inst.client._sdk.set_model.assert_not_called()
    finally:
        await pool.shutdown()
