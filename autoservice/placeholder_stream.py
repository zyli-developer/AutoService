"""Placeholder-then-stream reply flow (占位续写).

T1A.6 产出 | 2026-04-16
关联: PRD α2 / US-2.2 / LocalEngine send_message + edit_message

Flow:
1. Customer sends message
2. ModelRouter decides fast/slow path
3. If slow path → send placeholder via fast model (< 1s)
4. Slow model generates full response (5-15s)
5. edit_message replaces placeholder with full content
6. EventBus emits message.edited → frontend renders in-place update

Key integration points:
- ConversationEngine.send_message() — send placeholder
- ConversationEngine.edit_message() — replace with full content
- ModelRouter.should_use_placeholder() — decide if placeholder needed
- sentiment.parse_sentiment() — strip sentiment annotation before display
- Timer sla_placeholder — track placeholder SLA
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Protocol, Optional, Callable, Awaitable

from autoservice.conversation_engine.types import ConversationMode
from autoservice.model_router import ModelRouter, RoutingDecision, ModelTier
from autoservice.sentiment import parse_sentiment, update_sentiment, Sentiment

logger = logging.getLogger("autoservice.placeholder_stream")


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class PlaceholderConfig:
    """Configuration for placeholder behavior."""
    placeholder_template: str = "正在为您查询，请稍候..."
    placeholder_template_en: str = "Looking into this for you..."
    thinking_indicator: str = "..."
    max_fast_response_ms: int = 1000
    max_slow_response_ms: int = 30000


@dataclass
class ReplyContext:
    """Context for a single reply flow."""
    conversation_id: str
    customer_message: str
    routing: RoutingDecision
    detected_language: Optional[str] = None
    placeholder_message_id: Optional[str] = None
    previous_sentiment: Optional[Sentiment] = None


@dataclass
class ReplyResult:
    """Result of a completed reply flow."""
    conversation_id: str
    message_id: str
    content: str
    used_placeholder: bool
    sentiment: Optional[Sentiment] = None
    sentiment_deteriorated: bool = False


# ---------------------------------------------------------------------------
# Engine interface (subset of ConversationEngine protocol)
# ---------------------------------------------------------------------------

class EngineInterface(Protocol):
    async def send_message(
        self, conversation_id: str, *, source: str, content: str, **kwargs
    ) -> object: ...

    async def edit_message(
        self, conversation_id: str, message_id: str, *, new_content: str, edited_by: str
    ) -> object: ...

    async def switch_mode(
        self,
        conversation_id: str,
        target: ConversationMode,
        *,
        triggered_by: str,
        trigger: str,
    ) -> None: ...


# Model call interface
ModelCallFn = Callable[[str, str, str], Awaitable[str]]
# (role, conversation_id, message) -> response


# ---------------------------------------------------------------------------
# PlaceholderStreamFlow
# ---------------------------------------------------------------------------

class PlaceholderStreamFlow:
    """Orchestrates the placeholder-then-stream reply pattern.

    Usage:
        flow = PlaceholderStreamFlow(engine, router, fast_call, slow_call)
        result = await flow.handle_customer_message(conv_id, message)
    """

    def __init__(
        self,
        engine: EngineInterface,
        router: ModelRouter,
        fast_model_call: ModelCallFn,
        slow_model_call: ModelCallFn,
        config: PlaceholderConfig | None = None,
    ):
        self._engine = engine
        self._router = router
        self._fast_call = fast_model_call
        self._slow_call = slow_model_call
        self._config = config or PlaceholderConfig()

    async def handle_customer_message(
        self,
        conversation_id: str,
        message: str,
        detected_language: Optional[str] = None,
        previous_sentiment: Optional[Sentiment] = None,
    ) -> ReplyResult:
        """Handle incoming customer message with placeholder-stream pattern."""

        # Step 1: Route
        routing = self._router.route(message, detected_language)
        ctx = ReplyContext(
            conversation_id=conversation_id,
            customer_message=message,
            routing=routing,
            detected_language=detected_language,
            previous_sentiment=previous_sentiment,
        )

        # Step 2: Fast or slow path
        if self._router.should_use_placeholder(routing):
            return await self._slow_path_with_placeholder(ctx)
        else:
            return await self._fast_path(ctx)

    async def _fast_path(self, ctx: ReplyContext) -> ReplyResult:
        """Direct response via fast model — no placeholder needed."""
        raw_response = await self._fast_call(
            ctx.routing.agent_role.value,
            ctx.conversation_id,
            ctx.customer_message,
        )

        sentiment_result, clean_content = parse_sentiment(raw_response)
        if sentiment_result and ctx.previous_sentiment is not None:
            update_sentiment(sentiment_result, ctx.previous_sentiment)

        msg = await self._engine.send_message(
            ctx.conversation_id,
            source=f"agent:{ctx.routing.agent_role.value}",
            content=clean_content,
        )

        return ReplyResult(
            conversation_id=ctx.conversation_id,
            message_id=msg.id,
            content=clean_content,
            used_placeholder=False,
            sentiment=sentiment_result.sentiment if sentiment_result else None,
            sentiment_deteriorated=sentiment_result.deteriorated if sentiment_result else False,
        )

    async def _slow_path_with_placeholder(self, ctx: ReplyContext) -> ReplyResult:
        """Send placeholder first, then replace with full response."""

        # Step 1: Send placeholder immediately
        placeholder_text = self._get_placeholder_text(ctx.detected_language)
        placeholder_msg = await self._engine.send_message(
            ctx.conversation_id,
            source=f"agent:{ctx.routing.agent_role.value}",
            content=placeholder_text,
            metadata={"is_placeholder": True},
        )
        ctx.placeholder_message_id = placeholder_msg.id
        logger.debug(
            "Placeholder sent: conv=%s msg=%s",
            ctx.conversation_id, placeholder_msg.id,
        )

        # Step 2: Generate full response via slow model (with timeout)
        timeout_s = self._config.max_slow_response_ms / 1000.0
        try:
            raw_response = await asyncio.wait_for(
                self._slow_call(
                    ctx.routing.agent_role.value,
                    ctx.conversation_id,
                    ctx.customer_message,
                ),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            # Placeholder timed out — escalate to human (copilot mode)
            logger.warning(
                "Slow model timed out after %.1fs: conv=%s — escalating to human",
                timeout_s, ctx.conversation_id,
            )
            escalation_text = "正在为您转接人工客服"
            await self._engine.switch_mode(
                ctx.conversation_id,
                ConversationMode.COPILOT,
                triggered_by="system:placeholder_timeout",
                trigger="placeholder_timeout",
            )
            edited_msg = await self._engine.edit_message(
                ctx.conversation_id,
                placeholder_msg.id,
                new_content=escalation_text,
                edited_by="system:placeholder_timeout",
            )
            return ReplyResult(
                conversation_id=ctx.conversation_id,
                message_id=edited_msg.id,
                content=escalation_text,
                used_placeholder=True,
            )

        sentiment_result, clean_content = parse_sentiment(raw_response)
        if sentiment_result and ctx.previous_sentiment is not None:
            update_sentiment(sentiment_result, ctx.previous_sentiment)

        # Step 3: Edit placeholder with full content
        edited_msg = await self._engine.edit_message(
            ctx.conversation_id,
            placeholder_msg.id,
            new_content=clean_content,
            edited_by=f"agent:{ctx.routing.agent_role.value}",
        )
        logger.debug(
            "Placeholder replaced: conv=%s msg=%s len=%d",
            ctx.conversation_id, placeholder_msg.id, len(clean_content),
        )

        return ReplyResult(
            conversation_id=ctx.conversation_id,
            message_id=edited_msg.id,
            content=clean_content,
            used_placeholder=True,
            sentiment=sentiment_result.sentiment if sentiment_result else None,
            sentiment_deteriorated=sentiment_result.deteriorated if sentiment_result else False,
        )

    def _get_placeholder_text(self, detected_language: Optional[str] = None) -> str:
        if detected_language and detected_language.startswith("en"):
            return self._config.placeholder_template_en
        return self._config.placeholder_template
