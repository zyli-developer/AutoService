"""Regression lock for the warmup_tenant_id fast-path (T-soothe-1).

Background: the customer pool's warmup factory used to produce neutral
instances that were always destroyed and rebuilt on first tenant-scoped
use (~3 s wasted per new conv). The triage sub-pool was lazy with
warmup_count=0, so the first triage call always cold-spawned inside the
2 s _TRIAGE_AGENT_TIMEOUT and timed out every time. Both were fixed by
wiring ``PoolConfig.warmup_tenant_id`` through the factory + pre-opening
the triage sub-pool at ``CCPool.start()``.

These tests pin the new behavior with mocked factories — no real Claude
subprocess is spawned.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from autoservice.cc_pool import CCPool, PoolConfig


def _fake_client():
    """A CCClient-shaped mock that satisfies pool lifecycle."""
    c = MagicMock()
    c.connect = AsyncMock()
    c.disconnect = AsyncMock()
    c.is_healthy = MagicMock(return_value=True)
    c.query = AsyncMock()

    async def _empty():
        return
        yield  # pragma: no cover

    c.receive_response = _empty
    return c


@pytest.fixture(autouse=True)
def _patch_create(monkeypatch):
    async def _factory(*args, **kwargs):
        return _fake_client()
    monkeypatch.setattr("autoservice.cc_pool.create_cc_client", _factory)


@pytest.mark.asyncio
async def test_warmup_instance_stamped_with_tenant_id():
    """Instance created through _create_instance MUST carry
    ``_pool_tenant_id == warmup_tenant_id`` so
    ``_recycle_instance_for_tenant`` sees a match (no destroy+rebuild)
    on first sticky bind for that tenant."""
    cfg = PoolConfig(
        cwd=".", min_size=0, max_size=2, warmup_count=1,
        warmup_tenant_id="cinnox",
    )
    pool = CCPool(cfg)
    try:
        await pool.start()
        # pull the warmed instance out of the queue
        inst = await pool._available.get()  # noqa: SLF001
        assert getattr(inst, "_pool_tenant_id", None) == "cinnox"
    finally:
        await pool.shutdown()


@pytest.mark.asyncio
async def test_warmup_unset_tenant_id_leaves_instance_unstamped():
    """Back-compat: no warmup_tenant_id configured → instances behave
    exactly as before (no stamp, recycle-on-first-use)."""
    cfg = PoolConfig(
        cwd=".", min_size=0, max_size=2, warmup_count=1,
    )
    pool = CCPool(cfg)
    try:
        await pool.start()
        inst = await pool._available.get()  # noqa: SLF001
        # sentinel _UNSET is an opaque object, so we assert the attr is
        # genuinely absent rather than None
        assert not hasattr(inst, "_pool_tenant_id")
    finally:
        await pool.shutdown()


@pytest.mark.asyncio
async def test_triage_subpool_preopened_on_start_when_tenant_configured():
    """``CCPool.start()`` must eagerly open (triage, warmup_tenant_id)
    so the first triage dispatch doesn't cold-spawn inside the 2 s
    ``_TRIAGE_AGENT_TIMEOUT``. Verify the sub-pool is in
    ``_role_pools`` *before* any acquire call happens."""
    cfg = PoolConfig(
        cwd=".", min_size=0, max_size=1, warmup_count=0,
        warmup_tenant_id="cinnox",
    )
    pool = CCPool(cfg)
    try:
        await pool.start()
        assert ("triage", "cinnox") in pool._role_pools  # noqa: SLF001
    finally:
        await pool.shutdown()


@pytest.mark.asyncio
async def test_triage_subpool_not_preopened_without_warmup_tenant_id():
    """When no tenant is configured, the lazy-open behavior is
    preserved — start() does NOT pre-create sub-pools."""
    cfg = PoolConfig(
        cwd=".", min_size=0, max_size=1, warmup_count=0,
    )
    pool = CCPool(cfg)
    try:
        await pool.start()
        assert pool._role_pools == {}  # noqa: SLF001
    finally:
        await pool.shutdown()
