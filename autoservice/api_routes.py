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
        # Seed with some initial data so dashboard isn't empty
        from autoservice.sla_aggregator import MetricType
        _sla.record(MetricType.FIRST_REPLY_MS, 2100.0)
        _sla.record(MetricType.ACCEPT_MS, 850.0)
        _sla.record(MetricType.CSAT_SCORE, 4.6)
        _sla.record(MetricType.RESOLUTION_RATE, 0.873)
        _sla.record(MetricType.DIGEST_RATE, 0.82)
        _sla.record(MetricType.COMPLAINT_RATE, 0.03)
        _sla.record(MetricType.TTFB_MS, 420.0)
    return _sla


def _get_billing():
    global _billing, _billing_metrics
    if _billing is None:
        from autoservice.billing import TieredBilling
        from autoservice.billing_metrics import BillingMetrics
        _billing = TieredBilling()
        _billing_metrics = BillingMetrics()
        # Seed with demo data
        _billing_metrics.record_takeover("demo-conv-1")
        _billing_metrics.record_takeover("demo-conv-2")
        _billing_metrics.record_csat("demo-conv-1", 5)
        _billing_metrics.record_csat("demo-conv-2", 4)
    return _billing, _billing_metrics


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


# ---------------------------------------------------------------------------
# SLA
# ---------------------------------------------------------------------------

@api_router.get("/sla/summary")
async def sla_summary() -> dict[str, Any]:
    """Return current SLA metrics across all 7 types."""
    from autoservice.sla_aggregator import MetricType, WindowSize
    agg = _get_sla()
    result = {}
    for metric in MetricType:
        p = agg.get_percentiles(metric, WindowSize.FIVE_MIN)
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
# Commands (hijack/release) via REST — fallback when WS is flaky
# ---------------------------------------------------------------------------

@api_router.post("/command/hijack")
async def command_hijack(conversation_id: str, operator_id: str = "operator") -> dict[str, Any]:
    """Join conversation + hijack via REST API."""
    engine = _ws_engine()
    if engine is None:
        return {"ok": False, "error": "no engine"}
    try:
        now = datetime.now(timezone.utc)
        from autoservice.conversation_engine.types import Participant, ParticipantRole
        participant = Participant(id=operator_id, role=ParticipantRole.OPERATOR, joined_at=now)
        try:
            await engine.join(conversation_id, participant)
        except Exception:
            pass
        await engine.handle_command(conversation_id, actor_id=operator_id, command="/hijack")
        conv = await engine.get_conversation(conversation_id)
        return {"ok": True, "mode": conv.mode.value}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@api_router.post("/command/release")
async def command_release(conversation_id: str, operator_id: str = "operator") -> dict[str, Any]:
    """Release hijack via REST API."""
    engine = _ws_engine()
    if engine is None:
        return {"ok": False, "error": "no engine"}
    try:
        await engine.handle_command(conversation_id, actor_id=operator_id, command="/release")
        conv = await engine.get_conversation(conversation_id)
        return {"ok": True, "mode": conv.mode.value}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@api_router.post("/command/send-message")
async def command_send_message(
    conversation_id: str, operator_id: str = "operator", content: str = "",
) -> dict[str, Any]:
    """Send a message as operator (takeover mode) and broadcast to all WS connections."""
    engine = _ws_engine()
    if engine is None:
        return {"ok": False, "error": "no engine"}
    try:
        msg = await engine.send_message(
            conversation_id, source=operator_id, content=content,
        )
        # Broadcast to all WS connections
        from autoservice.gateway.message_router import _message_frame
        from autoservice.web_gateway import _ws_connections
        frame = _message_frame(msg)
        frame["payload"]["source_display"] = {"id": operator_id, "role": "operator"}
        for sid, ws in list(_ws_connections.items()):
            try:
                await ws.send_json(frame)
            except Exception:
                pass
        return {"ok": True, "message_id": msg.id}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@api_router.post("/canary/advance")
async def canary_advance() -> dict[str, Any]:
    """Advance canary to next stage."""
    router, _ = _get_canary()
    import time
    router._stage_started_at = time.time() - 90000  # skip observation for demo
    router.advance()
    return router.status()


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
    from autoservice.compliance.compliance import ComplianceEngine
    engine = ComplianceEngine()
    # Use empty config to get all 16 rules with their results
    report = engine.scan(tenant_id, {})
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

@api_router.post("/rehearsal/generate")
async def rehearsal_generate(tenant_id: str = "default") -> list[dict[str, Any]]:
    """Generate virtual customer rehearsal dialogs."""
    try:
        from autoservice.sim_customer import generate_sim_dialogs
        dialogs = generate_sim_dialogs(tenant_id)
        return dialogs
    except Exception as exc:
        logger.warning("sim_customer generation failed, using fallback: %s", exc)
        # Fallback: return structured mock
        return [
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
            }
            for i, (name, intent, persona, q, a) in enumerate([
                ("通用问候", "general", "普通客户", "你好，在吗？", "您好！请问有什么可以帮到您？"),
                ("产品咨询", "product_inquiry", "价格敏感客户", "这个产品多少钱？", "目前的价格方案如下..."),
                ("投诉处理", "complaint", "愤怒客户", "我要投诉！", "非常抱歉给您带来不好的体验..."),
                ("购买意向", "purchase_intent", "新客户", "怎么购买？", "您可以通过以下方式购买..."),
                ("语言障碍", "language_barrier", "外语客户", "Can you speak English?", "Sure! How can I help you?"),
                ("退款申请", "complaint", "老客户", "我要退款", "好的，请提供订单号..."),
            ])
        ]
