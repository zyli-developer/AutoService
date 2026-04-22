"""Regression lock: CCPool main pool factory must create customer-role
instances. If someone ever reverts the factory to role=None, this test
catches it.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from autoservice.cc_pool import CCPool, PoolConfig


@pytest.mark.asyncio
async def test_main_pool_factory_passes_role_customer():
    cfg = PoolConfig(cwd=".", min_size=0, max_size=0, warmup_count=0)

    with patch("autoservice.cc_pool.create_cc_client") as mk:
        mk.return_value = AsyncMock()
        pool = CCPool(cfg)
        # Call the factory directly (AsyncPool stores it as a zero-arg
        # callable returning awaitable)
        factory_fn = pool._factory  # noqa: SLF001
        await factory_fn()

    assert mk.called
    call_kwargs = mk.call_args.kwargs
    assert call_kwargs.get("role") == "customer"
    assert call_kwargs.get("tenant_id") is None  # warmup, no tenant yet
    assert call_kwargs.get("enable_kb_tool") is False
