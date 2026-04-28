"""Pre-triage instant acknowledgement bubble.

Spec: docs/superpowers/specs/2026-04-26-instant-ack-multi-bubble-queue-design.md §5
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from fastapi import WebSocket

    from autoservice.conversation_engine import ConversationEngine
    from autoservice.conversation_engine.types import Message

log = logging.getLogger("autoservice.gateway.agent_ack")

#: Path to the bilingual ack template bank.
_TEMPLATES_PATH: Path = Path(__file__).parent / "ack_templates.yaml"

#: CJK + hangul + hiragana/katakana unicode ranges. Any one match → zh.
_CJK_RE = re.compile(r"[　-鿿가-힯぀-ヿ]")

#: Length-based ack-skip thresholds. Below these (zh/en respectively),
#: the ack is skipped to avoid duplicate-greeting bubbles. See spec §5.1.1.
_DEFAULT_SKIP_LEN_ZH = int(os.getenv("ACK_SKIP_LEN_ZH", "8"))
_DEFAULT_SKIP_LEN_EN = int(os.getenv("ACK_SKIP_LEN_EN", "15"))

#: Jitter range (server-side schedule). Wire-observable adds RTT.
_DEFAULT_DELAY_MIN_MS = int(os.getenv("ACK_DELAY_MIN_MS", "100"))
_DEFAULT_DELAY_MAX_MS = int(os.getenv("ACK_DELAY_MAX_MS", "300"))

#: Cinnox is the demo target — bias lang to zh on ambiguous input.
_ZH_DEFAULT_TENANTS: frozenset[str] = frozenset({"cinnox"})

_templates_cache: dict[str, list[str]] | None = None


def _load_templates() -> dict[str, list[str]]:
    """Load + cache the ack template bank. Errors fall back to a single
    static line per language so the main pipeline never breaks."""
    global _templates_cache
    if _templates_cache is not None:
        return _templates_cache
    try:
        with _TEMPLATES_PATH.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if "zh" not in data or "en" not in data:
            raise ValueError("ack_templates.yaml missing zh or en keys")
        _templates_cache = {"zh": list(data["zh"]), "en": list(data["en"])}
    except Exception:
        log.exception(
            "ack_templates.yaml failed to load — using static fallback",
        )
        _templates_cache = {"zh": ["好的"], "en": ["OK"]}
    return _templates_cache


def detect_lang(customer_text: str, tenant_id: str | None = None) -> str:
    """Return 'zh' or 'en' from a regex scan over CJK ranges.

    For ambiguous input (no CJK chars and only punctuation/symbols / no ASCII
    letters), tenants in ``_ZH_DEFAULT_TENANTS`` default to ``zh``.
    """
    if _CJK_RE.search(customer_text):
        return "zh"
    if tenant_id in _ZH_DEFAULT_TENANTS:
        # If the text contains zero alphabet characters, we can't classify
        # by alphabet — bias to zh for the cinnox demo.
        if not any(c.isalpha() for c in customer_text):
            return "zh"
    return "en"


def should_skip_ack(
    customer_text: str,
    lang: str,
    *,
    skip_len_zh: int = _DEFAULT_SKIP_LEN_ZH,
    skip_len_en: int = _DEFAULT_SKIP_LEN_EN,
) -> bool:
    """Length-based skip heuristic — see §5.1.1.

    Short messages overwhelmingly correlate with greetings/thanks/byes,
    where triage will fire a direct-reply that would duplicate the ack.
    """
    stripped_len = len(customer_text.strip())
    if lang == "zh":
        return stripped_len < skip_len_zh
    return stripped_len < skip_len_en


def pick_ack_text(lang: str, *, rng: random.Random | None = None) -> str:
    bank = _load_templates()
    pool = bank.get(lang) or bank.get("en") or ["OK"]
    r = rng or random
    return r.choice(pool)


async def send_pretriage_ack(
    engine: "ConversationEngine",
    conv_id: str,
    ws: "WebSocket",
    customer_text: str,
    *,
    tenant_id: str | None = None,
    delay_min_ms: int = _DEFAULT_DELAY_MIN_MS,
    delay_max_ms: int = _DEFAULT_DELAY_MAX_MS,
    rng: random.Random | None = None,
) -> "Message | None":
    """Emit a pre-triage acknowledgement bubble.

    Returns the persisted ``Message`` on success, or ``None`` if the ack
    was skipped (length heuristic) OR if persistence/WS push failed
    (errors are logged, not raised — main pipeline must not break).
    """
    if os.getenv("INSTANT_ACK_ENABLED", os.getenv("PLACEHOLDER_ENABLED", "1")) != "1":
        # Both new var and the deprecated alias respect "0" → no-op.
        return None
    lang = detect_lang(customer_text, tenant_id=tenant_id)
    if should_skip_ack(customer_text, lang):
        return None

    # Schedule the small humanizing delay.
    r = rng or random
    delay_ms = r.uniform(delay_min_ms, delay_max_ms)
    await asyncio.sleep(delay_ms / 1000.0)

    text = pick_ack_text(lang, rng=r)
    try:
        msg = await engine.send_message(
            conv_id, source="agent", content=text, metadata={"is_ack": True},
        )
    except Exception:
        log.exception("Pre-triage ack persist failed conv=%s", conv_id)
        return None

    # Push frame to customer's WS + broadcast to operator squad. Failures
    # are swallowed — see spec §5.4.
    try:
        from autoservice.gateway.message_router import _message_frame, _broadcast_to_squad
        frame = _message_frame(msg)
        try:
            await ws.send_json(frame)
        except Exception:
            log.warning("Pre-triage ack ws push failed conv=%s", conv_id)
        try:
            await _broadcast_to_squad(frame, conv_id, exclude_ws=ws)
        except Exception:
            log.debug("Pre-triage ack broadcast failed conv=%s", conv_id)
    except Exception:
        log.exception("Pre-triage ack frame build failed conv=%s", conv_id)
    return msg
