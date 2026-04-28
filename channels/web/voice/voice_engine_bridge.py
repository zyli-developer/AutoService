"""LLM bridge for voice sessions, backed by AutoService's cc_pool.

Replaces cc-openclaw's ActorBridge (which connected to a separate
channel_server actor over WebSocket). Wraps ``cc_pool.session_query`` so
voice Session/SplitSession can fetch agent text replies for each user
turn. The same ``cc_pool`` instance services /ws/customer chat replies,
so voice and chat share routing / per-tenant KB / model tier behavior.

Greeting / comfort text generation is NOT done here — those are static
strings configured per session and spoken via Doubao TTS directly.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path
from typing import Awaitable, Callable

log = logging.getLogger(__name__)


# Strip XML-style "system reminder" tags that Claude occasionally leaks
# into its replies when the prompt structure resembles a system block.
# Symptom: voice TTS reads "您好...  end-of-system-reminder" as the
# closing tag becomes audible. Catches both opening and closing forms,
# any case, with optional attributes / extra whitespace.
_LEAKED_TAG_RE = re.compile(
    r"</?\s*(?:system[_-]?reminder|voice[_-]?mode[_-]?rules?|"
    r"ip[_-]?reminder|user[_-]?prompt[_-]?submit[_-]?hook)"
    r"\s*[^>]*>",
    re.IGNORECASE,
)


def _sanitize_reply(text: str) -> str:
    """Strip leaked system-block tags + tidy whitespace."""
    if not text:
        return text
    cleaned = _LEAKED_TAG_RE.sub("", text)
    # Collapse triple+ blank lines that the strip might leave behind.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _load_voice_soul(tenant_id: str | None) -> str | None:
    """Return the voice-mode soul markdown for ``tenant_id`` if present.

    Voice mode imposes constraints that would degrade text chat (≤ 20 zh
    chars per sentence, no markdown, ≤ 15 s reply), so we keep voice
    instructions in a SEPARATE file from ``customer_soul.md`` and inject
    it as a first-turn prompt prefix only when the user opens voice.

    Lookup order (mirrors :func:`autoservice.cc_pool._load_soul`):

      1. ``<cwd>/.autoservice/sandbox/<tenant_id>/souls/customer_soul.voice.md``
      2. ``<cwd>/plugins/<tenant_id>/souls/customer_soul.voice.md``
      3. ``None`` (no voice soul → bridge runs without prefix injection)

    Path-traversal guards mirror the pool helper.
    """
    if not tenant_id:
        return None
    if "/" in tenant_id or "\\" in tenant_id or ".." in tenant_id:
        log.warning(
            "Rejecting suspicious tenant_id for voice soul: %r", tenant_id,
        )
        return None
    cwd = Path.cwd()
    candidates = [
        cwd / ".autoservice" / "sandbox" / tenant_id / "souls"
            / "customer_soul.voice.md",
        cwd / "plugins" / tenant_id / "souls" / "customer_soul.voice.md",
    ]
    for path in candidates:
        try:
            if path.is_file():
                return path.read_text(encoding="utf-8")
        except OSError:
            continue
    return None


class VoiceEngineBridge:
    """Per-session LLM bridge. One instance per voice WebSocket call.

    The ``conversation_id`` is sticky-bound to a CC instance via
    ``cc_pool.session_query`` so multi-turn voice conversations preserve
    context across user utterances. The same ``conversation_id`` is also
    used by the chat-side ``/ws/customer`` flow, which means a user who
    voice-talks then types continues with the same agent context.
    """

    def __init__(
        self,
        *,
        conversation_id: str,
        tenant_id: str | None = None,
        tier: str = "fast",
    ) -> None:
        self.conversation_id = conversation_id
        self.tenant_id = tenant_id
        self.tier = tier
        # Per-bridge unique Claude SDK session_id. The cc_pool sticky
        # binding is keyed by ``conversation_id`` so we still hit the
        # same warm instance (tenant soul + KB tool already injected),
        # but Claude SDK keeps separate conversation threads per
        # session_id — so a fresh VoiceEngineBridge (= fresh /ws/voice
        # connect) starts a clean Claude thread. Without this, a
        # disconnect while the bot was mid-reply leaves that turn in
        # Claude's history; the next connect's first turn would inherit
        # the unfinished context and Claude would "continue" / echo
        # the previous reply.
        self._cc_session_id = uuid.uuid4().hex
        # First-turn voice-soul prefix injection. Loaded once at
        # construction so a missing file or read error during startup
        # doesn't penalize subsequent turns. Stays in memory until the
        # session ends — not large (~6 KB).
        self._voice_soul = _load_voice_soul(tenant_id)
        self._voice_soul_injected = False
        if self._voice_soul:
            log.info(
                "VoiceEngineBridge: voice soul loaded (tenant=%s, %d bytes)",
                tenant_id, len(self._voice_soul),
            )

    async def query(
        self,
        text: str,
        *,
        timeout: float = 60.0,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Single user turn → assistant reply text.

        Returns the concatenated text of all ``AssistantMessage`` content
        blocks emitted by ``CCPool.session_query``. Tool-call blocks and
        metadata are dropped — voice TTS only consumes plain text.

        ``on_chunk`` (optional): if provided, awaited for each text
        increment as soon as it arrives — enables streaming TTS so the
        bot starts speaking before the full reply is generated. Compatible
        with both pool modes:

        * ``include_partial_messages=True`` → SDK yields ``StreamEvent``
          deltas; each delta is forwarded to ``on_chunk`` immediately.
        * ``include_partial_messages=False`` → SDK yields a single
          ``AssistantMessage`` with the full text; ``on_chunk`` fires once
          with the full text at the end. Caller still benefits from the
          single-callback API even without partial-message streaming.

        ``on_chunk`` callbacks are awaited serially in arrival order so
        downstream (e.g. ``chat_tts_text``) sees coherent text fragments.
        """
        from autoservice.cc_pool import get_pool
        pool = await get_pool()

        # First-turn prefix injection. Voice soul (e.g., "≤ 20 chars per
        # sentence, no markdown, ≤ 15 s reply") is delivered ONCE; CC's
        # sticky session retains the constraint across subsequent turns.
        #
        # Plain natural-language framing — earlier "[Voice mode]" /
        # "---" / "User said:" framing made Claude occasionally emit
        # </system-reminder> closing tags as if it were inside a system
        # block. The sanitizer below catches stragglers, but cleaner
        # framing prevents the leak in the first place.
        if self._voice_soul and not self._voice_soul_injected:
            prompt = (
                "The user has just opened a voice call. The conversation "
                "will be played aloud to them, so please follow the voice-"
                "mode guidelines below for the rest of this session. Do "
                "not echo or quote these guidelines back; just apply them.\n"
                "\n"
                f"{self._voice_soul}\n"
                "\n"
                "Now please respond in voice-mode style. The user just "
                f"said:\n{text}"
            )
            self._voice_soul_injected = True
            log.info(
                "VoiceEngineBridge: injecting voice soul prefix on first turn "
                "(prompt grew from %d to %d chars)",
                len(text), len(prompt),
            )
        else:
            prompt = text

        async def _drain() -> str:
            try:
                from claude_agent_sdk.types import StreamEvent
            except Exception:
                StreamEvent = None  # type: ignore[assignment]

            full = ""
            saw_stream_text = False
            iterator = pool.session_query(
                self.conversation_id,
                prompt,
                tenant_id=self.tenant_id,
                tier=self.tier,
                # Per-voice-call session — see __init__ comment.
                session_id=self._cc_session_id,
            )
            async for item in iterator:
                # Streaming: SDK emits StreamEvent with content_block_delta
                # text_delta when include_partial_messages=True.
                if StreamEvent is not None and isinstance(item, StreamEvent):
                    ev = getattr(item, "event", None) or {}
                    if ev.get("type") == "content_block_delta":
                        delta = ev.get("delta") or {}
                        if delta.get("type") == "text_delta":
                            chunk = delta.get("text") or ""
                            if chunk:
                                saw_stream_text = True
                                full += chunk
                                if on_chunk is not None:
                                    await on_chunk(chunk)
                    continue

                # Otherwise duck-type as a message (real AssistantMessage
                # or any test double exposing .content). Skip when we
                # already streamed deltas — emitting the full text now
                # would double-count.
                if saw_stream_text:
                    continue
                content = getattr(item, "content", None)
                if content is None:
                    continue
                for block in content:
                    block_text = getattr(block, "text", None)
                    if isinstance(block_text, str) and block_text:
                        full += block_text
                        if on_chunk is not None:
                            await on_chunk(block_text)
            return full

        try:
            full = await asyncio.wait_for(_drain(), timeout=timeout)
        except asyncio.TimeoutError:
            log.warning(
                "VoiceEngineBridge.query timed out after %.1fs (conv=%s)",
                timeout, self.conversation_id,
            )
            raise
        # Strip leaked system-block tags before returning. on_chunk
        # callers see the raw deltas — they're transient (used for
        # typewriter/streaming) and the final persisted text comes
        # from this sanitized return value.
        sanitized = _sanitize_reply(full)
        if sanitized != full:
            log.info(
                "VoiceEngineBridge: stripped leaked tags from reply "
                "(was %d chars, now %d)", len(full), len(sanitized),
            )
        return sanitized

    async def close(self) -> None:
        """Release the sticky CC binding so the next call starts fresh.

        Best-effort: if CCPool doesn't expose end_session at this
        revision (older versions auto-expire instead) we silently skip.
        """
        try:
            from autoservice.cc_pool import get_pool
            pool = await get_pool()
            end_session = getattr(pool, "end_session", None)
            if end_session is None:
                return
            await end_session(self.conversation_id)
        except Exception:
            log.debug(
                "VoiceEngineBridge.close: end_session failed (conv=%s)",
                self.conversation_id, exc_info=True,
            )
