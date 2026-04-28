"""Unit tests for TurnQueue per-conv serialization."""
from __future__ import annotations

import asyncio

import pytest

from autoservice.gateway.turn_queue import QueueFullError, TurnQueue


@pytest.mark.asyncio
async def test_single_submit_runs_immediately():
    q = TurnQueue()
    seen: list[str] = []

    async def runner():
        seen.append("ran")

    await q.submit("c1", runner)
    # Wait for the loop task to finish.
    await asyncio.sleep(0.05)
    assert seen == ["ran"]
    assert q.queue_depth("c1") == 0
    assert not q.has_in_flight("c1")


@pytest.mark.asyncio
async def test_two_submits_run_serially():
    q = TurnQueue()
    seen: list[str] = []

    started_first = asyncio.Event()
    finish_first = asyncio.Event()

    async def first():
        seen.append("first-start")
        started_first.set()
        await finish_first.wait()
        seen.append("first-end")

    async def second():
        seen.append("second")

    await q.submit("c1", first)
    await started_first.wait()
    # second submitted while first is in flight → must queue, not run.
    await q.submit("c1", second)
    assert seen == ["first-start"]
    assert q.queue_depth("c1") == 1

    finish_first.set()
    await asyncio.sleep(0.05)
    assert seen == ["first-start", "first-end", "second"]
    assert q.queue_depth("c1") == 0
    assert not q.has_in_flight("c1")


@pytest.mark.asyncio
async def test_strict_fifo_across_five():
    q = TurnQueue()
    seen: list[int] = []
    block = asyncio.Event()

    def make_runner(i: int):
        async def runner():
            if i == 0:
                await block.wait()
            seen.append(i)
        return runner

    # submit #0 first; it blocks. The rest queue up FIFO.
    await q.submit("c1", make_runner(0))
    await asyncio.sleep(0)
    for i in range(1, 5):
        await q.submit("c1", make_runner(i))
    assert q.queue_depth("c1") == 4

    block.set()
    await asyncio.sleep(0.1)
    assert seen == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_queue_full_raises():
    q = TurnQueue(max_queue_depth=2)
    block = asyncio.Event()

    async def first():
        await block.wait()

    async def noop():
        pass

    await q.submit("c1", first)
    await asyncio.sleep(0)
    await q.submit("c1", noop)  # queue depth 1
    await q.submit("c1", noop)  # queue depth 2 (at cap)
    with pytest.raises(QueueFullError):
        await q.submit("c1", noop)  # 3rd queued submit → reject
    block.set()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_runner_exception_does_not_break_queue():
    q = TurnQueue()
    seen: list[str] = []

    async def boom():
        raise RuntimeError("kaboom")

    async def good():
        seen.append("good")

    await q.submit("c1", boom)
    await q.submit("c1", good)
    await asyncio.sleep(0.05)
    assert seen == ["good"]
    assert q.queue_depth("c1") == 0
    assert not q.has_in_flight("c1")


@pytest.mark.asyncio
async def test_state_cleaned_up_after_drain():
    q = TurnQueue()

    async def noop():
        pass

    await q.submit("c1", noop)
    await asyncio.sleep(0.05)
    # _state should have removed c1
    assert "c1" not in q._state


@pytest.mark.asyncio
async def test_independent_conversations_run_concurrently():
    q = TurnQueue()
    a_done = asyncio.Event()
    b_done = asyncio.Event()
    block = asyncio.Event()

    async def a_run():
        await block.wait()
        a_done.set()

    async def b_run():
        b_done.set()

    await q.submit("a", a_run)
    await q.submit("b", b_run)
    # b must finish even while a blocks — separate conv, separate loop.
    await asyncio.wait_for(b_done.wait(), timeout=0.2)
    assert not a_done.is_set()
    block.set()
    await asyncio.wait_for(a_done.wait(), timeout=0.2)
