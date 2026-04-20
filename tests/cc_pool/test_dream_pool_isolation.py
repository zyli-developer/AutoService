"""T3B.5 — dream pool isolation & role-aware acquire.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §2.5
Red-line: CON-06 — Dream agent runs via cc_pool role=dream in a size-1
pool, independent from customer pool.

These tests pin the invariants a subtle regression in ``cc_pool`` could
break:

1. ``acquire(role='dream')`` and ``acquire(role='customer')`` route to
   two distinct pool instances — a dream checkout never consumes a
   customer slot.
2. The dream pool is hard-capped at size=1: a second concurrent dream
   acquire must queue behind the first rather than grow the pool.
3. Dream-role clients receive the tenant's ``dream_soul.md`` (or
   ``_FALLBACK_DREAM_SOUL`` on miss) as their SDK system prompt.
4. Release routes back to the correct pool — no cross-contamination.
5. Unknown roles raise :class:`NotImplementedError` with a pointer to
   the extension path.
6. :func:`shutdown_pool` tears both pools down cleanly.

All tests fake the Claude SDK subprocess via a patched
``ClaudeSDKClient`` — zero network, zero subprocesses.

All tests are ``async def`` so pytest-asyncio (``asyncio_mode=auto`` in
pyproject.toml) owns the event loop lifecycle. Using ``asyncio.run()``
here would taint the default event loop policy and cause deprecation-
flavoured regressions in legacy tests (e.g. test_proposal_pipeline.py)
that still call ``asyncio.get_event_loop()``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from autoservice import cc_pool as cc_pool_mod
from autoservice.cc_pool import CCPool, PoolConfig
from autoservice.soul_generator import _FALLBACK_DREAM_SOUL


# ---------------------------------------------------------------------------
# Fake SDK client — captures the options the pool constructs it with and
# otherwise is a drop-in for :class:`ClaudeSDKClient` (connect/disconnect
# succeed, stays "healthy").
# ---------------------------------------------------------------------------


class _FakeSDKClient:
    """Minimal ClaudeSDKClient stand-in. Exposes the captured options."""

    # Class-level history of every instance created — handy for tests
    # that want to count constructions or inspect the order of injected
    # system prompts.
    history: list["_FakeSDKClient"] = []

    def __init__(self, options):
        self.options = options
        self.connected = False
        self.disconnected = False
        # ``CCClient.is_healthy`` reads ``self._transport._process.returncode``
        # — we fake the same attribute tree so a pool health check
        # considers the instance healthy.
        class _FakeProc:
            returncode = None

        class _FakeTransport:
            _process = _FakeProc()

        self._transport = _FakeTransport()
        _FakeSDKClient.history.append(self)

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.disconnected = True

    async def query(self, *args, **kwargs):  # pragma: no cover — unused here
        return None


@pytest.fixture(autouse=True)
def _patch_sdk(tmp_path, monkeypatch):
    """Swap in the fake SDK for every test in this module.

    Also chdir into *tmp_path* so the pool's cwd-relative lookups
    (``.autoservice/sandbox/*``, ``plugins/*``) only see the per-test
    filesystem.
    """
    _FakeSDKClient.history.clear()
    monkeypatch.chdir(tmp_path)
    # Reset the module-level singletons so each test starts fresh. The
    # shutdown helper is idempotent — calling it before any start is a
    # no-op.
    cc_pool_mod._pool = None
    cc_pool_mod._dream_pool = None
    with patch.object(cc_pool_mod, "ClaudeSDKClient", _FakeSDKClient):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_customer_pool() -> CCPool:
    """Construct a small customer pool suitable for tests."""
    cfg = PoolConfig(min_size=1, max_size=2, warmup_count=1)
    return CCPool(cfg)


def _write_dream_soul(
    root: Path, tenant_id: str, content: str, *, sandbox: bool = True,
) -> Path:
    """Write ``souls/dream_soul.md`` for *tenant_id* under *root*.

    ``sandbox=True`` places it under ``.autoservice/sandbox/<tid>/`` (the
    master-side layout). ``sandbox=False`` uses ``plugins/<tid>/`` (fork-
    side). Both paths are probed by the pool's dream-soul resolver — the
    tests below exercise the sandbox branch because that's the layout
    :func:`master_tenant.ensure_master_tenant` produces.
    """
    base = root / ".autoservice" / "sandbox" if sandbox else root / "plugins"
    souls_dir = base / tenant_id / "souls"
    souls_dir.mkdir(parents=True, exist_ok=True)
    path = souls_dir / "dream_soul.md"
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_dream_pool_independent_from_customer():
    """Dream acquires must not consume customer pool slots."""
    pool = _build_customer_pool()
    await pool.start()
    try:
        # Snapshot customer pool state before the dream acquire.
        customer_total_before = pool.size
        customer_avail_before = pool.available_count

        async with pool.acquire(role="dream", tenant_id=None) as dream_inst:
            # The dream instance must live on a *different* pool from
            # the customer one. We expose the dream pool via the
            # module-level singleton; it must exist and be distinct.
            assert cc_pool_mod._dream_pool is not None
            assert cc_pool_mod._dream_pool is not pool

            # The dream instance is tracked by the dream pool, not
            # the customer pool.
            assert dream_inst.id in cc_pool_mod._dream_pool._all_instances
            assert dream_inst.id not in pool._all_instances

            # Customer pool is untouched: same size, same availability.
            assert pool.size == customer_total_before
            assert pool.available_count == customer_avail_before

            # And the instance carries the dream role tag.
            assert getattr(dream_inst, "_pool_role", None) == "dream"
    finally:
        await pool.shutdown()
        await cc_pool_mod.shutdown_pool()


async def test_dream_pool_size_one():
    """A second concurrent dream acquire must queue, not grow the pool."""
    # No customer pool — the dream pool is independent, lazily
    # constructed on first acquire. That exercises the lazy-init
    # path too.
    async with cc_pool_mod._acquire_dream(
        tenant_id=None, timeout=5.0,
    ):
        assert cc_pool_mod._dream_pool is not None
        # Size == 1 (the one we just checked out; nothing else warm).
        assert cc_pool_mod._dream_pool.size == 1

        # Attempting a second concurrent acquire must block (the
        # pool's available queue is empty AND size == max_size == 1).
        # We give it a tight timeout and expect a TimeoutError rather
        # than a successful checkout — that IS the size-1 invariant.
        second_cm = cc_pool_mod._acquire_dream(
            tenant_id=None, timeout=0.2,
        )
        with pytest.raises(TimeoutError):
            async with second_cm:
                pytest.fail(
                    "dream pool grew beyond size=1 — CON-06 violated",
                )

        # Sanity: still exactly one instance tracked.
        assert cc_pool_mod._dream_pool.size == 1
        assert cc_pool_mod._dream_pool._config.max_size == 1

    # After release the available count recovers to 1.
    assert cc_pool_mod._dream_pool.available_count == 1
    await cc_pool_mod.shutdown_pool()


async def test_dream_client_has_dream_soul_system_prompt(tmp_path):
    """Dream-role acquire injects the tenant's dream_soul.md as system prompt."""
    tid = "_master"
    marker_soul = (
        "# Custom Dream Soul for _master\n\n"
        "## Anti-Patterns\n"
        "- NEVER auto-apply a proposal (red-line CON-04)\n"
    )
    _write_dream_soul(tmp_path, tid, marker_soul)

    async with cc_pool_mod._acquire_dream(
        tenant_id=tid, timeout=5.0,
    ) as inst:
        # The acquire path recycles the warmup instance and builds a
        # fresh one carrying the tenant's soul. The newest fake SDK
        # client in history is the one handed to the caller.
        injected = inst.client._sdk.options.system_prompt  # noqa: SLF001
        assert injected == marker_soul
        # And the red-line marker is present — tests will need to
        # see this even if future edits reflow the fallback content.
        assert "NEVER auto-apply" in injected

    await cc_pool_mod.shutdown_pool()


async def test_dream_fallback_soul_when_file_missing(tmp_path):
    """Tenant with no ``dream_soul.md`` falls back to the inlined constant."""
    tid = "ghost_tenant"
    # Deliberately do NOT call _write_dream_soul — the tenant root
    # simply does not exist. :func:`_resolve_dream_tenant_root` returns
    # None and :func:`_load_dream_soul` hands back the fallback.

    async with cc_pool_mod._acquire_dream(
        tenant_id=tid, timeout=5.0,
    ) as inst:
        injected = inst.client._sdk.options.system_prompt  # noqa: SLF001
        assert injected == _FALLBACK_DREAM_SOUL
        # The fallback has the CON-04 anti-pattern marker too —
        # confirm the semantic red-line survives the fallback.
        assert "No self-modification" in injected

    await cc_pool_mod.shutdown_pool()


async def test_release_routes_to_correct_pool():
    """Customer + dream acquires release back to their respective pools."""
    pool = _build_customer_pool()
    await pool.start()
    try:
        customer_avail_before = pool.available_count

        async with pool.acquire(role="customer") as cust_inst:
            # Customer instance sits in the customer pool.
            assert cust_inst.id in pool._all_instances
            assert cc_pool_mod._dream_pool is None or (
                cust_inst.id
                not in cc_pool_mod._dream_pool._all_instances
            )

            async with pool.acquire(
                role="dream", tenant_id=None,
            ) as dream_inst:
                assert (
                    dream_inst.id
                    in cc_pool_mod._dream_pool._all_instances
                )
                assert dream_inst.id not in pool._all_instances

        # After both context managers exit:
        # - Customer pool's available count is back to its pre-
        #   acquire level (we took 1, we returned 1).
        assert pool.available_count == customer_avail_before
        # - Dream pool's one instance is back in its own queue.
        assert cc_pool_mod._dream_pool.available_count == 1
        # - Neither pool picked up the other's instance.
        assert not set(pool._all_instances) & set(
            cc_pool_mod._dream_pool._all_instances,
        )
    finally:
        await pool.shutdown()
        await cc_pool_mod.shutdown_pool()


async def test_unknown_role_raises():
    """``role='translate'`` (or any other unknown role) must raise."""
    pool = _build_customer_pool()
    await pool.start()
    try:
        with pytest.raises(NotImplementedError) as excinfo:
            # Note: ``acquire`` for unknown roles raises synchronously
            # from the role dispatch — before returning any context
            # manager. That's the intended contract (fail fast).
            pool.acquire(role="translate")

        msg = str(excinfo.value)
        # Message is actionable: names the rejected role AND points
        # at the extension path.
        assert "translate" in msg
        assert "_KNOWN_ROLES" in msg or "Known roles" in msg
    finally:
        await pool.shutdown()
        await cc_pool_mod.shutdown_pool()


async def test_shutdown_closes_both_pools():
    """``shutdown_pool()`` tears down customer + dream + clears globals."""
    # Force both pools to exist by doing one acquire of each.
    await cc_pool_mod.get_pool(
        PoolConfig(min_size=1, max_size=1, warmup_count=1),
    )
    async with cc_pool_mod._acquire_dream(
        tenant_id=None, timeout=5.0,
    ):
        pass

    assert cc_pool_mod._pool is not None
    assert cc_pool_mod._dream_pool is not None
    customer_instances = list(cc_pool_mod._pool._all_instances.values())
    dream_instances = list(
        cc_pool_mod._dream_pool._all_instances.values(),
    )

    await cc_pool_mod.shutdown_pool()

    # Globals cleared.
    assert cc_pool_mod._pool is None
    assert cc_pool_mod._dream_pool is None
    # Every instance in both pools had ``disconnect`` called on its
    # fake SDK client.
    for inst in customer_instances + dream_instances:
        assert inst.client._sdk.disconnected is True, (  # noqa: SLF001
            f"instance {inst.id} was not disconnected on shutdown"
        )


async def test_customer_acquire_backcompat_unchanged():
    """The M1 no-kwarg ``pool.acquire()`` path must still work byte-for-byte.

    This is the single most important back-compat assertion: every M1
    caller (``CCPool.query``, ``session_query``, channels, operator
    console) uses ``async with pool.acquire() as inst``. That call must
    return a PooledInstance from the customer pool, never touch the
    dream pool, and not pass through the role-dispatch branch.
    """
    pool = _build_customer_pool()
    await pool.start()
    try:
        # No kwargs → customer path, no dream pool construction.
        assert cc_pool_mod._dream_pool is None
        async with pool.acquire() as inst:
            assert inst.id in pool._all_instances
            # The dream pool must NOT have been lazily constructed
            # by a customer-only acquire.
            assert cc_pool_mod._dream_pool is None
            # Back-compat: no role tag on a customer instance.
            assert not hasattr(inst, "_pool_role") or getattr(
                inst, "_pool_role", None,
            ) != "dream"
    finally:
        await pool.shutdown()
        await cc_pool_mod.shutdown_pool()


async def test_dream_tenant_switch_recycles_instance(tmp_path):
    """Second acquire with a different tenant_id rebuilds the warm instance.

    Spec §2.5 mandates the dream instance carries the *tenant's* soul —
    so acquiring for tenant A and then tenant B must not reuse A's
    instance (which would serve A's soul to B's run).
    """
    soul_a = "# Dream soul for tenantA\nMarker-A\n"
    soul_b = "# Dream soul for tenantB\nMarker-B\n"
    _write_dream_soul(tmp_path, "tenantA", soul_a)
    _write_dream_soul(tmp_path, "tenantB", soul_b)

    async with cc_pool_mod._acquire_dream(
        tenant_id="tenantA", timeout=5.0,
    ) as inst_a:
        prompt_a = inst_a.client._sdk.options.system_prompt  # noqa: SLF001
        assert prompt_a == soul_a

    async with cc_pool_mod._acquire_dream(
        tenant_id="tenantB", timeout=5.0,
    ) as inst_b:
        prompt_b = inst_b.client._sdk.options.system_prompt  # noqa: SLF001
        assert prompt_b == soul_b
        assert prompt_a != prompt_b

    await cc_pool_mod.shutdown_pool()
