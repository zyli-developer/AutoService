"""REST API routes — expose backend capabilities to frontend SPAs.

Bridges existing backend classes (SLAAggregator, TieredBilling, ProposalPipeline,
CanaryRouter, ComplianceEngine, sim_customer) to HTTP endpoints.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response

from autoservice import auth, dream_agent, dream_runs
from autoservice.canary import CanaryStage

logger = logging.getLogger("autoservice.api")

# Global engine reference (set by web_gateway on startup)
_engine_ref = None

def _set_engine(engine):
    global _engine_ref
    _engine_ref = engine

def _ws_engine():
    return _engine_ref

api_router = APIRouter(prefix="/api", tags=["api"])

# Path to the repo-root config.local.yaml that drives the /api/onboard/publish
# fork_creator selector (spec §3.4).  Module-level so tests can monkeypatch
# it to an isolated tmp file.  Resolved lazily at import to a project-root
# absolute path so requests from any cwd hit the same file.
_PUBLISH_CONFIG_PATH: Path = (
    Path(__file__).resolve().parent.parent / ".autoservice" / "config.local.yaml"
)

# ---------------------------------------------------------------------------
# Singleton instances (lazy init, shared across requests)
# ---------------------------------------------------------------------------
_sla = None
_billing = None
_billing_metrics = None
_canary = None
_canary_monitor = None
_proposal_pipeline = None


def _get_sla():
    global _sla
    if _sla is None:
        from autoservice.sla_aggregator import SLAAggregator
        _sla = SLAAggregator()
    return _sla


def get_sla_aggregator():
    """Return the shared SLAAggregator singleton.

    Use this to pass the instance to message_router hooks so that
    conversation events feed real SLA data (T6D.1).
    """
    return _get_sla()


def _get_billing():
    global _billing, _billing_metrics
    if _billing is None:
        from autoservice.billing import TieredBilling
        from autoservice.billing_metrics import BillingMetrics
        _billing = TieredBilling()
        _billing_metrics = BillingMetrics()
        # Seed operator leaderboard with demo data (T6D.4)
        _billing_metrics.record_operator_handle("op_zhang", name="张伟", csat=5, response_ms=2800)
        _billing_metrics.record_operator_handle("op_zhang", name="张伟", csat=4, response_ms=3100)
        _billing_metrics.record_operator_handle("op_zhang", name="张伟", csat=5, response_ms=2600)
        _billing_metrics.record_operator_handle("op_zhang", name="张伟", csat=4, response_ms=3400)
        _billing_metrics.record_operator_handle("op_zhang", name="张伟", csat=5, response_ms=2900)
        _billing_metrics.record_operator_handle("op_li", name="李娜", csat=4, response_ms=3500)
        _billing_metrics.record_operator_handle("op_li", name="李娜", csat=5, response_ms=3200)
        _billing_metrics.record_operator_handle("op_li", name="李娜", csat=4, response_ms=3800)
        _billing_metrics.record_operator_handle("op_wang", name="王芳", csat=5, response_ms=2100)
        _billing_metrics.record_operator_handle("op_wang", name="王芳", csat=5, response_ms=2300)
    return _billing, _billing_metrics


def get_billing_metrics():
    """Return the shared BillingMetrics singleton.

    Use this to pass the instance to MetricsPlugin so that mode-change
    and CSAT events feed real billing data (T6C.2).
    """
    _, metrics = _get_billing()
    return metrics


def _get_canary():
    global _canary, _canary_monitor
    if _canary is None:
        from autoservice.canary import CanaryRouter
        from autoservice.canary_monitor import CanaryMonitor
        _canary = CanaryRouter()
        _canary_monitor = CanaryMonitor(_canary)
        _canary_monitor.set_baseline({
            "avg_response_time": 200,
            "csat_score": 4.2,
            "complaint_rate": 0.02,
        })
    return _canary, _canary_monitor


def _get_proposal_pipeline():
    global _proposal_pipeline
    if _proposal_pipeline is None:
        from pathlib import Path
        from autoservice.memory_pool import MemoryPool
        from autoservice.proposal_pipeline import ProposalPipeline
        db_dir = Path(".autoservice/data")
        db_dir.mkdir(parents=True, exist_ok=True)
        mp = MemoryPool(db_dir / "memory_pool.db")
        _proposal_pipeline = ProposalPipeline(
            memory_pool=mp, db_path=db_dir / "proposals.db",
        )
    return _proposal_pipeline


def _parse_proposal_id(text: str, command: str) -> str | None:
    """Extract proposal ID from '/approve #N' or '/approve prop_xxxx' format."""
    rest = text[len(command):].strip()
    # Match #N (shorthand — look up by row index) or prop_xxx (direct ID)
    if rest.startswith("#"):
        rest = rest[1:].strip()
    if not rest:
        return None
    # If it looks like a direct proposal ID, return as-is
    if rest.startswith("prop_"):
        return rest
    # Numeric shorthand: treat as 1-based index into proposal list
    try:
        idx = int(rest) - 1
        pp = _get_proposal_pipeline()
        proposals = pp.list_proposals()
        if 0 <= idx < len(proposals):
            return proposals[idx]["id"]
        return None
    except (ValueError, IndexError):
        return rest  # try as literal ID


def _handle_approve_command(text: str) -> dict[str, Any]:
    """Parse /approve, update proposal status, activate canary."""
    proposal_id = _parse_proposal_id(text, "/approve")
    if not proposal_id:
        return {"role": "dream_engine", "content": "⚠️ 用法: /approve #N 或 /approve prop_xxxx\n请指定提案编号。"}

    pp = _get_proposal_pipeline()
    updated = pp.update_status(proposal_id, "accepted")
    if updated is None:
        return {"role": "dream_engine", "content": f"⚠️ 提案 {proposal_id!r} 未找到。使用 /status 查看可用提案。"}

    # Activate canary — advance from DISABLED to STAGE_5
    canary_msg = ""
    try:
        router, _ = _get_canary()
        if router.percentage == 0:
            if router.can_advance():
                new_stage = router.advance()
                canary_msg = f"\n🚀 灰度已启动: {router.percentage}% ({new_stage.value})"
            else:
                canary_msg = "\n⏳ 灰度观察期未满，请稍后使用 /advance 推进"
        else:
            canary_msg = f"\n⚡ 灰度已在运行中: {router.percentage}%"
    except Exception as exc:
        canary_msg = f"\n⚠️ 灰度启动失败: {exc}"

    return {
        "role": "dream_engine",
        "content": f"✅ 提案 {proposal_id} 已批准 (accepted){canary_msg}\n"
        f"📋 {updated.get('title', '')}"
    }


def _handle_reject_command(text: str) -> dict[str, Any]:
    """Parse /reject, update proposal status."""
    proposal_id = _parse_proposal_id(text, "/reject")
    if not proposal_id:
        return {"role": "dream_engine", "content": "⚠️ 用法: /reject #N 或 /reject prop_xxxx\n请指定提案编号。"}

    pp = _get_proposal_pipeline()
    updated = pp.update_status(proposal_id, "rejected")
    if updated is None:
        return {"role": "dream_engine", "content": f"⚠️ 提案 {proposal_id!r} 未找到。使用 /status 查看可用提案。"}

    return {
        "role": "dream_engine",
        "content": f"❌ 提案 {proposal_id} 已拒绝 (rejected)\n📋 {updated.get('title', '')}"
    }


# ---------------------------------------------------------------------------
# Session / deployment mode (T1B.5)
# ---------------------------------------------------------------------------
#
# admin-portal 双模式切换端点。M1 始终返回 master；M2 将根据部署类型
# （Master 本仓 vs Tenant fork）返回 tenant + tenant_id。
# See: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §5.3
#
# No authentication in M1 (will be added M2 with tenant-admin RBAC).

_PLATFORM_BRAND_NAME = "AutoService"


def _read_brand_from_config(cfg_path: Path) -> str | None:
    """Read ``brand_name`` from a config.json; ``None`` if absent/invalid.

    I/O and parse errors are logged and swallowed — brand resolution must
    never 500.
    """
    if not cfg_path.exists():
        return None
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("brand_name lookup failed for %s: %s", cfg_path, exc)
        return None
    brand = cfg.get("brand_name")
    if isinstance(brand, str) and brand.strip():
        return brand.strip()
    return None


def _try_resolve_brand_name(tenant_id: str | None) -> str | None:
    """Return the tenant-configured brand_name, or ``None`` if unset.

    Never falls back to the platform default — callers who want that
    must wrap the result themselves.  The customer-chat WS handshake
    relies on the ``None`` signal so it can defer to the widget's i18n
    fallback (avoids rendering ``"AutoService 客服"`` as a fake brand).

    Lookup order:
      1. ``plugins/<tid>/config.json["brand_name"]`` — L3 deploy snapshot.
      2. ``.autoservice/sandbox/<tid>/config.json["brand_name"]`` —
         wizard-authored sandbox state (not yet published).

    Both paths are CWD-relative so they stay aligned under tests that
    ``chdir`` into a tmp dir.  At runtime the server is started from the
    project root, matching :data:`autoservice.onboarding.SANDBOX_ROOT`.
    """
    if not tenant_id:
        return None
    brand = _read_brand_from_config(Path("plugins") / tenant_id / "config.json")
    if brand:
        return brand
    return _read_brand_from_config(
        Path(".autoservice") / "sandbox" / tenant_id / "config.json"
    )


def _resolve_brand_name_for_tenant(tenant_id: str | None) -> str:
    """Tenant-scoped brand_name with platform-default fallback.

    Used by the admin top-bar (``/api/session/mode``) where a non-empty
    string is always required.  See :func:`_try_resolve_brand_name` for
    the nullable variant used by the customer WS handshake.
    """
    return _try_resolve_brand_name(tenant_id) or _PLATFORM_BRAND_NAME


def _resolve_brand_name(mode: str, self_tid: str | None) -> str:
    """Resolve the brand_name shown in the top bar (spec §4.5).

    Lookup order:
      1. Tenant-mode fork: delegate to :func:`_resolve_brand_name_for_tenant`
         (plugins → sandbox → platform default).
      2. Master mode: always the platform default ("AutoService").  Tenant
         admins visiting the master host will see their brand surfaced by
         the session-level tenant lookup in a later milestone (M3 scope).
    """
    if mode == "tenant" and self_tid:
        return _resolve_brand_name_for_tenant(self_tid)
    return _PLATFORM_BRAND_NAME


@api_router.get("/session/mode")
async def get_session_mode(request: Request) -> dict[str, Any]:
    """Deployment mode + auth-state for the admin-portal AuthGate (spec §4.5).

    Always 200.  The response discriminator is ``authenticated``:

        {
          "mode": "master" | "tenant",
          "tenant_id": "<tid>" | null,
          "authenticated": bool,
          "authenticated_as": "<email>" | null,
          "tier": 0 | 1 | null,
          "brand_name": "<str>"
        }

    - Anonymous callers see ``authenticated=false``, ``tier=null``, the
      mode-appropriate ``tenant_id``/``brand_name``.  No other tenants'
      scope is leaked.
    - Tier derivation: NULL session.tenant_id → 0 (``_master`` /
      ``_local_admin`` internal admin, CON-05); non-NULL → 1.  M2 never
      returns 2 (subtenant reserved).
    """
    # Deployment mode + self-tenant (fork's own id).  The bootstrap helper
    # caches these, so each call is cheap.  A missing config.local.yaml
    # degrades to master mode + null tenant — matches the lifespan
    # ``_bootstrap_internal_tenants`` fallback in web_gateway.
    try:
        from autoservice import bootstrap
        mode = bootstrap.get_deployment_mode()
        self_tid = bootstrap.get_tenant_id()
    except Exception:
        mode = "master"
        self_tid = None

    # Auth state — optional; anon callers get authenticated=false without
    # ever touching the DB when the cookie is absent.
    session: dict | None = None
    sid = request.cookies.get(AUTH_SESSION_COOKIE)
    if sid:
        try:
            conn = _get_auth_db()
            session = auth.lookup_session(conn, sid)
        except Exception:
            logger.warning("session lookup failed in /session/mode", exc_info=True)
            session = None

    if session is None:
        return {
            "mode": mode,
            "tenant_id": self_tid,
            "authenticated": False,
            "authenticated_as": None,
            "tier": None,
            "brand_name": _resolve_brand_name(mode, self_tid),
        }

    session_tid = session.get("tenant_id")
    tier = 0 if session_tid is None else 1
    # When an authenticated admin has a session-level tenant scope (tier-1)
    # the response exposes that tenant_id — the frontend's AuthGate uses it
    # to decide which layout to render even on the master host.
    response_tid = session_tid if session_tid is not None else self_tid

    return {
        "mode": mode,
        "tenant_id": response_tid,
        "authenticated": True,
        "authenticated_as": session.get("admin_email"),
        "tier": tier,
        "brand_name": _resolve_brand_name(mode, self_tid),
    }


# ---------------------------------------------------------------------------
# Master · tenant directory (T1F.6)
# ---------------------------------------------------------------------------
#
# Scans .autoservice/sandbox/<tid>/config.json (and .autoservice/archived/...)
# to power the Master-view TenantListTab. Each directory's config.json is the
# source of truth — see autoservice.onboarding._write_sandbox_config_skeleton
# and autoservice.publish._archive_sandbox.
#
# M1: no auth. M2 will gate with tenant-admin RBAC (see spec §5.3 and the
# tenant-sandbox M2 design doc).
#
# See: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §5.2

_SANDBOX_ROOT = Path(".autoservice") / "sandbox"
_ARCHIVED_ROOT = Path(".autoservice") / "archived"


def _read_tenant_config(cfg_path: Path, *, status_override: str | None = None) -> dict[str, Any] | None:
    """Read a tenant config.json, returning a projection with the listing fields.

    Returns None if the file is missing or unparseable — the listing endpoint
    silently skips such entries (a corrupt config shouldn't 500 the whole list).
    ``status_override`` is used for archived entries whose on-disk config may or
    may not have been stamped with ``status=archived`` yet (see publish.py §7.2).
    """
    if not cfg_path.exists():
        return None
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read tenant config at %s: %s", cfg_path, exc)
        return None
    return {
        "tenant_id": cfg.get("tenant_id"),
        "brand_name": cfg.get("brand_name"),
        "industry": cfg.get("industry"),
        "status": status_override or cfg.get("status", "unknown"),
        "created_at": cfg.get("created_at"),
    }


@api_router.get("/master/tenants")
async def list_master_tenants() -> list[dict[str, Any]]:
    """List all tenants known to this Master deployment.

    Scans ``.autoservice/sandbox/<tid>/`` (sandbox + published_pending_fork)
    and ``.autoservice/archived/<tid>_<ts>/`` (archived) for ``config.json``
    files, projecting the listing fields. Returns ``[]`` when neither
    directory exists or contains any tenant configs.
    """
    out: list[dict[str, Any]] = []

    if _SANDBOX_ROOT.exists() and _SANDBOX_ROOT.is_dir():
        for tid_dir in sorted(_SANDBOX_ROOT.iterdir()):
            if not tid_dir.is_dir():
                continue
            entry = _read_tenant_config(tid_dir / "config.json")
            if entry is not None:
                out.append(entry)

    if _ARCHIVED_ROOT.exists() and _ARCHIVED_ROOT.is_dir():
        for tid_dir in sorted(_ARCHIVED_ROOT.iterdir()):
            if not tid_dir.is_dir():
                continue
            # Archived directory names are "<tid>_<ts>" — use the config's own
            # tenant_id as authoritative, but force status=archived since the
            # list is what A sees and archived entries must render as such.
            entry = _read_tenant_config(tid_dir / "config.json", status_override="archived")
            if entry is not None:
                out.append(entry)

    return out


# ---------------------------------------------------------------------------
# SLA
# ---------------------------------------------------------------------------

_PERIOD_TO_WINDOW: dict[str, str] = {"5m": "5m", "1h": "1h", "24h": "24h"}


@api_router.get("/conversations/active")
async def list_active_conversations(
    squad_id: str | None = None, operator_id: str | None = None,
) -> dict[str, Any]:
    """Return active (non-closed) conversations, optionally filtered by squad
    or operator. Used by the operator console on login to seed the
    conversation list without waiting for live events."""
    engine = _ws_engine()
    if engine is None:
        return {"conversations": []}
    convs = await engine.list_active_conversations(
        operator_id=operator_id, squad_id=squad_id,
    )
    items: list[dict[str, Any]] = []
    for c in convs:
        # Pull last message for preview (used by conversation card)
        try:
            msgs = await engine.get_messages(c.id, viewer_role="operator", limit=100)
        except Exception:
            msgs = []
        last_msg = msgs[-1] if msgs else None
        last_content = last_msg.content if last_msg else ""
        last_sender = last_msg.source if last_msg else ""
        last_ts = (
            last_msg.timestamp.isoformat()
            if last_msg and hasattr(last_msg.timestamp, "isoformat")
            else (c.updated_at.isoformat() if hasattr(c.updated_at, "isoformat") else "")
        )
        items.append({
            "id": c.id,
            "squad_id": c.metadata.get("squad_id", ""),
            "customer_id": next(
                (p.id for p in c.participants if p.role.value == "customer"),
                "",
            ),
            "mode": c.mode.value if hasattr(c.mode, "value") else str(c.mode),
            "state": c.state.value if hasattr(c.state, "value") else str(c.state),
            "last_message": last_content,
            "last_sender": "customer" if (last_sender and last_sender != "agent" and not last_sender.startswith("op")) else ("agent" if last_sender == "agent" else "operator"),
            "last_activity_ts": last_ts,
            "takeover_operator_id": c.takeover_operator_id,
        })
    return {"conversations": items}


@api_router.get("/sla/summary")
async def sla_summary(period: str = "5m") -> dict[str, Any]:
    """Return current SLA metrics across all 7 types for a given time window."""
    from autoservice.sla_aggregator import MetricType, WindowSize
    from fastapi.responses import JSONResponse

    if period not in _PERIOD_TO_WINDOW:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Invalid period '{period}'. Must be one of: 5m, 1h, 24h"},
        )

    window = WindowSize(period)
    agg = _get_sla()
    result = {}
    for metric in MetricType:
        p = agg.get_percentiles(metric, window)
        result[metric.value] = {
            "p50": p.p50, "p95": p.p95, "count": p.count,
            "min": p.min_val, "max": p.max_val,
        }
    return result


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------

@api_router.get("/billing/invoices")
async def billing_invoices() -> list[dict[str, Any]]:
    """Return billing invoices for recent periods."""
    billing, metrics = _get_billing()
    periods = ["2026-04", "2026-03", "2026-02"]
    invoices = []
    for period in periods:
        bill = billing.generate_bill(metrics, period)
        invoices.append(bill)
    return invoices


# ---------------------------------------------------------------------------
# Metrics — Takeover Trend (T6D.3)
# ---------------------------------------------------------------------------

@api_router.get("/metrics/takeover-trend")
async def takeover_trend(period: str = "week") -> list[dict[str, Any]]:
    """Return takeover counts grouped by date for the last week or month."""
    _, metrics = _get_billing()
    return metrics.get_takeover_trend(period)


# ---------------------------------------------------------------------------
# Operator Leaderboard (T6D.4)
# ---------------------------------------------------------------------------

@api_router.get("/metrics/operator-leaderboard")
async def operator_leaderboard() -> list[dict[str, Any]]:
    """Return operator performance data sorted by handled count descending."""
    _, metrics = _get_billing()
    return metrics.get_operator_leaderboard()


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------

@api_router.get("/proposals")
async def list_proposals(status: str | None = None) -> list[dict[str, Any]]:
    """List proposals from the Dream Engine pipeline."""
    pp = _get_proposal_pipeline()
    return pp.list_proposals(status=status)


@api_router.post("/proposals/run")
async def run_proposal_pipeline() -> list[dict[str, Any]]:
    """Trigger the proposal pipeline and return results."""
    pp = _get_proposal_pipeline()
    return await pp.run()


# ---------------------------------------------------------------------------
# Dream agent — trigger + runs history (T3B.6)
# ---------------------------------------------------------------------------
#
# POST /api/dream/trigger   — fire a background run_dream() for a tenant
# GET  /api/dream/runs      — list historical dream_runs rows for a tenant
#
# Background execution: we use ``asyncio.create_task`` rather than FastAPI's
# ``BackgroundTasks`` because ``BackgroundTasks`` blocks the server worker
# until the task completes (it runs AFTER the response is sent but on the
# same request handling slot).  ``run_dream`` can run for many seconds to
# minutes; fire-and-forget via ``create_task`` is the only way to return
# 202 Accepted immediately.  See spec §2.6 "非阻塞"。
#
# Concurrency guard: before scheduling, we query ``dream_runs.list_runs``
# for any row with ``status='running'`` — matches spec §2.2 cooldown intent
# and prevents the tenant from stacking overlapping runs.
#
# Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §2.6

# Offline-dev / CI fallback for /api/dream/trigger.  Post-T5S.14 the
# default production path always goes through the real LLM tool-loop
# (``dream_agent.run_dream`` for per-tenant, ``master_dream_agent.
# run_platform_dream`` for master).  Setting ``DREAM_DEV_STUB=1``
# short-circuits BOTH paths to :func:`_run_dev_stub_dream` — three
# seed proposals after a short sleep, no LLM traffic, no API key
# required.  Useful for:
#   * CI suites that have no ``ANTHROPIC_API_KEY`` / no local Claude CLI
#   * Offline demos / video capture where deterministic output matters
#   * Smoke-testing the Dream Engine UI without spending tokens
#
# MUST stay unset in production.  Read once at import; restart to flip.
DREAM_DEV_STUB_ENABLED = os.environ.get("DREAM_DEV_STUB") == "1"
DREAM_DEV_STUB_DELAY_SEC = 3.0

_dream_runs_db_conn = None


def _get_dream_runs_db():
    """Return (lazy) shared ``dream_runs`` SQLite connection.

    Reuses a single connection across requests — matches ``_get_proposal_pipeline``
    and avoids the connection-per-request thrash that would otherwise occur on
    a hot endpoint.  The DB file lives under ``.autoservice/database/dream_runs.db``
    by default (see :func:`autoservice.dream_runs.open_connection`).
    """
    global _dream_runs_db_conn
    if _dream_runs_db_conn is None:
        _dream_runs_db_conn = dream_runs.open_connection()
    return _dream_runs_db_conn


def _reset_dream_runs_db_for_tests(conn=None):
    """Test-only hook: replace the cached runs-db connection.

    Passing ``conn=None`` simply clears the cache so the next call to
    :func:`_get_dream_runs_db` re-opens from disk.  Passing a prepared
    ``sqlite3.Connection`` lets tests inject an in-memory DB with the
    schema pre-applied via :func:`autoservice.dream_runs.init_schema`.
    """
    global _dream_runs_db_conn
    _dream_runs_db_conn = conn


def _tenant_exists(tenant_id: str) -> bool:
    """Return ``True`` when ``.autoservice/sandbox/<tid>/`` or ``plugins/<tid>/`` exists.

    Mirrors :func:`autoservice.dream_agent._resolve_tenant_root` — sandbox
    takes precedence on master deployments; plugin dir is the fork-side
    location for ``_local_admin`` and materialised tenant forks.  Resolution
    uses repo-relative paths so a ``monkeypatch.chdir(tmp_path)`` in tests
    switches the lookup root without any code changes here.
    """
    if (Path(".autoservice") / "sandbox" / tenant_id).exists():
        return True
    if (Path("plugins") / tenant_id).exists():
        return True
    return False


@api_router.post("/dream/trigger")
async def dream_trigger(payload: dict[str, Any] = Body(...)) -> Any:
    """Kick off a Dream agent run for a tenant (spec §2.6).

    Request body::

        {"tenant_id": "<tid>"}

    Response (202 Accepted)::

        {"run_id": "<uuid>", "status": "started", "tenant_id": "<tid>"}

    Errors:
        - 422 — missing / empty ``tenant_id`` (handled via JSONResponse so
          the shape matches other endpoints; FastAPI's default Pydantic
          422 would wrap the error differently)
        - 404 — tenant has neither a sandbox nor a plugin directory
        - 409 — tenant already has a ``status='running'`` row (another
          dream run is in flight); caller should retry after it ends

    The run executes in the background — the HTTP response returns
    immediately (202 Accepted), long before :func:`run_dream` completes.
    The ``run_id`` in the response is the row inserted by
    ``dream_runs.start_run`` inside the background task; clients poll
    ``GET /api/dream/runs`` to observe its terminal state.
    """
    from fastapi.responses import JSONResponse

    tenant_id = (payload.get("tenant_id") or "").strip() if isinstance(payload, dict) else ""
    if not tenant_id:
        return JSONResponse(
            status_code=422,
            content={"error": "tenant_id is required"},
        )

    if not _tenant_exists(tenant_id):
        return JSONResponse(
            status_code=404,
            content={"error": f"tenant {tenant_id!r} not found", "tenant_id": tenant_id},
        )

    # Concurrency guard — only one run per tenant at a time.  We fetch a
    # modest page size and filter in Python rather than adding a status
    # filter to list_runs (keeps that API minimal for M2).
    runs_conn = _get_dream_runs_db()
    recent = dream_runs.list_runs(runs_conn, tenant_id, limit=20)
    if any(r.get("status") == "running" for r in recent):
        return JSONResponse(
            status_code=409,
            content={
                "error": "dream run already in progress",
                "tenant_id": tenant_id,
            },
        )

    # Open the run row synchronously so we can return its id in the 202
    # payload; the background task will continue updating/finalising it.
    run_id = dream_runs.start_run(runs_conn, tenant_id)

    try:
        await _spawn_dream_run_with_run_id(tenant_id, run_id)
    except Exception as exc:  # noqa: BLE001 — surface setup failures
        # If spawning fails we must finalise the row we just opened so it
        # doesn't remain 'running' forever (which would also falsely trip
        # the concurrency guard above on subsequent requests).
        try:
            dream_runs.end_run(
                runs_conn, run_id, status="failed",
                error=f"spawn failed: {type(exc).__name__}: {exc}",
            )
        except Exception:
            logger.exception("dream_runs.end_run cleanup failed for %s", run_id)
        return JSONResponse(
            status_code=500,
            content={"error": f"failed to start dream run: {exc}", "tenant_id": tenant_id},
        )

    return JSONResponse(
        status_code=202,
        content={
            "run_id": run_id,
            "status": "started",
            "tenant_id": tenant_id,
        },
    )


# Seed proposals for the dev stub path.  Three distinct categories /
# risk levels so the admin-portal review UI renders visibly different
# rows (useful for screen recording + reviewer-flow smoke tests).  These
# go through the normal ``dream_agent.emit_proposal`` — they land as
# ``status='draft'`` under CON-04, same as LLM-emitted proposals.
_DREAM_DEV_STUB_SEEDS = [
    {
        "category": "response_quality",
        "title": "[dev stub] Agent 回复中 '您好' 使用频率偏高",
        "description": "最近 20 轮对话里 Agent 开场白 65% 使用 '您好'，缺乏场景区分度。",
        "suggestion": "在 customer soul 中加入多样化招呼语池，按时段/客户类型选择。",
        "evidence": "greet_ratio=0.65; window=20; sample=conv_20260421_a3f2",
        "risk_level": "low",
        "target_role": "customer",
    },
    {
        "category": "knowledge_gap",
        "title": "[dev stub] 近期 3 轮对话命中空 KB",
        "description": "客户询问退款政策细则时 kb_search 返回空，Agent 回复不确定。",
        "suggestion": "向 KB 补充退款政策 FAQ (refund_policy_v2) 并重建索引。",
        "evidence": "missed=['退款多久到账','部分退款可以吗','跨境退款流程']; kb_hits=0",
        "risk_level": "medium",
        "target_role": "customer",
    },
    {
        "category": "escalation_signal",
        "title": "[dev stub] 同一客户 5 分钟内 3 次请求转人工",
        "description": "客户 end_u_8811 在 5 分钟内连续请求 '要人工'，Agent 未主动降级。",
        "suggestion": "在 rules.yaml 增加 escalation 触发器：同意图 >= 2 次即转 operator。",
        "evidence": "end_user=end_u_8811; escalation_count=3; window_seconds=300",
        "risk_level": "high",
        "target_role": "customer",
    },
]


async def _run_dev_stub_dream(
    tenant_id: str,
    proposals_conn: Any,
    runs_conn: Any,
) -> None:
    """Dev-only stub that mimics a successful ``run_dream`` without the LLM.

    Opens its own ``dream_runs`` row (mirrors the 2-row pattern the real
    ``run_dream`` produces alongside the trigger-row), sleeps a few seconds
    so the admin-portal UI shows a visible ``running`` state, then emits
    three seed proposals via :func:`dream_agent.emit_proposal` and closes
    the row as ``completed``.  Token counts are fabricated — enough to
    render non-zero values in the UI without implying real LLM work.

    Only reachable when ``DREAM_DEV_STUB_ENABLED`` is true.  Production
    boots with the env var unset and this function is never called.
    """
    stub_run_id = dream_runs.start_run(runs_conn, tenant_id)
    try:
        await asyncio.sleep(DREAM_DEV_STUB_DELAY_SEC)
        emitted = 0
        for seed in _DREAM_DEV_STUB_SEEDS:
            dream_agent.emit_proposal(
                proposals_conn,
                tenant_id=tenant_id,
                category=seed["category"],
                title=seed["title"],
                description=seed["description"],
                suggestion=seed["suggestion"],
                evidence=seed["evidence"],
                risk_level=seed["risk_level"],
                target_role=seed["target_role"],
            )
            emitted += 1
        dream_runs.update_run(
            runs_conn, stub_run_id,
            tool_calls=emitted, proposals_emitted=emitted,
            tokens_in=123, tokens_out=456,
        )
        dream_runs.end_run(
            runs_conn, stub_run_id,
            status="completed", tokens_in=123, tokens_out=456,
        )
    except Exception as exc:  # noqa: BLE001 — always finalise the stub row
        try:
            dream_runs.end_run(
                runs_conn, stub_run_id,
                status="failed", error=f"{type(exc).__name__}: {exc}",
            )
        except Exception:
            logger.exception("dev stub end_run cleanup failed for %s", stub_run_id)
        raise


async def _spawn_dream_run_with_run_id(tenant_id: str, run_id: str) -> None:
    """Schedule the right dream entry for an already-opened ``dream_runs`` row.

    Routing (M3 T2S.8 mirrors ``dream_scheduler._dispatch``):
    * ``tenant_id == bootstrap.MASTER_TENANT_ID`` → ``run_platform_dream``
      (cross-tenant aggregate; does NOT open its own ``dream_runs`` row, so
      the pre-opened trigger-row IS the agent row → 1 row per trigger).
    * otherwise → per-tenant ``dream_agent.run_dream``, which opens its own
      ``dream_runs`` row internally (2 rows per trigger — the pre-opened
      trigger-row records the "requested" state, the run_dream-row the
      "observed" state; both visible via ``GET /api/dream/runs``).

    A future refactor may let ``run_dream`` accept a pre-opened ``run_id``
    — out of scope for T3B.6.

    The ``finally`` block records the REAL outcome (completed / failed)
    on the trigger-row so the UI doesn't show a misleading green row next
    to the actual failed agent row.

    Tests monkey-patch this function to a no-op so they can assert the
    trigger endpoint's HTTP behaviour without touching cc_pool.
    """
    from autoservice.cc_pool import get_pool
    from autoservice.memory_pool import MemoryPool
    from autoservice import bootstrap as _bootstrap

    pool = await get_pool()
    pp = _get_proposal_pipeline()
    proposals_conn = pp._conn
    runs_conn = _get_dream_runs_db()
    mempool = getattr(pp, "_memory_pool", None) or MemoryPool()

    # M3 T2S.8 routing: for the master tenant, dispatch to run_platform_dream
    # (cross-tenant aggregate dream) — mirrors dream_scheduler._dispatch logic.
    # Per-tenant run_dream requires llm_send + cc_pool capabilities that the
    # master tenant deliberately doesn't have.
    is_master = tenant_id == _bootstrap.MASTER_TENANT_ID

    async def _run_and_mark():
        """Wrap the chosen dream entry so the pre-opened trigger-row is finalised.

        Routing (post-T5S.14):
          1. ``DREAM_DEV_STUB=1`` → :func:`_run_dev_stub_dream` for ALL
             tenants (master + per-tenant).  Offline-dev fallback only.
          2. master tenant (``_master``) → ``run_platform_dream`` —
             real cross-tenant LLM tool-loop (T4S.4b).
          3. per-tenant → ``dream_agent.run_dream`` with ``llm_send=None``
             → CC pool's ``call_with_tools`` surface (T5S.14 / T3B.5).

        Row-count contract: exactly ONE ``dream_runs`` row per trigger.
        We open ``run_id`` above; the agent entry (master or per-tenant)
        reuses it via the ``run_id=`` kwarg instead of opening a second
        one.  The dev-stub deliberately opens its own row (it's a
        fixture, not a real run) so its behaviour matches DREAM_DEV_STUB
        users' expectations.
        """
        agent_status = "completed"
        agent_error: str | None = None
        try:
            if DREAM_DEV_STUB_ENABLED:
                # Offline-dev fallback — no LLM traffic, deterministic output.
                # Gates both master and per-tenant paths so CI without an
                # Anthropic key can still exercise the trigger endpoint +
                # Dream UI.  See DREAM_DEV_STUB_ENABLED docstring above.
                await _run_dev_stub_dream(tenant_id, proposals_conn, runs_conn)
            elif is_master:
                from autoservice import master_dream_agent as _master_dream
                await _master_dream.run_platform_dream(
                    tenant_id,
                    pool,
                    mempool,
                    proposals_conn,
                    runs_conn,
                    max_tool_turns=10,
                    run_id=run_id,
                )
            else:
                # Per-tenant default: run_dream acquires a dream-role CC
                # pool client and calls its call_with_tools surface
                # (T5S.14).  llm_send defaulted to None — previously raised
                # RuntimeError; now drives a real tool-loop.
                await dream_agent.run_dream(
                    tenant_id,
                    pool,
                    mempool,
                    proposals_conn,
                    runs_conn,
                    max_tool_turns=10,
                    run_id=run_id,
                )
        except Exception as exc:  # noqa: BLE001
            agent_status = "failed"
            agent_error = f"{type(exc).__name__}: {exc}"
            logger.exception("dream run failed for tenant=%s", tenant_id)
        finally:
            # Close the trigger-row with the REAL outcome (completed vs failed)
            # so the UI doesn't show a misleading green "completed" row next
            # to the actual failed agent-row.
            try:
                dream_runs.end_run(
                    runs_conn, run_id, status=agent_status, error=agent_error,
                )
            except Exception:
                logger.exception(
                    "dream_runs.end_run cleanup for trigger row %s failed", run_id,
                )

    asyncio.create_task(_run_and_mark())


@api_router.get("/dream/status")
async def dream_status(tenant_id: str) -> Any:
    """Return this tenant's current Dream scheduler status (M3 T4S.3b).

    Consumed by admin-portal's Dream status band (M3.5 D1 UI).  Exposes
    the ``should_trigger`` reason_code vocabulary so the UI can render
    idle / cool_down / running / never_active / scheduled / manual_off
    states without scraping logs.

    Query params:
        tenant_id: required, non-empty.

    Response::

        {
          "tenant_id": "<tid>",
          "running": bool,
          "reason_code": "<snake_case>",
          "last_run_summary": {
              "run_id": "<id>",
              "started_at": "<iso>",
              "ended_at": "<iso|null>",
              "status": "<running|completed|failed>",
              "proposals_emitted": int,
              "tool_calls": int,
          } | null,
          "next_eligible_at": "<iso|null>"
        }

    An unknown tenant / no-config returns reason_code='never_active' with
    200 OK — the UI treats it as "waiting for first dream tick".
    """
    from fastapi.responses import JSONResponse
    if not tenant_id or not tenant_id.strip():
        return JSONResponse(
            status_code=422, content={"error": "tenant_id required"},
        )

    tid = tenant_id.strip()

    # Pull last run summary (may be empty — return null gracefully)
    runs_conn = _get_dream_runs_db()
    last_runs = dream_runs.list_runs(runs_conn, tid, limit=1)
    last_run_summary = None
    if last_runs:
        r = last_runs[0]
        last_run_summary = {
            "run_id": r.get("id"),
            "started_at": r.get("started_at"),
            "ended_at": r.get("ended_at"),
            "status": r.get("status"),
            "proposals_emitted": r.get("proposals_emitted"),
            "tool_calls": r.get("tool_calls"),
        }

    # Compute reason_code via should_trigger — reuse scheduler's tenant config
    # reader + memory_pool to avoid duplicating config-parsing logic.
    from autoservice import dream_scheduler as _ds
    from autoservice.memory_pool import MemoryPool

    # Lightweight tenant_dream_cfg read (inlined — scheduler's reader is a
    # bound method; we only need the 'dream' sub-dict).
    tenant_dream_cfg: dict = {}
    try:
        from pathlib import Path
        import json as _json
        cfg_path = (
            Path(".autoservice/sandbox") / tid / "config.json"
        )
        if cfg_path.exists():
            with cfg_path.open(encoding="utf-8") as f:
                full_cfg = _json.load(f)
            tenant_dream_cfg = full_cfg.get("dream") or {}
    except Exception:  # noqa: BLE001
        tenant_dream_cfg = {}

    mempool = MemoryPool()
    try:
        _is_running, reason = _ds.should_trigger(
            tid, tenant_dream_cfg, mempool, runs_conn,
        )
    except Exception:  # noqa: BLE001
        # Defensive: any scheduler-side error → treat as never_active so UI
        # shows a sane default instead of a 500.
        reason = "never_active"
        _is_running = False

    # "running" is distinct from is_running-eligible — check the DB directly
    # for an in-flight row.
    running_now = False
    try:
        for r in dream_runs.list_runs(runs_conn, tid, limit=5):
            if r.get("status") == "running":
                running_now = True
                break
    except Exception:  # noqa: BLE001
        pass

    return {
        "tenant_id": tid,
        "running": running_now,
        "reason_code": reason,
        "last_run_summary": last_run_summary,
        "next_eligible_at": None,  # reserved for M3.5 — compute from cool_down window
    }


@api_router.get("/dream/runs")
async def dream_runs_list(tenant_id: str, limit: int = 20) -> dict[str, Any]:
    """Return this tenant's Dream run history, newest first (spec §2.6).

    Query params:
        tenant_id: required, non-empty — the tenant to list runs for.
        limit:     optional, clamped to [1, 100] (default 20).  Values
                   outside the range are clamped rather than rejected so
                   the admin-portal can safely pass ``limit=-1`` or a
                   paginated slider's value without a 400.

    Response::

        {"tenant_id": "<tid>", "runs": [DreamRun, ...]}

    Each ``DreamRun`` carries the 10 documented fields from the
    ``dream_runs`` schema: ``id``, ``tenant_id``, ``started_at``,
    ``ended_at``, ``status``, ``tool_calls``, ``tokens_in``,
    ``tokens_out``, ``proposals_emitted``, ``error``.  Missing columns
    surface as ``None`` (e.g. ``ended_at`` on an in-flight run).

    An unknown tenant returns ``{runs: [], tenant_id}`` with 200 OK —
    the endpoint cannot distinguish "tenant has never run dream" from
    "tenant doesn't exist", and the frontend treats both identically.
    """
    from fastapi.responses import JSONResponse

    if not tenant_id or not tenant_id.strip():
        return JSONResponse(
            status_code=422,
            content={"error": "tenant_id is required"},
        )

    # Clamp the limit — spec §2.6 calls for ``limit: int = 20`` bounded to
    # [1, 100].  A non-positive ``limit`` (or one above 100) is silently
    # clamped rather than rejected; the contract documents this.  We use
    # ``int(limit)`` directly (not ``limit or 20``) because ``0`` is a
    # valid caller input that must clamp to 1, not fall through to the
    # default.
    try:
        limit_val = int(limit)
    except (TypeError, ValueError):
        limit_val = 20
    clamped = max(1, min(limit_val, 100))

    runs_conn = _get_dream_runs_db()
    rows = dream_runs.list_runs(runs_conn, tenant_id.strip(), limit=clamped)

    # Project to the documented 10-field shape so the response doesn't
    # accidentally leak schema columns added in a later migration.
    projected = [
        {
            "id": r.get("id"),
            "tenant_id": r.get("tenant_id"),
            "started_at": r.get("started_at"),
            "ended_at": r.get("ended_at"),
            "status": r.get("status"),
            "tool_calls": r.get("tool_calls"),
            "tokens_in": r.get("tokens_in"),
            "tokens_out": r.get("tokens_out"),
            "proposals_emitted": r.get("proposals_emitted"),
            "error": r.get("error"),
        }
        for r in rows
    ]

    return {"tenant_id": tenant_id.strip(), "runs": projected}


# ---------------------------------------------------------------------------
# Canary
# ---------------------------------------------------------------------------

@api_router.get("/canary/status")
async def canary_status() -> dict[str, Any]:
    """Return canary router status + monitor check."""
    router, monitor = _get_canary()
    status = router.status()
    check = monitor.check()
    return {
        "stage": status["percentage"],
        "percentage": status["percentage"],
        "can_advance": status.get("can_advance", False),
        "history": status.get("history", []),
        "monitor": check,
    }


# ---------------------------------------------------------------------------
# Dream Engine config dialog (T6E.9)
# ---------------------------------------------------------------------------
_dream_config_session: Any = None


def _get_dream_session():
    global _dream_config_session
    if _dream_config_session is None:
        from autoservice.dream_config_dialog import DreamConfigSession
        _dream_config_session = DreamConfigSession()
    return _dream_config_session


def _dream_sandbox_config_path(tenant_id: str) -> Path:
    """Resolve the on-disk sandbox config.json path for a tenant (T1B.6)."""
    return Path(f".autoservice/sandbox/{tenant_id}/config.json")


def _persist_dream_config(tenant_id: str, params: dict[str, Any]) -> bool:
    """Sync confirmed Dream Engine params to sandbox ``config.json`` (T1B.6).

    One-way write — in-memory ``DreamConfigSession`` remains the runtime source
    of truth.  Only the 4 confirmed keys (``trigger``, ``coverage``,
    ``risk_threshold``, ``canary``) are persisted under the ``"dream"`` key.

    Gracefully skips (returns ``False``) when the tenant sandbox directory
    does not yet exist — matches how other sandbox-dependent endpoints treat
    missing tenants.  Returns ``True`` on successful write.

    Fixes bug #9 (see docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §3.5).
    """
    path = _dream_sandbox_config_path(tenant_id)
    if not path.parent.exists():
        logger.info(
            "dream config sync skipped — sandbox dir missing: tenant=%s", tenant_id
        )
        return False

    try:
        if path.exists():
            cfg = json.loads(path.read_text(encoding="utf-8"))
        else:
            cfg = {"tenant_id": tenant_id}
    except Exception as exc:
        logger.warning(
            "dream config sync failed to read existing config: tenant=%s err=%s",
            tenant_id,
            exc,
        )
        return False

    if not isinstance(cfg, dict):
        logger.warning(
            "dream config sync aborted — config.json is not a dict: tenant=%s",
            tenant_id,
        )
        return False

    cfg.setdefault("dream", {})
    cfg["dream"] = {
        "trigger": params.get("trigger"),
        "coverage": params.get("coverage"),
        "risk_threshold": params.get("risk_threshold"),
        "canary": params.get("canary"),
    }
    try:
        path.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning(
            "dream config sync failed to write config: tenant=%s err=%s",
            tenant_id,
            exc,
        )
        return False
    logger.info("dream config synced: tenant=%s", tenant_id)
    return True


# ---------------------------------------------------------------------------
# Management Chat — master-side admin conversational interface (T7B.6)
# ---------------------------------------------------------------------------
#
# Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §2.7
# ("A 的 ManagementChat 接入 ``_master``").
#
# Wire contract:
#   POST /api/management/chat  {message: str}  -> {reply: str}
#   errors: 422 (bad body), 503 (pool unavailable)
#
# The M1 slash-command / Dream-Engine-config dispatcher is preserved as
# ``/api/management/chat-legacy`` (below) for one milestone; it will be
# removed once the _master admin tool set lands (M3+).
#
# Design-note refs (eval-doc-019):
#   * Uses ``cc_pool.acquire(role="customer", tenant_id="_master")`` as the
#     spec mandates. The ``tenant_id`` is cosmetic today on the customer
#     path (see cc_pool.py:440-444 — customer role ignores tenant_id and
#     goes through ``super().acquire()``); passing it here pins the contract
#     for the forthcoming soul-injection PR.
#   * Uses ``async with pool.acquire(...) as instance`` + ``instance.client
#     .query / .receive_response`` (cc_pool.py:359-366 pattern) rather than
#     ``pool.query()`` so the tenant_id kwarg stays visible at the call
#     site for the mock-based test assertion (test #4).
#   * NO stub-LLM fallback; the regression guard test #6 greps for this.


@api_router.post("/management/chat")
async def management_chat(body: dict = Body(...)) -> dict[str, Any]:
    """M2 — route management chat to ``_master`` customer agent via cc_pool.

    Spec §2.7: the platform admin A talks to the ``_master`` tenant's
    customer agent. Admin tool set (``list_tenants``, ``read_proposals``,
    ``approve_proposal`` …) is deferred to M3 per eval-doc-019; M2 just
    routes text through on plain customer soul.

    Request body::

        {"message": "<str>"}

    Responses:
        * 200  ``{"reply": "<text>"}``
        * 422  ``{"error": "message required"}`` for missing/empty/non-str
        * 503  ``{"error": "cc_pool unavailable (POOL_MODE disabled?)"}``

    M2 design invariant guarded by tests/api/test_management_chat.py::
    test_management_chat_regression_no_stub_llm — this handler must not
    contain legacy dialog logic.  Slash-command and dream-config dialog
    are handled by the companion ``/api/management/chat-legacy`` endpoint
    until the unified dialog migration lands in M3.5 (see
    docs/plans/m3.5-mini-sprint.md D3 · im-block renderer work).
    """
    message = body.get("message") if isinstance(body, dict) else None
    if not isinstance(message, str) or not message.strip():
        return JSONResponse(
            status_code=422,
            content={"error": "message required"},
        )

    from autoservice.cc_pool import get_pool

    pool = await get_pool()
    if pool is None:
        return JSONResponse(
            status_code=503,
            content={"error": "cc_pool unavailable (POOL_MODE disabled?)"},
        )

    # Spec §2.7 — ManagementChat routes to _master.
    reply_parts: list[str] = []
    async with pool.acquire(role="customer", tenant_id="_master") as instance:
        await instance.client.query(message)
        async for msg in instance.client.receive_response():
            content = getattr(msg, "content", None)
            if isinstance(content, str):
                reply_parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    text = getattr(block, "text", None)
                    if isinstance(text, str):
                        reply_parts.append(text)

    return {"reply": "".join(reply_parts)}


@api_router.post("/management/chat-legacy")
async def management_chat_legacy(
    message: str = "", tenant_id: str = "default",
) -> dict[str, Any]:
    """M1 slash-command / Dream-Engine-config dispatcher — kept one milestone.

    The M2 ``/api/management/chat`` endpoint replaces this handler with real
    ``_master`` routing (spec §2.7).  The M1 behaviour (``/rules``,
    ``/status``, ``/approve``, ``/reject``, ``/rollback``, ``@Dream
    Engine``, Dream-Engine config dialog) is preserved here verbatim under
    the ``-legacy`` URL so any pre-M2 integration that depends on the
    slash-command UX has a one-milestone migration window. Will be
    deleted at M3 once the ``_master`` admin tool set lands.
    """
    text = message.strip()
    if not text:
        return {"role": "system", "content": "请输入命令或消息。支持: /rules, /status, /approve, /reject, /rollback, @Dream Engine"}

    # Dream Engine config dialog — check if session is active first (T6E.9)
    dream_session = _get_dream_session()
    if dream_session.is_active():
        response, done = dream_session.process_input(text)
        # T1B.6 — on final confirmation (transition to DONE), sync the 4
        # confirmed params to sandbox config.json.  Cancel path also returns
        # done=True but _reset()s to IDLE, so checking DONE filters out cancel.
        if done:
            from autoservice.dream_config_dialog import (
                DreamConfigStep,
                on_config_confirmed,
            )
            if dream_session.step == DreamConfigStep.DONE:
                _persist_dream_config(tenant_id, dream_session.get_config())
                # T4B.3 — let the DreamScheduler re-read this tenant's
                # config on its next tick. Safe no-op when no scheduler
                # is running (tests, CLI).
                on_config_confirmed(tenant_id)
        return {"role": "dream_engine", "content": response}

    # @Dream Engine or /dream-config — start config dialog (T6E.9)
    from autoservice.dream_config_dialog import is_dream_config_trigger
    if is_dream_config_trigger(text):
        prompt = dream_session.start()
        return {"role": "dream_engine", "content": prompt}

    # /rules — show current rules
    if text.startswith("/rules"):
        try:
            from autoservice.rules import handle_rules_command
            args = text[len("/rules"):].strip().split() or ["show"]
            result = handle_rules_command(args)
            return {"role": "dream_engine", "content": f"📋 规则配置:\n{result}"}
        except Exception as exc:
            return {"role": "dream_engine", "content": f"规则查询失败: {exc}"}

    # /status — system status overview
    if text.startswith("/status"):
        try:
            from autoservice.sla_aggregator import MetricType, WindowSize
            agg = _get_sla()
            lines = ["📊 系统状态:"]
            for metric in MetricType:
                p = agg.get_percentiles(metric, WindowSize.FIVE_MIN)
                val = f"P50={p.p50:.1f}" if p.p50 is not None else "无数据"
                lines.append(f"  · {metric.value}: {val} (n={p.count})")
            # Canary status
            router, monitor = _get_canary()
            status = router.status()
            lines.append(f"  · 灰度: {status['percentage']}%")
            check = monitor.check()
            lines.append(f"  · 监控: {check['status']}")
            return {"role": "dream_engine", "content": "\n".join(lines)}
        except Exception as exc:
            return {"role": "dream_engine", "content": f"状态查询失败: {exc}"}

    # /approve #N — approve a proposal and activate canary
    if text.startswith("/approve"):
        return _handle_approve_command(text)

    # /reject #N — reject a proposal
    if text.startswith("/reject"):
        return _handle_reject_command(text)

    # /rollback — rollback canary
    if text.startswith("/rollback"):
        try:
            router, _ = _get_canary()
            router.rollback()
            return {"role": "dream_engine", "content": f"⏪ 已回滚灰度发布，当前阶段: {router.status()['percentage']}%"}
        except Exception as exc:
            return {"role": "dream_engine", "content": f"回滚失败: {exc}"}

    # Default — Dream Engine general response
    return {
        "role": "dream_engine",
        "content": f"收到。我是 Dream Engine，负责夜间学习和优化。\n\n"
        f"可用命令:\n"
        f"  /rules — 查看/配置规则\n"
        f"  /status — 系统状态概览\n"
        f"  /approve #N — 批准提案\n"
        f"  /reject #N — 拒绝提案\n"
        f"  /rollback — 回滚灰度发布\n\n"
        f"您说: \"{text}\"\n我会记录这条反馈用于下次优化。"
    }


# ---------------------------------------------------------------------------
# Admin Chat (tenant-side `_local_admin` conversation — T6F.6)
# ---------------------------------------------------------------------------

@api_router.post("/admin/chat")
async def admin_chat(body: dict = Body(...)) -> dict[str, Any]:
    """M2 stub — tenant-side ChatTab → `_local_admin` agent (spec §4.4).

    Accepts a JSON body ``{"message": <str>}`` and returns ``{"reply": <str>}``.

    **M2 scope — stub**: full routing to the fork's ``_local_admin`` agent
    via ``run_dream`` is deferred (tracked by T7B.6 `/api/management/chat →
    _master routing` and the tenant-side symmetric task). The stub preserves
    the wire contract so the frontend (batch-11) can be developed and tested
    against a stable endpoint; the real routing swap is backend-only and
    won't touch ``ChatTab.tsx``.

    **Auth**: no ``Depends(auth.require_tenant_access)`` yet — the target
    tenant id (`_local_admin` for tenant mode, `_master` for master mode)
    isn't surfaced in the request body/path, and the spec §4.4 semantics
    pin it at the server side. Adding a dep here would 401 every caller and
    break the M2 smoke flow. Protection lands with the real routing batch.

    See: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §4.4
    """
    message = (body.get("message") if isinstance(body, dict) else None) or ""
    text = message.strip() if isinstance(message, str) else ""
    if not text:
        return {"reply": "(empty message — nothing to send)"}
    return {
        "reply": (
            f"(stub) Received: {text!r}. "
            f"_local_admin agent integration pending (T7B.6 / run_dream wire-up)."
        )
    }


@api_router.post("/canary/advance")
async def canary_advance(force: bool = False) -> dict[str, Any]:
    """Advance canary to next stage.

    Query params:
        force: skip observation period check (dev/debug only)

    Returns 423 Locked if observation period has not elapsed (unless force=true).
    """
    from fastapi.responses import JSONResponse
    router, _ = _get_canary()
    if force:
        import time
        router._stage_started_at = 0  # bypass observation window
    if not router.can_advance():
        if router.current_stage == CanaryStage.STAGE_100:
            return JSONResponse(
                status_code=423,
                content={"error": "Already at STAGE_100, cannot advance further"},
            )
        import time
        elapsed_s = time.time() - router._stage_started_at
        remaining_s = router._observation_hours * 3600 - elapsed_s
        remaining_h = remaining_s / 3600
        return JSONResponse(
            status_code=423,
            content={
                "error": f"Observation period not complete ({remaining_h:.1f}h remaining)",
                "remaining_hours": round(remaining_h, 1),
            },
        )
    new_stage = router.advance()
    status = router.status()
    status["message"] = f"Advanced to {new_stage.value} ({router.percentage}%)"
    return status


@api_router.post("/canary/rollback")
async def canary_rollback() -> dict[str, Any]:
    """Rollback canary."""
    router, _ = _get_canary()
    router.rollback()
    return router.status()


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------

@api_router.post("/compliance/check")
async def compliance_check(tenant_id: str = "default") -> dict[str, Any]:
    """Run compliance scan on tenant config."""
    import json as _json
    from pathlib import Path as _Path
    from autoservice.compliance.compliance import ComplianceEngine

    # Load real tenant config from activation directory
    config_path = _Path(f".autoservice/tenants/{tenant_id}/config.json")
    if not config_path.exists():
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=404,
            content={
                "error": f"Tenant '{tenant_id}' not found. Run /api/onboard/activate first.",
                "tenant_id": tenant_id,
            },
        )

    try:
        raw_config = _json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to read tenant config: {exc}", "tenant_id": tenant_id},
        )

    # Build nested config that compliance rules can resolve via dot-notation.
    # Rules check "tenant.<field>" and "soul.<field>" paths.
    config: dict[str, Any] = {}
    config["tenant"] = {k: v for k, v in raw_config.items() if k != "soul"}
    if "soul" in raw_config:
        config["soul"] = raw_config["soul"]
    else:
        # Try loading soul config from a separate soul.json if present
        soul_path = config_path.parent / "soul.json"
        if soul_path.exists():
            try:
                config["soul"] = _json.loads(soul_path.read_text(encoding="utf-8"))
            except Exception:
                config["soul"] = {}

    engine = ComplianceEngine()
    report = engine.scan(tenant_id, config)
    return {
        "tenant_id": report.tenant_id,
        "risk_level": report.risk_level.value,
        "total_rules": report.total_rules,
        "passed": report.passed,
        "failed": report.failed,
        "pass_rate": report.pass_rate,
        "blocking": {
            "sandbox_blocked": report.blocking.sandbox_blocked,
            "production_blocked": report.blocking.production_blocked,
        },
        "results": [
            {
                "rule_id": r.rule_id,
                "name": r.name_zh,
                "severity": r.severity,
                "passed": r.passed,
                "field": r.field,
                "remediation_doc": r.remediation_doc,
            }
            for r in report.results
        ],
    }


# ---------------------------------------------------------------------------
# Rehearsal (virtual customer)
# ---------------------------------------------------------------------------

def _get_kb_path(tenant_id: str) -> str:
    """Resolve knowledge-base SQLite path for a tenant."""
    from pathlib import Path
    # Tenant-specific KB takes priority; fall back to shared KB
    tenant_kb = Path(f".autoservice/tenants/{tenant_id}/kb/kb.db")
    if tenant_kb.exists():
        return str(tenant_kb)
    shared_kb = Path(".autoservice/database/knowledge_base/kb.db")
    return str(shared_kb)


def _get_llm_client():
    """Create an async LLM client wrapper around the Anthropic SDK.

    Returns None if the anthropic SDK is not installed or API key is missing.
    """
    try:
        import anthropic

        class _AsyncLLMClient:
            """Thin async wrapper matching the ``generate()`` protocol
            expected by ``sim_customer``."""

            def __init__(self):
                self._client = anthropic.AsyncAnthropic()

            async def generate(self, prompt: str) -> str:
                message = await self._client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=2048,
                    messages=[{"role": "user", "content": prompt}],
                )
                return message.content[0].text

        return _AsyncLLMClient()
    except Exception:
        return None


_VALID_REVIEW_STATUSES = {"pending", "approved", "flagged"}


def _rehearsal_path(tenant_id: str) -> Path:
    """Resolve the on-disk rehearsal.json path for a tenant sandbox."""
    return Path(f".autoservice/sandbox/{tenant_id}/rehearsal.json")


def _persist_rehearsal(tenant_id: str, demo_mode: bool, dialogs: list[dict[str, Any]]) -> None:
    """Write rehearsal.json to the tenant sandbox directory.

    Every dialog is initialized with ``review_status='pending'``,
    ``review_note=''`` and ``reviewed_at=None`` so the frontend can
    restore review state after a reload (fixes bug #4).
    """
    path = _rehearsal_path(tenant_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "demo_mode": demo_mode,
        "dialogs": [
            {
                **d,
                "review_status": "pending",
                "review_note": "",
                "reviewed_at": None,
            }
            for d in dialogs
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@api_router.post("/rehearsal/generate")
async def rehearsal_generate(tenant_id: str = "default") -> dict[str, Any]:
    """Generate virtual customer rehearsal dialogs.

    Attempts real LLM-powered generation via ``sim_customer``.  When the LLM
    is unavailable (missing SDK, no API key, network error …) the endpoint
    falls back to >=10 hardcoded demo dialogs, each tagged with
    ``is_demo: true``.

    T1B.3: every successful response is also persisted to
    ``.autoservice/sandbox/<tenant_id>/rehearsal.json`` with initial
    ``review_status='pending'`` so refreshing the frontend doesn't lose
    review progress (fixes bug #4).
    """
    try:
        from autoservice.sim_customer import generate_sim_dialogs

        kb_path = _get_kb_path(tenant_id)
        llm_client = _get_llm_client()
        if llm_client is None:
            raise RuntimeError("LLM client unavailable — anthropic SDK missing or unconfigured")

        dialogs = await generate_sim_dialogs(
            tenant_id,
            kb_path=kb_path,
            llm_client=llm_client,
        )
        dialog_list = [
            {
                "id": d.id if hasattr(d, "id") else f"dialog-{i:03d}",
                "scenario": d.scenario if hasattr(d, "scenario") else {},
                "persona": d.persona if hasattr(d, "persona") else {},
                "turns": d.turns if hasattr(d, "turns") else [],
                "language": d.language if hasattr(d, "language") else "zh",
                "review_status": d.review_status if hasattr(d, "review_status") else "pending",
                "is_demo": False,
            }
            for i, d in enumerate(dialogs)
        ]
        _persist_rehearsal(tenant_id, demo_mode=False, dialogs=dialog_list)
        return {"demo_mode": False, "dialogs": dialog_list}
    except Exception as exc:
        logger.warning("sim_customer generation failed, using demo fallback: %s", exc)
        # Fallback: >=10 structured demo dialogs covering major business scenarios
        _DEMO_DIALOGS = [
            ("通用问候", "general", "普通客户",
             "你好，在吗？", "您好！请问有什么可以帮到您？"),
            ("产品咨询", "product_inquiry", "价格敏感客户",
             "这个产品多少钱？", "目前的价格方案如下..."),
            ("投诉处理", "complaint", "愤怒客户",
             "我要投诉！服务太差了！", "非常抱歉给您带来不好的体验，我来帮您处理..."),
            ("购买意向", "purchase_intent", "新客户",
             "怎么购买？流程是什么？", "您可以通过以下方式购买..."),
            ("语言障碍", "language_barrier", "外语客户",
             "Can you speak English?", "Sure! How can I help you today?"),
            ("退款申请", "refund", "老客户",
             "我要退款，订单号是12345", "好的，请稍等，我帮您查询订单12345的退款流程..."),
            ("售后服务", "after_sales", "VIP客户",
             "产品出了问题，怎么维修？", "请您提供产品序列号，我们将为您安排维修服务..."),
            ("配送查询", "delivery_inquiry", "焦急客户",
             "我的快递到哪了？已经等了三天了", "请提供您的订单号，我帮您查询物流状态..."),
            ("账户问题", "account_issue", "技术小白",
             "我登不上账号了，密码忘记了", '请点击登录页的"忘记密码"，我引导您重置...'),
            ("功能咨询", "feature_inquiry", "企业客户",
             "你们支持批量导入吗？有API吗？", "支持的，我们提供批量导入和完整的API接口..."),
            ("优惠活动", "promotion", "促销敏感客户",
             "现在有什么优惠活动吗？", "目前我们有以下优惠活动正在进行中..."),
            ("多轮对话", "multi_turn", "犹豫客户",
             "我再考虑一下吧", "没问题，如果您有任何疑问随时可以联系我们..."),
        ]
        dialog_list = [
            {
                "id": f"dialog-{i:03d}",
                "scenario": {"id": f"scenario-{i}", "name_zh": name, "intent": intent},
                "persona": {"id": f"persona-{i}", "name_zh": persona, "traits": []},
                "turns": [
                    {"role": "customer", "content": q, "metadata": {}},
                    {"role": "agent", "content": a, "metadata": {}},
                ],
                "language": "zh",
                "review_status": "pending",
                "is_demo": True,
            }
            for i, (name, intent, persona, q, a) in enumerate(_DEMO_DIALOGS)
        ]
        _persist_rehearsal(tenant_id, demo_mode=True, dialogs=dialog_list)
        return {"demo_mode": True, "dialogs": dialog_list}


@api_router.post("/rehearsal/review")
async def rehearsal_review(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Update a single dialog's review status in rehearsal.json.

    Request body::

        {
            "tenant_id": "<tid>",
            "dialog_id": "<did>",
            "review_status": "pending|approved|flagged",
            "review_note": "<optional text>"
        }

    Response on success::

        {"status": "ok", "dialog_id": "<did>", "review_status": "<status>"}

    Errors:
        - 400 when review_status is not one of {pending, approved, flagged}
        - 404 when the tenant has no rehearsal.json yet, or dialog_id is unknown
    """
    from fastapi.responses import JSONResponse

    tenant_id = (payload.get("tenant_id") or "").strip()
    dialog_id = (payload.get("dialog_id") or "").strip()
    review_status = (payload.get("review_status") or "").strip()
    review_note = payload.get("review_note", "") or ""

    if not tenant_id or not dialog_id:
        return JSONResponse(
            status_code=400,
            content={"error": "tenant_id and dialog_id are required"},
        )

    if review_status not in _VALID_REVIEW_STATUSES:
        return JSONResponse(
            status_code=400,
            content={
                "error": f"Invalid review_status {review_status!r}. "
                f"Must be one of: {sorted(_VALID_REVIEW_STATUSES)}"
            },
        )

    path = _rehearsal_path(tenant_id)
    if not path.exists():
        return JSONResponse(
            status_code=404,
            content={
                "error": f"No rehearsal.json found for tenant {tenant_id!r}. "
                f"Call /api/rehearsal/generate first."
            },
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to read rehearsal.json: {exc}"},
        )

    dialogs = data.get("dialogs", [])
    target = next((d for d in dialogs if d.get("id") == dialog_id), None)
    if target is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": f"dialog_id {dialog_id!r} not found in tenant "
                f"{tenant_id!r} rehearsal.json"
            },
        )

    target["review_status"] = review_status
    target["review_note"] = review_note
    target["reviewed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "status": "ok",
        "dialog_id": dialog_id,
        "review_status": review_status,
    }


# ---------------------------------------------------------------------------
# Publish gate + sandbox freeze/archive (T1B.7)
# ---------------------------------------------------------------------------
#
# `/api/onboard/publish`  — fires the Step 4 "一键对外" button
# `/api/onboard/unfreeze` — debug/misfire recovery: restore an archived
#                           sandbox to its pre-publish state.
#
# Business logic lives in autoservice.publish; this layer only translates
# between HTTP + JSON and the module's Python API.
#
# Spec refs: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §6 / §7


@api_router.post("/onboard/publish")
async def onboard_publish(payload: dict[str, Any] = Body(...)) -> Any:
    """Publish a sandbox — run gate, build tarball, freeze + archive.

    Request body::

        {
            "tenant_id": "<tid>",                 # required
            "override_compliance_critical": bool, # optional
            "signer": "<email>"                   # required when override=true
        }

    Returns (200)::

        {
          "status": "published",
          "tenant_id": "<tid>",
          "artifact": ".autoservice/published/tenant_<tid>_publish_<ts>.tar.gz",
          "artifact_sha256": "<hex>",
          "runbook": ".autoservice/published/<tid>_PUBLISH_RUNBOOK.md",
          "record":  ".autoservice/published/<tid>.json",
          "archived_to": ".autoservice/archived/<tid>_<ts>",
          "gate": { ... GateResult dump ... }
        }

    Errors:
        - 400 — missing ``tenant_id``, or ``override=true`` without ``signer``
        - 404 — sandbox dir missing for tenant
        - 409 — gate blocked (no valid override); body contains gate detail
    """
    from fastapi.responses import JSONResponse
    from autoservice import publish as publish_mod

    tenant_id = (payload.get("tenant_id") or "").strip()
    override = bool(payload.get("override_compliance_critical") or False)
    signer = (payload.get("signer") or "").strip() or None

    if not tenant_id:
        return JSONResponse(
            status_code=400,
            content={"error": "tenant_id is required"},
        )
    if override and not signer:
        return JSONResponse(
            status_code=400,
            content={
                "error": "override_compliance_critical=true requires signer",
            },
        )

    # Select ForkCreator based on config.local.yaml.  Returns None when the
    # admin has not opted in or gh is unavailable — publish() then falls
    # back to its default LocalTarballForkCreator (M1 manual-runbook path).
    fork_creator = publish_mod.select_fork_creator_from_config(
        _PUBLISH_CONFIG_PATH
    )

    try:
        result = publish_mod.publish(
            tenant_id,
            override=override,
            signer=signer,
            fork_creator=fork_creator,
        )
    except FileNotFoundError as exc:
        return JSONResponse(
            status_code=404,
            content={"error": str(exc), "tenant_id": tenant_id},
        )

    if result.get("status") == "blocked":
        # Gate failed — 409 so the UI can show blocking_reasons to the user.
        return JSONResponse(
            status_code=409,
            content={
                "error": "publish blocked by gate",
                "tenant_id": tenant_id,
                **result,
            },
        )

    return result


@api_router.post("/onboard/unfreeze")
async def onboard_unfreeze(payload: dict[str, Any] = Body(...)) -> Any:
    """Move an archived sandbox back to ``.autoservice/sandbox/<tid>/``.

    For debug / misfire recovery. Request body::

        {"tenant_id": "<tid>", "reason": "<non-empty text>"}

    Errors:
        - 400 — missing tenant_id or reason
        - 404 — no archive found, or live sandbox already occupies the slot
    """
    from fastapi.responses import JSONResponse
    from autoservice import publish as publish_mod

    tenant_id = (payload.get("tenant_id") or "").strip()
    reason = (payload.get("reason") or "").strip()

    if not tenant_id or not reason:
        return JSONResponse(
            status_code=400,
            content={"error": "tenant_id and reason are required"},
        )

    try:
        return publish_mod.unfreeze(tenant_id, reason)
    except FileNotFoundError as exc:
        return JSONResponse(
            status_code=404,
            content={"error": str(exc), "tenant_id": tenant_id},
        )
    except FileExistsError as exc:
        return JSONResponse(
            status_code=409,
            content={"error": str(exc), "tenant_id": tenant_id},
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": str(exc), "tenant_id": tenant_id},
        )


# ---------------------------------------------------------------------------
# Magic-link auth endpoints (T5B.2 / T5B.3 / T5B.4)
# ---------------------------------------------------------------------------
#
# Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §5.
#
# Flow:
#   1. Admin hits POST /api/auth/request-login with their email.
#   2. If the email is on config.local.yaml.auth.admin_emails, a short-TTL
#      login token is persisted and either SMTP-sent or written to the dev
#      log (when SMTP host is empty). The 200 response is identical either
#      way — anti-enumeration (spec §5.2).
#   3. Admin clicks the link, which hits GET /api/auth/verify?token=…&redirect=…
#      The token is burned atomically; a 30-day session cookie is minted and
#      the browser is 302'd to the redirect target.
#   4. POST /api/auth/logout revokes the session and clears the cookie.
#
# CON-08 (m2-task-hints.yaml risks) — magic-link HTTP-sniffing is accepted in
# dev; the cookie `Secure` flag is conditional on the request being HTTPS.
# Production runbook must front this with HTTPS.

# Cookie name for admin sessions.  Spec §5.2 uses "adm_s"; we pick the more
# readable "auth_session" — T5B.5 / T6F.2 reconciliation will pick the final
# name when the frontend AuthGate lands.
AUTH_SESSION_COOKIE = "auth_session"

# Path for dev-mode magic link log (spec §5.6). One JSONL line per send.
_DEV_MAIL_LOG = Path(".autoservice") / "logs" / "auth-devmail.jsonl"

# Dev auto-login gate (spec docs/superpowers/specs/2026-04-21-dev-auto-login-design.md).
# Read ONCE at import — changing AUTH_DEV_MODE at runtime requires a process
# restart (tests monkeypatch this attribute directly). Production images must
# never set this variable.
DEV_MODE_ENABLED = os.environ.get("AUTH_DEV_MODE") == "1"


_auth_db_conn = None


def _get_auth_db():
    """Return the shared auth SQLite connection (lazy singleton).

    Mirrors :func:`_get_dream_runs_db`.  The DB lives under
    ``.autoservice/database/auth.db`` by default (see
    :func:`autoservice.auth.open_connection`).
    """
    global _auth_db_conn
    if _auth_db_conn is None:
        _auth_db_conn = auth.open_connection()
    return _auth_db_conn


def _reset_auth_db_for_tests(conn=None):
    """Test-only hook: inject an in-memory sqlite3 connection.

    Passing ``conn=None`` clears the cache so the next call re-opens from
    disk.  Tests pass a prepared in-memory connection (schema applied via
    :func:`autoservice.auth.apply_schema`) so they never hit the on-disk DB.
    """
    global _auth_db_conn
    _auth_db_conn = conn


def _load_admin_emails() -> list[str]:
    """Read the ``auth.admin_emails`` allowlist from config.local.yaml.

    Returns an empty list when the file or field is missing.  Case is
    normalised to lowercase for membership checks.

    Returns a fresh list per call — cheap (small YAML) and keeps the
    allowlist hot-reloadable without needing a reset hook for tests.
    """
    try:
        from autoservice import bootstrap
        cfg = bootstrap._load_local_config()
    except Exception:
        return []

    auth_cfg = cfg.get("auth") or {}
    emails = auth_cfg.get("admin_emails") or []
    if not isinstance(emails, list):
        return []
    return [str(e).strip().lower() for e in emails if e]


def _smtp_host() -> str:
    """Return the configured SMTP host (empty string if unset → dev log mode)."""
    try:
        from autoservice import bootstrap
        cfg = bootstrap._load_local_config()
    except Exception:
        return ""
    auth_cfg = cfg.get("auth") or {}
    smtp_cfg = auth_cfg.get("smtp") or {}
    host = smtp_cfg.get("host") or ""
    return str(host).strip()


def _load_dev_personas() -> list[str]:
    """Read ``auth.dev.personas`` from config.local.yaml.

    Returns ``["admin@dev.local"]`` when the file, the section, or the list is
    missing so the frontend combobox always has at least one suggestion.
    """
    try:
        from autoservice import bootstrap
        cfg = bootstrap._load_local_config()
    except Exception:
        return ["admin@dev.local"]

    dev_cfg = ((cfg.get("auth") or {}).get("dev") or {})
    personas = dev_cfg.get("personas")
    if not isinstance(personas, list) or not personas:
        return ["admin@dev.local"]
    return [str(p).strip() for p in personas if str(p).strip()]


def _scan_dev_tenants() -> list[str]:
    """Enumerate tenants for the dev-login dropdown.

    Always starts with ``_master`` (the tier-0 built-in, not a plugin
    directory). Then scans ``plugins/*/config.json`` and collects each
    plugin's ``tenant_id`` (falling back to the directory name when
    ``config.json`` is absent / unreadable / missing the field).

    ``_example`` is filtered out unless ``auth.dev.tenant_include_examples``
    is truthy in config.local.yaml.
    """
    try:
        from autoservice import bootstrap
        cfg = bootstrap._load_local_config()
    except Exception:
        cfg = {}
    dev_cfg = ((cfg.get("auth") or {}).get("dev") or {})
    include_examples = bool(dev_cfg.get("tenant_include_examples"))

    tenants: list[str] = ["_master"]
    plugins_dir = Path("plugins")
    if plugins_dir.is_dir():
        for child in sorted(plugins_dir.iterdir()):
            if not child.is_dir():
                continue
            cfg_path = child / "config.json"
            tid: str | None = None
            if cfg_path.is_file():
                try:
                    data = json.loads(cfg_path.read_text(encoding="utf-8"))
                    raw = data.get("tenant_id")
                    if isinstance(raw, str) and raw.strip():
                        tid = raw.strip()
                except (json.JSONDecodeError, OSError):
                    tid = None
            if tid is None:
                tid = child.name
            if tid == "_example" and not include_examples:
                continue
            if tid not in tenants:
                tenants.append(tid)
    return tenants


def _dev_log_magic_link(
    email: str,
    tenant_id: str | None,
    token: str,
    link: str,
) -> None:
    """Persist a magic link to the dev log + emit a WARNING-level log record.

    Writes one JSONL line to ``.autoservice/logs/auth-devmail.jsonl`` (spec
    §5.6).  Operators grep this file during local dev; in prod SMTP is
    configured so this path is never exercised.
    """
    _DEV_MAIL_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "email": email,
        "tenant_id": tenant_id,
        "token": token,
        "link": link,
    }
    with _DEV_MAIL_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # Loud banner so dev-mode operators notice the link in the console.
    logger.warning(
        "[dev-mail] Magic link for %s (tenant=%s): %s",
        email, tenant_id or "_master", link,
    )


def _build_magic_link(request: Request, token: str, redirect: str) -> str:
    """Compose the absolute magic link URL shown to the admin.

    Uses the request's scheme + host so operators running behind a tunnel
    (ngrok, localtunnel) get a link that actually resolves.
    """
    base = str(request.base_url).rstrip("/")
    from urllib.parse import quote
    return f"{base}/api/auth/verify?token={quote(token)}&redirect={quote(redirect)}"


def _send_smtp_magic_link(email: str, link: str) -> None:
    """Send the magic link via SMTP using .autoservice/config.local.yaml.auth.smtp.

    M2 implementation is minimal — host/port/from only.  M3 can add TLS
    credentials when needed.  This path is intentionally not exercised by
    the test suite (tests run in dev-log mode).
    """
    import smtplib
    from email.message import EmailMessage
    from autoservice import bootstrap

    cfg = bootstrap._load_local_config()
    smtp_cfg = (cfg.get("auth") or {}).get("smtp") or {}
    host = str(smtp_cfg.get("host") or "").strip()
    port = int(smtp_cfg.get("port") or 25)
    sender = str(smtp_cfg.get("from") or "no-reply@autoservice.local").strip()

    msg = EmailMessage()
    msg["Subject"] = "Your AutoService admin login link"
    msg["From"] = sender
    msg["To"] = email
    msg.set_content(f"Click to sign in (expires in 10 min):\n\n{link}\n")

    with smtplib.SMTP(host, port) as server:
        server.send_message(msg)


@api_router.post("/auth/request-login")
async def auth_request_login(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> Any:
    """Issue a magic-link login token for an admin email (spec §5.2).

    Request body::

        {"email": "<admin@example.com>", "tenant_id": "<tid>"}  # tenant_id optional

    Response (always 200, anti-enumeration per spec §5.2)::

        {"status": "sent", "delivered": "smtp" | "log"}

    Behaviour:
        * If ``email`` is on ``config.local.yaml.auth.admin_emails`` a token
          is persisted and delivered (SMTP if host is set, else dev log).
        * If ``email`` is NOT on the allowlist the response is identical
          but no token is persisted and no mail is sent.
        * Missing ``email`` field → 422.

    The ``tenant_id`` field is optional — ``NULL`` means a ``_master`` tier-0
    session will be created when the token is verified.
    """
    email_raw = payload.get("email") if isinstance(payload, dict) else None
    if not isinstance(email_raw, str) or not email_raw.strip():
        return JSONResponse(
            status_code=422,
            content={"error": "email is required"},
        )

    email = email_raw.strip().lower()
    tenant_id = payload.get("tenant_id") if isinstance(payload, dict) else None
    if isinstance(tenant_id, str):
        tenant_id = tenant_id.strip() or None
    else:
        tenant_id = None

    allowlist = _load_admin_emails()
    smtp_host = _smtp_host()
    delivered = "smtp" if smtp_host else "log"

    # Anti-enumeration: we ALWAYS return the same shape.  Side effects only
    # happen for allowlisted addresses.
    if email in allowlist:
        conn = _get_auth_db()
        token = auth.issue_login_token(conn, email, tenant_id=tenant_id)

        # Default redirect target: _master tier-0 goes to /admin, a tenant
        # session goes to /tenant/<tid>/admin.  Caller can override via the
        # verify endpoint's ?redirect= query param.
        redirect = f"/tenant/{tenant_id}/admin" if tenant_id else "/admin"

        # Dev UX: when vite (:5175) and uvicorn (:8000) run on different
        # ports, the browser-built `redirect` (absolute URL on the frontend
        # origin) lets the post-verify 302 land back on the admin-portal
        # instead of the backend's bare /admin path.  Accept the override
        # only when its origin equals the request's Origin header — prevents
        # an attacker who can submit /request-login from turning the magic
        # link into an open redirect for phishing.
        override = payload.get("redirect") if isinstance(payload, dict) else None
        if isinstance(override, str) and override.strip():
            from urllib.parse import urlparse
            cand = urlparse(override.strip())
            origin_hdr = request.headers.get("origin") or ""
            origin_parsed = urlparse(origin_hdr)
            if (
                cand.scheme in ("http", "https")
                and origin_parsed.scheme
                and cand.scheme == origin_parsed.scheme
                and cand.netloc == origin_parsed.netloc
            ):
                redirect = override.strip()

        link = _build_magic_link(request, token, redirect)

        if smtp_host:
            try:
                _send_smtp_magic_link(email, link)
            except Exception:
                # Fall back to dev log so the admin still has a way in if
                # SMTP is misconfigured (spec §5.6 spirit).
                logger.exception("SMTP send failed for %s; falling back to dev log", email)
                _dev_log_magic_link(email, tenant_id, token, link)
                delivered = "log"
        else:
            _dev_log_magic_link(email, tenant_id, token, link)

    return {"status": "sent", "delivered": delivered}


@api_router.get("/auth/verify")
async def auth_verify(
    request: Request,
    token: str | None = None,
    redirect: str = "/admin",
) -> Any:
    """Burn a login token and mint a session cookie (spec §5.2).

    Query params:
        token:    required, non-empty — the magic-link token to consume.
        redirect: optional — path the browser is sent to after cookie is
                  set.  Defaults to ``/admin``.

    Response:
        * 302 to ``redirect`` with ``Set-Cookie: auth_session=…`` on success.
        * 401 (plain text) on unknown / expired / already-consumed tokens.
        * 422 when ``token`` is missing or empty.

    The cookie is ``HttpOnly + SameSite=Lax`` unconditionally; the ``Secure``
    flag is set only when the request was served over HTTPS — CON-08 dev
    waiver is honoured.
    """
    if not token or not token.strip():
        return JSONResponse(
            status_code=422,
            content={"error": "token is required"},
        )

    conn = _get_auth_db()
    result = auth.consume_login_token(conn, token.strip())
    if result is None:
        return PlainTextResponse(
            "Invalid or expired login link",
            status_code=401,
        )

    admin_email, tenant_id = result
    session_id = auth.create_session(conn, admin_email, tenant_id=tenant_id)

    response = RedirectResponse(url=redirect, status_code=302)
    secure_flag = request.url.scheme == "https"
    response.set_cookie(
        key=AUTH_SESSION_COOKIE,
        value=session_id,
        max_age=auth.DEFAULT_SESSION_TTL_DAYS * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=secure_flag,
        path="/",
    )
    return response


@api_router.post("/auth/logout")
async def auth_logout(request: Request) -> Response:
    """Revoke the current session and clear the cookie (spec §5.2).

    Always returns 204 — idempotent.  No cookie, unknown session, or
    already-revoked session are all handled silently.
    """
    sid = request.cookies.get(AUTH_SESSION_COOKIE)
    if sid:
        conn = _get_auth_db()
        auth.revoke_session(conn, sid)

    response = Response(status_code=204)
    secure_flag = request.url.scheme == "https"
    response.set_cookie(
        key=AUTH_SESSION_COOKIE,
        value="",
        max_age=0,
        httponly=True,
        samesite="lax",
        secure=secure_flag,
        path="/",
    )
    return response


# ---------------------------------------------------------------------------
# Dev auto-login endpoints (spec 2026-04-21-dev-auto-login-design.md)
# ---------------------------------------------------------------------------
#
# Both endpoints are gated by DEV_MODE_ENABLED (env AUTH_DEV_MODE=1).
# When disabled:
#   • GET /auth/dev-mode  → {"enabled": false}   (200)
#   • POST /auth/dev-login → 404 Not Found
# When enabled, see tasks 2 and 4 in the plan for the full behaviour.


@api_router.get("/auth/dev-mode")
async def auth_dev_mode() -> Any:
    """Public probe: tells the frontend whether dev-login is available.

    When disabled, the response is intentionally minimal — no personas or
    tenants are leaked. When enabled, returns personas (from config.local.yaml)
    and tenants (scanned from plugins/).
    """
    if not DEV_MODE_ENABLED:
        return {"enabled": False}
    return {
        "enabled": True,
        "personas": _load_dev_personas(),
        "tenants": _scan_dev_tenants(),
    }


@api_router.post("/auth/dev-login")
async def auth_dev_login(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> Any:
    """Dev-only: mint a session cookie directly, bypassing magic-link.

    Gated by AUTH_DEV_MODE=1. When disabled, returns 404 to avoid advertising
    the endpoint's existence in production.

    Request body::

        {"email": "<admin@dev.local>", "tenant_id": "<tid>" | null}

    Response (200)::

        {"ok": true, "redirect": "/admin" | "/tenant/<tid>/admin"}

    Side effects on success:
      • Row inserted into the ``sessions`` table.
      • ``auth_session`` cookie set (HttpOnly, SameSite=Lax, Max-Age = session TTL).
      • WARNING log line + JSONL audit entry.
    """
    if not DEV_MODE_ENABLED:
        return JSONResponse(status_code=404, content={"error": "not found"})

    email_raw = payload.get("email") if isinstance(payload, dict) else None
    if not isinstance(email_raw, str) or not email_raw.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "email is required"},
        )
    email = email_raw.strip().lower()

    tenant_raw = payload.get("tenant_id") if isinstance(payload, dict) else None
    if isinstance(tenant_raw, str):
        tenant_id = tenant_raw.strip() or None
    else:
        tenant_id = None

    conn = _get_auth_db()
    session_id = auth.create_session(conn, email, tenant_id=tenant_id)

    sid_prefix = session_id[:8]
    logger.warning(
        "[dev-login] minted session for %s (tenant=%s, sid=%s…)",
        email, tenant_id or "_master", sid_prefix,
    )
    _DEV_MAIL_LOG.parent.mkdir(parents=True, exist_ok=True)
    audit_record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": "dev_login",
        "email": email,
        "tenant_id": tenant_id,
        "session_id_prefix": sid_prefix,
    }
    with _DEV_MAIL_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(audit_record, ensure_ascii=False) + "\n")

    redirect_target = f"/tenant/{tenant_id}/admin" if tenant_id else "/admin"

    response = JSONResponse(content={"ok": True, "redirect": redirect_target})
    secure_flag = request.url.scheme == "https"
    response.set_cookie(
        key=AUTH_SESSION_COOKIE,
        value=session_id,
        max_age=auth.DEFAULT_SESSION_TTL_DAYS * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=secure_flag,
        path="/",
    )
    return response


# ---------------------------------------------------------------------------
# Mount operator routes (M3 T1S.2 + T1S.4)
# ---------------------------------------------------------------------------
# Must be at module bottom so all api_router.* definitions above are complete
# before include_router merges operator_router's paths in.
from autoservice.operator_routes import operator_router as _operator_router  # noqa: E402

api_router.include_router(_operator_router)
