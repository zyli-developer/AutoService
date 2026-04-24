"""Tests for ``autoservice.role_switch`` — handoff-triggered role switch (M3 T3S.2).

Contract: docs/contracts/m3/e3-triage.md §2.3.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from autoservice.history_compressor import COMPRESSION_THRESHOLD_MESSAGES
from autoservice.role_switch import (
    RoleSwitchOutcome,
    maybe_role_switch,
)


# ──────────────────────────────────────────────────────────────────────────
# Test doubles
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class _Msg:
    role: str
    content: str


class _FakePool:
    """Minimal cc_pool stub recording calls."""

    def __init__(self):
        self.released: list[str] = []
        self.acquired: list[dict] = []
        self._next_instance = object()

    async def release_sticky(self, key: str) -> None:
        self.released.append(key)

    async def acquire_sticky(
        self, key: str, *, role=None, tenant_id=None, timeout=None,
    ) -> Any:
        self.acquired.append({
            "key": key, "role": role, "tenant_id": tenant_id,
            "timeout": timeout,
        })
        return self._next_instance


def _make_event_recorder():
    events: list[tuple[str, dict]] = []

    async def emit(name: str, payload: dict) -> None:
        events.append((name, payload))

    return events, emit


# ──────────────────────────────────────────────────────────────────────────
# No handoff present
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_handoff_returns_none_and_original_output():
    pool = _FakePool()
    out, cleaned = await maybe_role_switch(
        agent_output="plain reply with no tag",
        conversation_id="c1", current_role="customer", tenant_id="acme",
        history=[], cc_pool=pool,
    )
    assert out is None
    assert cleaned == "plain reply with no tag"
    assert pool.released == []
    assert pool.acquired == []


@pytest.mark.asyncio
async def test_malformed_handoff_returns_none():
    pool = _FakePool()
    out, cleaned = await maybe_role_switch(
        agent_output='<handoff />',  # missing required 'to' attr
        conversation_id="c1", current_role="customer", tenant_id="acme",
        history=[], cc_pool=pool,
    )
    assert out is None
    assert pool.released == []


@pytest.mark.asyncio
async def test_unknown_role_returns_none():
    pool = _FakePool()
    out, cleaned = await maybe_role_switch(
        agent_output='<handoff to="hacker" />',
        conversation_id="c1", current_role="customer", tenant_id="acme",
        history=[], cc_pool=pool,
    )
    assert out is None
    assert pool.released == []


# ──────────────────────────────────────────────────────────────────────────
# Same-role guard (no-op but strip tag)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handoff_to_same_role_is_noop():
    """Agent emitting <handoff to='customer'> while it IS customer → no switch."""
    pool = _FakePool()
    out, cleaned = await maybe_role_switch(
        agent_output='reply <handoff to="customer" /> end',
        conversation_id="c1", current_role="customer", tenant_id="acme",
        history=[], cc_pool=pool,
    )
    assert out is None
    # Tag stripped even though switch didn't happen
    assert "<handoff" not in cleaned
    assert pool.released == []
    assert pool.acquired == []


# ──────────────────────────────────────────────────────────────────────────
# Happy path: full switch
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_switches_role_and_emits_events():
    pool = _FakePool()
    events, emit = _make_event_recorder()
    history = [_Msg("customer", f"msg {i}") for i in range(5)]

    out, cleaned = await maybe_role_switch(
        agent_output='handing off <handoff to="lead" reason="wants demo" />',
        conversation_id="conv-42",
        current_role="customer",
        tenant_id="acme",
        history=history,
        cc_pool=pool,
        emit_event=emit,
    )

    assert out is not None
    assert isinstance(out, RoleSwitchOutcome)
    assert out.from_role == "customer"
    assert out.to_role == "lead"
    assert out.reason == "wants demo"
    assert out.conversation_id == "conv-42"
    assert "<handoff" not in cleaned
    assert "<handoff" not in out.cleaned_agent_output

    # Pool orchestration
    assert pool.released == ["conv-42"]
    assert len(pool.acquired) == 1
    acq = pool.acquired[0]
    assert acq["key"] == "conv-42"
    assert acq["role"] == "lead"
    assert acq["tenant_id"] == "acme"

    # Events emitted in order
    assert [e[0] for e in events] == ["handoff.detected", "role.switched"]
    assert events[0][1]["from_role"] == "customer"
    assert events[0][1]["to_role"] == "lead"
    assert events[1][1]["conversation_id"] == "conv-42"


@pytest.mark.asyncio
async def test_reseed_prompt_contains_role_and_tail():
    pool = _FakePool()
    history = [_Msg("customer", f"turn {i}") for i in range(5)]
    out, _ = await maybe_role_switch(
        agent_output='<handoff to="translate" />',
        conversation_id="c1", current_role="customer", tenant_id="acme",
        history=history, cc_pool=pool,
    )
    assert out is not None
    # Short history (5 < 20) → compressed=False; tail has all 5 msgs
    assert "[Handoff to translate]" in out.reseed_prompt
    assert "turn 4" in out.reseed_prompt
    assert out.compression.compressed is False


@pytest.mark.asyncio
async def test_reseed_prompt_compresses_long_history():
    pool = _FakePool()
    history = [_Msg("customer", f"turn {i}") for i in range(30)]
    out, _ = await maybe_role_switch(
        agent_output='<handoff to="lead" />',
        conversation_id="c1", current_role="customer", tenant_id="acme",
        history=history, cc_pool=pool,
    )
    assert out is not None
    assert out.compression.compressed is True
    assert "[Conversation summary so far]" in out.reseed_prompt
    # Tail is last 3 messages
    assert "turn 29" in out.reseed_prompt
    assert "turn 27" in out.reseed_prompt


# ──────────────────────────────────────────────────────────────────────────
# Event emitter optional
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_emitter_still_switches():
    pool = _FakePool()
    out, _ = await maybe_role_switch(
        agent_output='<handoff to="lead" />',
        conversation_id="c1", current_role="customer", tenant_id="acme",
        history=[], cc_pool=pool,
        emit_event=None,
    )
    assert out is not None
    assert pool.acquired[0]["role"] == "lead"


# ──────────────────────────────────────────────────────────────────────────
# Pool instance carried on outcome
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_outcome_carries_new_pool_instance():
    pool = _FakePool()
    sentinel = object()
    pool._next_instance = sentinel
    out, _ = await maybe_role_switch(
        agent_output='<handoff to="lead" />',
        conversation_id="c1", current_role="customer", tenant_id="acme",
        history=[], cc_pool=pool,
    )
    assert out.pool_instance is sentinel


# ──────────────────────────────────────────────────────────────────────────
# Acquire timeout propagated
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_acquire_timeout_passed_through():
    pool = _FakePool()
    await maybe_role_switch(
        agent_output='<handoff to="lead" />',
        conversation_id="c1", current_role="customer", tenant_id="acme",
        history=[], cc_pool=pool,
        acquire_timeout=5.0,
    )
    assert pool.acquired[0]["timeout"] == 5.0


# ──────────────────────────────────────────────────────────────────────────
# Outcome immutability
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_outcome_is_frozen():
    pool = _FakePool()
    out, _ = await maybe_role_switch(
        agent_output='<handoff to="lead" />',
        conversation_id="c1", current_role="customer", tenant_id="acme",
        history=[], cc_pool=pool,
    )
    with pytest.raises(Exception):
        out.to_role = "hacker"  # type: ignore[misc]
