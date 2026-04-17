"""E2E tests for T6C.2 — Metrics Plugin → BillingMetrics Wiring.

Covers: takeover recording, negative mode-change filtering, CSAT event flow,
graceful operation without BillingMetrics, API real data.
All 5 test cases from plan-T6C.2.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

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
def metrics_with_billing(billing):
    return MetricsPlugin(billing_metrics=billing), billing


@pytest.fixture
def metrics_standalone():
    """MetricsPlugin without BillingMetrics (optional dependency)."""
    return MetricsPlugin(billing_metrics=None)


@pytest.fixture
def conv():
    return Conversation(
        id="conv-metrics-1",
        state=ConversationState.ACTIVE,
        mode=ConversationMode.AUTO,
        participants=(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# TC-019: Mode change to TAKEOVER triggers record_takeover()
# ---------------------------------------------------------------------------

async def test_tc019_takeover_triggers_billing(metrics_with_billing, conv):
    """on_mode_changed(TAKEOVER) calls BillingMetrics.record_takeover()."""
    metrics, billing = metrics_with_billing

    await metrics.on_mode_changed(
        conv, ConversationMode.AUTO, ConversationMode.TAKEOVER, "operator"
    )

    assert metrics.mode_changes.get("AUTO→TAKEOVER", 0) >= 1 or \
        metrics.mode_changes.get("auto→takeover", 0) >= 1, \
        "mode_changes counter should increment"

    snapshot = billing.get_current_snapshot()
    assert snapshot.takeover_count >= 1, \
        "BillingMetrics should record at least 1 takeover"


# ---------------------------------------------------------------------------
# TC-020: Non-TAKEOVER mode change does NOT trigger record_takeover
# ---------------------------------------------------------------------------

async def test_tc020_non_takeover_no_billing(metrics_with_billing, conv):
    """on_mode_changed to non-TAKEOVER mode does not call record_takeover."""
    metrics, billing = metrics_with_billing

    await metrics.on_mode_changed(
        conv, ConversationMode.TAKEOVER, ConversationMode.AUTO, "auto"
    )

    # Counter should track the change
    key_found = any("AUTO" in k or "auto" in k for k in metrics.mode_changes)
    assert key_found, "mode change should be tracked in counters"

    # But billing takeover should NOT increment
    snapshot = billing.get_current_snapshot()
    assert snapshot.takeover_count == 0, \
        "non-TAKEOVER mode change should not record takeover"


# ---------------------------------------------------------------------------
# TC-021: CSAT event triggers record_csat()
# ---------------------------------------------------------------------------

async def test_tc021_csat_event_triggers_billing(metrics_with_billing):
    """on_event(CSAT_RECORDED) flows through to BillingMetrics.record_csat()."""
    metrics, billing = metrics_with_billing

    event = Event(
        id="evt-csat-5",
        type=EventType.CONVERSATION_CSAT_RECORDED
        if hasattr(EventType, "CONVERSATION_CSAT_RECORDED")
        else "conversation.csat_recorded",
        conversation_id="conv-csat-bill",
        data={"score": 5},
        timestamp=datetime.now(timezone.utc),
    )
    await metrics.on_event(event)

    assert 5 in metrics.csat_scores, "score should be in csat_scores list"
    snapshot = billing.get_current_snapshot()
    assert snapshot.csat_total_responses >= 1, \
        "BillingMetrics should have 1 CSAT response"


# ---------------------------------------------------------------------------
# TC-022: MetricsPlugin works without BillingMetrics
# ---------------------------------------------------------------------------

async def test_tc022_graceful_without_billing(metrics_standalone, conv):
    """MetricsPlugin operates normally when billing_metrics=None."""
    metrics = metrics_standalone

    # Should not raise
    await metrics.on_mode_changed(
        conv, ConversationMode.AUTO, ConversationMode.TAKEOVER, "operator"
    )

    event = Event(
        id="evt-no-bill",
        type=EventType.CONVERSATION_CSAT_RECORDED
        if hasattr(EventType, "CONVERSATION_CSAT_RECORDED")
        else "conversation.csat_recorded",
        conversation_id="conv-no-bill",
        data={"score": 3},
        timestamp=datetime.now(timezone.utc),
    )
    await metrics.on_event(event)

    # Internal counters still work
    assert 3 in metrics.csat_scores
    total_mode = sum(metrics.mode_changes.values())
    assert total_mode >= 1, "mode_changes counter should still work"


# ---------------------------------------------------------------------------
# TC-023: /api/billing/summary returns real data
# ---------------------------------------------------------------------------

async def test_tc023_billing_api_real_data(metrics_with_billing):
    """After recording events, BillingMetrics returns real (non-seed) data."""
    metrics, billing = metrics_with_billing

    conv1 = Conversation(
        id="conv-real-1",
        state=ConversationState.ACTIVE,
        mode=ConversationMode.AUTO,
        participants=(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    conv2 = Conversation(
        id="conv-real-2",
        state=ConversationState.ACTIVE,
        mode=ConversationMode.AUTO,
        participants=(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    # Record 2 takeovers + 1 CSAT
    await metrics.on_mode_changed(
        conv1, ConversationMode.AUTO, ConversationMode.TAKEOVER, "op"
    )
    await metrics.on_mode_changed(
        conv2, ConversationMode.AUTO, ConversationMode.TAKEOVER, "op"
    )

    event = Event(
        id="evt-real-csat",
        type=EventType.CONVERSATION_CSAT_RECORDED
        if hasattr(EventType, "CONVERSATION_CSAT_RECORDED")
        else "conversation.csat_recorded",
        conversation_id="conv-real-1",
        data={"score": 4},
        timestamp=datetime.now(timezone.utc),
    )
    await metrics.on_event(event)

    snapshot = billing.get_current_snapshot()
    assert snapshot.takeover_count == 2, \
        f"expected 2 takeovers, got {snapshot.takeover_count}"
    assert snapshot.csat_total_responses == 1, \
        f"expected 1 CSAT response, got {snapshot.csat_total_responses}"
