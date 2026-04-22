"""Placeholder-then-stream behavior in `_drain_with_placeholder`.

Strategy 1 + 3 (per design discussion 2026-04-22):
  1) Eligibility gate — only target_role in {customer, lead} can ever
     trigger a placeholder. translate/triage paths return the haiku reply
     directly and must never see a "正在查询..." bubble.
  2) Timer gate — even when eligible, only fire if the first model token
     hasn't arrived within `delay_s`. Sub-second sonnet replies stay
     placeholder-free.

These tests stub the CC SDK message stream and a minimal engine/ws so the
helper can be exercised without spinning up the gateway.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoservice.gateway.message_router import (
    PLACEHOLDER_DELAY_S,
    PLACEHOLDER_ELIGIBLE_ROLES,
    _drain_with_placeholder,
    _placeholder_text,
)


# ---------------------------------------------------------------------------
# Fakes mirroring just enough of CC SDK + engine + ws shapes
# ---------------------------------------------------------------------------

@dataclass
class _FakeBlock:
    text: str


@dataclass
class _FakeAssistantMessage:
    """Walks like claude_agent_sdk.types.AssistantMessage for isinstance checks."""
    content: list[_FakeBlock]


@dataclass
class _FakeResultMessage:
    result: str | None


@pytest.fixture(autouse=True)
def _patch_sdk_types(monkeypatch):
    """Make _drain_with_placeholder's isinstance() checks match our fakes.

    The helper imports AssistantMessage/ResultMessage at call time from
    claude_agent_sdk.types; we swap those attributes for our dataclasses
    so the streaming branch picks them up without instantiating real SDK
    objects.
    """
    import claude_agent_sdk.types as sdk_types
    monkeypatch.setattr(sdk_types, "AssistantMessage", _FakeAssistantMessage)
    monkeypatch.setattr(sdk_types, "ResultMessage", _FakeResultMessage)


def _msg(content: str, *, mid: str = "m-1"):
    """Construct a stub Message-shaped namespace for engine.send_message."""
    from types import SimpleNamespace
    return SimpleNamespace(
        id=mid, conversation_id="conv-1", source="agent",
        content=content, sequence_number=1,
        timestamp=__import__("datetime").datetime.utcnow(),
        edit_of=None, metadata={"is_placeholder": True},
        visibility=__import__(
            "autoservice.conversation_engine.types", fromlist=["MessageVisibility"],
        ).MessageVisibility.PUBLIC,
    )


async def _stream(items: list[Any], pre_delay_s: float = 0.0):
    """AsyncIterator factory — sleeps `pre_delay_s` before first yield."""
    if pre_delay_s > 0:
        await asyncio.sleep(pre_delay_s)
    for x in items:
        yield x


@pytest.fixture()
def fake_engine():
    eng = MagicMock()
    eng.send_message = AsyncMock(return_value=_msg("正在查询..."))
    return eng


@pytest.fixture()
def fake_ws():
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


@pytest.fixture(autouse=True)
def _stub_broadcast(monkeypatch):
    """`_drain_with_placeholder` calls _broadcast_to_squad on placeholder push;
    operator-side broadcast is a separate concern — short-circuit it.
    """
    async def _noop(*args, **kwargs):
        return
    monkeypatch.setattr(
        "autoservice.gateway.message_router._broadcast_to_squad", _noop,
    )


# ---------------------------------------------------------------------------
# Constants + helpers — unit tests
# ---------------------------------------------------------------------------

class TestConstants:
    def test_eligible_roles_default(self):
        assert PLACEHOLDER_ELIGIBLE_ROLES == frozenset({"customer", "lead"})

    def test_delay_default_is_1500ms(self):
        assert PLACEHOLDER_DELAY_S == pytest.approx(1.5)


class TestPlaceholderText:
    def test_chinese_default(self):
        assert "正在" in _placeholder_text(None)
        assert "正在" in _placeholder_text("zh")

    def test_english_when_lang_starts_with_en(self):
        text = _placeholder_text("en")
        assert "正在" not in text
        # Loose assertion — exact wording may evolve, just ensure it's English.
        assert any(w in text.lower() for w in ("looking", "moment", "checking"))


# ---------------------------------------------------------------------------
# Strategy 1 — eligibility gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ineligible_role_never_sends_placeholder(fake_engine, fake_ws):
    """translate/triage paths must skip placeholder even on long delays."""
    iterator = _stream(
        [_FakeAssistantMessage([_FakeBlock("hello")])],
        pre_delay_s=0.05,  # well past the test's tiny delay_s
    )
    reply, ph = await _drain_with_placeholder(
        iterator, engine=fake_engine, conv_id="conv-1",
        target_role="translate", ws=fake_ws, eligible=False,
        delay_s=0.01,
    )
    assert reply == "hello"
    assert ph is None
    fake_engine.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_eligible_flag_required_for_placeholder(fake_engine, fake_ws):
    """eligible=False short-circuits the timer regardless of role string."""
    iterator = _stream(
        [_FakeAssistantMessage([_FakeBlock("ok")])],
        pre_delay_s=0.05,
    )
    reply, ph = await _drain_with_placeholder(
        iterator, engine=fake_engine, conv_id="conv-1",
        target_role="customer", ws=fake_ws, eligible=False,
        delay_s=0.01,
    )
    assert ph is None
    fake_engine.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# Strategy 3 — timer gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fast_first_token_skips_placeholder(fake_engine, fake_ws):
    """Token within delay_s → no placeholder, no engine.send_message."""
    iterator = _stream(
        [_FakeAssistantMessage([_FakeBlock("instant")])],
        pre_delay_s=0.0,  # arrives immediately
    )
    reply, ph = await _drain_with_placeholder(
        iterator, engine=fake_engine, conv_id="conv-1",
        target_role="customer", ws=fake_ws, eligible=True,
        delay_s=0.10,
    )
    assert reply == "instant"
    assert ph is None
    fake_engine.send_message.assert_not_called()
    fake_ws.send_json.assert_not_called()


@pytest.mark.asyncio
async def test_slow_first_token_triggers_placeholder(fake_engine, fake_ws):
    """First token after delay_s → placeholder sent, ws push happens."""
    iterator = _stream(
        [_FakeAssistantMessage([_FakeBlock("late reply")])],
        pre_delay_s=0.08,  # delay_s = 0.02 → token arrives ~4x later
    )
    reply, ph = await _drain_with_placeholder(
        iterator, engine=fake_engine, conv_id="conv-1",
        target_role="customer", ws=fake_ws, eligible=True,
        delay_s=0.02,
    )
    assert reply == "late reply"
    assert ph is not None
    fake_engine.send_message.assert_called_once()
    # Verify metadata flag the frontend keys off of.
    call_kwargs = fake_engine.send_message.call_args.kwargs
    assert call_kwargs["metadata"] == {"is_placeholder": True}
    fake_ws.send_json.assert_called_once()


@pytest.mark.asyncio
async def test_lead_role_also_eligible(fake_engine, fake_ws):
    """lead is the second role in the eligibility set — same behavior."""
    iterator = _stream(
        [_FakeAssistantMessage([_FakeBlock("商机")])],
        pre_delay_s=0.08,
    )
    reply, ph = await _drain_with_placeholder(
        iterator, engine=fake_engine, conv_id="conv-1",
        target_role="lead", ws=fake_ws, eligible=True,
        delay_s=0.02,
    )
    assert ph is not None
    assert reply == "商机"


# ---------------------------------------------------------------------------
# Robustness — engine/ws failures must not break the stream
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_placeholder_send_failure_degrades_silently(fake_engine, fake_ws):
    """If engine.send_message raises during placeholder, the helper still
    returns the full reply — the customer just doesn't see a placeholder."""
    fake_engine.send_message.side_effect = RuntimeError("engine busy")
    iterator = _stream(
        [_FakeAssistantMessage([_FakeBlock("recovered")])],
        pre_delay_s=0.08,
    )
    reply, ph = await _drain_with_placeholder(
        iterator, engine=fake_engine, conv_id="conv-1",
        target_role="customer", ws=fake_ws, eligible=True,
        delay_s=0.02,
    )
    assert reply == "recovered"
    assert ph is None  # send failed → treated as no-placeholder


@pytest.mark.asyncio
async def test_ws_push_failure_does_not_lose_placeholder_msg(fake_engine, fake_ws):
    """ws.send_json failure shouldn't mask the fact that a placeholder
    was persisted via engine.send_message — caller still needs to edit it."""
    fake_ws.send_json.side_effect = RuntimeError("ws closed")
    iterator = _stream(
        [_FakeAssistantMessage([_FakeBlock("delivered")])],
        pre_delay_s=0.08,
    )
    reply, ph = await _drain_with_placeholder(
        iterator, engine=fake_engine, conv_id="conv-1",
        target_role="customer", ws=fake_ws, eligible=True,
        delay_s=0.02,
    )
    assert ph is not None  # engine persisted; only push failed
    assert reply == "delivered"


@pytest.mark.asyncio
async def test_iterator_exception_cancels_pending_placeholder(fake_engine, fake_ws):
    """If the model stream raises before any token, the placeholder timer
    must be torn down without leaving a dangling task."""
    async def _broken():
        await asyncio.sleep(0.005)
        raise RuntimeError("model exploded")
        yield  # pragma: no cover

    with pytest.raises(RuntimeError, match="model exploded"):
        await _drain_with_placeholder(
            _broken(), engine=fake_engine, conv_id="conv-1",
            target_role="customer", ws=fake_ws, eligible=True,
            delay_s=0.10,  # placeholder would fire at 100ms — exception at 5ms wins
        )
    # No placeholder should have been sent — timer hadn't elapsed yet.
    fake_engine.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# Reply accumulation — drains the same way as the existing inline loop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multiple_assistant_blocks_concatenate(fake_engine, fake_ws):
    iterator = _stream(
        [
            _FakeAssistantMessage([_FakeBlock("Hello "), _FakeBlock("world")]),
            _FakeAssistantMessage([_FakeBlock("!")]),
        ],
    )
    reply, _ = await _drain_with_placeholder(
        iterator, engine=fake_engine, conv_id="conv-1",
        target_role="customer", ws=fake_ws, eligible=True, delay_s=1.0,
    )
    assert reply == "Hello world!"


@pytest.mark.asyncio
async def test_result_message_replaces_accumulated_text(fake_engine, fake_ws):
    """Match existing _generate_agent_reply behavior: ResultMessage.result
    overwrites the accumulated stream (it's the canonical final form)."""
    iterator = _stream(
        [
            _FakeAssistantMessage([_FakeBlock("partial")]),
            _FakeResultMessage(result="canonical final"),
        ],
    )
    reply, _ = await _drain_with_placeholder(
        iterator, engine=fake_engine, conv_id="conv-1",
        target_role="customer", ws=fake_ws, eligible=True, delay_s=1.0,
    )
    assert reply == "canonical final"


# ---------------------------------------------------------------------------
# Progressive streaming — intermediate `message_edited` pushes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_progressive_edits_pushed_during_stream(
    fake_engine, fake_ws, monkeypatch,
):
    """After the placeholder lands, subsequent SDK chunks should emit
    intermediate `message_edited` frames so the UI fills in progressively
    instead of waiting for the final `engine.edit_message` flush.

    The frames must reference the placeholder's `message_id` (in-place
    update, not a new bubble) and carry the accumulated `new_content`.
    """
    import autoservice.gateway.message_router as mr
    # Lower thresholds so the test exercises the push path without
    # having to emit hundreds of characters or sleep 200ms between
    # iterations.
    monkeypatch.setattr(mr, "STREAM_EDIT_MIN_DELTA_CHARS", 3)
    monkeypatch.setattr(mr, "STREAM_EDIT_MIN_INTERVAL_S", 0.0)

    async def _gen():
        # Placeholder timer = 0.02s; first yield after 0.05s → placeholder
        # is guaranteed to land before any token, so all three chunks
        # below flow through the progressive-push branch.
        await asyncio.sleep(0.05)
        yield _FakeAssistantMessage([_FakeBlock("ABC")])
        yield _FakeAssistantMessage([_FakeBlock("DEF")])
        yield _FakeAssistantMessage([_FakeBlock("GHI")])

    reply, ph = await _drain_with_placeholder(
        _gen(), engine=fake_engine, conv_id="conv-1",
        target_role="customer", ws=fake_ws, eligible=True, delay_s=0.02,
    )
    assert reply == "ABCDEFGHI"
    assert ph is not None

    edit_frames = [
        call.args[0] for call in fake_ws.send_json.call_args_list
        if call.args[0].get("type") == "message_edited"
    ]
    # Three chunks × 3 chars ≥ 3-char threshold → one push per chunk.
    assert len(edit_frames) == 3
    # All progress frames edit the same placeholder id.
    for frame in edit_frames:
        assert frame["payload"]["message_id"] == ph.id
        assert frame["payload"]["edited_by"] == "agent:customer"
    # Content accumulates across pushes.
    assert edit_frames[0]["payload"]["new_content"] == "ABC"
    assert edit_frames[1]["payload"]["new_content"] == "ABCDEF"
    assert edit_frames[2]["payload"]["new_content"] == "ABCDEFGHI"


@pytest.mark.asyncio
async def test_no_streaming_edits_without_placeholder(
    fake_engine, fake_ws, monkeypatch,
):
    """Fast-path (first token within delay_s) skips the placeholder —
    without a message_id there is nothing to edit, so no intermediate
    frames should fire even if the stream keeps producing."""
    import autoservice.gateway.message_router as mr
    monkeypatch.setattr(mr, "STREAM_EDIT_MIN_DELTA_CHARS", 1)
    monkeypatch.setattr(mr, "STREAM_EDIT_MIN_INTERVAL_S", 0.0)

    async def _gen():
        yield _FakeAssistantMessage([_FakeBlock("fast")])
        yield _FakeAssistantMessage([_FakeBlock(" chunk")])

    reply, ph = await _drain_with_placeholder(
        _gen(), engine=fake_engine, conv_id="conv-1",
        target_role="customer", ws=fake_ws, eligible=True, delay_s=1.0,
    )
    assert reply == "fast chunk"
    assert ph is None
    fake_ws.send_json.assert_not_called()


@pytest.mark.asyncio
async def test_throttle_suppresses_sub_threshold_deltas(
    fake_engine, fake_ws, monkeypatch,
):
    """Tiny deltas below `STREAM_EDIT_MIN_DELTA_CHARS` must not trigger
    a push — otherwise every SDK token would crash across the WS."""
    import autoservice.gateway.message_router as mr
    # Keep the default 40-char threshold; zero the interval so the test
    # is exercising the char-threshold gate in isolation.
    monkeypatch.setattr(mr, "STREAM_EDIT_MIN_INTERVAL_S", 0.0)

    async def _gen():
        await asyncio.sleep(0.05)
        # Five 5-char chunks = 25 chars total, all below the 40-char
        # gate. None should produce an intermediate frame.
        for _ in range(5):
            yield _FakeAssistantMessage([_FakeBlock("abcde")])

    reply, ph = await _drain_with_placeholder(
        _gen(), engine=fake_engine, conv_id="conv-1",
        target_role="customer", ws=fake_ws, eligible=True, delay_s=0.02,
    )
    assert reply == "abcde" * 5
    assert ph is not None

    edit_frames = [
        call.args[0] for call in fake_ws.send_json.call_args_list
        if call.args[0].get("type") == "message_edited"
    ]
    assert edit_frames == []  # only the placeholder `message` frame fired
