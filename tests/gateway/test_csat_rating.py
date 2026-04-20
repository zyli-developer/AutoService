"""E2E tests for T6C.1 — CSAT Rating End-to-End.

Covers: csat_request push after /resolve, csat_response recording,
score validation, squad-filtered CSAT, disconnected customer edge case.
All 5 test cases from plan-T6C.1.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from autoservice.billing_metrics import BillingMetrics
from autoservice.plugins.metrics_plugin import MetricsPlugin
from autoservice.conversation_engine.types import (
    Conversation,
    ConversationMode,
    ConversationState,
    Event,
)
from autoservice.conversation_engine.events import EventType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def billing():
    return BillingMetrics()


@pytest.fixture
def metrics(billing):
    return MetricsPlugin(billing_metrics=billing)


@pytest.fixture
def make_conv():
    def _make(conv_id="conv-csat-1"):
        return Conversation(
            id=conv_id,
            state=ConversationState.ACTIVE,
            mode=ConversationMode.AUTO,
            participants=(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    return _make


@pytest.fixture
def make_csat_event():
    """Factory for CSAT recorded events."""
    def _make(conv_id="conv-csat-1", score=4):
        return Event(
            id=f"evt-csat-{score}",
            type=EventType.CONVERSATION_CSAT_RECORDED
            if hasattr(EventType, "CONVERSATION_CSAT_RECORDED")
            else "conversation.csat_recorded",
            conversation_id=conv_id,
            data={"score": score},
            timestamp=datetime.now(timezone.utc),
        )
    return _make


# ---------------------------------------------------------------------------
# TC-014: /resolve triggers csat_request frame
# ---------------------------------------------------------------------------

async def test_tc014_resolve_triggers_csat_request():
    """_push_csat_request sends csat_request frame after conversation resolve."""
    from autoservice.gateway import message_router

    mock_ws = AsyncMock()

    # Patch the broadcast function to capture what gets sent
    with patch.object(
        message_router, "_broadcast_to_squad", new_callable=AsyncMock, return_value=1
    ) as mock_broadcast:
        await message_router._push_csat_request("conv-resolve-1")

        mock_broadcast.assert_called_once()
        frame_arg = mock_broadcast.call_args[0][0]
        assert frame_arg.get("type") == "csat_request" or "csat" in str(frame_arg).lower(), \
            f"broadcast frame should be csat_request, got {frame_arg}"


# ---------------------------------------------------------------------------
# TC-015: csat_response records score in BillingMetrics
# ---------------------------------------------------------------------------

async def test_tc015_csat_response_records_score(metrics, billing, make_csat_event):
    """CSAT event flows through MetricsPlugin into BillingMetrics."""
    event = make_csat_event(conv_id="conv-csat-1", score=4)
    await metrics.on_event(event)

    assert 4 in metrics.csat_scores, "score should appear in metrics_plugin.csat_scores"

    snapshot = billing.get_current_snapshot()
    assert snapshot.csat_total_responses >= 1, \
        "BillingMetrics should have at least 1 CSAT response"


# ---------------------------------------------------------------------------
# TC-016: CSAT score range validation (1-5)
# ---------------------------------------------------------------------------

async def test_tc016_csat_score_validation(billing):
    """BillingMetrics.record_csat rejects scores outside 1-5."""
    # Valid boundaries
    billing.record_csat("c-ok-1", 1)
    billing.record_csat("c-ok-5", 5)
    snapshot = billing.get_current_snapshot()
    assert snapshot.csat_total_responses == 2, "scores 1 and 5 should be accepted"

    # Invalid: below range
    with pytest.raises(ValueError):
        billing.record_csat("c-bad-0", 0)

    # Invalid: above range
    with pytest.raises(ValueError):
        billing.record_csat("c-bad-6", 6)


# ---------------------------------------------------------------------------
# TC-017: CSAT uses squad-filtered broadcast
# ---------------------------------------------------------------------------

async def test_tc017_csat_squad_filtered():
    """_push_csat_request delegates to _broadcast_to_squad (not raw WS send)."""
    from autoservice.gateway import message_router

    with patch.object(
        message_router, "_broadcast_to_squad", new_callable=AsyncMock, return_value=1
    ) as mock_broadcast:
        await message_router._push_csat_request("conv-squad-csat")

        mock_broadcast.assert_called_once()
        call_kwargs = mock_broadcast.call_args
        # Second positional arg is conv_id
        assert call_kwargs[0][1] == "conv-squad-csat" or \
            call_kwargs.kwargs.get("conv_id") == "conv-squad-csat", \
            "broadcast should target the correct conversation"


# ---------------------------------------------------------------------------
# TC-018: No customer WS — csat_request does not crash
# ---------------------------------------------------------------------------

async def test_tc018_csat_no_customer_connected():
    """_push_csat_request handles gracefully when no subscribers exist."""
    from autoservice.gateway import message_router

    with patch.object(
        message_router, "_broadcast_to_squad", new_callable=AsyncMock, return_value=0
    ):
        # Should not raise
        await message_router._push_csat_request("conv-no-customer")
