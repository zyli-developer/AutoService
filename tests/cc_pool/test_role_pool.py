"""Role pool acquisition + reaper — §2.3 of the spec.

These tests stub out the CC client factory so no real Claude process is
spawned; they exercise only the pool selection / lifecycle logic.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from autoservice.cc_pool import CCPool, PoolConfig, _KNOWN_ROLES


def _fake_client_factory():
    """Return a CCClient-shaped MagicMock with async connect/disconnect."""
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.is_healthy = MagicMock(return_value=True)
    client.query = AsyncMock()

    async def _empty_response():
        return
        yield  # pragma: no cover
    client.receive_response = _empty_response
    return client


@pytest.fixture(autouse=True)
def _patch_create(monkeypatch):
    async def _factory(*args, **kwargs):
        return _fake_client_factory()
    monkeypatch.setattr("autoservice.cc_pool.create_cc_client", _factory)


@pytest.fixture()
async def pool():
    p = CCPool(PoolConfig(min_size=0, max_size=2, warmup_count=0))
    await p.start()
    yield p
    await p.shutdown()


def test_known_roles_includes_new_roles():
    assert {"customer", "dream", "lead", "translate", "triage"} <= _KNOWN_ROLES


@pytest.mark.asyncio
async def test_lead_role_acquire_succeeds(pool):
    async with pool.acquire(role="lead", tenant_id="acme") as inst:
        assert inst is not None
        assert getattr(inst, "_pool_role", None) == "lead"


@pytest.mark.asyncio
async def test_triage_role_single_instance(pool):
    """Triage role has size=1 regardless of tenant config."""
    async with pool.acquire(role="triage", tenant_id="acme") as inst1:
        assert inst1 is not None
    async with pool.acquire(role="triage", tenant_id="acme") as inst2:
        assert inst2 is not None


@pytest.mark.asyncio
async def test_per_tenant_isolation(pool):
    async with pool.acquire(role="lead", tenant_id="acme") as a:
        assert getattr(a, "_pool_role", None) == "lead"
    async with pool.acquire(role="lead", tenant_id="beta") as b:
        assert getattr(b, "_pool_role", None) == "lead"
    assert ("lead", "acme") in pool._role_pools
    assert ("lead", "beta") in pool._role_pools


@pytest.mark.asyncio
async def test_unknown_role_raises(pool):
    with pytest.raises(NotImplementedError):
        async with pool.acquire(role="no-such-role") as _:
            pass


@pytest.mark.asyncio
async def test_reaper_closes_idle_pools(pool, monkeypatch):
    monkeypatch.setattr("autoservice.cc_pool._REAP_IDLE_SEC", 0.05)
    async with pool.acquire(role="lead", tenant_id="acme") as _:
        pass
    assert ("lead", "acme") in pool._role_pools
    await pool._reap_idle_role_pools_once()
    await asyncio.sleep(0.1)
    await pool._reap_idle_role_pools_once()
    assert ("lead", "acme") not in pool._role_pools


@pytest.mark.asyncio
async def test_concurrent_acquire_same_key_shares_subpool(pool):
    """Concurrent first-acquires for the same (role, tenant) must share one sub-pool."""
    async def _take():
        async with pool.acquire(role="lead", tenant_id="concurrent") as inst:
            await asyncio.sleep(0.01)
            return inst
    results = await asyncio.gather(*[_take() for _ in range(4)])
    assert len(results) == 4
    # Only one sub-pool entry should exist for the (role, tenant) key.
    assert ("lead", "concurrent") in pool._role_pools
    assert sum(1 for k in pool._role_pools if k == ("lead", "concurrent")) == 1
