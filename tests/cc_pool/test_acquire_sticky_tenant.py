"""Tests for CCPool.acquire_sticky(chat_id, tenant_id=...)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from autoservice.cc_pool import CCPool, PoolConfig, StickyTenantMismatch


async def _recycle_stub(pool, inst, **kw):
    """Mirror the production helper's stamping contract.

    ``_recycle_instance_for_tenant`` stamps ``_pool_tenant_id`` on the
    returned instance after rebuild. Success-path tests must mirror that
    contract so the override's post-condition (binding visible to the
    next acquire) holds in the mock world too.
    """
    inst._pool_tenant_id = kw["tenant_id"]
    return inst


@pytest.mark.asyncio
async def test_first_bind_triggers_recycle_to_target_tenant():
    cfg = PoolConfig(cwd=".", min_size=1, max_size=1, warmup_count=1)
    with patch("autoservice.cc_pool.create_cc_client", new=AsyncMock()):
        pool = CCPool(cfg)
        await pool.start()
        try:
            with patch(
                "autoservice.cc_pool._recycle_instance_for_tenant",
                new=AsyncMock(side_effect=_recycle_stub),
            ) as recycle:
                inst = await pool.acquire_sticky("conv-1", tenant_id="mystore")
            recycle.assert_awaited_once()
            call = recycle.await_args
            assert call.kwargs["role"] == "customer"
            assert call.kwargs["tenant_id"] == "mystore"
            assert inst._pool_tenant_id == "mystore"
        finally:
            await pool.shutdown()


@pytest.mark.asyncio
async def test_second_bind_same_tenant_reuses_without_recycle():
    cfg = PoolConfig(cwd=".", min_size=1, max_size=1, warmup_count=1)
    with patch("autoservice.cc_pool.create_cc_client", new=AsyncMock()):
        pool = CCPool(cfg)
        await pool.start()
        try:
            with patch(
                "autoservice.cc_pool._recycle_instance_for_tenant",
                new=AsyncMock(side_effect=_recycle_stub),
            ) as recycle:
                first = await pool.acquire_sticky("conv-1", tenant_id="mystore")
                second = await pool.acquire_sticky("conv-1", tenant_id="mystore")
            # Recycle only on first bind
            assert recycle.await_count == 1
            assert first is second
        finally:
            await pool.shutdown()


@pytest.mark.asyncio
async def test_cross_tenant_rebind_raises():
    cfg = PoolConfig(cwd=".", min_size=1, max_size=1, warmup_count=1)
    with patch("autoservice.cc_pool.create_cc_client", new=AsyncMock()):
        pool = CCPool(cfg)
        await pool.start()
        try:
            with patch(
                "autoservice.cc_pool._recycle_instance_for_tenant",
                new=AsyncMock(side_effect=_recycle_stub),
            ):
                await pool.acquire_sticky("conv-1", tenant_id="mystore")
                with pytest.raises(StickyTenantMismatch):
                    await pool.acquire_sticky("conv-1", tenant_id="other")
        finally:
            await pool.shutdown()


@pytest.mark.asyncio
async def test_recycle_failure_falls_back_to_uncycled_instance():
    """If rebuild fails, we still bind the warm instance (degraded but alive).

    The instance is stamped with the target tenant_id so subsequent acquires
    for the same conv succeed as zero-cost matches, not StickyTenantMismatch.
    """
    cfg = PoolConfig(cwd=".", min_size=1, max_size=1, warmup_count=1)
    with patch("autoservice.cc_pool.create_cc_client", new=AsyncMock()):
        pool = CCPool(cfg)
        await pool.start()
        try:
            with patch(
                "autoservice.cc_pool._recycle_instance_for_tenant",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ):
                first = await pool.acquire_sticky("conv-1", tenant_id="mystore")
                # Post-condition: instance stamped to target tenant (even though
                # soul wasn't actually injected) so subsequent acquires don't
                # mistakenly raise StickyTenantMismatch.
                assert getattr(first, "_pool_tenant_id", "<unset>") == "mystore"
                # Second acquire with same tenant_id: should match (no new
                # recycle attempt, no exception).
                second = await pool.acquire_sticky("conv-1", tenant_id="mystore")
                assert second is first
        finally:
            await pool.shutdown()


@pytest.mark.asyncio
async def test_no_tenant_skips_recycle():
    """tenant_id=None → no recycle call, parent semantics preserved."""
    cfg = PoolConfig(cwd=".", min_size=1, max_size=1, warmup_count=1)
    with patch("autoservice.cc_pool.create_cc_client", new=AsyncMock()):
        pool = CCPool(cfg)
        await pool.start()
        try:
            with patch(
                "autoservice.cc_pool._recycle_instance_for_tenant",
                new=AsyncMock(side_effect=_recycle_stub),
            ) as recycle:
                await pool.acquire_sticky("conv-1", tenant_id=None)
            recycle.assert_not_awaited()
        finally:
            await pool.shutdown()
