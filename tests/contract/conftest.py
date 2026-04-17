"""Shared fixtures for ConversationEngine contract tests.

Design:
- Tests are engine-implementation agnostic.
- An implementation registers via env var `AUTOSERVICE_CONTRACT_ENGINE_FACTORY`
  or by calling `register_engine_factory(...)` from a downstream conftest.
- Without a registered factory, tests skip — the suite is shipped before
  any implementation (M0 contract-freeze phase).
"""

from __future__ import annotations

import importlib
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import pytest

from autoservice.conversation_engine import (
    ConversationEngine,
    Participant,
    ParticipantRole,
)

EngineFactory = Callable[[], Awaitable[ConversationEngine]]

_FACTORY: EngineFactory | None = None


def register_engine_factory(factory: EngineFactory) -> None:
    """Downstream test packages call this to plug in a concrete engine."""
    global _FACTORY
    _FACTORY = factory


def _load_factory_from_env() -> EngineFactory | None:
    path = os.environ.get("AUTOSERVICE_CONTRACT_ENGINE_FACTORY")
    if not path:
        return None
    module_path, _, attr = path.partition(":")
    if not module_path or not attr:
        raise RuntimeError(
            f"AUTOSERVICE_CONTRACT_ENGINE_FACTORY must be 'module:callable', got {path!r}"
        )
    module = importlib.import_module(module_path)
    return getattr(module, attr)


@pytest.fixture
async def engine() -> ConversationEngine:
    factory = _FACTORY or _load_factory_from_env()
    if factory is None:
        pytest.skip(
            "contract: no engine factory registered — "
            "set AUTOSERVICE_CONTRACT_ENGINE_FACTORY or call "
            "tests.contract.conftest.register_engine_factory(...)"
        )
    return await factory()


@pytest.fixture
def make_participant() -> Callable[..., Participant]:
    def _make(
        *,
        id: str,
        role: ParticipantRole,
        metadata: dict[str, Any] | None = None,
    ) -> Participant:
        return Participant(
            id=id,
            role=role,
            joined_at=datetime.now(timezone.utc),
            metadata=metadata or {},
        )

    return _make


@pytest.fixture
async def conversation(engine: ConversationEngine):
    """Fresh conversation bound to web channel, unique external_id."""
    import uuid

    conv = await engine.create_conversation(
        channel="web",
        external_id=f"sess_{uuid.uuid4().hex[:12]}",
    )
    return conv
