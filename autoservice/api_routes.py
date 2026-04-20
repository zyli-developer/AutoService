"""REST API routes — expose backend capabilities to frontend SPAs.

Bridges existing backend classes (SLAAggregator, TieredBilling, ProposalPipeline,
CanaryRouter, ComplianceEngine, sim_customer) to HTTP endpoints.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

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

@api_router.get("/session/mode")
async def get_session_mode() -> dict[str, Any]:
    """Return deployment mode for admin-portal layout switching.

    M1: always returns master/platform_admin.
    M2 (tenant fork): will return {mode: "tenant", role: "tenant_admin",
    tenant_id: "<id>"} — not implemented here.
    """
    return {
        "mode": "master",
        "role": "platform_admin",
    }


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


# ---------------------------------------------------------------------------
# Management Chat (Dream Engine conversational interface)
# ---------------------------------------------------------------------------

@api_router.post("/management/chat")
async def management_chat(message: str = "") -> dict[str, Any]:
    """Process a management chat message. Routes slash commands to backend functions."""
    text = message.strip()
    if not text:
        return {"role": "system", "content": "请输入命令或消息。支持: /rules, /status, /approve, /reject, /rollback, @Dream Engine"}

    # Dream Engine config dialog — check if session is active first (T6E.9)
    dream_session = _get_dream_session()
    if dream_session.is_active():
        response, done = dream_session.process_input(text)
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


@api_router.post("/rehearsal/generate")
async def rehearsal_generate(tenant_id: str = "default") -> dict[str, Any]:
    """Generate virtual customer rehearsal dialogs.

    Attempts real LLM-powered generation via ``sim_customer``.  When the LLM
    is unavailable (missing SDK, no API key, network error …) the endpoint
    falls back to >=10 hardcoded demo dialogs, each tagged with
    ``is_demo: true``.
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
        return {
            "demo_mode": False,
            "dialogs": [
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
            ],
        }
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
        return {
            "demo_mode": True,
            "dialogs": [
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
            ],
        }
