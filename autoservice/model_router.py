"""ModelRouter + FastClassifier for dual-model routing.

T1A.5 产出 | 2026-04-16
关联: PRD α2 / US-2.2 / agents/triage/soul.md

Routes incoming messages to the appropriate agent pool (fast/slow model)
based on intent classification and confidence scoring.
"""

import asyncio
import logging
import os
import re
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Optional, Protocol

log = logging.getLogger("triage.router")


def _triage_agent_enabled() -> bool:
    """Gate the haiku-backed triage agent fallback.

    When ``TRIAGE_AGENT_ENABLED`` is ``"0"`` / ``"false"`` / ``"no"`` (case-
    insensitive), ``ModelRouter.route_message`` skips the ``await
    _invoke_triage_agent`` branch entirely and uses the FastClassifier
    result directly even when confidence is below the medium threshold.

    Default: **enabled** (``True``). The agent provides semantic
    classification for messages that don't hit any FastClassifier
    keywords, and crucially decides the model tier (fast vs slow) for
    those ambiguous messages — which FastClassifier's ``general_question``
    fallback can't do meaningfully. The flag exists so deployments that
    care more about latency than tier accuracy can force-skip the
    ``_TRIAGE_AGENT_TIMEOUT`` cost.

    Read each time so tests can ``monkeypatch.setenv`` without reloading
    the module. The env var is evaluated per call — hot toggle is fine.
    """
    raw = os.getenv("TRIAGE_AGENT_ENABLED", "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _triage_agent_timeout_s() -> float:
    """Budget (seconds) for the full triage agent round-trip.

    Default 8 s — covers haiku TTFT + short classification output +
    Claude Agent SDK stdio bridge overhead on a warm pool. Measured
    locally at ~4-6 s depending on network to Anthropic; 8 s leaves
    headroom for the slow tail without blowing up perceived latency
    when the agent eventually gets invoked on a keyword-miss message.

    Override via ``TRIAGE_AGENT_TIMEOUT_S`` env var (e.g. ``"12"`` for
    slower links). Invalid values log a warning and fall back to the
    default. Read each call so the value can be adjusted without a
    restart — though the server still caches the class attribute
    ``ModelRouter._TRIAGE_AGENT_TIMEOUT`` as the documented default for
    tests that monkey-patch it directly (e.g. the E2E suite pins 0.05 s
    to exercise the timeout path deterministically).
    """
    raw = os.getenv("TRIAGE_AGENT_TIMEOUT_S")
    if raw is None:
        return ModelRouter._TRIAGE_AGENT_TIMEOUT
    try:
        return float(raw)
    except ValueError:
        log.warning(
            "Invalid TRIAGE_AGENT_TIMEOUT_S=%r (not a float) — "
            "using default %s",
            raw, ModelRouter._TRIAGE_AGENT_TIMEOUT,
        )
        return ModelRouter._TRIAGE_AGENT_TIMEOUT


_TRIAGE_OUTPUT_RE = re.compile(
    r"\[分流\]\s*"
    r"意图\s*:\s*(?P<intent>\w+)\s*\|\s*"
    r"信心\s*:\s*(?P<confidence>[\w.]+)\s*\|\s*"
    r"路由\s*:\s*(?P<route_to>\w+)\s*\|\s*"
    r"原因\s*:\s*(?P<reason>[^|]+?)"
    r"(?:\s*\|\s*摘要\s*:\s*\"(?P<summary>[^\"]+)\")?"
    r"(?:\s*\|\s*回复\s*:\s*\"(?P<direct_reply>[^\"]+)\")?"
    r"\s*$"
)

#: Accepted ``路由`` values from a triage agent. ``direct`` is the new
#: short-circuit route (template reply sent by gateway, no pool call);
#: see :class:`AgentRole` for the corresponding enum value.
_TRIAGE_ROLE_WHITELIST = {"customer", "lead", "translate", "direct"}


#: Max residue length (after stripping matched keywords + whitespace +
#: punctuation) for a message to qualify as "pure social". Tuned to allow
#: natural fillers like 您/啊/呀 after 你好/谢谢/再见 while blocking anything
#: with a real business clause attached.
_DIRECT_SOCIAL_MAX_RESIDUE = 6

#: Characters that signal a substantive question even when a greeting
#: keyword is present. `?`/`？` → actual question; digits → usually
#: product codes, amounts, dates, phone numbers.
_NON_SOCIAL_SIGNAL_RE = re.compile(r"[?？0-9]")

#: Punctuation + whitespace to strip when measuring residue. Uses a
#: hand-picked set rather than `\W` because CJK punctuation (，。！？)
#: isn't classified as non-word in Python's `re` under UNICODE.
_RESIDUE_STRIP_RE = re.compile(
    r"[\s,\.!\?;:\-_/\\\(\)\[\]\{\}'\"`~@#\$%\^&\*\+="
    r"，。！？；：、《》（）【】「」『』—…·]+"
)


def _is_pure_social(message: str, keywords: list[str]) -> bool:
    """Whether ``message`` is a pure social pattern (greeting/thanks/bye).

    A raw substring match on ``"你好"`` fires on any message that happens
    to start with a greeting — including substantive business questions.
    Direct-route intents short-circuit the pool entirely, so a false
    positive here sends the customer a template reply while their real
    question is silently dropped. This guard requires:

      1. No ``?``/``？`` or digits in the message (signal of a real
         question or data-bearing content)
      2. After stripping every matched keyword and filler punctuation,
         at most :data:`_DIRECT_SOCIAL_MAX_RESIDUE` word characters remain

    Both conditions must hold. If either fails, the keyword match is
    ignored and the message falls through to other intents (or the
    general_question fallback).
    """
    if _NON_SOCIAL_SIGNAL_RE.search(message):
        return False
    lowered = message.lower()
    for kw in sorted(keywords, key=len, reverse=True):
        lowered = lowered.replace(kw.lower(), "")
    residue = _RESIDUE_STRIP_RE.sub("", lowered)
    return len(residue) <= _DIRECT_SOCIAL_MAX_RESIDUE


def _parse_triage_output(raw: str) -> dict | None:
    """Parse a triage agent [分流] line. Returns dict or None on hard failure.

    Normalizes common Chinese-LLM formatting drift before regex match:

    * Full-width colon (``：``) → ``:``
    * Full-width pipe (``｜``) → ``|``
    * Markdown emphasis (``**`` / ``__``) stripped
    * Chinese square brackets (``【】``) → ``[]``

    Also tolerates two specific model-output patterns observed in
    production:

    1. **Full-width punctuation** — haiku on Chinese-heavy prompts
       routinely emits full-width ``：`` / ``｜`` which the strict ASCII
       regex silently rejects. First seen 2026-04-23 on a 5 s
       successful triage call that still landed on ``source=fallback``.
    2. **Self-repetition** — haiku sometimes emits the same ``[分流]``
       block twice without a separator between them, making the
       line-anchored regex (``\\s*$``) miss both copies. Fixed by
       splitting the normalized string with a look-ahead at ``[分流]``
       so each block is tried independently. Observed 2026-04-23 on
       ``"nihao 啊"`` — agent produced the correct greeting classification
       twice, but both were dropped before this fix.
    """
    if not raw:
        return None
    normalized_full = (
        raw
        .replace("：", ":")
        .replace("｜", "|")
        .replace("**", "")
        .replace("__", "")
        .replace("【", "[")
        .replace("】", "]")
    )
    # Candidate strategy (order matters — first match wins):
    #   1. Each [分流] block as its own segment (covers duplicated-
    #      output case). Lookahead split keeps the marker on the right
    #      side of each cut, so every non-empty segment starts with
    #      [分流] and the main regex's end-anchor (\s*$) can match at
    #      the segment boundary.
    #   2. Each original line (preserves pre-fix behavior when the
    #      model outputs a clean single-line [分流] — no regression
    #      for the 2026-04-22 baseline format).
    candidates: list[str] = []
    for seg in re.split(r"(?=\[分流\])", normalized_full):
        seg = seg.strip()
        if seg:
            candidates.append(seg)
    for line in normalized_full.splitlines():
        line = line.strip()
        if line:
            candidates.append(line)

    for normalized in candidates:
        m = _TRIAGE_OUTPUT_RE.match(normalized)
        if m:
            try:
                conf = float(m.group("confidence"))
            except (TypeError, ValueError):
                conf = 0.5
            role = m.group("route_to")
            if role not in _TRIAGE_ROLE_WHITELIST:
                role = "customer"
            return {
                "intent": m.group("intent"),
                "confidence": max(0.0, min(1.0, conf)),
                "route_to": role,
                "reason": m.group("reason").strip(),
                "summary": m.group("summary"),
                "direct_reply": m.group("direct_reply"),
            }
    return None


class Intent(str, Enum):
    PRODUCT_INQUIRY = "product_inquiry"
    COMPLAINT = "complaint"
    PURCHASE_INTENT = "purchase_intent"
    LANGUAGE_BARRIER = "language_barrier"
    GENERAL_QUESTION = "general_question"
    # Social-pattern intents that skip the pool entirely (direct reply
    # from a template in classify_intent.yaml). Safe because the reply
    # text is data-driven, never LLM-generated — no hallucination risk
    # on business facts.
    GREETING = "greeting"
    THANKS = "thanks"
    BYE = "bye"


class ModelTier(str, Enum):
    FAST = "fast"    # haiku — < 1s
    SLOW = "slow"    # sonnet — 5-15s


class AgentRole(str, Enum):
    CUSTOMER = "customer"
    TRANSLATE = "translate"
    LEAD = "lead"
    TRIAGE = "triage"
    #: Pseudo-role for template-driven direct replies. Not a real CC
    #: sub-pool — the gateway short-circuits on this value and sends
    #: ``ClassificationResult.direct_reply`` via ``engine.send_message``.
    DIRECT = "direct"


@dataclass
class ClassificationResult:
    intent: Intent
    confidence: float               # 0.0 - 1.0
    route_to: AgentRole
    model_tier: ModelTier
    priority: str = "normal"        # normal | high
    summary: Optional[str] = None   # 低信心时附加摘要
    #: Set iff ``route_to == AgentRole.DIRECT`` — the template reply the
    #: gateway sends verbatim without invoking any pool.
    direct_reply: Optional[str] = None


@dataclass
class RoutingDecision:
    agent_role: AgentRole
    model_tier: ModelTier
    priority: str
    classification: ClassificationResult
    needs_operator_notice: bool = False  # 中/低信心时通知 operator


@dataclass
class TriageDecision:
    """Triage-and-route decision consumed by triage_and_route()."""
    role: str                          # customer | lead | translate | direct
    confidence: float
    source: Literal["fastpath", "triage_agent", "fallback"]
    intent: str
    detected_language: Optional[str]
    summary: Optional[str] = None
    needs_operator_notice: bool = False
    previous_role: Optional[str] = None
    #: Populated only when ``role == "direct"``. The gateway persists this
    #: via ``engine.send_message`` and returns without touching any pool.
    direct_reply: Optional[str] = None
    #: ``"fast"`` | ``"slow"`` | ``None``. Hint for the customer sticky
    #: session — ``CCPool.session_query(tier=...)`` will escalate the
    #: instance to slow_model on the first slow-tier turn and keep it
    #: there. Derived from ``ClassificationResult.model_tier``; ``None``
    #: means "leave instance on its default model" (e.g. direct / lead /
    #: translate paths that don't use session_query at all).
    tier: Optional[str] = None


class _TenantConfigLike(Protocol):
    supported_languages: list[str]
    tenant_id: str | None


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
                # Direct-route intents (greeting/thanks/bye) short-circuit
                # the pool with a template reply. Require the message to
                # be a pure social pattern — "你好,我要问..." must fall
                # through to customer, not template-reply the real question.
                if intent_cfg.get("route_to") == AgentRole.DIRECT.value:
                    if not _is_pure_social(message, keywords):
                        continue
                score = min(0.5 + hits * 0.15, 0.95)
                if score > best_score:
                    best_score = score
                    best_intent = intent_name

        # Fallback to general_question
        if best_intent is None:
            best_intent = "general_question"
            best_score = 0.4

        intent_cfg = self._intents[best_intent]

        # Direct-reply template lookup — only meaningful when the config
        # routes this intent to AgentRole.DIRECT. For English messages we
        # prefer ``direct_reply_en`` when present, falling back to the
        # canonical ``direct_reply`` (Chinese).
        direct_reply = None
        route_to = intent_cfg["route_to"]
        if route_to == AgentRole.DIRECT.value:
            if detected_language and detected_language.lower().startswith("en"):
                direct_reply = intent_cfg.get("direct_reply_en") or intent_cfg.get("direct_reply")
            else:
                direct_reply = intent_cfg.get("direct_reply")
            # Invariant: direct route must carry a template. A tenant overlay
            # can flip ``route_to: direct`` on an intent that doesn't define
            # a ``direct_reply``; that would leave the gateway short-circuit
            # with nothing to send and fall through to a
            # ``pool.acquire(role="direct")`` that raises NotImplementedError.
            # Demote here so every ClassificationResult is internally
            # consistent.
            if not direct_reply:
                log.warning(
                    "intent=%s has route_to=direct but no direct_reply "
                    "template — demoting to customer",
                    best_intent,
                )
                route_to = AgentRole.CUSTOMER.value

        return ClassificationResult(
            intent=Intent(best_intent),
            confidence=best_score,
            route_to=AgentRole(route_to),
            model_tier=ModelTier(intent_cfg["model_tier"]),
            priority=intent_cfg.get("priority", "normal"),
            summary=message[:100] if best_score < self._thresholds["medium"] else None,
            direct_reply=direct_reply,
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

    async def route_message(
        self,
        message: str,
        *,
        tenant_config: "_TenantConfigLike",
        conv_id: Optional[str] = None,
        engine: Any = None,
    ) -> TriageDecision:
        """Full triage-and-route decision (async).

        Steps:
          1. detect language (heuristic + langdetect)
          2. if language NOT IN tenant.supported_languages → translate
          3. FastClassifier with tenant overlay
          4. drift probe (engine.incr_drift / reset_drift)
          5. decide fastpath vs fallback (Task 8 will replace the fallback branch
             with a real triage-agent call)
        """
        from autoservice.language_detect import detect_language

        tenant_id = getattr(tenant_config, "tenant_id", None)
        supported = set(getattr(tenant_config, "supported_languages", []) or ["zh", "en"])

        lang = detect_language(message)
        if lang != "unknown" and lang not in supported:
            return TriageDecision(
                role="translate",
                confidence=0.9,
                source="fastpath",
                intent="language_barrier",
                detected_language=lang,
                needs_operator_notice=False,
                tier="fast",
            )

        clf = FastClassifier.for_tenant(tenant_id)
        fast = clf.classify(message, detected_language=lang if lang != "unknown" else None)

        previous_role: Optional[str] = None
        drift_count = 0
        if conv_id is not None and engine is not None:
            state = await engine.get_triage_state(conv_id)
            previous_role = state.get("active_role")
            if previous_role and previous_role != fast.route_to.value:
                drift_count = await engine.incr_drift(conv_id)
            else:
                await engine.reset_drift(conv_id)

        threshold = self._thresholds["medium"]
        can_fastpath = (
            fast.confidence >= threshold
            and (previous_role is None or drift_count < 2)
        )
        if can_fastpath:
            return TriageDecision(
                role=fast.route_to.value,
                confidence=fast.confidence,
                source="fastpath",
                intent=fast.intent.value,
                detected_language=lang if lang != "unknown" else None,
                summary=fast.summary,
                needs_operator_notice=fast.confidence < self._thresholds["high"],
                previous_role=previous_role,
                direct_reply=fast.direct_reply,
                tier=fast.model_tier.value,
            )

        # Fast classifier is uncertain. Either call the haiku triage agent
        # for a semantic second opinion (legacy), or skip it and trust the
        # fast result (default as of 2026-04-23 — see ``_triage_agent_enabled``
        # docstring for the 2 s timeout rationale). When skipped, we reuse
        # the same ``_triage_fallback`` shape the timeout/exception branches
        # of ``_invoke_triage_agent`` would produce, so downstream
        # (triage_dispatch SIDE message, conv metadata, tests) keeps the
        # same envelope.
        if not _triage_agent_enabled():
            return self._triage_fallback(
                message, fast, lang if lang != "unknown" else None,
                previous_role,
            )

        return await self._invoke_triage_agent(
            message=message,
            tenant_id=tenant_id,
            fast_result=fast,
            detected_language=lang if lang != "unknown" else None,
            previous_role=previous_role,
        )

    # 15 s default budget for the full triage agent round-trip. Escalated
    # 2 s → 4 s → 8 s → 15 s over 2026-04-23 as successive timeouts
    # revealed haiku's real latency distribution on the observed network:
    # one-shot measurements 5 s / 8 s / 8 s on warm pool instances, with
    # the 8 s attempt precisely hitting the previous ceiling. 15 s
    # clearly covers the tail; override per-deploy with the
    # ``TRIAGE_AGENT_TIMEOUT_S`` env var (see ``_triage_agent_timeout_s``
    # helper) without touching code.
    #
    # Cost: when the agent is invoked (low-confidence messages, ~10%
    # after keyword expansion), customer reply is delayed by up to 15 s.
    # The 90% fastpath case pays nothing either way.
    #
    # Tests monkey-patch this attribute directly (e.g. 0.05 s in the
    # E2E triage suite to exercise timeout-fallback deterministically),
    # so it's kept as a class attribute rather than inlined into the
    # helper.
    _TRIAGE_AGENT_TIMEOUT = 15.0
    _POOL_ACQUIRE_TIMEOUT = 0.5

    async def _triage_agent_one_shot(self, message: str, tenant_id: str | None) -> str:
        """One-shot triage agent call returning the raw [分流] line."""
        from autoservice.cc_pool import get_pool
        pool = await get_pool()
        prompt = self._render_triage_prompt(message)
        async with pool.acquire(role="triage", tenant_id=tenant_id,
                                 timeout=self._POOL_ACQUIRE_TIMEOUT) as inst:
            await inst.client.query(prompt, session_id=f"triage-{id(inst)}")
            parts: list[str] = []
            from claude_agent_sdk.types import AssistantMessage, ResultMessage
            async for msg in inst.client.receive_response():
                if isinstance(msg, AssistantMessage) and msg.content:
                    for b in msg.content:
                        if hasattr(b, "text"):
                            parts.append(b.text)
                elif isinstance(msg, ResultMessage) and msg.result:
                    parts.append(msg.result)
            return "".join(parts).strip()

    def _render_triage_prompt(self, message: str) -> str:
        return (
            "按 soul 指定格式输出单行 [分流] 判断。只回一行,不要多余说明。\n\n"
            f"客户消息: {message}"
        )

    def _triage_fallback(
        self,
        message: str,
        fast_result: "ClassificationResult",
        detected_language: str | None,
        previous_role: str | None,
    ) -> TriageDecision:
        """Construct a fallback TriageDecision from the fast classifier result."""
        return TriageDecision(
            role=fast_result.route_to.value,
            confidence=fast_result.confidence,
            source="fallback",
            intent=fast_result.intent.value,
            detected_language=detected_language,
            summary=(fast_result.summary or message[:100]),
            needs_operator_notice=True,
            previous_role=previous_role,
            direct_reply=fast_result.direct_reply,
            tier=fast_result.model_tier.value,
        )

    async def _invoke_triage_agent(
        self,
        message: str,
        tenant_id: str | None,
        fast_result: "ClassificationResult",
        detected_language: str | None,
        previous_role: str | None,
    ) -> TriageDecision:
        # asyncio.CancelledError is a BaseException (not Exception) and will
        # propagate naturally through this try/except block — intentional.
        #
        # ``_triage_agent_timeout_s`` reads ``TRIAGE_AGENT_TIMEOUT_S`` env
        # var each call (falls back to the class attribute). Tests that
        # monkey-patch ``ModelRouter._TRIAGE_AGENT_TIMEOUT`` directly
        # still win because the helper defaults to the class attribute
        # when the env var is unset.
        timeout_s = _triage_agent_timeout_s()
        try:
            raw = await asyncio.wait_for(
                self._triage_agent_one_shot(message, tenant_id),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            log.warning(
                "triage agent timed out for tenant=%s (budget=%.1fs)",
                tenant_id, timeout_s,
            )
            return self._triage_fallback(
                message, fast_result, detected_language, previous_role,
            )
        except Exception as exc:
            log.warning("triage agent call failed: %s", exc, exc_info=True)
            return self._triage_fallback(
                message, fast_result, detected_language, previous_role,
            )
        parsed = _parse_triage_output(raw)
        if parsed is None:
            # Silent fall-through was a debug black hole — haiku ran
            # successfully (no timeout, no exception), but the output
            # didn't match _TRIAGE_OUTPUT_RE and operators saw "源:
            # fallback" with no explanation. Log the raw output so
            # prompt / parser drift becomes diagnosable. Truncate at
            # 300 chars to keep log lines bounded even if the model
            # goes off-script with a paragraph.
            log.warning(
                "triage agent output didn't parse for tenant=%s; "
                "raw=%r — using fast fallback",
                tenant_id, (raw or "")[:300],
            )
            return self._triage_fallback(
                message, fast_result, detected_language, previous_role,
            )

        # Invariant: route=direct MUST carry a non-empty direct_reply — the
        # gateway short-circuits the pool entirely for this role and has
        # nothing to send if the template is missing. Fall through to
        # pool.acquire(role="direct") would hit NotImplementedError since
        # "direct" isn't a real sub-pool. Demote to customer instead.
        agent_role = parsed["route_to"]
        agent_direct_reply = parsed.get("direct_reply")
        if agent_role == "direct" and not agent_direct_reply:
            log.warning(
                "triage agent returned route=direct without 回复: field "
                "(intent=%s) — demoting to customer",
                parsed.get("intent"),
            )
            agent_role = "customer"

        # Triage-agent output doesn't carry a tier — derive it from the
        # yaml config of the claimed intent. Unknown intents (agent
        # hallucinates a new one) fall back to the fast_result's tier.
        agent_tier: str | None = None
        intent_cfg = self._classifier._intents.get(parsed["intent"])
        if intent_cfg and intent_cfg.get("model_tier"):
            agent_tier = intent_cfg["model_tier"]
        else:
            agent_tier = fast_result.model_tier.value

        return TriageDecision(
            role=agent_role,
            confidence=parsed["confidence"],
            source="triage_agent",
            intent=parsed["intent"],
            detected_language=detected_language,
            summary=parsed.get("summary"),
            needs_operator_notice=parsed["confidence"] < self._thresholds["medium"],
            previous_role=previous_role,
            direct_reply=agent_direct_reply,
            tier=agent_tier,
        )

    def should_use_placeholder(self, decision: RoutingDecision) -> bool:
        """Whether to send a placeholder message before the full response.

        Placeholder is used when routing to slow model tier, giving the
        customer immediate feedback while the full response generates.
        """
        return decision.model_tier == ModelTier.SLOW
