"""ModelRouter + FastClassifier for dual-model routing.

T1A.5 产出 | 2026-04-16
关联: PRD α2 / US-2.2 / agents/triage/soul.md

Routes incoming messages to the appropriate agent pool (fast/slow model)
based on intent classification and confidence scoring.
"""

import yaml
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Intent(str, Enum):
    PRODUCT_INQUIRY = "product_inquiry"
    COMPLAINT = "complaint"
    PURCHASE_INTENT = "purchase_intent"
    LANGUAGE_BARRIER = "language_barrier"
    GENERAL_QUESTION = "general_question"


class ModelTier(str, Enum):
    FAST = "fast"    # haiku — < 1s
    SLOW = "slow"    # sonnet — 5-15s


class AgentRole(str, Enum):
    CUSTOMER = "customer"
    TRANSLATE = "translate"
    LEAD = "lead"
    TRIAGE = "triage"


@dataclass
class ClassificationResult:
    intent: Intent
    confidence: float               # 0.0 - 1.0
    route_to: AgentRole
    model_tier: ModelTier
    priority: str = "normal"        # normal | high
    summary: Optional[str] = None   # 低信心时附加摘要


@dataclass
class RoutingDecision:
    agent_role: AgentRole
    model_tier: ModelTier
    priority: str
    classification: ClassificationResult
    needs_operator_notice: bool = False  # 中/低信心时通知 operator


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).parent / "classify_intent.yaml"
_config: Optional[dict] = None


def _load_config() -> dict:
    global _config
    if _config is None:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            _config = yaml.safe_load(f)
    return _config


def get_confidence_thresholds() -> dict:
    return _load_config()["confidence"]


def get_timeout_config(stage: str) -> dict:
    return _load_config()["timeouts"].get(stage, {})


# ---------------------------------------------------------------------------
# FastClassifier — keyword-based intent classification (fast path)
# ---------------------------------------------------------------------------

class FastClassifier:
    """Keyword-based intent classifier for the fast path (triage stage).

    Uses keyword matching as a first pass. In production, this would be
    augmented by the triage agent (haiku) for semantic understanding.
    """

    _tenant_cache: dict[str | None, "FastClassifier"] = {}

    def __init__(self):
        config = _load_config()
        self._intents = config["intents"]
        self._thresholds = config["confidence"]

    @classmethod
    def for_tenant(cls, tenant_id: str | None) -> "FastClassifier":
        """Return a tenant-scoped classifier (cached per tenant_id)."""
        if tenant_id in cls._tenant_cache:
            return cls._tenant_cache[tenant_id]
        from autoservice.tenant_triage_config import load_classify_intent_config
        cfg = load_classify_intent_config(tenant_id)
        inst = cls.__new__(cls)
        inst._intents = cfg["intents"]
        inst._thresholds = cfg["confidence"]
        cls._tenant_cache[tenant_id] = inst
        return inst

    @classmethod
    def clear_tenant_cache(cls) -> None:
        """Test hook — drop cached per-tenant classifiers."""
        cls._tenant_cache.clear()

    def classify(self, message: str, detected_language: Optional[str] = None) -> ClassificationResult:
        """Classify a message into an intent with confidence score."""
        message_lower = message.lower()

        # Language barrier detection (highest priority)
        if detected_language and detected_language not in ("zh", "en"):
            return ClassificationResult(
                intent=Intent.LANGUAGE_BARRIER,
                confidence=0.9,
                route_to=AgentRole.TRANSLATE,
                model_tier=ModelTier.FAST,
                priority="high",
            )

        # Keyword matching
        best_intent = None
        best_score = 0.0

        for intent_name, intent_cfg in self._intents.items():
            keywords = intent_cfg.get("keywords", [])
            if not keywords:
                continue
            hits = sum(1 for kw in keywords if kw in message_lower)
            if hits > 0:
                score = min(0.5 + hits * 0.15, 0.95)
                if score > best_score:
                    best_score = score
                    best_intent = intent_name

        # Fallback to general_question
        if best_intent is None:
            best_intent = "general_question"
            best_score = 0.4

        intent_cfg = self._intents[best_intent]

        return ClassificationResult(
            intent=Intent(best_intent),
            confidence=best_score,
            route_to=AgentRole(intent_cfg["route_to"]),
            model_tier=ModelTier(intent_cfg["model_tier"]),
            priority=intent_cfg.get("priority", "normal"),
            summary=message[:100] if best_score < self._thresholds["medium"] else None,
        )


# ---------------------------------------------------------------------------
# ModelRouter — decides fast vs slow path and target agent
# ---------------------------------------------------------------------------

class ModelRouter:
    """Routes messages to the appropriate agent pool and model tier.

    Decision flow:
    1. FastClassifier does keyword-based intent classification
    2. If confidence >= high → direct route
    3. If confidence >= medium → route + notify operator
    4. If confidence >= low → route to customer (safe default) + attach summary
    5. If confidence < low → request human intervention
    """

    def __init__(self):
        self._classifier = FastClassifier()
        self._thresholds = get_confidence_thresholds()

    def route(self, message: str, detected_language: Optional[str] = None) -> RoutingDecision:
        """Route a message to the appropriate agent and model tier."""
        result = self._classifier.classify(message, detected_language)

        needs_notice = False

        if result.confidence < self._thresholds["low"]:
            # Very uncertain — override to customer + flag for operator
            result = ClassificationResult(
                intent=result.intent,
                confidence=result.confidence,
                route_to=AgentRole.CUSTOMER,
                model_tier=ModelTier.SLOW,
                priority="high",
                summary=result.summary or message[:100],
            )
            needs_notice = True
        elif result.confidence < self._thresholds["medium"]:
            needs_notice = True

        return RoutingDecision(
            agent_role=result.route_to,
            model_tier=result.model_tier,
            priority=result.priority,
            classification=result,
            needs_operator_notice=needs_notice,
        )

    def should_use_placeholder(self, decision: RoutingDecision) -> bool:
        """Whether to send a placeholder message before the full response.

        Placeholder is used when routing to slow model tier, giving the
        customer immediate feedback while the full response generates.
        """
        return decision.model_tier == ModelTier.SLOW
