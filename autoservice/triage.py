"""Smart triage agent with confidence model.

T2A.2 产出 | 2026-04-16
关联: PRD α5 / B6 / agents/triage/soul.md / model_router.py FastClassifier

Replaces simple keyword-based route_query with a multi-signal confidence model.
Combines keyword matching, message length heuristics, language detection,
and conversation context to produce a calibrated confidence score.

The triage agent uses haiku (fast model) for semantic understanding
when keyword-based classification has low confidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence

from autoservice.model_router import (
    Intent, AgentRole, ModelTier, ClassificationResult, FastClassifier,
)


class TriageSignal(str, Enum):
    """Individual signal types that contribute to confidence."""
    KEYWORD_MATCH = "keyword_match"
    MESSAGE_LENGTH = "message_length"
    LANGUAGE_DETECT = "language_detect"
    URGENCY_MARKERS = "urgency_markers"
    CONTEXT_HISTORY = "context_history"
    MULTI_INTENT = "multi_intent"


@dataclass
class SignalScore:
    """Score from a single triage signal."""
    signal: TriageSignal
    intent: Intent
    weight: float        # contribution weight (0-1)
    confidence: float    # signal-level confidence (0-1)
    detail: str = ""


@dataclass
class TriageResult:
    """Full triage result with signal breakdown."""
    intent: Intent
    confidence: float                          # aggregate 0-1
    route_to: AgentRole
    model_tier: ModelTier
    priority: str = "normal"
    signals: list[SignalScore] = field(default_factory=list)
    needs_semantic_fallback: bool = False       # True if should invoke haiku for clarity
    summary: Optional[str] = None
    multi_intent: bool = False                  # True if multiple intents detected


# ---------------------------------------------------------------------------
# Signal weights
# ---------------------------------------------------------------------------

SIGNAL_WEIGHTS = {
    TriageSignal.KEYWORD_MATCH: 0.35,
    TriageSignal.MESSAGE_LENGTH: 0.10,
    TriageSignal.LANGUAGE_DETECT: 0.15,
    TriageSignal.URGENCY_MARKERS: 0.20,
    TriageSignal.CONTEXT_HISTORY: 0.10,
    TriageSignal.MULTI_INTENT: 0.10,
}

# Urgency markers
_URGENCY_PATTERNS_ZH = re.compile(r"(投诉|举报|退款|赔偿|法律|律师|曝光|消协|工商|紧急|马上|立刻)")
_URGENCY_PATTERNS_EN = re.compile(r"(complain|refund|legal|lawyer|urgent|immediately|asap|sue|report)", re.I)


# ---------------------------------------------------------------------------
# TriageAgent — multi-signal confidence model
# ---------------------------------------------------------------------------

class TriageAgent:
    """Smart triage with multi-signal confidence scoring.

    Combines:
    1. Keyword matching (FastClassifier baseline)
    2. Message length heuristics (very short = ambiguous)
    3. Language detection signal
    4. Urgency markers (escalation indicators)
    5. Conversation history context (repeat queries, topic shifts)
    6. Multi-intent detection (mixed signals)

    If aggregate confidence < 0.5, flags for semantic fallback (haiku call).
    """

    def __init__(self):
        self._classifier = FastClassifier()

    def classify(
        self,
        message: str,
        detected_language: Optional[str] = None,
        conversation_history: Optional[Sequence[str]] = None,
    ) -> TriageResult:
        """Classify message with multi-signal confidence model."""
        signals: list[SignalScore] = []

        # Signal 1: Keyword match (baseline from FastClassifier)
        baseline = self._classifier.classify(message, detected_language)
        signals.append(SignalScore(
            signal=TriageSignal.KEYWORD_MATCH,
            intent=baseline.intent,
            weight=SIGNAL_WEIGHTS[TriageSignal.KEYWORD_MATCH],
            confidence=baseline.confidence,
            detail=f"keyword→{baseline.intent.value}",
        ))

        # Signal 2: Message length heuristic
        msg_len = len(message.strip())
        if msg_len < 5:
            len_conf = 0.2   # Very short = very ambiguous
        elif msg_len < 20:
            len_conf = 0.5
        elif msg_len < 100:
            len_conf = 0.8
        else:
            len_conf = 0.9   # Long messages usually have clear intent
        signals.append(SignalScore(
            signal=TriageSignal.MESSAGE_LENGTH,
            intent=baseline.intent,
            weight=SIGNAL_WEIGHTS[TriageSignal.MESSAGE_LENGTH],
            confidence=len_conf,
            detail=f"len={msg_len}",
        ))

        # Signal 3: Language detection
        lang_conf = 0.5  # neutral default
        lang_intent = baseline.intent
        if detected_language and detected_language not in ("zh", "en"):
            lang_conf = 0.95
            lang_intent = Intent.LANGUAGE_BARRIER
        elif detected_language:
            lang_conf = 0.7  # known language, no barrier
        signals.append(SignalScore(
            signal=TriageSignal.LANGUAGE_DETECT,
            intent=lang_intent,
            weight=SIGNAL_WEIGHTS[TriageSignal.LANGUAGE_DETECT],
            confidence=lang_conf,
            detail=f"lang={detected_language or 'unknown'}",
        ))

        # Signal 4: Urgency markers
        urgency_hits = len(_URGENCY_PATTERNS_ZH.findall(message)) + len(_URGENCY_PATTERNS_EN.findall(message))
        if urgency_hits > 0:
            urgency_conf = min(0.5 + urgency_hits * 0.2, 0.95)
            urgency_intent = Intent.COMPLAINT
        else:
            urgency_conf = 0.5
            urgency_intent = baseline.intent
        signals.append(SignalScore(
            signal=TriageSignal.URGENCY_MARKERS,
            intent=urgency_intent,
            weight=SIGNAL_WEIGHTS[TriageSignal.URGENCY_MARKERS],
            confidence=urgency_conf,
            detail=f"urgency_hits={urgency_hits}",
        ))

        # Signal 5: Conversation history context
        history_conf = 0.5
        if conversation_history:
            if len(conversation_history) > 5:
                history_conf = 0.7  # Long conversation = more context
            if any("投诉" in h or "complaint" in h.lower() for h in conversation_history[-3:]):
                history_conf = 0.8  # Recent complaint context
        signals.append(SignalScore(
            signal=TriageSignal.CONTEXT_HISTORY,
            intent=baseline.intent,
            weight=SIGNAL_WEIGHTS[TriageSignal.CONTEXT_HISTORY],
            confidence=history_conf,
            detail=f"history_len={len(conversation_history) if conversation_history else 0}",
        ))

        # Signal 6: Multi-intent detection
        intent_votes = {}
        for s in signals:
            intent_votes[s.intent] = intent_votes.get(s.intent, 0) + s.weight * s.confidence
        sorted_intents = sorted(intent_votes.items(), key=lambda x: -x[1])
        multi_intent = len(sorted_intents) > 1 and sorted_intents[1][1] > sorted_intents[0][1] * 0.5
        multi_conf = 0.3 if multi_intent else 0.8
        signals.append(SignalScore(
            signal=TriageSignal.MULTI_INTENT,
            intent=sorted_intents[0][0],
            weight=SIGNAL_WEIGHTS[TriageSignal.MULTI_INTENT],
            confidence=multi_conf,
            detail=f"multi={multi_intent}",
        ))

        # Aggregate: weighted confidence
        total_weight = sum(s.weight for s in signals)
        aggregate_conf = sum(s.weight * s.confidence for s in signals) / total_weight if total_weight else 0.0

        # Winner intent: highest vote
        final_intent = sorted_intents[0][0]

        # Override for strong language barrier signal
        if lang_intent == Intent.LANGUAGE_BARRIER and lang_conf > 0.9:
            final_intent = Intent.LANGUAGE_BARRIER

        # Override for strong urgency signal
        if urgency_hits >= 2 and urgency_conf > 0.7:
            final_intent = Intent.COMPLAINT

        # Map intent → agent role + model tier
        intent_config = self._classifier._intents.get(final_intent.value, {})
        route_to = AgentRole(intent_config.get("route_to", "customer"))
        model_tier = ModelTier(intent_config.get("model_tier", "slow"))
        priority = "high" if urgency_hits > 0 or final_intent == Intent.COMPLAINT else intent_config.get("priority", "normal")

        return TriageResult(
            intent=final_intent,
            confidence=round(aggregate_conf, 3),
            route_to=route_to,
            model_tier=model_tier,
            priority=priority,
            signals=signals,
            needs_semantic_fallback=aggregate_conf < 0.5,
            summary=message[:100] if aggregate_conf < 0.5 else None,
            multi_intent=multi_intent,
        )
