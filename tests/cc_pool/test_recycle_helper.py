"""Tests for _recycle_instance_for_tenant — the helper that injects the
correct tenant soul onto a pooled instance at acquire time.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from autoservice.cc_pool import _recycle_instance_for_tenant, _UNSET


class _FakeInstance:
    def __init__(self, inst_id="cc-001"):
        self.id = inst_id
        self.client = MagicMock()


@pytest.mark.asyncio
async def test_recycle_same_tenant_is_noop():
    pool = MagicMock()
    pool._destroy_instance = AsyncMock()
    inst = _FakeInstance()
    inst._pool_tenant_id = "acme"

    result = await _recycle_instance_for_tenant(
        pool, inst, role="customer", tenant_id="acme",
    )

    assert result is inst
    pool._destroy_instance.assert_not_called()


@pytest.mark.asyncio
async def test_recycle_tenant_mismatch_rebuilds():
    pool = MagicMock()
    pool._destroy_instance = AsyncMock()
    new_inst = _FakeInstance(inst_id="cc-002")

    inst = _FakeInstance()
    inst._pool_tenant_id = "acme"

    with patch(
        "autoservice.cc_pool._make_tenant_instance",
        new=AsyncMock(return_value=new_inst),
    ) as mk:
        result = await _recycle_instance_for_tenant(
            pool, inst, role="customer", tenant_id="mystore",
        )

    assert result is new_inst
    assert result._pool_tenant_id == "mystore"
    pool._destroy_instance.assert_awaited_once_with(inst)
    mk.assert_awaited_once()


@pytest.mark.asyncio
async def test_recycle_first_bind_unset_tag_rebuilds():
    """Warm instance fresh from factory has no _pool_tenant_id attr → rebuild."""
    pool = MagicMock()
    pool._destroy_instance = AsyncMock()
    new_inst = _FakeInstance(inst_id="cc-003")

    inst = _FakeInstance()
    # Deliberately do NOT set _pool_tenant_id

    with patch(
        "autoservice.cc_pool._make_tenant_instance",
        new=AsyncMock(return_value=new_inst),
    ):
        result = await _recycle_instance_for_tenant(
            pool, inst, role="customer", tenant_id="mystore",
        )

    assert result is new_inst
    pool._destroy_instance.assert_awaited_once()


@pytest.mark.asyncio
async def test_recycle_rebuild_failure_propagates():
    pool = MagicMock()
    pool._destroy_instance = AsyncMock()
    inst = _FakeInstance()

    with patch(
        "autoservice.cc_pool._make_tenant_instance",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            await _recycle_instance_for_tenant(
                pool, inst, role="customer", tenant_id="mystore",
            )
    pool._destroy_instance.assert_awaited_once()


@pytest.mark.asyncio
async def test_recycle_both_none_is_noop():
    """Instance stamped with _pool_tenant_id=None and target tenant_id=None:
    must be treated as match (noop), NOT as "unset" (which would rebuild).
    Validates the _UNSET sentinel does its job.
    """
    pool = MagicMock()
    pool._destroy_instance = AsyncMock()
    inst = _FakeInstance()
    inst._pool_tenant_id = None  # explicitly stamped to None

    with patch(
        "autoservice.cc_pool._make_tenant_instance",
        new=AsyncMock(),
    ) as mk:
        result = await _recycle_instance_for_tenant(
            pool, inst, role="dream", tenant_id=None,
        )

    assert result is inst
    pool._destroy_instance.assert_not_called()
    mk.assert_not_called()
