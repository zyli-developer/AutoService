"""Unit tests for OfflineWatcher — operator disconnect → AUTO after grace period."""
import asyncio
import pytest
from datetime import datetime, timezone

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import (
    ConversationMode, Participant, ParticipantRole,
)
from autoservice.gateway.offline_watcher import OfflineWatcher


@pytest.mark.asyncio
async def test_disconnect_then_grace_expires_switches_conv_to_auto():
    eng = LocalEngine()
    conv = await eng.create_conversation(channel="web", external_id="x")
    now = datetime.now(timezone.utc)
    await eng.join(conv.id, Participant(id="cust1", role=ParticipantRole.CUSTOMER, joined_at=now))
    await eng.join(conv.id, Participant(id="op42", role=ParticipantRole.OPERATOR, joined_at=now))
    await eng.handle_command(conv.id, actor_id="op42", command="/hijack")

    watcher = OfflineWatcher(eng, grace_ms=50)
    watcher.on_connect("op42")
    watcher.on_disconnect("op42")
    await asyncio.sleep(0.1)

    final = await eng.get_conversation(conv.id)
    assert final.mode == ConversationMode.AUTO


@pytest.mark.asyncio
async def test_reconnect_within_grace_cancels():
    eng = LocalEngine()
    conv = await eng.create_conversation(channel="web", external_id="x")
    now = datetime.now(timezone.utc)
    await eng.join(conv.id, Participant(id="cust1", role=ParticipantRole.CUSTOMER, joined_at=now))
    await eng.join(conv.id, Participant(id="op42", role=ParticipantRole.OPERATOR, joined_at=now))
    await eng.handle_command(conv.id, actor_id="op42", command="/hijack")

    watcher = OfflineWatcher(eng, grace_ms=100)
    watcher.on_connect("op42")
    watcher.on_disconnect("op42")
    await asyncio.sleep(0.03)
    watcher.on_connect("op42")  # reconnect
    await asyncio.sleep(0.1)

    final = await eng.get_conversation(conv.id)
    assert final.mode == ConversationMode.TAKEOVER


@pytest.mark.asyncio
async def test_disconnect_with_no_takeover_conversations_is_noop():
    eng = LocalEngine()
    watcher = OfflineWatcher(eng, grace_ms=30)
    watcher.on_connect("op42")
    watcher.on_disconnect("op42")
    await asyncio.sleep(0.05)
    # No exception, no state — pass.


@pytest.mark.asyncio
async def test_second_disconnect_cancels_first_task():
    """A second on_disconnect must cancel the first pending grace task."""
    eng = LocalEngine()
    conv = await eng.create_conversation(channel="web", external_id="x2")
    now = datetime.now(timezone.utc)
    await eng.join(conv.id, Participant(id="cust1", role=ParticipantRole.CUSTOMER, joined_at=now))
    await eng.join(conv.id, Participant(id="op42", role=ParticipantRole.OPERATOR, joined_at=now))
    await eng.handle_command(conv.id, actor_id="op42", command="/hijack")

    # Use a long grace so neither task fires during the test
    watcher = OfflineWatcher(eng, grace_ms=5000)
    watcher.on_connect("op42")
    watcher.on_disconnect("op42")
    first_task = watcher._pending["op42"]

    # Second disconnect before first task completes
    watcher.on_disconnect("op42")
    second_task = watcher._pending["op42"]

    # Give the event loop a tick to process cancellation
    await asyncio.sleep(0)

    assert first_task is not second_task, "second call should create a new task"
    assert first_task.cancelled(), "first task should have been cancelled"
    assert not second_task.done(), "second task should still be running"

    # Clean up — cancel second task to avoid dangling coroutine
    second_task.cancel()
    try:
        await second_task
    except asyncio.CancelledError:
        pass
