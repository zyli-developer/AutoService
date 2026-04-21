"""Test that CCPool.session_query forwards tenant_id to acquire_sticky."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from autoservice.cc_pool import CCPool, PoolConfig


@pytest.mark.asyncio
async def test_session_query_forwards_tenant_id():
    cfg = PoolConfig(cwd=".", min_size=1, max_size=1, warmup_count=1)
    with patch("autoservice.cc_pool.create_cc_client", new=AsyncMock()):
        pool = CCPool(cfg)
        await pool.start()
        try:
            # Build a fake pooled instance whose client's receive_response
            # yields nothing (immediate completion).
            fake_inst = MagicMock()
            fake_inst.query_count = 0
            fake_inst.client = MagicMock()
            fake_inst.client.query = AsyncMock()

            async def _empty_response():
                if False:
                    yield  # make this a generator, but yield nothing
                return

            fake_inst.client.receive_response = _empty_response

            with patch.object(
                pool, "acquire_sticky",
                new=AsyncMock(return_value=fake_inst),
            ) as acq:
                async for _ in pool.session_query(
                    "conv-1", "hello", tenant_id="mystore",
                ):
                    pass

            acq.assert_awaited_once()
            assert acq.await_args.kwargs.get("tenant_id") == "mystore"
        finally:
            await pool.shutdown()


@pytest.mark.asyncio
async def test_session_query_backward_compat_no_tenant_id():
    """Calling session_query without tenant_id should still work (default None)."""
    cfg = PoolConfig(cwd=".", min_size=1, max_size=1, warmup_count=1)
    with patch("autoservice.cc_pool.create_cc_client", new=AsyncMock()):
        pool = CCPool(cfg)
        await pool.start()
        try:
            fake_inst = MagicMock()
            fake_inst.query_count = 0
            fake_inst.client = MagicMock()
            fake_inst.client.query = AsyncMock()

            async def _empty_response():
                if False:
                    yield
                return

            fake_inst.client.receive_response = _empty_response

            with patch.object(
                pool, "acquire_sticky",
                new=AsyncMock(return_value=fake_inst),
            ) as acq:
                async for _ in pool.session_query("conv-1", "hello"):
                    pass

            acq.assert_awaited_once()
            # Default should propagate as None
            assert acq.await_args.kwargs.get("tenant_id") is None
        finally:
            await pool.shutdown()
