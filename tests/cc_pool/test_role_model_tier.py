"""Role → model tier binding (Plan B for fast/slow/dream model split).

The router-level fast/slow tier signal (model_router.ModelTier) used to be
discarded by `_create_role_pool` — every sub-pool ran whatever single model
was set in `cc_pool.model`. These tests pin the new behavior:

  customer / lead         → slow_model   (sonnet — quality-first paths)
  triage   / translate    → fast_model   (haiku  — sub-second paths)
  dream                    → dream_model  (own knob; falls back to slow_model
                                           then base model)

Tests stub `create_cc_client` so no real Claude subprocess is spawned —
each call captures the resolved `config.model` for assertion.
"""
from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoservice.cc_pool import (
    CCPool,
    PoolConfig,
    _resolve_model_for_role,
    _dream_pool_config,
    load_pool_config,
    shutdown_pool,
)


# ---------------------------------------------------------------------------
# Fake CC client + create_cc_client capture
# ---------------------------------------------------------------------------

def _fake_client():
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.is_healthy = MagicMock(return_value=True)
    client.query = AsyncMock()

    async def _empty():
        return
        yield  # pragma: no cover
    client.receive_response = _empty
    return client


@pytest.fixture()
def captured_calls(monkeypatch):
    """Patch create_cc_client; record (config, kwargs) for each call."""
    calls: list[tuple[PoolConfig, dict]] = []

    async def _factory(config, **kwargs):
        calls.append((config, kwargs))
        return _fake_client()

    monkeypatch.setattr("autoservice.cc_pool.create_cc_client", _factory)
    return calls


# ---------------------------------------------------------------------------
# _resolve_model_for_role — pure helper, no I/O
# ---------------------------------------------------------------------------

class TestResolveModelForRole:
    def test_fast_roles_pick_fast_model(self):
        cfg = PoolConfig(model="base-x", fast_model="haiku-x", slow_model="sonnet-x")
        assert _resolve_model_for_role(cfg, "triage") == "haiku-x"
        assert _resolve_model_for_role(cfg, "translate") == "haiku-x"

    def test_slow_roles_pick_slow_model(self):
        """Plan C (2026-04-22): customer moved to fast tier for the pool
        warmup (see _ROLE_TIER); escalation to slow_model happens per-turn
        via ``CCPool.session_query(..., tier='slow')`` + ``set_model``,
        not at pool construction. lead remains slow."""
        cfg = PoolConfig(model="base-x", fast_model="haiku-x", slow_model="sonnet-x")
        assert _resolve_model_for_role(cfg, "lead") == "sonnet-x"


class TestCustomerTierIsFast:
    """Plan C pinned behavior — customer pool default warms on fast_model."""

    def test_customer_resolves_to_fast_model(self):
        cfg = PoolConfig(model="base-x", fast_model="haiku-x", slow_model="sonnet-x")
        assert _resolve_model_for_role(cfg, "customer") == "haiku-x"

    def test_dream_picks_dream_model_when_set(self):
        cfg = PoolConfig(
            model="base-x", slow_model="sonnet-x", dream_model="opus-x",
        )
        assert _resolve_model_for_role(cfg, "dream") == "opus-x"

    def test_dream_falls_back_to_slow_when_dream_unset(self):
        cfg = PoolConfig(model="base-x", slow_model="sonnet-x")
        assert _resolve_model_for_role(cfg, "dream") == "sonnet-x"

    def test_dream_falls_back_to_base_when_slow_and_dream_unset(self):
        cfg = PoolConfig(model="base-x")
        assert _resolve_model_for_role(cfg, "dream") == "base-x"

    def test_fast_falls_back_to_base_when_fast_unset(self):
        cfg = PoolConfig(model="base-x")
        assert _resolve_model_for_role(cfg, "triage") == "base-x"

    def test_slow_falls_back_to_base_when_slow_unset(self):
        cfg = PoolConfig(model="base-x")
        assert _resolve_model_for_role(cfg, "customer") == "base-x"

    def test_unknown_role_falls_back_to_base(self):
        cfg = PoolConfig(model="base-x", fast_model="haiku-x")
        assert _resolve_model_for_role(cfg, "unknown") == "base-x"

    def test_all_unset_returns_none(self):
        cfg = PoolConfig()
        assert _resolve_model_for_role(cfg, "customer") is None
        assert _resolve_model_for_role(cfg, "triage") is None
        assert _resolve_model_for_role(cfg, "dream") is None


# ---------------------------------------------------------------------------
# PoolConfig — new fields
# ---------------------------------------------------------------------------

class TestPoolConfigTierFields:
    def test_defaults(self):
        cfg = PoolConfig()
        assert cfg.fast_model is None
        assert cfg.slow_model is None
        assert cfg.dream_model is None

    def test_yaml_loading(self, tmp_path):
        autoservice_dir = tmp_path / ".autoservice"
        autoservice_dir.mkdir()
        (autoservice_dir / "config.local.yaml").write_text(
            "cc_pool:\n"
            "  model: base-x\n"
            "  fast_model: claude-haiku-4-5\n"
            "  slow_model: claude-sonnet-4-6\n"
            "  dream_model: claude-opus-4-7\n",
            encoding="utf-8",
        )
        cfg = load_pool_config(cwd=str(tmp_path))
        assert cfg.fast_model == "claude-haiku-4-5"
        assert cfg.slow_model == "claude-sonnet-4-6"
        assert cfg.dream_model == "claude-opus-4-7"

    def test_env_var_override(self, monkeypatch):
        monkeypatch.setenv("CC_POOL_FAST_MODEL", "haiku-from-env")
        monkeypatch.setenv("CC_POOL_SLOW_MODEL", "sonnet-from-env")
        monkeypatch.setenv("CC_POOL_DREAM_MODEL", "opus-from-env")
        cfg = load_pool_config(cwd="/nonexistent")
        assert cfg.fast_model == "haiku-from-env"
        assert cfg.slow_model == "sonnet-from-env"
        assert cfg.dream_model == "opus-from-env"


# ---------------------------------------------------------------------------
# Sub-pool factories — model selection by role
# ---------------------------------------------------------------------------

@pytest.fixture()
async def tiered_pool(captured_calls):
    """A CCPool whose base config has all three tier knobs set."""
    cfg = PoolConfig(
        min_size=0, max_size=2, warmup_count=0,
        model="base-x",
        fast_model="haiku-x",
        slow_model="sonnet-x",
        dream_model="opus-x",
    )
    p = CCPool(cfg)
    await p.start()
    yield p, captured_calls
    await p.shutdown()


@pytest.mark.asyncio
async def test_role_pool_triage_gets_fast_model(tiered_pool):
    pool, calls = tiered_pool
    calls.clear()
    async with pool.acquire(role="triage", tenant_id="acme"):
        pass
    assert calls, "create_cc_client was never invoked"
    cfg, _ = calls[-1]
    assert cfg.model == "haiku-x", (
        f"triage sub-pool should use fast_model=haiku-x, got {cfg.model!r}"
    )


@pytest.mark.asyncio
async def test_role_pool_translate_gets_fast_model(tiered_pool):
    pool, calls = tiered_pool
    calls.clear()
    async with pool.acquire(role="translate", tenant_id="acme"):
        pass
    cfg, _ = calls[-1]
    assert cfg.model == "haiku-x"


@pytest.mark.asyncio
async def test_role_pool_lead_gets_slow_model(tiered_pool):
    pool, calls = tiered_pool
    calls.clear()
    async with pool.acquire(role="lead", tenant_id="acme"):
        pass
    cfg, _ = calls[-1]
    assert cfg.model == "sonnet-x"


# ---------------------------------------------------------------------------
# Main customer pool — uses slow_model
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_main_customer_pool_uses_fast_model(captured_calls):
    """Plan C: the customer pool warms on fast_model (haiku) — sticky
    sessions escalate to slow_model per-turn via
    ``CCPool.session_query(tier='slow')`` + ``ClaudeSDKClient.set_model``.
    This keeps idle sticky instances cheap and pushes sonnet spend to
    actual slow turns only."""
    cfg = PoolConfig(
        min_size=0, max_size=1, warmup_count=1,
        model="base-x",
        fast_model="haiku-x",
        slow_model="sonnet-x",
    )
    pool = CCPool(cfg)
    await pool.start()
    try:
        assert captured_calls, "warmup did not invoke create_cc_client"
        used_models = {c[0].model for c in captured_calls}
        assert "haiku-x" in used_models, (
            f"customer pool should warm with fast_model=haiku-x; saw {used_models}"
        )
        assert "sonnet-x" not in used_models, (
            "customer pool must not pick slow_model at warmup "
            "(slow is applied per-turn via set_model)"
        )
    finally:
        await pool.shutdown()


@pytest.mark.asyncio
async def test_main_customer_pool_falls_back_to_base_model(captured_calls):
    """When slow_model is unset, the customer pool keeps using `model`."""
    cfg = PoolConfig(
        min_size=0, max_size=1, warmup_count=1,
        model="base-only",
    )
    pool = CCPool(cfg)
    await pool.start()
    try:
        used_models = {c[0].model for c in captured_calls}
        assert used_models == {"base-only"}, (
            f"with no slow_model set, customer pool should keep model=base-only, "
            f"saw {used_models}"
        )
    finally:
        await pool.shutdown()


# ---------------------------------------------------------------------------
# Dream pool config — own helper since dream pool is module-level
# ---------------------------------------------------------------------------

class TestDreamPoolConfig:
    def test_dream_pool_config_uses_dream_model(self):
        base = PoolConfig(
            model="base-x", slow_model="sonnet-x", dream_model="opus-x",
        )
        dream_cfg = _dream_pool_config(base)
        assert dream_cfg.model == "opus-x"
        # Dream pool sizing invariants from spec §2.5 stay intact.
        assert dream_cfg.min_size == 1
        assert dream_cfg.max_size == 1
        assert dream_cfg.warmup_count == 1

    def test_dream_pool_config_falls_back_to_slow_model(self):
        base = PoolConfig(model="base-x", slow_model="sonnet-x")
        dream_cfg = _dream_pool_config(base)
        assert dream_cfg.model == "sonnet-x"

    def test_dream_pool_config_falls_back_to_base_model(self):
        base = PoolConfig(model="base-only")
        dream_cfg = _dream_pool_config(base)
        assert dream_cfg.model == "base-only"
