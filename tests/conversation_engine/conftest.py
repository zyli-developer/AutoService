"""Shared fixtures for tests/conversation_engine."""

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
    return Participant(
        id="u-customer-1",
        role=ParticipantRole.CUSTOMER,
        joined_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def participant_operator() -> Participant:
    return Participant(
        id="u-operator-1",
        role=ParticipantRole.OPERATOR,
        joined_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def participant_agent() -> Participant:
    return Participant(
        id="u-agent-1",
        role=ParticipantRole.AGENT,
        joined_at=datetime.now(timezone.utc),
    )
