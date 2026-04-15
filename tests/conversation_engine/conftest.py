"""Shared fixtures for tests/conversation_engine (T0.4)."""

from datetime import datetime, timezone

import pytest

from autoservice.conversation_engine import (
    LocalEngine,
    Participant,
    ParticipantRole,
)


@pytest.fixture
def engine() -> LocalEngine:
    """Fresh LocalEngine instance per test."""
    return LocalEngine()


@pytest.fixture
def participant_customer() -> Participant:
    """A customer-role participant with a UTC-aware join timestamp."""
    return Participant(
        id="u-customer-1",
        role=ParticipantRole.CUSTOMER,
        joined_at=datetime.now(timezone.utc),
    )
