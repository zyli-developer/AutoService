"""Dream Scheduler — background loop that auto-triggers ``run_dream`` per tenant.

T4B.1 / T4B.2 / T4B.3 | 2026-04-21

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §2.6.

Three public surfaces:

* :func:`should_trigger` — pure decision function (T4B.1, **yellow**). Given a
  tenant_id, its ``dream`` config block, a memory-pool probe and a
  dream_runs DB connection, decide whether the Dream agent should run NOW.
  Returns ``(bool, reason_code)`` for structured logging.
* :class:`DreamScheduler` — asyncio loop that every ``poll_interval_sec``
  enumerates active tenants, evaluates ``should_trigger`` and spawns
  :func:`autoservice.dream_agent.run_dream` for those that fire (T4B.2).
* :meth:`DreamScheduler.refresh` — re-reads a single tenant's config on
  disk; called by ``/dream-config`` on confirm so a config change takes
  effect by the next tick rather than the next hour (T4B.3).

Red-line CON-04 (spec §2.3): ``run_dream`` itself writes ``status='draft'``.
The scheduler just decides WHEN to call it; it never mutates proposal
state. The risk vs coverage gates here are cost/signal heuristics, not
safety gates.

Design notes (T4B.1 yellow — see commit body for reviewer verdict):

* **Rule ordering matters**. Check ``manual`` mode first (hard off-switch),
  then the running-row guard (cheapest DB query that can kill the decision),
  then the cool-down window (also a DB query but slightly more work),
  then the idle/scheduled trigger test (the business decision), finally
  the soft gates (coverage, risk_threshold). This ordering fails-closed
  cheaply — a tenant mid-run or mid-cool-down never touches the memory
  pool, which is the hot path.
* **Defaults** per spec §9 risk table: ``idle_threshold_min=30`` and
  ``cool_down_min=60`` — aggressive enough to let Dream learn, conservative
  enough to avoid a cost blowout if a tenant goes silent at 3am.
* **``never_active`` short-circuit**: tenants with no recorded memory turns
  are a pure cost drain — no signal to learn from. Reviewers of T4B.1 asked
  to make this explicit in the reason_code so operators can see it in logs.
"""

from __future__ import annotations

import asyncio
import logging
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── Defaults (spec §2.6 + §9) ──────────────────────────────────────────────

#: Minutes of inactivity a tenant must exhibit before ``trigger=idle`` fires.
#: Spec §9 risk-table prescribes 30min as the balanced default — short enough
#: to let Dream learn from fresh conversations, long enough that a brief
#: lunch break mid-session does not spawn a run.
DEFAULT_IDLE_THRESHOLD_MIN = 30

#: Hard cool-down after a terminal Dream run. Matches the M2 spec §2.2 bullet
#: "1h cool-down 硬写死（防抖动）". We keep the constant overridable via the
#: tenant's dream.cool_down_min so a test harness can drive it faster.
DEFAULT_COOL_DOWN_MIN = 60

#: Window, in minutes, around a scheduled HH:MM trigger in which we fire.
#: Spec §2.2 bullet "match simple HH:MM (M2 MVP: within 10 minutes of the
#: configured time window)".
SCHEDULED_WINDOW_MIN = 10

#: Look-back window for the "recent signal" heuristic when risk_threshold is
#: ``'high'`` — if no proposals have been emitted in this many days we treat
#: the tenant as having insufficient evidence to justify high-risk dreaming.
HIGH_RISK_SIGNAL_LOOKBACK_DAYS = 30

#: Trigger strings that mean "idle" (modern spec name + dialog's legacy name).
#: The ``/dream-config`` dialog historically wrote ``low_peak``; the M2 spec
#: uses ``idle``. Accept both so upgrading tenants don't need a migration.
_IDLE_TRIGGERS = frozenset({"idle", "low_peak"})
_SCHEDULED_TRIGGERS = frozenset({"scheduled"})
_MANUAL_TRIGGERS = frozenset({"manual"})


# ── T4B.1 · should_trigger (YELLOW) ────────────────────────────────────────


def should_trigger(
    tenant_id: str,
    tenant_dream_cfg: dict,
    memory_pool,
    dream_runs_db: sqlite3.Connection,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Decide whether to spawn ``run_dream`` for *tenant_id* right now.

    Pure — reads from the two DB-like objects passed in but never writes.
    Errors from DB reads are treated as "can't decide safely → skip" rather
    than raising, so a flaky runs-db row cannot break the scheduler tick.

    Args:
        tenant_id:         The tenant being evaluated.
        tenant_dream_cfg:  The tenant's ``config.json['dream']`` dict (may be
                           empty — defaults are applied).
        memory_pool:       Object exposing ``last_message_at(tenant_id)``.
                           See :mod:`autoservice.memory_pool`.
        dream_runs_db:     A sqlite3 connection with the ``dream_runs``
                           schema applied.
        now:               Injected clock for tests. Defaults to
                           ``datetime.now(tz=utc)``.

    Returns:
        ``(True, "<reason>")`` when the caller should fire ``run_dream``;
        ``(False, "<reason>")`` otherwise. ``reason`` is a short
        snake_case code suitable for logs and metrics.

    Reason-code vocabulary (exhaustive — one per decision path):

        ``manual_only``           — tenant set ``trigger='manual'``.
        ``already_running``       — a row with ``status='running'`` exists.
        ``cool_down_active``      — last terminal run ended < cool_down ago.
        ``coverage_disabled``     — tenant set ``coverage='none'``.
        ``insufficient_signal``   — risk='high' + no proposals in lookback.
        ``never_active``          — memory_pool has no turns for this tenant.
        ``not_idle``              — idle mode, but last message is recent.
        ``idle``                  — idle mode fires; last turn is old enough.
        ``scheduled_hit``         — scheduled mode fires; within the window.
        ``scheduled_miss``        — scheduled mode, outside window.
        ``unknown_trigger``       — config has a trigger string we don't know.
    """
    now = now or datetime.now(tz=timezone.utc)

    trigger = (tenant_dream_cfg or {}).get("trigger", "idle")

    # ── Rule 1 · manual is an absolute off-switch ──────────────────────
    # The scheduler must NEVER auto-fire a manual tenant — they opt in to
    # POST /api/dream/trigger only. This is the cheapest check, so it
    # runs first; even the DB isn't touched if a tenant is manual.
    if trigger in _MANUAL_TRIGGERS:
        return (False, "manual_only")

    # ── Rule 2 · already running? ──────────────────────────────────────
    # Cheaper than the cool-down check (same query page size, simpler
    # filter) and absolutely correct to short-circuit: you can never
    # want to fire a second run while the first is in flight.
    try:
        if _has_running_row(dream_runs_db, tenant_id):
            return (False, "already_running")
    except sqlite3.Error as exc:
        logger.warning(
            "dream_runs query failed for %s during running-check: %s — "
            "treating as 'already_running' to fail-closed",
            tenant_id, exc,
        )
        return (False, "already_running")

    # ── Rule 3 · cool-down since last terminal run ─────────────────────
    # Spec §9 risk table: "run_dream 结束后 1h cool-down 硬写死". We allow
    # an override via ``dream.cool_down_min`` so tests can use 0/1.
    cool_down_min = _pos_int(tenant_dream_cfg.get("cool_down_min"), DEFAULT_COOL_DOWN_MIN)
    try:
        if _recent_terminal(dream_runs_db, tenant_id, cool_down_min, now=now):
            return (False, "cool_down_active")
    except sqlite3.Error as exc:
        logger.warning(
            "dream_runs query failed for %s during cool-down check: %s — "
            "treating as cool-down active",
            tenant_id, exc,
        )
        return (False, "cool_down_active")

    # ── Rule 4 · coverage gate ─────────────────────────────────────────
    # Runs before the idle test: there's no reason to probe memory_pool
    # for an opted-out tenant. ``coverage='none'`` is an explicit opt-out;
    # any other value (including missing) passes through.
    coverage = (tenant_dream_cfg or {}).get("coverage")
    if coverage == "none":
        return (False, "coverage_disabled")

    # ── Rule 5 · risk=high soft gate ───────────────────────────────────
    # When a tenant demands 'high' risk tolerance we want some signal that
    # the agent is actually finding something to propose. No proposals in
    # the lookback window → the tenant is a cost drain, skip until human
    # review restarts the signal.
    if (tenant_dream_cfg or {}).get("risk_threshold") == "high":
        if not _has_recent_proposals(
            dream_runs_db, tenant_id,
            days=HIGH_RISK_SIGNAL_LOOKBACK_DAYS, now=now,
        ):
            return (False, "insufficient_signal")

    # ── Rule 6 · trigger-mode decision ─────────────────────────────────
    if trigger in _IDLE_TRIGGERS:
        try:
            last_msg = memory_pool.last_message_at(tenant_id)
        except Exception as exc:  # noqa: BLE001 — defensive
            logger.warning(
                "memory_pool.last_message_at raised for %s: %s — skipping",
                tenant_id, exc,
            )
            return (False, "never_active")
        if last_msg is None:
            return (False, "never_active")
        idle_threshold = timedelta(
            minutes=_pos_int(
                tenant_dream_cfg.get("idle_threshold_min"),
                DEFAULT_IDLE_THRESHOLD_MIN,
            )
        )
        if (now - _coerce_utc(last_msg)) < idle_threshold:
            return (False, "not_idle")
        return (True, "idle")

    if trigger in _SCHEDULED_TRIGGERS:
        scheduled_at = (tenant_dream_cfg or {}).get("scheduled_at")
        if _within_scheduled_window(scheduled_at, now):
            return (True, "scheduled_hit")
        return (False, "scheduled_miss")

    # Unknown trigger → opt-out fail-safe. Don't crash; record the fact.
    return (False, "unknown_trigger")


# ── Decision helpers ───────────────────────────────────────────────────────


def _has_running_row(conn: sqlite3.Connection, tenant_id: str) -> bool:
    """Return True if any ``dream_runs`` row for *tenant_id* is still running."""
    row = conn.execute(
        "SELECT 1 FROM dream_runs WHERE tenant_id = ? AND status = 'running' LIMIT 1",
        (tenant_id,),
    ).fetchone()
    return row is not None


def _recent_terminal(
    conn: sqlite3.Connection, tenant_id: str, cool_down_min: int,
    *, now: datetime,
) -> bool:
    """Return True if the tenant has a terminal run that ended within cool-down."""
    if cool_down_min <= 0:
        return False
    row = conn.execute(
        "SELECT ended_at FROM dream_runs "
        "WHERE tenant_id = ? AND status IN ('completed','failed','overrun') "
        "ORDER BY ended_at DESC LIMIT 1",
        (tenant_id,),
    ).fetchone()
    if row is None:
        return False
    ended_at_raw = row[0] if not hasattr(row, "keys") else row["ended_at"]
    if not ended_at_raw:
        # Terminal status but no ended_at recorded — treat as stale noise, not
        # an active cool-down. This protects against corrupt rows.
        return False
    try:
        ended_at = _parse_iso(ended_at_raw)
    except (ValueError, TypeError):
        return False
    return (now - ended_at) < timedelta(minutes=cool_down_min)


def _has_recent_proposals(
    conn: sqlite3.Connection, tenant_id: str, *, days: int, now: datetime,
) -> bool:
    """Best-effort check for recent proposals (risk-high heuristic).

    Uses the proposals_emitted counter on dream_runs as a proxy for the
    ``proposals`` table — this keeps the scheduler decoupled from the
    proposal DB. If the tenant has had at least one successful run that
    emitted a proposal in the lookback window, we treat that as enough
    signal to keep going.
    """
    cutoff = (now - timedelta(days=days)).isoformat()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM dream_runs "
            "WHERE tenant_id = ? AND proposals_emitted > 0 "
            "AND started_at >= ?",
            (tenant_id, cutoff),
        ).fetchone()
    except sqlite3.Error:
        # Fail-open for the heuristic — better to run occasionally than
        # permanently gate a tenant on a corrupt runs DB.
        return True
    n = row[0] if not hasattr(row, "keys") else row[0]
    return bool(n)


def _within_scheduled_window(scheduled_at: str | None, now: datetime) -> bool:
    """Return True if *now* is within ``SCHEDULED_WINDOW_MIN`` of ``scheduled_at``.

    ``scheduled_at`` is accepted as ``"HH:MM"`` (24h). Anything else is a miss.
    """
    if not scheduled_at or not isinstance(scheduled_at, str):
        return False
    try:
        hh_str, mm_str = scheduled_at.split(":", 1)
        hh, mm = int(hh_str), int(mm_str)
    except (ValueError, IndexError):
        return False
    if not (0 <= hh < 24 and 0 <= mm < 60):
        return False
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    delta = abs((now - target).total_seconds())
    return delta <= SCHEDULED_WINDOW_MIN * 60


def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 timestamp as a timezone-aware UTC datetime."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _coerce_utc(dt: datetime) -> datetime:
    """Ensure *dt* is timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _pos_int(value: Any, default: int) -> int:
    """Return ``int(value)`` when positive, else *default*."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return v if v > 0 else default


# ── T4B.2 · DreamScheduler loop ─────────────────────────────────────────────


class DreamScheduler:
    """Background asyncio loop that auto-triggers ``run_dream`` per tenant.

    Lifecycle:

    * :meth:`start` — spawn the loop task. Idempotent; calling twice is a
      no-op on the second call (returns early).
    * :meth:`stop` — cancel the loop task and await its death. Safe to call
      even if ``start`` never fired.
    * :meth:`refresh` — invalidate a tenant's cached config so the next
      tick re-reads ``config.json`` from disk (T4B.3). Also safe when the
      scheduler is not running — it just marks the cache dirty.

    The loop is **never supposed to raise**. Individual tenant errors are
    logged and swallowed so one bad tenant cannot starve the others.
    """

    def __init__(
        self,
        poll_interval_sec: float = 60.0,
        *,
        run_dream_fn: Callable[..., Awaitable[Any]] | None = None,
        should_trigger_fn: Callable[..., tuple[bool, str]] | None = None,
        sandbox_root: Path | None = None,
        plugins_root: Path | None = None,
        project_root: Path | None = None,
    ) -> None:
        """Build a scheduler.

        Args:
            poll_interval_sec: How often the loop wakes. Defaults to 60s per
                spec §2.2. Tests pass a much smaller value.
            run_dream_fn: Injection seam for the run_dream callable. Defaults
                to :func:`autoservice.dream_agent.run_dream`. Tests patch.
            should_trigger_fn: Injection seam for should_trigger. Defaults
                to the module-level function. Tests patch.
            sandbox_root: Override for ``.autoservice/sandbox``. Tests point
                this at ``tmp_path``.
            plugins_root: Override for ``plugins/``. Tests point this at
                ``tmp_path``.
            project_root: Override for the repo root used to compute the
                default sandbox/plugins locations.
        """
        self._poll_interval = float(poll_interval_sec)
        self._run_dream_fn = run_dream_fn
        self._should_trigger_fn = should_trigger_fn or should_trigger

        root = project_root or PROJECT_ROOT
        self._sandbox_root = sandbox_root or (root / ".autoservice" / "sandbox")
        self._plugins_root = plugins_root or (root / "plugins")

        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()
        self._refresh_requests: set[str] = set()
        self._inflight: set[asyncio.Task] = set()

        # Cached config per tenant — invalidated by ``refresh()``. Starts
        # empty; first read populates it.
        self._config_cache: dict[str, dict] = {}

    # ── Public lifecycle ───────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        """True when the loop task is live (started and not yet done)."""
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the background loop. No-op if already running."""
        if self.is_running:
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._loop(), name="dream_scheduler")
        logger.info(
            "DreamScheduler started (poll_interval=%.2fs)", self._poll_interval,
        )

    async def stop(self) -> None:
        """Stop the loop and wait for it to finish.

        Cancels the task, then awaits it so that CancelledError actually
        unwinds before we return — callers often hold the runtime resources
        (DB connections, cc_pool) that the loop is using.
        """
        self._stopped.set()
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        # Also drain any in-flight per-tenant run_dream tasks. Let them finish
        # naturally (we don't cancel them) but stop tracking them — they're
        # fire-and-forget and have their own error handling. Callers that
        # need to wait explicitly can ``await scheduler.drain()``.
        logger.info("DreamScheduler stopped")

    async def drain(self, timeout: float = 5.0) -> None:
        """Wait up to *timeout* seconds for in-flight run_dream tasks."""
        if not self._inflight:
            return
        done, pending = await asyncio.wait(
            list(self._inflight), timeout=timeout,
        )
        for t in pending:
            t.cancel()

    async def refresh(self, tenant_id: str) -> None:
        """Invalidate *tenant_id*'s cached config; next tick re-reads disk.

        Safe when the loop is not running — we just clear the cache entry.
        Not blocking on I/O: the next ``_tick`` will re-read under its
        normal try/except guard. This makes the method cheap enough to
        ``await`` from a FastAPI request handler.
        """
        self._refresh_requests.add(tenant_id)
        self._config_cache.pop(tenant_id, None)
        logger.debug("DreamScheduler: refresh requested for %s", tenant_id)

    # ── Tenant discovery ───────────────────────────────────────────────

    def _discover_active_tenants(self) -> list[str]:
        """Enumerate tenants worth polling.

        Includes:

        * ``_master`` when it exists under sandbox_root.
        * ``_local_admin`` when it exists under plugins_root (fork mode).
        * Every ``<sandbox_root>/<tid>/`` with status='active'.
        * Every ``<plugins_root>/<tid>/`` with status='active' (fork mode).

        The M2 spec explicitly excludes archived tenants. Tenants whose
        ``config.json`` is missing or unreadable are silently skipped —
        they're likely in the middle of being provisioned.
        """
        seen: set[str] = set()
        out: list[str] = []

        for root in (self._sandbox_root, self._plugins_root):
            if not root.exists():
                continue
            for child in sorted(root.iterdir()):
                if not child.is_dir():
                    continue
                tid = child.name
                if tid in seen:
                    continue
                if tid == "_example":
                    # Template, not a live tenant.
                    continue
                cfg_path = child / "config.json"
                if not cfg_path.is_file():
                    continue
                try:
                    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(cfg, dict):
                    continue
                status = cfg.get("status", "active")
                if status != "active":
                    continue
                seen.add(tid)
                out.append(tid)
        return out

    # ── Config + run_dream plumbing ────────────────────────────────────

    def _read_tenant_dream_cfg(self, tenant_id: str) -> dict:
        """Load (and cache) the ``dream`` block from a tenant's config.json."""
        if tenant_id in self._config_cache:
            return self._config_cache[tenant_id]

        for root in (self._sandbox_root, self._plugins_root):
            cfg_path = root / tenant_id / "config.json"
            if not cfg_path.is_file():
                continue
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            dream = cfg.get("dream") if isinstance(cfg, dict) else None
            result = dream if isinstance(dream, dict) else {}
            self._config_cache[tenant_id] = result
            return result

        self._config_cache[tenant_id] = {}
        return {}

    # ── Loop internals ─────────────────────────────────────────────────

    async def _loop(self) -> None:
        """Main scheduler coroutine. Ticks every poll_interval."""
        try:
            while not self._stopped.is_set():
                try:
                    await self._tick()
                except Exception:  # noqa: BLE001 — never die
                    logger.exception("DreamScheduler tick raised")
                try:
                    await asyncio.wait_for(
                        self._stopped.wait(), timeout=self._poll_interval,
                    )
                    # If wait_for returned without timing out → stopped is set
                    # → loop condition will break next check.
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            logger.info("DreamScheduler loop cancelled")
            raise
        finally:
            # Best-effort: allow subclasses / tests to observe a clean exit.
            self._stopped.set()

    async def _tick(self) -> None:
        """One pass: discover tenants, evaluate, fire."""
        # First drain any refresh requests that came in after the last tick;
        # they've already cleared cache entries, so there's nothing to do
        # except keep the set bounded.
        self._refresh_requests.clear()

        tenants = self._discover_active_tenants()

        from autoservice import dream_runs as _dream_runs
        # Open a short-lived connection per tick — simpler than holding a
        # long-lived one and coping with pickled state in tests.
        try:
            runs_conn = _dream_runs.open_connection()
        except sqlite3.Error as exc:
            logger.warning("dream_runs open_connection failed: %s", exc)
            return

        try:
            mempool = self._get_memory_pool()
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory_pool init failed: %s", exc)
            runs_conn.close()
            return

        try:
            for tid in tenants:
                try:
                    cfg = self._read_tenant_dream_cfg(tid)
                    should, reason = self._should_trigger_fn(
                        tid, cfg, mempool, runs_conn,
                    )
                    if should:
                        logger.info(
                            "DreamScheduler: firing run_dream for %s (reason=%s)",
                            tid, reason,
                        )
                        await self._spawn_run(tid)
                    else:
                        logger.debug(
                            "DreamScheduler: skipping %s (%s)", tid, reason,
                        )
                except Exception:  # noqa: BLE001 — one bad tenant mustn't kill the tick
                    logger.exception(
                        "DreamScheduler: error evaluating tenant %s", tid,
                    )
        finally:
            try:
                runs_conn.close()
            except sqlite3.Error:
                pass

    async def _spawn_run(self, tenant_id: str) -> None:
        """Spawn ``run_dream(tenant_id, ...)`` as a background task."""
        run_dream_fn = self._run_dream_fn or _import_run_dream()
        if run_dream_fn is None:
            logger.warning(
                "DreamScheduler: no run_dream callable available — skipping %s",
                tenant_id,
            )
            return

        coro = self._build_run_dream_coro(run_dream_fn, tenant_id)
        if coro is None:
            return
        task = asyncio.create_task(coro, name=f"run_dream:{tenant_id}")
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    def _build_run_dream_coro(
        self, run_dream_fn: Callable[..., Awaitable[Any]], tenant_id: str,
    ) -> Awaitable[Any] | None:
        """Prepare the coroutine to execute ``run_dream`` for *tenant_id*.

        Broken out for testability — tests override either ``_run_dream_fn``
        or :meth:`_spawn_run` to observe invocation, so this just does the
        mechanical "fetch resources, call the function" step.
        """
        try:
            cc_pool = self._get_cc_pool_sync()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "DreamScheduler: cc_pool acquire failed for %s: %s",
                tenant_id, exc,
            )
            cc_pool = None

        try:
            mempool = self._get_memory_pool()
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory_pool lookup failed: %s", exc)
            return None

        from autoservice import dream_runs as _dream_runs
        try:
            runs_conn = _dream_runs.open_connection()
        except sqlite3.Error as exc:
            logger.warning("dream_runs open failed: %s", exc)
            return None

        try:
            proposals_conn = self._get_proposals_conn()
        except Exception as exc:  # noqa: BLE001
            logger.warning("proposals conn acquire failed: %s", exc)
            runs_conn.close()
            return None

        return run_dream_fn(
            tenant_id,
            cc_pool,
            mempool,
            proposals_conn,
            runs_conn,
            max_tool_turns=10,
        )

    # ── Resource helpers (overridable in tests) ────────────────────────

    def _get_memory_pool(self):
        """Return a (possibly cached) MemoryPool. Overridable in tests."""
        from autoservice.memory_pool import MemoryPool
        if not hasattr(self, "_mempool") or self._mempool is None:
            self._mempool = MemoryPool()
        return self._mempool

    def _get_cc_pool_sync(self):
        """Return the CCPool via the existing module-level accessor.

        Deliberately synchronous — calling ``asyncio.run`` from inside
        an asyncio task is illegal. The actual pool is created eagerly
        by :func:`autoservice.web_gateway._warm_cc_pool` on startup, so
        by the time we reach here the cached singleton should already
        exist. If not, we return None; :func:`run_dream` must tolerate.
        """
        try:
            from autoservice import cc_pool as _cc_pool_mod
            return getattr(_cc_pool_mod, "_pool", None)
        except Exception:  # noqa: BLE001
            return None

    def _get_proposals_conn(self) -> sqlite3.Connection:
        """Return a proposals sqlite connection.

        Matches the pattern used by api_routes._get_proposal_pipeline —
        we share that pipeline's connection so writes land in the same
        DB the HTTP endpoints read from.
        """
        from autoservice.api_routes import _get_proposal_pipeline
        pp = _get_proposal_pipeline()
        return pp._conn


def _import_run_dream() -> Callable[..., Awaitable[Any]] | None:
    """Lazily import ``dream_agent.run_dream`` to avoid cycles at import time."""
    try:
        from autoservice.dream_agent import run_dream
    except ImportError:
        return None
    return run_dream


# ── Module-level scheduler singleton (web_gateway lifespan) ────────────────

_scheduler: DreamScheduler | None = None


def get_scheduler() -> DreamScheduler | None:
    """Return the process-wide scheduler, or ``None`` if none was set."""
    return _scheduler


def set_scheduler(scheduler: DreamScheduler | None) -> None:
    """Register the process-wide scheduler. Used by web_gateway startup."""
    global _scheduler
    _scheduler = scheduler


async def refresh(tenant_id: str) -> None:
    """Refresh the module-wide scheduler for *tenant_id*, if one exists.

    Safe no-op when the scheduler is not running (e.g. tests, CLI). This is
    the public entry point the ``/dream-config`` confirm handler calls.
    """
    sched = get_scheduler()
    if sched is None:
        return
    try:
        await sched.refresh(tenant_id)
    except Exception:  # noqa: BLE001 — never let refresh break the dialog
        logger.exception(
            "DreamScheduler.refresh raised for tenant %s (non-fatal)", tenant_id,
        )


__all__ = [
    "DEFAULT_IDLE_THRESHOLD_MIN",
    "DEFAULT_COOL_DOWN_MIN",
    "SCHEDULED_WINDOW_MIN",
    "HIGH_RISK_SIGNAL_LOOKBACK_DAYS",
    "DreamScheduler",
    "should_trigger",
    "refresh",
    "get_scheduler",
    "set_scheduler",
]
