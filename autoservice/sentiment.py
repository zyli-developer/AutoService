"""Sentiment detection prompt extension and event trigger.

T1A.11 产出 | 2026-04-16
关联: PRD α4 / L1.3 情绪识别 / agents/customer/soul.md §情绪感知

Provides:
1. Prompt prefix for sentiment annotation on every agent reply
2. Sentiment enum and parsing from agent output
3. Escalation event trigger on sentiment deterioration
"""

import re
from enum import Enum
from dataclasses import dataclass
from typing import Optional


class Sentiment(str, Enum):
    POSITIVE = "positive"    # 满意、感谢、正面
    NEUTRAL = "neutral"      # 平和、常规咨询
    NEGATIVE = "negative"    # 不满、失望、焦虑
    ANGRY = "angry"          # 愤怒、威胁、投诉升级


# Severity mapping for downstream consumers (metrics plugin, SLA)
SENTIMENT_SEVERITY = {
    Sentiment.POSITIVE: 0,
    Sentiment.NEUTRAL: 1,
    Sentiment.NEGATIVE: 2,
    Sentiment.ANGRY: 3,
}


@dataclass
class SentimentResult:
    sentiment: Sentiment
    confidence: float          # 0.0 - 1.0
    previous: Optional[Sentiment] = None
    deteriorated: bool = False  # True if worse than previous


# ---------------------------------------------------------------------------
# Prompt prefix — injected into agent system prompt
# ---------------------------------------------------------------------------

SENTIMENT_PROMPT_PREFIX = """## 情绪识别指令

在回复客户之前，先分析客户最新消息的情绪。在你的回复最开头用如下格式标注（此行对客户不可见，会被系统解析后移除）：

[SENTIMENT: <positive|neutral|negative|angry>, CONFIDENCE: <0.0-1.0>]

判断标准：
- positive: 客户表达满意、感谢、认可
- neutral: 平和的咨询或陈述，无明显情绪倾向
- negative: 不满、失望、焦虑、催促
- angry: 愤怒、威胁、要求投诉/赔偿/退款升级

注意：
- 基于客户消息内容判断，不受你自己回复的影响
- 如果不确定，倾向于标注更严重的情绪（宁可高估风险）
- confidence 反映你对判断的确信程度
"""


# ---------------------------------------------------------------------------
# Parser — extract sentiment annotation from agent output
# ---------------------------------------------------------------------------

_SENTIMENT_PATTERN = re.compile(
    r"\[SENTIMENT:\s*(positive|neutral|negative|angry)"
    r",\s*CONFIDENCE:\s*([\d.]+)\]",
    re.IGNORECASE,
)


def parse_sentiment(agent_output: str) -> tuple[Optional[SentimentResult], str]:
    """Parse sentiment annotation from agent output.

    Returns:
        (SentimentResult or None, cleaned output with annotation removed)
    """
    match = _SENTIMENT_PATTERN.search(agent_output)
    if not match:
        return None, agent_output

    sentiment = Sentiment(match.group(1).lower())
    confidence = min(max(float(match.group(2)), 0.0), 1.0)

    cleaned = agent_output[:match.start()] + agent_output[match.end():]
    cleaned = cleaned.lstrip("\n")

    return SentimentResult(sentiment=sentiment, confidence=confidence), cleaned


# ---------------------------------------------------------------------------
# Deterioration detector
# ---------------------------------------------------------------------------

def detect_deterioration(
    current: Sentiment,
    previous: Optional[Sentiment],
) -> bool:
    """Check if sentiment has deteriorated compared to previous turn."""
    if previous is None:
        return current == Sentiment.ANGRY  # First message angry = immediate flag
    return SENTIMENT_SEVERITY[current] > SENTIMENT_SEVERITY[previous]


def update_sentiment(
    result: SentimentResult,
    previous: Optional[Sentiment],
) -> SentimentResult:
    """Update a SentimentResult with deterioration detection."""
    result.previous = previous
    result.deteriorated = detect_deterioration(result.sentiment, previous)
    return result


# ---------------------------------------------------------------------------
# Event payload — for EventBus integration (T1A.3)
# ---------------------------------------------------------------------------

def sentiment_event_payload(
    conversation_id: str,
    result: SentimentResult,
) -> dict:
    """Build event payload for sentiment.detected / sentiment.deteriorated events.

    Event types:
    - sentiment.detected: emitted on every message
    - sentiment.deteriorated: emitted only when sentiment worsens
    """
    payload = {
        "conversation_id": conversation_id,
        "sentiment": result.sentiment.value,
        "confidence": result.confidence,
        "previous": result.previous.value if result.previous else None,
        "deteriorated": result.deteriorated,
    }
    return payload
