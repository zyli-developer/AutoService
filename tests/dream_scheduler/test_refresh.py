"""T4B.3 — Tests for scheduler refresh + /dream-config confirm integration.

Covers:

* ``DreamScheduler.refresh(tid)`` invalidates the cached config for that
  tenant only, so the next ``_read_tenant_dream_cfg`` picks up on-disk
  changes.
* Module-level :func:`dream_scheduler.refresh` is a safe no-op when no
  scheduler is registered (unit-test / CLI contexts).
* The ``/dream-config`` confirm endpoint calls the scheduler's refresh
  via :func:`autoservice.dream_config_dialog.on_config_confirmed`.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autoservice import dream_scheduler
from autoservice.dream_scheduler import DreamScheduler, refresh as module_refresh


# ── Fixtures ───────────────────────────────────────────────────────────────


def _write_tenant(
    root: Path, tenant_id: str, *, status: str = "active",
    dream: dict | None = None,
) -> None:
    tdir = root / tenant_id
    tdir.mkdir(parents=True, exist_ok=True)
    cfg = {"tenant_id": tenant_id, "status": status}
    if dream is not None:
        cfg["dream"] = dream
    (tdir / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8",
    )


@pytest.fixture()
def fake_roots(tmp_path: Path) -> tuple[Path, Path]:
    sandbox = tmp_path / ".autoservice" / "sandbox"
    plugins = tmp_path / "plugins"
    sandbox.mkdir(parents=True, exist_ok=True)
    plugins.mkdir(parents=True, exist_ok=True)
    return sandbox, plugins


@pytest.fixture(autouse=True)
def clear_scheduler_singleton():
    """Keep each test hermetic — clear the module-level scheduler singleton."""
    before = dream_scheduler.get_scheduler()
    dream_scheduler.set_scheduler(None)
    yield
    dream_scheduler.set_scheduler(before)


# ── refresh reloads config ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_invalidates_cached_config(fake_roots):
    """After refresh(), the next config read picks up disk changes."""
    sandbox, plugins = fake_roots
    _write_tenant(sandbox, "acme", dream={"trigger": "idle"})

    sched = DreamScheduler(sandbox_root=sandbox, plugins_root=plugins)

    # Prime the cache.
    cfg_before = sched._read_tenant_dream_cfg("acme")
    assert cfg_before == {"trigger": "idle"}

    # Mutate config on disk.
    _write_tenant(sandbox, "acme", dream={"trigger": "manual"})

    # Without refresh, the cache still has the old value.
    assert sched._read_tenant_dream_cfg("acme") == {"trigger": "idle"}

    await sched.refresh("acme")

    # After refresh, disk read returns the new value.
    assert sched._read_tenant_dream_cfg("acme") == {"trigger": "manual"}


@pytest.mark.asyncio
async def test_refresh_only_affects_target_tenant(fake_roots):
    """refresh('acme') must NOT evict 'other_co' from the cache."""
    sandbox, plugins = fake_roots
    _write_tenant(sandbox, "acme", dream={"trigger": "idle"})
    _write_tenant(sandbox, "other_co", dream={"trigger": "idle"})

    sched = DreamScheduler(sandbox_root=sandbox, plugins_root=plugins)

    # Prime both caches.
    sched._read_tenant_dream_cfg("acme")
    sched._read_tenant_dream_cfg("other_co")
    assert "acme" in sched._config_cache
    assert "other_co" in sched._config_cache

    await sched.refresh("acme")

    assert "acme" not in sched._config_cache
    assert "other_co" in sched._config_cache


# ── refresh safe without scheduler running ─────────────────────────────────


@pytest.mark.asyncio
async def test_module_refresh_noop_when_no_scheduler():
    """module_refresh without an active scheduler is a safe no-op."""
    assert dream_scheduler.get_scheduler() is None
    await module_refresh("acme")  # Must not raise.


@pytest.mark.asyncio
async def test_module_refresh_routes_to_registered_scheduler(fake_roots):
    """module_refresh calls scheduler.refresh when one is registered."""
    sandbox, plugins = fake_roots
    sched = DreamScheduler(sandbox_root=sandbox, plugins_root=plugins)
    dream_scheduler.set_scheduler(sched)

    with patch.object(sched, "refresh", new=AsyncMock()) as mock_refresh:
        await module_refresh("acme")

    mock_refresh.assert_awaited_once_with("acme")


@pytest.mark.asyncio
async def test_module_refresh_swallows_scheduler_errors(fake_roots):
    """An exception inside scheduler.refresh must not propagate."""
    sandbox, plugins = fake_roots
    sched = DreamScheduler(sandbox_root=sandbox, plugins_root=plugins)
    dream_scheduler.set_scheduler(sched)

    async def _boom(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("scheduler is sick")

    with patch.object(sched, "refresh", new=_boom):
        # Must not raise — we explicitly swallow.
        await module_refresh("acme")


# ── /dream-config confirm integration ──────────────────────────────────────


def _walk_dialog_to_confirm(client: TestClient, tenant_id: str) -> None:
    """Step a DreamConfigSession from IDLE to the CONFIRM step using defaults."""
    client.post("/api/management/chat", params={
        "message": "/dream-config", "tenant_id": tenant_id,
    })
    for answer in ("1", "1", "0.3", "1"):
        client.post("/api/management/chat", params={
            "message": answer, "tenant_id": tenant_id,
        })


def test_dream_config_confirm_calls_refresh(tmp_path, monkeypatch):
    """POST confirm → on_config_confirmed → scheduler.refresh(tid)."""
    # Redirect the sandbox write target so _persist_dream_config finds a dir.
    monkeypatch.chdir(tmp_path)
    sandbox = tmp_path / ".autoservice" / "sandbox"
    (sandbox / "acme").mkdir(parents=True, exist_ok=True)
    (sandbox / "acme" / "config.json").write_text(
        json.dumps({"tenant_id": "acme", "status": "sandbox"}),
        encoding="utf-8",
    )

    # Reset the module-level DreamConfigSession so tests don't leak.
    from autoservice import api_routes
    api_routes._dream_config_session = None

    # Register a mock scheduler that tracks refresh calls.
    mock_sched = MagicMock()
    mock_sched.refresh = AsyncMock()
    dream_scheduler.set_scheduler(mock_sched)

    from autoservice.api_routes import api_router
    app = FastAPI()
    app.include_router(api_router)

    try:
        with TestClient(app) as client:
            _walk_dialog_to_confirm(client, "acme")
            # Final confirmation — triggers _persist_dream_config +
            # on_config_confirmed.
            r = client.post(
                "/api/management/chat",
                params={"message": "yes", "tenant_id": "acme"},
            )
            assert r.status_code == 200
            assert "已保存" in r.json()["content"]
    finally:
        api_routes._dream_config_session = None

    mock_sched.refresh.assert_called_with("acme")


def test_dream_config_cancel_does_not_call_refresh(tmp_path, monkeypatch):
    """User says 'no' → dialog resets → refresh NOT called."""
    monkeypatch.chdir(tmp_path)
    sandbox = tmp_path / ".autoservice" / "sandbox"
    (sandbox / "acme").mkdir(parents=True, exist_ok=True)
    (sandbox / "acme" / "config.json").write_text(
        json.dumps({"tenant_id": "acme", "status": "sandbox"}),
        encoding="utf-8",
    )

    from autoservice import api_routes
    api_routes._dream_config_session = None

    mock_sched = MagicMock()
    mock_sched.refresh = AsyncMock()
    dream_scheduler.set_scheduler(mock_sched)

    from autoservice.api_routes import api_router
    app = FastAPI()
    app.include_router(api_router)

    try:
        with TestClient(app) as client:
            _walk_dialog_to_confirm(client, "acme")
            r = client.post(
                "/api/management/chat",
                params={"message": "no", "tenant_id": "acme"},
            )
            assert r.status_code == 200
            assert "取消" in r.json()["content"]
    finally:
        api_routes._dream_config_session = None

    mock_sched.refresh.assert_not_called()
