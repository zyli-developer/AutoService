"""T4B.2 — Unit tests for ``DreamScheduler`` loop + tenant discovery.

Mocks ``run_dream`` throughout — the real coroutine is expensive and
requires a live cc_pool. We override it via the constructor's
``run_dream_fn`` injection seam.

Tests set ``poll_interval_sec`` to a very small value so the loop fires
multiple times inside a short ``await asyncio.sleep(...)``. If these
timing assumptions get flaky on slower CI, bump both the interval and
the sleep by the same ratio.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from autoservice.dream_scheduler import DreamScheduler


# ── Helpers ────────────────────────────────────────────────────────────────


def _write_tenant(
    root: Path, tenant_id: str, *, status: str = "active",
    dream: dict | None = None,
) -> None:
    """Create ``<root>/<tid>/config.json`` with the supplied fields."""
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
    """Return ``(sandbox_root, plugins_root)`` under tmp_path."""
    sandbox = tmp_path / ".autoservice" / "sandbox"
    plugins = tmp_path / "plugins"
    sandbox.mkdir(parents=True, exist_ok=True)
    plugins.mkdir(parents=True, exist_ok=True)
    return sandbox, plugins


@pytest.fixture()
def noop_trigger():
    """A should_trigger stub that always returns (False, 'not_idle').

    Used as a safe default when a test is specifically about loop mechanics
    (start/stop) and not about firing.
    """
    def _fn(*args, **kwargs):  # noqa: ARG001
        return (False, "not_idle")
    return _fn


# ── Discovery ──────────────────────────────────────────────────────────────


def test_discover_active_tenants_includes_master_and_sandbox(fake_roots):
    """_master plus 2 active sandbox tenants, excluding an archived one."""
    sandbox, plugins = fake_roots
    _write_tenant(sandbox, "_master")
    _write_tenant(sandbox, "acme")
    _write_tenant(sandbox, "other_co")
    _write_tenant(sandbox, "archived_tenant", status="archived")

    sched = DreamScheduler(
        poll_interval_sec=0.01,
        sandbox_root=sandbox, plugins_root=plugins,
    )
    tenants = sched._discover_active_tenants()

    assert "_master" in tenants
    assert "acme" in tenants
    assert "other_co" in tenants
    assert "archived_tenant" not in tenants


def test_discover_active_tenants_includes_local_admin_from_plugins(fake_roots):
    """_local_admin under plugins/ is discovered (fork mode)."""
    sandbox, plugins = fake_roots
    _write_tenant(plugins, "_local_admin")
    _write_tenant(plugins, "b_tenant")
    # _example is a template, not a real tenant.
    _write_tenant(plugins, "_example")

    sched = DreamScheduler(sandbox_root=sandbox, plugins_root=plugins)
    tenants = sched._discover_active_tenants()

    assert "_local_admin" in tenants
    assert "b_tenant" in tenants
    assert "_example" not in tenants


def test_discover_active_tenants_ignores_missing_config(fake_roots):
    """A dir without config.json is silently ignored."""
    sandbox, plugins = fake_roots
    (sandbox / "half_provisioned").mkdir()

    sched = DreamScheduler(sandbox_root=sandbox, plugins_root=plugins)
    assert sched._discover_active_tenants() == []


# ── Lifecycle ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_loop_iterates_and_cancels_cleanly(fake_roots, noop_trigger):
    """start → sleep(short) → stop. Loop ran ≥2 times with no leak."""
    sandbox, plugins = fake_roots
    _write_tenant(sandbox, "acme")

    tick_count = 0

    def _counting_trigger(*args, **kwargs):  # noqa: ARG001
        nonlocal tick_count
        tick_count += 1
        return (False, "not_idle")

    sched = DreamScheduler(
        poll_interval_sec=0.03,
        sandbox_root=sandbox, plugins_root=plugins,
        should_trigger_fn=_counting_trigger,
    )
    await sched.start()
    await asyncio.sleep(0.15)
    await sched.stop()

    # Loop should have ticked at least twice.
    assert tick_count >= 2
    # And the task is gone.
    assert sched._task is None


@pytest.mark.asyncio
async def test_double_start_is_noop(fake_roots, noop_trigger):
    """Calling ``start`` twice does NOT spawn a second task."""
    sandbox, plugins = fake_roots
    sched = DreamScheduler(
        poll_interval_sec=0.05,
        sandbox_root=sandbox, plugins_root=plugins,
        should_trigger_fn=noop_trigger,
    )
    await sched.start()
    first_task = sched._task
    await sched.start()
    assert sched._task is first_task
    await sched.stop()


@pytest.mark.asyncio
async def test_stop_without_start_is_safe(fake_roots):
    """stop() without a preceding start() must not raise."""
    sandbox, plugins = fake_roots
    sched = DreamScheduler(sandbox_root=sandbox, plugins_root=plugins)
    await sched.stop()  # must not raise


# ── Firing run_dream ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_loop_spawns_run_dream_for_triggerable_tenants(fake_roots):
    """When should_trigger returns True, run_dream is called with the tid."""
    sandbox, plugins = fake_roots
    _write_tenant(sandbox, "acme", dream={"trigger": "idle"})
    _write_tenant(sandbox, "other", dream={"trigger": "manual"})

    run_dream_calls: list[str] = []

    async def _fake_run_dream(tenant_id, *args, **kwargs):  # noqa: ARG001
        run_dream_calls.append(tenant_id)

    def _trigger_only_acme(tid, *args, **kwargs):  # noqa: ARG001
        return (tid == "acme", "idle" if tid == "acme" else "manual_only")

    # Override _spawn_run to call the fake directly, sidestepping cc_pool
    # resource acquisition for this test.
    sched = DreamScheduler(
        poll_interval_sec=0.03,
        sandbox_root=sandbox, plugins_root=plugins,
        run_dream_fn=_fake_run_dream,
        should_trigger_fn=_trigger_only_acme,
    )

    async def _spawn_override(tenant_id):
        run_dream_calls.append(tenant_id)

    sched._spawn_run = _spawn_override  # type: ignore[assignment]

    await sched.start()
    await asyncio.sleep(0.12)
    await sched.stop()

    assert "acme" in run_dream_calls
    assert "other" not in run_dream_calls


@pytest.mark.asyncio
async def test_loop_skips_non_triggerable_tenants(fake_roots):
    """should_trigger=(False, _) → run_dream NOT called."""
    sandbox, plugins = fake_roots
    _write_tenant(sandbox, "acme")

    calls: list[str] = []

    async def _fake_run_dream(tenant_id, *args, **kwargs):  # noqa: ARG001
        calls.append(tenant_id)

    sched = DreamScheduler(
        poll_interval_sec=0.03,
        sandbox_root=sandbox, plugins_root=plugins,
        run_dream_fn=_fake_run_dream,
        should_trigger_fn=lambda *a, **k: (False, "not_idle"),
    )

    async def _spawn_override(tenant_id):
        calls.append(tenant_id)

    sched._spawn_run = _spawn_override  # type: ignore[assignment]

    await sched.start()
    await asyncio.sleep(0.12)
    await sched.stop()

    assert calls == []


# ── Error isolation ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_individual_tenant_error_does_not_kill_loop(fake_roots):
    """An exception during one tenant evaluation must NOT stop the loop."""
    sandbox, plugins = fake_roots
    _write_tenant(sandbox, "bad_tenant")
    _write_tenant(sandbox, "good_tenant")

    evaluated: list[str] = []

    def _trigger(tid, *args, **kwargs):  # noqa: ARG001
        evaluated.append(tid)
        if tid == "bad_tenant":
            raise RuntimeError("boom")
        return (False, "not_idle")

    sched = DreamScheduler(
        poll_interval_sec=0.03,
        sandbox_root=sandbox, plugins_root=plugins,
        should_trigger_fn=_trigger,
    )
    await sched.start()
    await asyncio.sleep(0.12)
    await sched.stop()

    # Both tenants must have been evaluated at least once — the bad one
    # raised but the good one still got its turn.
    assert "bad_tenant" in evaluated
    assert "good_tenant" in evaluated


@pytest.mark.asyncio
async def test_stop_cancels_loop_task_no_warning(fake_roots, noop_trigger):
    """stop() awaits cancellation — no 'coroutine was never awaited' warnings."""
    sandbox, plugins = fake_roots
    _write_tenant(sandbox, "acme")

    sched = DreamScheduler(
        poll_interval_sec=0.03,
        sandbox_root=sandbox, plugins_root=plugins,
        should_trigger_fn=noop_trigger,
    )
    await sched.start()
    # give it one tick to actually suspend on the stopped.wait
    await asyncio.sleep(0.05)
    await sched.stop()

    # After stop the _task reference should be None.
    assert sched._task is None
