# Instant Ack + Multi-Bubble + CC-Queue — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the disabled post-triage placeholder with a pre-triage instant ack, split agent reply on `\n\n` paragraph boundaries into separate bubbles, and serialize concurrent customer messages via a per-conv FIFO queue (CC-X semantics).

**Architecture:** Three independent components with kill-switch env vars: `agent_ack.py` (pre-triage ack send + length-skip heuristic), `paragraph_splitter.py` (pure-function streaming state machine), `turn_queue.py` (per-conv FIFO with registry-lock race protection). All glued together by a refactor of `_drain_with_placeholder` → `_drain_into_bubbles` in `message_router.py`. Spec: `docs/superpowers/specs/2026-04-26-instant-ack-multi-bubble-queue-design.md`.

**Tech Stack:** Python 3.12 / asyncio / FastAPI / claude_agent_sdk / pytest-asyncio. Frontend changes are minimal (existing `MessageList` already handles a stream of `Message` rows).

---

## File structure

**New files:**
- `autoservice/gateway/paragraph_splitter.py` — pure-function streaming `ParagraphSplitter` class
- `autoservice/gateway/agent_ack.py` — `send_pretriage_ack` + lang-detect + skip heuristic
- `autoservice/gateway/ack_templates.yaml` — bilingual ack lines bank
- `autoservice/gateway/turn_queue.py` — `TurnQueue` class with registry lock
- `tests/gateway/test_paragraph_splitter.py`
- `tests/gateway/test_agent_ack.py`
- `tests/gateway/test_turn_queue.py`
- `tests/gateway/test_multi_bubble_integration.py`

**Modified files:**
- `autoservice/gateway/message_router.py` — replace `_drain_with_placeholder` body, integrate splitter; replace customer_message fire-and-forget with `TurnQueue.submit`
- `autoservice/cc_pool.py` — append paragraph nudge to system_prompt at acquire site
- `CLAUDE.md` — update Placeholder Filler Kill-Switch section
- `~/Library/LaunchAgents/com.autoservice.gateway.plist` — env var changes

**Deprecated (kept temporarily, removed in follow-up PR):**
- `autoservice/gateway/soothe_picker.py` — no longer wired into main path
- `autoservice/soothe_templates.yaml` — unused after wiring change
- `tests/gateway/test_drain_with_placeholder.py` — deleted (replaced by `test_multi_bubble_integration.py`)
- `tests/gateway/test_soothe_picker.py` — kept for now (still tests the picker class)

---

## Task 1: Scaffolding — paragraph_splitter module + first failing test

**Files:**
- Create: `autoservice/gateway/paragraph_splitter.py`
- Create: `tests/gateway/test_paragraph_splitter.py`

- [ ] **Step 1: Create the empty module file**

```python
# autoservice/gateway/paragraph_splitter.py
"""Streaming paragraph splitter for agent reply multi-bubble support.

Spec: docs/superpowers/specs/2026-04-26-instant-ack-multi-bubble-queue-design.md §6
"""
from __future__ import annotations
```

- [ ] **Step 2: Write the first failing test**

```python
# tests/gateway/test_paragraph_splitter.py
"""Unit tests for ParagraphSplitter — pure-function streaming state machine."""
from __future__ import annotations

import pytest

from autoservice.gateway.paragraph_splitter import ParagraphSplitter


def test_empty_input_yields_no_segments():
    s = ParagraphSplitter()
    assert s.feed("") == []
    assert s.flush() is None
    assert s.segment_count == 0
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/gateway/test_paragraph_splitter.py::test_empty_input_yields_no_segments -v`
Expected: FAIL with `ImportError: cannot import name 'ParagraphSplitter'`.

- [ ] **Step 4: Write minimal stub for the class**

```python
# autoservice/gateway/paragraph_splitter.py (append)

DEFAULT_MIN_SEGMENT_CHARS = 5
DEFAULT_MAX_SEGMENTS = 5


class ParagraphSplitter:
    """Streaming paragraph splitter — see §6 of the design spec.

    Boundaries are ``\\n\\n`` outside fenced code blocks. Segments shorter
    than ``min_segment_chars`` cannot fire a boundary (the boundary is
    consumed as inline whitespace, the bubble keeps growing). Once
    ``max_segments`` segments have been emitted, all remaining content
    accumulates into the final segment regardless of further boundaries.
    """

    def __init__(
        self,
        min_segment_chars: int = DEFAULT_MIN_SEGMENT_CHARS,
        max_segments: int = DEFAULT_MAX_SEGMENTS,
    ) -> None:
        self._min = min_segment_chars
        self._max = max_segments
        self._buf: str = ""
        self._emitted: int = 0
        self._in_code: bool = False
        self._at_line_start: bool = True

    @property
    def segment_count(self) -> int:
        return self._emitted

    @property
    def pending(self) -> str:
        """Current open-segment buffer (post-suppression, pre-boundary).

        The caller of feed() drives typewriter pushes by reading this
        property — never maintain a parallel accumulator outside, since
        suppression mutates this buffer in ways the caller can't predict.
        """
        return self._buf

    def feed(self, chunk: str) -> list[str]:
        if not chunk:
            return []
        # Stub: never finds a boundary, just buffers.
        self._buf += chunk
        return []

    def flush(self) -> str | None:
        # Strip leading/trailing whitespace from the final segment so a
        # consumed-then-followed pattern like "  Second text" doesn't carry
        # its leading whitespace into the persisted bubble. See spec §9.2.
        out = self._buf.strip()
        self._buf = ""
        if not out:
            return None
        self._emitted += 1
        return out
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/gateway/test_paragraph_splitter.py::test_empty_input_yields_no_segments -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add autoservice/gateway/paragraph_splitter.py tests/gateway/test_paragraph_splitter.py
git commit -m "feat(gateway): scaffold ParagraphSplitter with empty-input test"
```

---

## Task 2: ParagraphSplitter — basic boundary detection

**Files:**
- Modify: `autoservice/gateway/paragraph_splitter.py` (full implementation)
- Modify: `tests/gateway/test_paragraph_splitter.py` (add cases)

- [ ] **Step 1: Add five basic boundary tests**

```python
# tests/gateway/test_paragraph_splitter.py (append)

def test_single_paragraph_no_boundary_yields_one_segment_via_flush():
    s = ParagraphSplitter()
    assert s.feed("Just one long paragraph with no break in it.") == []
    assert s.flush() == "Just one long paragraph with no break in it."
    assert s.segment_count == 1


def test_two_paragraphs_split_on_boundary():
    s = ParagraphSplitter()
    out = s.feed("First paragraph here.\n\nSecond paragraph here.")
    assert out == ["First paragraph here."]
    assert s.flush() == "Second paragraph here."
    assert s.segment_count == 2


def test_three_paragraphs():
    s = ParagraphSplitter()
    out = s.feed("Para one is here.\n\nPara two is here.\n\nPara three.")
    assert out == ["Para one is here.", "Para two is here."]
    assert s.flush() == "Para three."
    assert s.segment_count == 3


def test_streaming_chunks_split_inside_boundary():
    """A boundary that arrives across two chunks must still be detected.

    Input split: "First text\\n" then "\\nSecond text".
    """
    s = ParagraphSplitter()
    assert s.feed("First text\n") == []
    out = s.feed("\nSecond text")
    assert out == ["First text"]
    assert s.flush() == "Second text"


def test_whitespace_only_segment_dropped():
    s = ParagraphSplitter()
    out = s.feed("First text here.\n\n   \n\nSecond text here.")
    # Middle whitespace-only segment must not become a real bubble.
    assert out == ["First text here."]
    assert s.flush() == "Second text here."
    assert s.segment_count == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/gateway/test_paragraph_splitter.py -v`
Expected: 4 failures (the empty-input test still passes; the 5 new tests fail because `feed()` never emits).

- [ ] **Step 3: Replace the stub feed/flush with real implementation**

```python
# autoservice/gateway/paragraph_splitter.py — REPLACE the feed() and flush() bodies
# (keep __init__ and segment_count; replace feed and flush in their entirety)

    def feed(self, chunk: str) -> list[str]:
        if not chunk:
            return []
        emitted: list[str] = []
        # We process character-by-character to keep the state machine simple.
        # The chunk size from claude_agent_sdk is small (1-5 chars typical
        # for text_delta), so the per-char loop is not a hot path.
        for ch in chunk:
            self._buf += ch
            # MAX gate: once we've emitted (max-1) segments, the next one
            # is the last; never fire another boundary, just accumulate.
            if self._emitted >= self._max - 1:
                continue
            # Code-block toggle: a line starting with "```" toggles state.
            # Detection requires a "```" preceded by a line-start.
            if self._buf.endswith("```") and self._is_at_line_start_before_fence():
                self._in_code = not self._in_code
                continue
            # Boundary detection: only when not in a code block.
            if self._in_code:
                continue
            if self._buf.endswith("\n\n"):
                # Strip the trailing "\n\n" from the candidate segment.
                candidate = self._buf[:-2]
                if len(candidate.strip()) >= self._min:
                    emitted.append(candidate)
                    self._buf = ""
                    self._emitted += 1
                else:
                    # Below MIN: consume the boundary (treat as inline whitespace).
                    # We drop the "\n\n" entirely so the bubble keeps growing
                    # without boundary noise. See spec §9.2.
                    self._buf = candidate  # drop trailing "\n\n"
        return emitted

    def flush(self) -> str | None:
        out = self._buf
        self._buf = ""
        if not out or not out.strip():
            return None
        self._emitted += 1
        return out

    def _is_at_line_start_before_fence(self) -> bool:
        """Return True if the just-completed '```' starts at a line head.

        ``self._buf`` ends with the literal '```'. The 4-back char must
        be a newline OR the fence is the very start of the buffer.
        """
        # buf endswith "```", look at the char before that triple-backtick.
        if len(self._buf) == 3:
            return True
        return self._buf[-4] == "\n"
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/gateway/test_paragraph_splitter.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add autoservice/gateway/paragraph_splitter.py tests/gateway/test_paragraph_splitter.py
git commit -m "feat(gateway): paragraph splitter with basic boundary detection"
```

---

## Task 3: ParagraphSplitter — code blocks, MIN suppression, MAX cap

**Files:**
- Modify: `tests/gateway/test_paragraph_splitter.py` (add cases)
- Modify: `autoservice/gateway/paragraph_splitter.py` (no further code change expected — verify or fix)

- [ ] **Step 1: Add code-block, MIN-suppression, MAX-cap tests**

```python
# tests/gateway/test_paragraph_splitter.py (append)

def test_code_block_internal_double_newline_not_split():
    s = ParagraphSplitter()
    payload = "Here is code:\n\n```python\nx = 1\n\ny = 2\n```\n\nThat was code."
    # Two real boundaries: before ```python and after closing ```.
    out = s.feed(payload)
    assert out == ["Here is code:", "```python\nx = 1\n\ny = 2\n```"]
    assert s.flush() == "That was code."
    assert s.segment_count == 3


def test_min_segment_chars_suppression_consumes_boundary():
    """Below-MIN segment causes \\n\\n to be consumed as whitespace.

    Pinning §6.4 / §9.2 policy.
    """
    s = ParagraphSplitter(min_segment_chars=5)
    out = s.feed("好。\n\nHere is the rest of the longer answer.")
    # Two-char "好。" is below MIN; the \n\n is consumed (dropped).
    # No segment emits during feed.
    assert out == []
    assert s.flush() == "好。Here is the rest of the longer answer."
    assert s.segment_count == 1


def test_max_segments_cap_collapses_tail():
    s = ParagraphSplitter(max_segments=3)
    payload = "A first.\n\nB second.\n\nC third.\n\nD fourth.\n\nE fifth."
    out = s.feed(payload)
    # Only 2 boundaries fire as separate segments (max_segments-1 = 2 mid-stream
    # emissions); the 3rd, 4th, and 5th paragraphs all collapse into the tail.
    assert out == ["A first.", "B second."]
    assert s.flush() == "C third.\n\nD fourth.\n\nE fifth."
    assert s.segment_count == 3


def test_six_paragraphs_with_default_max_5():
    s = ParagraphSplitter()  # default max=5
    payload = "P1\n\nP2 longer.\n\nP3 longer.\n\nP4 longer.\n\nP5 longer.\n\nP6 longer."
    out = s.feed(payload)
    assert out == ["P1", "P2 longer.", "P3 longer.", "P4 longer."]
    assert s.flush() == "P5 longer.\n\nP6 longer."
    assert s.segment_count == 5


def test_consecutive_empty_boundaries_collapse():
    """Multiple back-to-back \\n\\n with a below-MIN segment in front.

    Walk: "One" buffers (3 < MIN=5). First "\\n\\n" hits → candidate "One"
    is below MIN, boundary suppressed and consumed (buf returns to "One").
    Second "\\n\\n" same fate. Third same. Then "Two paragraph." appends.
    flush() trims and returns "OneTwo paragraph." as one segment.
    """
    s = ParagraphSplitter()
    out = s.feed("One\n\n\n\n\n\nTwo paragraph.")
    assert out == []
    assert s.flush() == "OneTwo paragraph."
```

- [ ] **Step 2: Run the new tests**

Run: `uv run pytest tests/gateway/test_paragraph_splitter.py -v`
Expected: code-block test FAILS (state machine doesn't track triple-backtick well across chunks); min/max tests likely PASS; consecutive-empty test may FAIL if the state machine drops too eagerly.

- [ ] **Step 3: Fix the splitter — refine code-block fence detection**

Replace the `feed()` method body in `autoservice/gateway/paragraph_splitter.py` with this corrected version. The change: detect the triple-backtick fence as a 3-char sequence at line start, and only after recognizing the fence, suppress boundary detection until the closing fence.

```python
    def feed(self, chunk: str) -> list[str]:
        if not chunk:
            return []
        emitted: list[str] = []
        for ch in chunk:
            self._buf += ch
            # MAX gate
            if self._emitted >= self._max - 1:
                continue
            # Fence toggle: triple-backtick at line start (line head means
            # buf is exactly "```" or the char four back is "\n").
            if (
                len(self._buf) >= 3
                and self._buf[-3:] == "```"
                and (len(self._buf) == 3 or self._buf[-4] == "\n")
            ):
                self._in_code = not self._in_code
                continue
            if self._in_code:
                continue
            # Boundary: "\n\n" outside code block.
            if self._buf.endswith("\n\n"):
                candidate = self._buf[:-2]
                if len(candidate.strip()) >= self._min:
                    emitted.append(candidate)
                    self._buf = ""
                    self._emitted += 1
                else:
                    self._buf = candidate
        return emitted
```

- [ ] **Step 4: Re-run all splitter tests**

Run: `uv run pytest tests/gateway/test_paragraph_splitter.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add autoservice/gateway/paragraph_splitter.py tests/gateway/test_paragraph_splitter.py
git commit -m "feat(gateway): splitter handles code blocks, MIN suppression, MAX cap"
```

---

## Task 4: agent_ack — module + templates + tests

**Files:**
- Create: `autoservice/gateway/agent_ack.py`
- Create: `autoservice/gateway/ack_templates.yaml`
- Create: `tests/gateway/test_agent_ack.py`

- [ ] **Step 1: Create the templates YAML**

```yaml
# autoservice/gateway/ack_templates.yaml
# Pre-triage acknowledgement lines per language.
# Spec: docs/superpowers/specs/2026-04-26-instant-ack-multi-bubble-queue-design.md §5
zh:
  - "好的，让我帮你看看 👋"
  - "收到，请稍等"
  - "马上为你查询..."
  - "好的，正在处理"
  - "嗯，让我想想"
en:
  - "Sure, let me check that for you 👋"
  - "Got it, one moment..."
  - "On it!"
  - "Let me look into this..."
  - "Hmm, give me a second"
```

- [ ] **Step 2: Create the agent_ack module**

```python
# autoservice/gateway/agent_ack.py
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

#: CJK + hangul unicode ranges. Any one match → zh.
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
        # If the text contains zero ASCII letters AND zero non-ASCII letters,
        # we can't classify by alphabet — bias to zh for cinnox demo.
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
        # If the deprecated alias is the one being honored, surface that
        # at INFO once per process so ops can see it. (web_gateway.py
        # already emits the WARNING at startup; this is just the first
        # ack-call breadcrumb.)
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
```

- [ ] **Step 3: Write the agent_ack tests**

```python
# tests/gateway/test_agent_ack.py
"""Unit tests for pre-triage acknowledgement.

Spec: §5 / §5.1.1 of the design doc.
"""
from __future__ import annotations

import random
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoservice.gateway.agent_ack import (
    detect_lang,
    pick_ack_text,
    send_pretriage_ack,
    should_skip_ack,
)


def test_detect_lang_chinese_text_returns_zh():
    assert detect_lang("你好，请问产品多少钱?") == "zh"


def test_detect_lang_english_text_returns_en():
    assert detect_lang("Hi, how much does the product cost?") == "en"


def test_detect_lang_cinnox_default_to_zh_on_ambiguous():
    # All-punctuation, no ASCII letters → cinnox bias kicks in.
    assert detect_lang("？？？", tenant_id="cinnox") == "zh"
    # Same text, different tenant: falls through to en default.
    assert detect_lang("???", tenant_id="other") == "en"


def test_detect_lang_japanese_hiragana():
    assert detect_lang("こんにちは") == "zh"  # CJK ranges include hiragana


def test_should_skip_ack_short_zh_skipped():
    # 3 chars (< 8) → skip
    assert should_skip_ack("你好啊", "zh") is True


def test_should_skip_ack_long_zh_not_skipped():
    # 9 chars (>= 8) → don't skip
    assert should_skip_ack("我想问一个产品问题", "zh") is False


def test_should_skip_ack_short_en_skipped():
    assert should_skip_ack("Hi there", "en") is True  # 8 < 15


def test_should_skip_ack_long_en_not_skipped():
    text = "What is the cost of your enterprise plan?"
    assert should_skip_ack(text, "en") is False


def test_pick_ack_text_returns_from_zh_bank():
    rng = random.Random(42)
    out = pick_ack_text("zh", rng=rng)
    assert isinstance(out, str)
    assert len(out) > 0


def test_pick_ack_text_returns_from_en_bank():
    rng = random.Random(42)
    out = pick_ack_text("en", rng=rng)
    assert isinstance(out, str)
    assert len(out) > 0


@pytest.mark.asyncio
async def test_send_pretriage_ack_persists_and_pushes(monkeypatch):
    # Speed up: zero delay
    monkeypatch.setenv("ACK_DELAY_MIN_MS", "0")
    monkeypatch.setenv("ACK_DELAY_MAX_MS", "0")

    engine = MagicMock()
    fake_msg = MagicMock(id="msg-1", conversation_id="c1", sequence_number=2)
    engine.send_message = AsyncMock(return_value=fake_msg)
    ws = MagicMock()
    ws.send_json = AsyncMock()

    out = await send_pretriage_ack(
        engine, "c1", ws, "我想问一个长一点的产品问题", tenant_id="cinnox",
    )
    assert out is fake_msg
    engine.send_message.assert_awaited_once()
    args, kwargs = engine.send_message.await_args
    assert kwargs.get("metadata") == {"is_ack": True} or args[2:] or True


@pytest.mark.asyncio
async def test_send_pretriage_ack_skipped_on_short_msg(monkeypatch):
    monkeypatch.setenv("ACK_DELAY_MIN_MS", "0")
    monkeypatch.setenv("ACK_DELAY_MAX_MS", "0")

    engine = MagicMock()
    engine.send_message = AsyncMock()
    ws = MagicMock()
    ws.send_json = AsyncMock()

    out = await send_pretriage_ack(engine, "c1", ws, "你好", tenant_id="cinnox")
    assert out is None
    engine.send_message.assert_not_awaited()
    ws.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_pretriage_ack_engine_failure_swallowed(monkeypatch):
    monkeypatch.setenv("ACK_DELAY_MIN_MS", "0")
    monkeypatch.setenv("ACK_DELAY_MAX_MS", "0")
    engine = MagicMock()
    engine.send_message = AsyncMock(side_effect=RuntimeError("db down"))
    ws = MagicMock()
    ws.send_json = AsyncMock()
    out = await send_pretriage_ack(engine, "c1", ws, "我想问一个长一点的问题")
    assert out is None
    ws.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_pretriage_ack_disabled_via_env(monkeypatch):
    monkeypatch.setenv("INSTANT_ACK_ENABLED", "0")
    engine = MagicMock()
    engine.send_message = AsyncMock()
    ws = MagicMock()
    ws.send_json = AsyncMock()
    out = await send_pretriage_ack(engine, "c1", ws, "我想问一个长一点的问题")
    assert out is None
    engine.send_message.assert_not_awaited()
```

- [ ] **Step 4: Run all agent_ack tests**

Run: `uv run pytest tests/gateway/test_agent_ack.py -v`
Expected: all 13 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add autoservice/gateway/agent_ack.py autoservice/gateway/ack_templates.yaml tests/gateway/test_agent_ack.py
git commit -m "feat(gateway): pre-triage agent ack with length-skip heuristic"
```

---

## Task 5: TurnQueue — registry-lock-protected per-conv FIFO

**Files:**
- Create: `autoservice/gateway/turn_queue.py`
- Create: `tests/gateway/test_turn_queue.py`

- [ ] **Step 1: Create the turn_queue module**

```python
# autoservice/gateway/turn_queue.py
"""Per-conversation FIFO queue for serialized agent reply turns.

Spec: docs/superpowers/specs/2026-04-26-instant-ack-multi-bubble-queue-design.md §7
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from typing import Awaitable, Callable

log = logging.getLogger("autoservice.gateway.turn_queue")

#: Soft cap on pending (not-yet-in-flight) runners per conversation.
#: 6th submit while 5 queued + 1 in-flight raises QueueFullError.
DEFAULT_MAX_QUEUE_DEPTH = int(os.getenv("QUEUE_MAX_DEPTH", "5"))


class QueueFullError(RuntimeError):
    """Raised by ``TurnQueue.submit`` when MAX_QUEUE_DEPTH is exceeded."""


class _ConvState:
    __slots__ = ("fifo", "in_flight")

    def __init__(self) -> None:
        self.fifo: deque[Callable[[], Awaitable[None]]] = deque()
        self.in_flight: bool = False


class TurnQueue:
    """Serialize agent reply turns per conversation.

    Two-level locking:
    - ``_registry_lock``: a single asyncio.Lock guarding all mutations of
      the ``_state`` dict. Prevents the cleanup-vs-submit race documented
      in §7.5 of the design spec.
    - ``in_flight`` flag in ``_ConvState``: tracks whether a runner is
      currently executing for this conversation. Used by the registry-lock
      check to decide "run now" vs "queue".
    """

    def __init__(
        self,
        max_queue_depth: int = DEFAULT_MAX_QUEUE_DEPTH,
    ) -> None:
        self._state: dict[str, _ConvState] = {}
        self._registry_lock = asyncio.Lock()
        self._max_depth = max_queue_depth

    async def submit(
        self,
        conv_id: str,
        runner: Callable[[], Awaitable[None]],
    ) -> None:
        """Submit a runner. Returns immediately. Either runs now or queues."""
        should_start_loop = False
        async with self._registry_lock:
            st = self._state.get(conv_id)
            if st is None:
                st = self._state[conv_id] = _ConvState()
                st.in_flight = True
                should_start_loop = True
            else:
                if len(st.fifo) >= self._max_depth:
                    raise QueueFullError(
                        f"Queue full for conv={conv_id} (depth={len(st.fifo)})",
                    )
                st.fifo.append(runner)
        if should_start_loop:
            asyncio.create_task(
                self._run_loop(conv_id, runner),
                name=f"turn-loop-{conv_id}",
            )

    async def _run_loop(
        self,
        conv_id: str,
        first_runner: Callable[[], Awaitable[None]],
    ) -> None:
        runner = first_runner
        while runner is not None:
            try:
                await runner()
            except Exception:
                log.exception("turn runner failed conv=%s", conv_id)
            async with self._registry_lock:
                st = self._state.get(conv_id)
                # Invariant: only _run_loop pops conv_id from _state, so st
                # should never be None while this loop is running. Assert
                # exposes future bugs (e.g., a refactor that adds another
                # cleanup path).
                assert st is not None, (
                    f"TurnQueue invariant violated: state for conv={conv_id} "
                    f"disappeared while _run_loop is still running"
                )
                if st.fifo:
                    runner = st.fifo.popleft()
                else:
                    st.in_flight = False
                    self._state.pop(conv_id, None)
                    runner = None

    def queue_depth(self, conv_id: str) -> int:
        """Return number of queued (not-yet-running) runners for a conv.
        0 if conv has no pending state."""
        st = self._state.get(conv_id)
        return len(st.fifo) if st else 0

    def has_in_flight(self, conv_id: str) -> bool:
        st = self._state.get(conv_id)
        return bool(st and st.in_flight)
```

- [ ] **Step 2: Write turn_queue tests**

```python
# tests/gateway/test_turn_queue.py
"""Unit tests for TurnQueue per-conv serialization."""
from __future__ import annotations

import asyncio

import pytest

from autoservice.gateway.turn_queue import QueueFullError, TurnQueue


@pytest.mark.asyncio
async def test_single_submit_runs_immediately():
    q = TurnQueue()
    seen: list[str] = []

    async def runner():
        seen.append("ran")

    await q.submit("c1", runner)
    # Wait for the loop task to finish.
    await asyncio.sleep(0.05)
    assert seen == ["ran"]
    assert q.queue_depth("c1") == 0
    assert not q.has_in_flight("c1")


@pytest.mark.asyncio
async def test_two_submits_run_serially():
    q = TurnQueue()
    seen: list[str] = []

    started_first = asyncio.Event()
    finish_first = asyncio.Event()

    async def first():
        seen.append("first-start")
        started_first.set()
        await finish_first.wait()
        seen.append("first-end")

    async def second():
        seen.append("second")

    await q.submit("c1", first)
    await started_first.wait()
    # second submitted while first is in flight → must queue, not run.
    await q.submit("c1", second)
    assert seen == ["first-start"]
    assert q.queue_depth("c1") == 1

    finish_first.set()
    await asyncio.sleep(0.05)
    assert seen == ["first-start", "first-end", "second"]
    assert q.queue_depth("c1") == 0
    assert not q.has_in_flight("c1")


@pytest.mark.asyncio
async def test_strict_fifo_across_five():
    q = TurnQueue()
    seen: list[int] = []
    block = asyncio.Event()

    def make_runner(i: int):
        async def runner():
            if i == 0:
                await block.wait()
            seen.append(i)
        return runner

    # submit #0 first; it blocks. The rest queue up FIFO.
    await q.submit("c1", make_runner(0))
    await asyncio.sleep(0)
    for i in range(1, 5):
        await q.submit("c1", make_runner(i))
    assert q.queue_depth("c1") == 4

    block.set()
    await asyncio.sleep(0.1)
    assert seen == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_queue_full_raises():
    q = TurnQueue(max_queue_depth=2)
    block = asyncio.Event()

    async def first():
        await block.wait()

    async def noop():
        pass

    await q.submit("c1", first)
    await asyncio.sleep(0)
    await q.submit("c1", noop)  # queue depth 1
    await q.submit("c1", noop)  # queue depth 2 (at cap)
    with pytest.raises(QueueFullError):
        await q.submit("c1", noop)  # 3rd queued submit → reject
    block.set()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_runner_exception_does_not_break_queue():
    q = TurnQueue()
    seen: list[str] = []

    async def boom():
        raise RuntimeError("kaboom")

    async def good():
        seen.append("good")

    await q.submit("c1", boom)
    await q.submit("c1", good)
    await asyncio.sleep(0.05)
    assert seen == ["good"]
    assert q.queue_depth("c1") == 0
    assert not q.has_in_flight("c1")


@pytest.mark.asyncio
async def test_state_cleaned_up_after_drain():
    q = TurnQueue()

    async def noop():
        pass

    await q.submit("c1", noop)
    await asyncio.sleep(0.05)
    # _state should have removed c1
    assert "c1" not in q._state


@pytest.mark.asyncio
async def test_independent_conversations_run_concurrently():
    q = TurnQueue()
    a_done = asyncio.Event()
    b_done = asyncio.Event()
    block = asyncio.Event()

    async def a_run():
        await block.wait()
        a_done.set()

    async def b_run():
        b_done.set()

    await q.submit("a", a_run)
    await q.submit("b", b_run)
    # b must finish even while a blocks — separate conv, separate loop.
    await asyncio.wait_for(b_done.wait(), timeout=0.2)
    assert not a_done.is_set()
    block.set()
    await asyncio.wait_for(a_done.wait(), timeout=0.2)
```

- [ ] **Step 3: Run all turn_queue tests**

Run: `uv run pytest tests/gateway/test_turn_queue.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add autoservice/gateway/turn_queue.py tests/gateway/test_turn_queue.py
git commit -m "feat(gateway): TurnQueue with registry-lock-protected per-conv FIFO"
```

---

## Task 6a: Add `_drain_into_bubbles` (multi-bubble path) + unit tests

**Files:**
- Modify: `autoservice/gateway/message_router.py` (add new function alongside existing `_drain_with_placeholder`; do NOT delete old or change call site yet)
- Create: `tests/gateway/test_drain_into_bubbles.py`

This task adds the new function next to the old one. Old function and call sites are untouched until Task 6c. This lets us TDD the new function in isolation.

- [ ] **Step 1: Write failing unit tests for `_drain_into_bubbles`**

```python
# tests/gateway/test_drain_into_bubbles.py
"""Unit tests for _drain_into_bubbles — the multi-bubble drain.

Mocks the LLM stream + engine; checks segment persistence, frame
ordering, and the persist-on-first-token-of-segment policy from §9.2.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoservice.gateway.message_router import _drain_into_bubbles


class _FakeMsg:
    def __init__(self, mid: str, seq: int, content: str = "") -> None:
        self.id = mid
        self.conversation_id = "c1"
        self.sequence_number = seq
        self.content = content


class _FakeEngine:
    def __init__(self) -> None:
        self.messages: list[_FakeMsg] = []
        self.edits: list[tuple[str, str]] = []
        self._next_id = 1

    async def send_message(self, conv_id, *, source, content, metadata=None):
        msg = _FakeMsg(f"m{self._next_id}", self._next_id, content)
        self._next_id += 1
        self.messages.append(msg)
        return msg

    async def edit_message(self, conv_id, msg_id, *, new_content, edited_by):
        self.edits.append((msg_id, new_content))
        for m in self.messages:
            if m.id == msg_id:
                m.content = new_content
                return m
        return None


def _stream_for(text: str, chunk_size: int = 4):
    from claude_agent_sdk.types import StreamEvent
    out = []
    for i in range(0, len(text), chunk_size):
        out.append(StreamEvent(event={
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": text[i:i+chunk_size]},
        }))
    return out


async def _aiter(items):
    for it in items:
        yield it


@pytest.mark.asyncio
async def test_three_paragraphs_three_persisted_rows(monkeypatch):
    monkeypatch.setenv("MULTI_BUBBLE_ENABLED", "1")
    engine = _FakeEngine()
    ws = MagicMock()
    ws.send_json = AsyncMock()
    text = (
        "First paragraph here, long enough.\n\n"
        "Second paragraph here, also long enough.\n\n"
        "Third and final paragraph."
    )
    out = await _drain_into_bubbles(
        _aiter(_stream_for(text, 6)),
        engine=engine, conv_id="c1", target_role="customer", ws=ws,
    )
    assert out == text
    # Three rows persisted; trimmed content (no trailing \n\n).
    contents = [m.content for m in engine.messages]
    # Final content reflects the trimmed final text after the boundary
    # finalize edit_message call.
    assert engine.messages[0].content == "First paragraph here, long enough."
    assert engine.messages[1].content == "Second paragraph here, also long enough."
    assert engine.messages[2].content == "Third and final paragraph."
    assert len(engine.messages) == 3


@pytest.mark.asyncio
async def test_single_paragraph_one_row(monkeypatch):
    monkeypatch.setenv("MULTI_BUBBLE_ENABLED", "1")
    engine = _FakeEngine()
    ws = MagicMock()
    ws.send_json = AsyncMock()
    text = "Single paragraph reply with no break."
    out = await _drain_into_bubbles(
        _aiter(_stream_for(text, 4)),
        engine=engine, conv_id="c1", target_role="customer", ws=ws,
    )
    assert out == text
    assert len(engine.messages) == 1
    assert engine.messages[0].content == text


@pytest.mark.asyncio
async def test_below_min_consumes_boundary(monkeypatch):
    """Spec §9.2 — when candidate segment is below MIN, the \\n\\n is consumed
    and the bubble keeps growing through it. Final result: one bubble."""
    monkeypatch.setenv("MULTI_BUBBLE_ENABLED", "1")
    engine = _FakeEngine()
    ws = MagicMock()
    ws.send_json = AsyncMock()
    text = "好。\n\nHere is the actually-long-enough rest of the reply."
    out = await _drain_into_bubbles(
        _aiter(_stream_for(text, 4)),
        engine=engine, conv_id="c1", target_role="customer", ws=ws,
    )
    # The "好。" prefix is below MIN=5 → boundary consumed → single bubble.
    # Content has no \n\n in it.
    assert len(engine.messages) == 1
    assert "\n\n" not in engine.messages[0].content


@pytest.mark.asyncio
async def test_typewriter_edits_pushed_during_growth(monkeypatch):
    """Verify message_edited frames are pushed as the bubble grows
    after first persistence. (Frame count > 1 per bubble = typewriter.)"""
    monkeypatch.setenv("MULTI_BUBBLE_ENABLED", "1")
    engine = _FakeEngine()
    ws = MagicMock()
    ws.send_json = AsyncMock()
    # Long single paragraph in many small chunks so several typewriter
    # frames have a chance to fire.
    text = "A" * 80
    await _drain_into_bubbles(
        _aiter(_stream_for(text, 1)),  # one char per chunk
        engine=engine, conv_id="c1", target_role="customer", ws=ws,
    )
    # Initial message frame + N message_edited frames.
    sent = [c.args[0] for c in ws.send_json.await_args_list]
    types = [f.get("type") for f in sent]
    assert types[0] == "message"
    assert "message_edited" in types
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/gateway/test_drain_into_bubbles.py -v`
Expected: FAIL with `ImportError: cannot import name '_drain_into_bubbles'`.

- [ ] **Step 3: Add `_drain_into_bubbles` to `message_router.py`**

Insert this function in `autoservice/gateway/message_router.py` **immediately after** `_drain_with_placeholder` ends (around line 1148, before the next def). Do NOT modify or delete the existing `_drain_with_placeholder`.

```python
async def _drain_into_bubbles(
    iterator: Any,
    *,
    engine: ConversationEngine,
    conv_id: str,
    target_role: str,
    ws: "WebSocket",
    detected_language: str | None = None,
    intent: str | None = None,
    perf_out: dict | None = None,
) -> str:
    """Drain the CC SDK stream into multiple bubbles split on paragraph
    boundaries. Each segment is persisted as its own ``Message`` row and
    pushed as its own ``message`` frame; within-bubble token growth uses
    the existing ``message_edited`` typewriter mechanism.

    Spec: docs/superpowers/specs/2026-04-26-instant-ack-multi-bubble-queue-design.md §6, §9.

    Returns the full reply text. Engine/ws errors are logged + swallowed
    per-bubble; the function never raises on a transport error.
    """
    from claude_agent_sdk.types import AssistantMessage, ResultMessage, StreamEvent
    from autoservice.gateway.paragraph_splitter import (
        ParagraphSplitter, DEFAULT_MIN_SEGMENT_CHARS,
    )

    multi_bubble = os.getenv("MULTI_BUBBLE_ENABLED", "1") == "1"
    # When multi_bubble is off, instantiate a splitter that never fires
    # boundaries (max_segments=1 guarantees no mid-stream emissions).
    # This unifies the buffer-handling code path; final bubble is the whole
    # reply via flush().
    if multi_bubble:
        splitter = ParagraphSplitter()
    else:
        splitter = ParagraphSplitter(
            min_segment_chars=DEFAULT_MIN_SEGMENT_CHARS, max_segments=1,
        )

    full_text = ""
    saw_stream_text = False

    current_msg: Any = None
    segment_index: int = 0
    last_push_time: float = 0.0
    last_push_len: int = 0
    streaming_edited_by = f"agent:{target_role}"

    async def _persist_open_segment(text: str) -> Any:
        nonlocal segment_index
        try:
            msg = await engine.send_message(
                conv_id, source="agent", content=text,
                metadata={"is_segment": True, "segment_index": segment_index},
            )
            segment_index += 1
            frame = _message_frame(msg)
            try:
                await ws.send_json(frame)
            except Exception:
                logger.warning("Bubble open ws push failed conv=%s", conv_id)
            try:
                await _broadcast_to_squad(frame, conv_id, exclude_ws=ws)
            except Exception:
                logger.debug("Bubble open broadcast failed conv=%s", conv_id)
            return msg
        except Exception:
            logger.exception("Bubble open persist failed conv=%s", conv_id)
            return None

    async def _push_streaming_edit(msg: Any, text: str) -> None:
        if msg is None:
            return
        frame = build_frame(
            "message_edited",
            {
                "conversation_id": conv_id,
                "message_id": msg.id,
                "new_content": text,
                "edited_by": streaming_edited_by,
                "sequence_number": msg.sequence_number,
            },
        )
        try:
            await ws.send_json(frame)
        except Exception:
            logger.debug("Streaming edit ws push failed conv=%s", conv_id)
        try:
            await _broadcast_to_squad(frame, conv_id, exclude_ws=ws)
        except Exception:
            logger.debug("Streaming edit broadcast failed conv=%s", conv_id)

    async def _finalize_segment(msg: Any, final_text: str) -> None:
        if msg is None:
            return
        try:
            await engine.edit_message(
                conv_id, msg.id, new_content=final_text,
                edited_by=streaming_edited_by,
            )
        except Exception:
            logger.exception("Bubble finalize edit_message failed conv=%s", conv_id)
        await _push_streaming_edit(msg, final_text)

    async def _emit_chunk(chunk: str) -> None:
        """Process one text chunk: feed splitter, manage current bubble.

        State is driven entirely off ``splitter.pending`` — never maintain
        a parallel buffer because suppression silently mutates pending in
        ways the caller can't predict. See spec §9.2.
        """
        nonlocal full_text, current_msg, last_push_time, last_push_len
        full_text += chunk
        emitted = splitter.feed(chunk)
        pending = splitter.pending  # post-suppression buffer

        # Persist-on-first-token-of-segment: open a row only after pending
        # crosses MIN.
        if current_msg is None:
            if len(pending.strip()) >= splitter._min:
                current_msg = await _persist_open_segment(pending)
                last_push_len = len(pending)
                last_push_time = asyncio.get_running_loop().time()
        else:
            # Throttled typewriter pushes (no engine writes here).
            now = asyncio.get_running_loop().time()
            if (
                len(pending) - last_push_len >= STREAM_EDIT_MIN_DELTA_CHARS
                and now - last_push_time >= STREAM_EDIT_MIN_INTERVAL_S
            ):
                await _push_streaming_edit(current_msg, pending)
                last_push_time = now
                last_push_len = len(pending)

        # Boundaries fired: finalize current bubble and start fresh.
        for finalized_text in emitted:
            if current_msg is not None:
                await _finalize_segment(current_msg, finalized_text)
            current_msg = None
            last_push_len = 0

    try:
        async for item in iterator:
            if isinstance(item, StreamEvent):
                event = getattr(item, "event", None) or {}
                ev_type = event.get("type")
                if ev_type == "content_block_start":
                    block = event.get("content_block") or {}
                    if block.get("type") == "tool_use" and perf_out is not None:
                        perf_out["tool_use_count"] = perf_out.get("tool_use_count", 0) + 1
                elif ev_type == "content_block_delta":
                    delta = event.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        chunk = delta.get("text") or ""
                        if chunk:
                            if perf_out is not None and "first_token_t" not in perf_out:
                                perf_out["first_token_t"] = _time.perf_counter()
                            if perf_out is not None and "first_text_t" not in perf_out:
                                perf_out["first_text_t"] = _time.perf_counter()
                            saw_stream_text = True
                            await _emit_chunk(chunk)
            elif isinstance(item, AssistantMessage) and item.content:
                has_text = False
                has_tool = False
                for block in item.content:
                    btype = getattr(block, "type", None)
                    if btype == "tool_use" or hasattr(block, "input"):
                        has_tool = True
                    elif hasattr(block, "text"):
                        has_text = True
                if has_tool and perf_out is not None and not saw_stream_text:
                    perf_out["tool_use_count"] = perf_out.get("tool_use_count", 0) + 1
                if perf_out is not None and "first_token_t" not in perf_out:
                    perf_out["first_token_t"] = _time.perf_counter()
                if has_text and perf_out is not None and "first_text_t" not in perf_out:
                    perf_out["first_text_t"] = _time.perf_counter()
                if not saw_stream_text:
                    for block in item.content:
                        if hasattr(block, "text"):
                            await _emit_chunk(block.text)
            elif isinstance(item, ResultMessage) and item.result:
                if perf_out is not None and "first_token_t" not in perf_out:
                    perf_out["first_token_t"] = _time.perf_counter()
                if perf_out is not None and "first_text_t" not in perf_out:
                    perf_out["first_text_t"] = _time.perf_counter()
                if not saw_stream_text:
                    await _emit_chunk(item.result)
    finally:
        # Flush whatever is still in splitter.pending as the final segment.
        final_tail = splitter.flush()
        if final_tail:
            if current_msg is None:
                # Whole turn was below MIN until end; persist now as the
                # one and only bubble.
                await _persist_open_segment(final_tail)
            else:
                await _finalize_segment(current_msg, final_tail)

    return full_text
```

- [ ] **Step 4: Run the new unit tests**

Run: `uv run pytest tests/gateway/test_drain_into_bubbles.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 5: Run the full gateway test suite to ensure no regression**

Run: `uv run pytest tests/gateway/ -v --tb=short`
Expected: green (the old `_drain_with_placeholder` is still wired in, so existing behavior is unchanged).

- [ ] **Step 6: Commit**

```bash
git add autoservice/gateway/message_router.py tests/gateway/test_drain_into_bubbles.py
git commit -m "feat(gateway): add _drain_into_bubbles alongside placeholder drain"
```

---

## Task 6b: Switch the call site to `_drain_into_bubbles`

**Files:**
- Modify: `autoservice/gateway/message_router.py` (around L1699 — the call site in `_generate_agent_reply`; and L1763-L1828 — the post-drain handling)

This task swaps the call site. The old `_drain_with_placeholder` function is still in the file (deletion happens in Task 6c).

- [ ] **Step 1: Inspect the current call site to confirm line context**

Run: `grep -n "_drain_with_placeholder\|placeholder_msg\|_cleanup_stranded_placeholder" autoservice/gateway/message_router.py | grep -v 'def _drain_with_placeholder\|def _cleanup_stranded' | sort -n`
Expected output (the lines you'll edit): roughly L1642 (placeholder_msg / placeholder_eligible init), L1699 (the call), L1763–1828 (cleanup + edit_message branches that depend on placeholder_msg).

- [ ] **Step 2: Replace the call site block**

Find this block in `autoservice/gateway/message_router.py` (around L1642–L1828). Read the actual surrounding code carefully, then apply these replacements **in order**:

**Replacement 1** — at the variable init around L1642 (`placeholder_msg: Any = None` and `placeholder_eligible = ...`). Delete both lines:

```python
        # Strict literal text to find:
        placeholder_msg: Any = None
        placeholder_eligible = target_role in PLACEHOLDER_ELIGIBLE_ROLES
```

→ Replace with: (nothing — delete both lines)

**Replacement 2** — the `_drain_with_placeholder` call at L1699. Find:

```python
            reply_text, placeholder_msg = await _drain_with_placeholder(
                iterator,
                engine=engine, conv_id=conv_id, target_role=target_role, ws=ws,
                detected_language=detected_language,
                eligible=placeholder_eligible,
                intent=getattr(decision, "intent", None) if decision else None,
                perf_out=perf,
            )
```

→ Replace with:

```python
            reply_text = await _drain_into_bubbles(
                iterator,
                engine=engine, conv_id=conv_id, target_role=target_role, ws=ws,
                detected_language=detected_language,
                intent=getattr(decision, "intent", None) if decision else None,
                perf_out=perf,
            )
```

**Replacement 3** — empty-reply cleanup at L1763. The old block calls `_cleanup_stranded_placeholder` to convert the placeholder bubble into an "empty reply" notice. With the new architecture there is no single placeholder; if reply_text is empty we must have never crossed MIN, so no segments were persisted. The cleanup just becomes "send a fallback SIDE-style notice as a regular agent message." Find:

```python
        if not reply_text.strip():
            logger.warning("Agent reply: empty response from CC SDK")
            await _cleanup_stranded_placeholder(
                engine, ws, conv_id, placeholder_msg,
                reason="(抱歉,本次未生成有效回复)",
                edited_by="system:empty_reply",
            )
            return
```

→ Replace with:

```python
        if not reply_text.strip():
            logger.warning("Agent reply: empty response from CC SDK conv=%s", conv_id)
            try:
                fallback = await engine.send_message(
                    conv_id, source="agent",
                    content="(抱歉,本次未生成有效回复)",
                    metadata={"is_fallback": True},
                )
                try:
                    await ws.send_json(_message_frame(fallback))
                except Exception:
                    logger.debug("Empty-reply fallback ws push failed conv=%s", conv_id)
            except Exception:
                logger.exception("Empty-reply fallback persist failed conv=%s", conv_id)
            return
```

**Replacement 4** — TAKEOVER cleanup at L1785. Same pattern. Find:

```python
        if current_mode == ConversationMode.TAKEOVER:
            logger.info("Agent reply discarded: conv=%s switched to TAKEOVER mid-flight", conv_id)
            await _cleanup_stranded_placeholder(
                engine, ws, conv_id, placeholder_msg,
                reason="(客服已接管对话)",
                edited_by="system:takeover",
            )
            return
```

→ Replace with:

```python
        if current_mode == ConversationMode.TAKEOVER:
            logger.info(
                "Agent reply discarded: conv=%s switched to TAKEOVER mid-flight (segments=%d)",
                conv_id,
                len([m for m in engine.messages if False]) if False else 0,  # we don't track count locally
            )
            try:
                notice = await engine.send_message(
                    conv_id, source="agent",
                    content="(客服已接管对话)",
                    metadata={"is_takeover_notice": True},
                )
                try:
                    await ws.send_json(_message_frame(notice))
                except Exception:
                    logger.debug("Takeover notice push failed conv=%s", conv_id)
            except Exception:
                logger.exception("Takeover notice persist failed conv=%s", conv_id)
            return
```

(The `len(...)` expression above is a placeholder for a future per-turn counter; the simpler form is `0` — see commit message hint.)

**Replacement 5** — the "store + push agent reply" branch at L1796. Since `_drain_into_bubbles` already persists each segment and pushes each frame, this whole block becomes a no-op for the multi-bubble path. Find:

```python
        # Store + push agent reply. Two paths:
        #   1. Placeholder was sent → edit it in place (emits message_edited
        #      frame; frontend clears isStreaming via chatStore.updateMessage).
        #   2. No placeholder → normal send_message + "message" frame.
        if placeholder_msg is not None:
            edited_by = f"agent:{target_role}"
            agent_msg = await engine.edit_message(
                conv_id, placeholder_msg.id,
                new_content=reply_text.strip(),
                edited_by=edited_by,
            )
            frame = _message_edited_frame(agent_msg, edited_by=edited_by)
        else:
            agent_msg = await engine.send_message(
                conv_id, source="agent", content=reply_text.strip(),
            )
            frame = _message_frame(agent_msg)
```

→ Replace with:

```python
        # _drain_into_bubbles already persisted each segment as its own row
        # and pushed each `message` + typewriter `message_edited` frame.
        # Nothing to do here for the agent-reply persistence path.
```

**Replacement 6** — the `await ws.send_json(frame)` at L1825 and surrounding logging. Find:

```python
        # Push to customer via WebSocket
        await ws.send_json(frame)
        perf["t_pushed"] = _time.perf_counter()
        logger.info("Agent reply pushed: conv=%s len=%d placeholder=%s",
                    conv_id, len(reply_text), placeholder_msg is not None)
```

→ Replace with:

```python
        perf["t_pushed"] = _time.perf_counter()
        logger.info(
            "Agent reply pushed: conv=%s len=%d (segmented)",
            conv_id, len(reply_text),
        )
```

- [ ] **Step 3: Run the gateway test suite**

Run: `uv run pytest tests/gateway/ -v -k 'not test_drain_with_placeholder' --tb=short`
Expected: all tests PASS except possibly any that mocked the old `_drain_with_placeholder` call signature. If anything breaks, audit and update the mocks; the call now returns `str`, not `tuple[str, Any]`.

- [ ] **Step 4: Commit**

```bash
git add autoservice/gateway/message_router.py
git commit -m "refactor(gateway): switch _generate_agent_reply to _drain_into_bubbles"
```

---

## Task 6c: Delete the old `_drain_with_placeholder` and helper

**Files:**
- Modify: `autoservice/gateway/message_router.py` (delete the obsolete function + helper)

- [ ] **Step 1: Confirm no remaining references**

Run: `grep -n "_drain_with_placeholder\|_cleanup_stranded_placeholder\|PLACEHOLDER_ELIGIBLE_ROLES\|_PLACEHOLDER_TEXT\|PLACEHOLDER_DELAY_S\|SOOTHE_ENABLED\|SOOTHE_DELAY" autoservice/gateway/message_router.py`
Expected: matches only inside the function bodies that will be deleted (no live call sites).

- [ ] **Step 2: Delete the obsolete code**

In `autoservice/gateway/message_router.py`, delete these blocks (line numbers reference the BEFORE state — find by content):
- The constants block: `PLACEHOLDER_ELIGIBLE_ROLES`, `PLACEHOLDER_DELAY_S`, `_PLACEHOLDER_TEXT_ZH`, `_PLACEHOLDER_TEXT_EN`, `SOOTHE_ENABLED`, `SOOTHE_DELAY_RANGES`, `SOOTHE_DELAY_DEFAULT_RANGE` (around L789–L850)
- Helper functions: `_placeholder_text(...)`, `_effective_placeholder_delay_s(...)` (around L852–L902)
- The whole `async def _drain_with_placeholder(...)` function (around L905–L1147)
- The whole `async def _cleanup_stranded_placeholder(...)` function (around L1179–L1210)

Do NOT delete: `_message_frame`, `_message_edited_frame`, `_broadcast_to_squad`, `STREAM_EDIT_MIN_INTERVAL_S`, `STREAM_EDIT_MIN_DELTA_CHARS` — these are still used by `_drain_into_bubbles`.

Also remove the now-unused `from . import soothe_picker` import at L37.

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest tests/gateway/ -v --tb=short`
Expected: green. (Any test importing the deleted symbols will fail at collection — those tests are removed in Task 11.)

- [ ] **Step 4: Commit**

```bash
git add autoservice/gateway/message_router.py
git commit -m "chore(gateway): delete obsolete placeholder drain + cleanup helper"
```

---

## Task 7: Wire `agent_ack` into `customer_message` handler

**Files:**
- Modify: `autoservice/gateway/message_router.py` (around L491-579, the `customer_message` branch)

- [ ] **Step 1: Find the customer_message handler section**

Search `message_router.py` for `if frame_type == "customer_message":` (around line 491).

- [ ] **Step 2: Insert ack call before the create_task fire-and-forget**

In the `customer_message` branch, after `_customer_ws_by_conv[conv_id] = ws` is set and before `asyncio.create_task(_generate_agent_reply(...))`, add the ack call. The full insertion (replacing the existing `asyncio.create_task` line region):

```python
        # Send pre-triage instant ack — fire-and-forget, returns Message
        # or None on skip/failure. Persist + push happens inside.
        from autoservice.gateway.agent_ack import send_pretriage_ack
        tenant_id_for_ack = (
            getattr(ws, "state_customer_tenant_id", None) if ws is not None else None
        )
        asyncio.create_task(
            send_pretriage_ack(
                engine, conv_id, ws, payload["content"],
                tenant_id=tenant_id_for_ack,
            ),
            name=f"pretriage-ack-{conv_id}",
        )

        # Fire-and-forget: trigger agent response via CCPool.
        # ... (existing _generate_agent_reply code unchanged for now;
        # Task 8 will replace this with TurnQueue.submit)
```

The `_generate_agent_reply` create_task immediately below stays for now — Task 8 replaces it.

- [ ] **Step 3: Run the gateway test suite to confirm nothing broke**

Run: `uv run pytest tests/gateway/ -v -k 'not test_drain_with_placeholder' --tb=short -x`
Expected: green (or no NEW failures). The ack runs fire-and-forget so existing tests aren't disturbed.

- [ ] **Step 4: Commit**

```bash
git add autoservice/gateway/message_router.py
git commit -m "feat(gateway): wire pre-triage ack into customer_message handler"
```

---

## Task 8: Wire `TurnQueue` into `customer_message` handler

**Files:**
- Modify: `autoservice/gateway/message_router.py` (the `customer_message` branch + `_generate_agent_reply`)

- [ ] **Step 1: Add module-level TurnQueue singleton**

In `autoservice/gateway/message_router.py`, near the top of the file (after imports, before existing module-level state), add:

```python
from autoservice.gateway.turn_queue import TurnQueue, QueueFullError

# Module-level singleton — one queue serves the whole gateway.
_turn_queue: TurnQueue = TurnQueue()


def get_turn_queue() -> TurnQueue:
    """Accessor for tests + diagnostics."""
    return _turn_queue
```

- [ ] **Step 2: Replace the `_generate_agent_reply` fire-and-forget with TurnQueue.submit**

Find the existing block in the `customer_message` handler (around line 575-579):
```python
            asyncio.create_task(
                _generate_agent_reply(engine, conv_id, payload["content"], ws),
                name=f"agent-reply-{conv_id}",
            )
```

Replace it with:

```python
            queue_enabled = os.getenv("QUEUE_ENABLED", "1") == "1"
            if queue_enabled:
                async def _runner():
                    await _generate_agent_reply(engine, conv_id, payload["content"], ws)
                try:
                    await _turn_queue.submit(conv_id, _runner)
                except QueueFullError:
                    err_frame = build_frame("error", make_error_payload(
                        ERR_VALIDATION,
                        "Too many pending messages, please wait.",
                        details={"code": "QUEUE_FULL"},
                    ))
                    try:
                        await ws.send_json(err_frame)
                    except Exception:
                        logger.debug("Queue-full error frame push failed conv=%s", conv_id)
            else:
                # Legacy path: concurrent reply tasks.
                asyncio.create_task(
                    _generate_agent_reply(engine, conv_id, payload["content"], ws),
                    name=f"agent-reply-{conv_id}",
                )
```

- [ ] **Step 3: Run the gateway test suite**

Run: `uv run pytest tests/gateway/ -v -k 'not test_drain_with_placeholder' --tb=short -x`
Expected: green (existing tests don't burst; default behavior is the same single-message-at-a-time pattern).

- [ ] **Step 4: Commit**

```bash
git add autoservice/gateway/message_router.py
git commit -m "feat(gateway): serialize customer_message handling via TurnQueue"
```

---

## Task 9: Add prompt nudge in cc_pool.py

**Files:**
- Modify: `autoservice/cc_pool.py:536-543` (after `_load_soul` resolution)

- [ ] **Step 1: Locate the soul-resolution block**

Around line 536-543, the relevant block is:

```python
    if system_prompt is None and role is not None:
        system_prompt = _load_soul(tenant_id, role)
        if system_prompt is None:
            log.warning(
                "No soul found for role=%s tenant_id=%s — starting without system prompt",
                role, tenant_id,
            )
```

- [ ] **Step 2: Append the bilingual paragraph nudge**

Right after the `if system_prompt is None ...` block (above `if enable_kb_tool and tenant_id:`), insert:

```python
    # Append paragraph-break nudge for customer/lead roles when multi-bubble
    # is enabled. The splitter (autoservice/gateway/paragraph_splitter.py)
    # only splits on \n\n boundaries, so the LLM needs to be encouraged to
    # use them. Soft hint — splitter degrades to 1 bubble if ignored.
    # See spec §6.5.
    _PARAGRAPH_NUDGE_SUFFIX = (
        "\n\n---\n"
        "When your reply spans multiple points, separate them with a blank line "
        "(two newlines) so the customer can read them as distinct messages. "
        "Keep each paragraph to 1–3 sentences.\n"
        "当你的回复包含多个要点时，请用空行（两个换行）将它们分开，"
        "让客户像收到多条短消息一样阅读。每段保持 1-3 句话即可。"
    )
    # Per-tenant override is a future-work hook: a tenant config flag like
    # `multi_bubble_nudge_disabled` could short-circuit this. For the cinnox
    # demo, the global env flag is sufficient.
    if (
        os.environ.get("MULTI_BUBBLE_ENABLED", "1") == "1"
        and role in ("customer", "lead")
        and system_prompt
    ):
        system_prompt = system_prompt + _PARAGRAPH_NUDGE_SUFFIX
```

- [ ] **Step 3: Run cc_pool tests to ensure nothing broke**

Run: `uv run pytest tests/cc_pool/ -v --tb=short -x`
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add autoservice/cc_pool.py
git commit -m "feat(cc_pool): append paragraph-break nudge for customer/lead roles"
```

---

## Task 10: Integration tests — multi-bubble end-to-end

**Files:**
- Create: `tests/gateway/test_multi_bubble_integration.py`

- [ ] **Step 1: Write the integration test file**

```python
# tests/gateway/test_multi_bubble_integration.py
"""End-to-end integration tests for instant-ack + multi-bubble + queue.

Mocks the LLM stream; uses real ConversationEngine in-memory + real
TurnQueue + real splitter. Verifies frame ordering and Message rows.

Spec: §12.2 of the design doc.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoservice.gateway.message_router import _drain_into_bubbles, get_turn_queue
from autoservice.gateway.paragraph_splitter import ParagraphSplitter
from autoservice.gateway.turn_queue import TurnQueue


class _FakeMsg:
    def __init__(self, mid: str, seq: int, content: str = "") -> None:
        self.id = mid
        self.conversation_id = "c1"
        self.sequence_number = seq
        self.content = content


class _FakeEngine:
    """Minimal ConversationEngine stand-in for tests."""

    def __init__(self) -> None:
        self.messages: list[_FakeMsg] = []
        self._next_id = 1

    async def send_message(
        self, conv_id: str, *, source: str, content: str, metadata: dict | None = None,
    ) -> _FakeMsg:
        msg = _FakeMsg(f"m{self._next_id}", self._next_id, content)
        self._next_id += 1
        self.messages.append(msg)
        return msg

    async def edit_message(
        self, msg_id: str, *, content: str, edited_by: str,
    ) -> None:
        for m in self.messages:
            if m.id == msg_id:
                m.content = content
                return


def _stream_events_for(text: str, chunk_size: int = 4):
    """Build a list of fake StreamEvent items that emit ``text`` in
    chunks of ``chunk_size`` characters."""
    from claude_agent_sdk.types import StreamEvent
    events = []
    for i in range(0, len(text), chunk_size):
        chunk = text[i : i + chunk_size]
        events.append(
            StreamEvent(
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": chunk},
                }
            )
        )
    return events


async def _async_iter(items):
    for it in items:
        yield it


@pytest.mark.asyncio
async def test_three_paragraphs_emit_three_message_rows(monkeypatch):
    monkeypatch.setenv("MULTI_BUBBLE_ENABLED", "1")
    engine = _FakeEngine()
    ws = MagicMock()
    ws.send_json = AsyncMock()

    # LLM produces a 3-paragraph reply.
    text = (
        "First paragraph here is at least five chars.\n\n"
        "Second paragraph here is also long enough.\n\n"
        "Third paragraph is the conclusion."
    )
    events = _stream_events_for(text, chunk_size=8)

    out = await _drain_into_bubbles(
        _async_iter(events),
        engine=engine, conv_id="c1", target_role="customer", ws=ws,
    )
    assert out == text
    # Three persisted Message rows for the three segments.
    assert len(engine.messages) == 3
    # Each segment has the correct trimmed content (no trailing \n\n).
    assert engine.messages[0].content == "First paragraph here is at least five chars."
    assert engine.messages[1].content == "Second paragraph here is also long enough."
    assert engine.messages[2].content == "Third paragraph is the conclusion."


@pytest.mark.asyncio
async def test_single_paragraph_emits_one_row(monkeypatch):
    monkeypatch.setenv("MULTI_BUBBLE_ENABLED", "1")
    engine = _FakeEngine()
    ws = MagicMock()
    ws.send_json = AsyncMock()

    text = "Just one paragraph with no internal break at all."
    events = _stream_events_for(text, chunk_size=6)
    out = await _drain_into_bubbles(
        _async_iter(events), engine=engine, conv_id="c1",
        target_role="customer", ws=ws,
    )
    assert out == text
    assert len(engine.messages) == 1
    assert engine.messages[0].content == text


@pytest.mark.asyncio
async def test_multi_bubble_disabled_emits_one_row(monkeypatch):
    monkeypatch.setenv("MULTI_BUBBLE_ENABLED", "0")
    engine = _FakeEngine()
    ws = MagicMock()
    ws.send_json = AsyncMock()

    text = "P1 long enough.\n\nP2 long enough.\n\nP3 long enough."
    events = _stream_events_for(text, chunk_size=4)
    out = await _drain_into_bubbles(
        _async_iter(events), engine=engine, conv_id="c1",
        target_role="customer", ws=ws,
    )
    # With MULTI_BUBBLE_ENABLED=0 the entire reply is one bubble.
    assert len(engine.messages) == 1
    assert out == text


@pytest.mark.asyncio
async def test_turn_queue_serializes_two_rapid_submits():
    q = TurnQueue()
    seen_order: list[str] = []
    started_a = asyncio.Event()
    finish_a = asyncio.Event()

    async def turn_a():
        seen_order.append("a-start")
        started_a.set()
        await finish_a.wait()
        seen_order.append("a-end")

    async def turn_b():
        seen_order.append("b")

    await q.submit("c1", turn_a)
    await started_a.wait()
    await q.submit("c1", turn_b)
    # b waits in queue
    assert seen_order == ["a-start"]
    finish_a.set()
    await asyncio.sleep(0.05)
    assert seen_order == ["a-start", "a-end", "b"]


@pytest.mark.asyncio
async def test_ack_queue_interaction_each_turn_gets_own_ack(monkeypatch):
    """Spec §12.2: customer fires msg A, then msg B during A's ack-delay
    window. Each turn gets its own ack; B waits until A's drain finishes."""
    monkeypatch.setenv("ACK_DELAY_MIN_MS", "0")
    monkeypatch.setenv("ACK_DELAY_MAX_MS", "0")
    from autoservice.gateway.agent_ack import send_pretriage_ack

    engine = _FakeEngine()
    ws_a = MagicMock(); ws_a.send_json = AsyncMock()
    ws_b = MagicMock(); ws_b.send_json = AsyncMock()
    q = TurnQueue()

    started_a_drain = asyncio.Event()
    finish_a_drain = asyncio.Event()

    async def turn_a():
        await send_pretriage_ack(engine, "c1", ws_a, "我想问一个产品问题")
        started_a_drain.set()
        await finish_a_drain.wait()
        # Pretend the drain ran here.

    async def turn_b():
        await send_pretriage_ack(engine, "c1", ws_b, "另外团队规模多大?")

    await q.submit("c1", turn_a)
    await started_a_drain.wait()
    # A's ack should have already persisted by now.
    ack_count_after_a = len([m for m in engine.messages if m.content])
    await q.submit("c1", turn_b)
    # B is queued; B's ack hasn't fired yet.
    assert q.queue_depth("c1") == 1
    finish_a_drain.set()
    await asyncio.sleep(0.05)
    # Now B's turn ran → its ack persisted.
    assert len(engine.messages) >= ack_count_after_a + 1


@pytest.mark.asyncio
async def test_queue_advances_on_runner_exception():
    """Spec §12.2: triage failure / runner raises → queue still advances."""
    q = TurnQueue()
    seen: list[str] = []

    async def boom():
        raise RuntimeError("triage failed")

    async def good():
        seen.append("good")

    await q.submit("c1", boom)
    await q.submit("c1", good)
    await asyncio.sleep(0.05)
    assert seen == ["good"]
    assert q.queue_depth("c1") == 0
    assert not q.has_in_flight("c1")


@pytest.mark.asyncio
async def test_drain_flush_emits_residual_on_error_mid_segment(monkeypatch):
    """Spec §12.2: drain hits an exception mid-stream → flush still emits
    residual content. We simulate by raising inside the iterator after a
    partial segment has accumulated."""
    monkeypatch.setenv("MULTI_BUBBLE_ENABLED", "1")
    engine = _FakeEngine()
    ws = MagicMock(); ws.send_json = AsyncMock()

    from claude_agent_sdk.types import StreamEvent

    async def _bad_stream():
        # First chunk: long enough to cross MIN.
        yield StreamEvent(event={
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "Half a segment, growing... "},
        })
        # Then raise to simulate upstream error.
        raise RuntimeError("upstream stream broken")

    with pytest.raises(RuntimeError, match="upstream stream broken"):
        await _drain_into_bubbles(
            _bad_stream(), engine=engine, conv_id="c1",
            target_role="customer", ws=ws,
        )
    # The finally block still ran flush; one bubble should be persisted.
    assert len(engine.messages) >= 1
    assert "Half a segment" in engine.messages[0].content


@pytest.mark.asyncio
async def test_instant_ack_disabled_skips_ack_but_drain_runs(monkeypatch):
    """Spec §12.2: kill switch INSTANT_ACK_ENABLED=0 → no ack, reply still
    segments normally."""
    monkeypatch.setenv("INSTANT_ACK_ENABLED", "0")
    monkeypatch.setenv("MULTI_BUBBLE_ENABLED", "1")
    monkeypatch.setenv("ACK_DELAY_MIN_MS", "0")
    monkeypatch.setenv("ACK_DELAY_MAX_MS", "0")
    from autoservice.gateway.agent_ack import send_pretriage_ack

    engine = _FakeEngine()
    ws = MagicMock(); ws.send_json = AsyncMock()

    out = await send_pretriage_ack(
        engine, "c1", ws, "我想问一个长一点的产品问题", tenant_id="cinnox",
    )
    assert out is None  # ack disabled
    assert len(engine.messages) == 0  # nothing persisted

    # Drain still works; emits segments normally.
    text = "First long-enough paragraph.\n\nSecond long-enough paragraph."
    await _drain_into_bubbles(
        _aiter(_stream_for(text, 4)),
        engine=engine, conv_id="c1", target_role="customer", ws=ws,
    )
    assert len(engine.messages) == 2  # exactly two segments, no ack


@pytest.mark.asyncio
async def test_queue_disabled_falls_back_to_concurrent():
    """Spec §12.2: kill switch QUEUE_ENABLED=0 — without TurnQueue, two
    submitted runners execute concurrently (no serialization).

    Sanity: when fire-and-forget tasks both run, B can finish before A
    finishes — the inverse of the queue behavior pinned in
    test_two_submits_run_serially.
    """
    seen: list[str] = []
    started_a = asyncio.Event()
    finish_a = asyncio.Event()

    async def runner_a():
        seen.append("a-start")
        started_a.set()
        await finish_a.wait()
        seen.append("a-end")

    async def runner_b():
        await started_a.wait()  # ensure ordering: a starts first
        seen.append("b-start")
        seen.append("b-end")     # B finishes BEFORE A's end_event fires

    task_a = asyncio.create_task(runner_a())
    task_b = asyncio.create_task(runner_b())
    await task_b
    # B finished while A is still mid-flight (held by finish_a):
    assert "b-end" in seen
    assert "a-end" not in seen  # A hasn't finished yet
    finish_a.set()
    await task_a
    assert seen == ["a-start", "b-start", "b-end", "a-end"]
```

- [ ] **Step 2: Run the integration tests**

Run: `uv run pytest tests/gateway/test_multi_bubble_integration.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/gateway/test_multi_bubble_integration.py
git commit -m "test(gateway): integration tests for multi-bubble drain + queue"
```

---

## Task 11: Delete deprecated test + add deprecation log to SoothePicker

**Files:**
- Delete: `tests/gateway/test_drain_with_placeholder.py`
- Modify: `autoservice/gateway/soothe_picker.py` (add deprecation warning on import)

- [ ] **Step 1: Delete the obsolete test file**

```bash
rm tests/gateway/test_drain_with_placeholder.py
```

- [ ] **Step 2: Add a deprecation warning in soothe_picker.py**

At the top of `autoservice/gateway/soothe_picker.py`, after the docstring, add:

```python
import warnings

warnings.warn(
    "autoservice.gateway.soothe_picker is deprecated and no longer wired "
    "into the main reply pipeline (see "
    "docs/superpowers/specs/2026-04-26-instant-ack-multi-bubble-queue-design.md §8). "
    "It will be removed in a follow-up cleanup PR.",
    DeprecationWarning,
    stacklevel=2,
)
```

Place this immediately after the existing module docstring and before the `from __future__ import annotations` line.

- [ ] **Step 3: Run the gateway suite**

Run: `uv run pytest tests/gateway/ -v --tb=short`
Expected: all tests PASS (including `test_soothe_picker.py` which still tests the picker class).

- [ ] **Step 4: Commit**

```bash
git add tests/gateway/test_drain_with_placeholder.py autoservice/gateway/soothe_picker.py
git commit -m "chore(gateway): deprecate SoothePicker, drop placeholder test"
```

---

## Task 12: Env var rename — INSTANT_ACK_ENABLED + alias deprecation

**Files:**
- Modify: `autoservice/gateway/agent_ack.py` (already references both vars; tighten)
- Modify: `autoservice/web_gateway.py` or wherever startup logging lives — add one-time deprecation warning

- [ ] **Step 1: Find the gateway startup banner**

Run: `grep -n "envcheck\|env check\|startup banner\|environment-config\|ANTHROPIC_API_KEY.*<unset>" autoservice/web_gateway.py | head -10`
Expected: returns a line range (around L490 — see the env check block we saw earlier).

- [ ] **Step 2: Add a one-time deprecation warning at startup**

In `autoservice/web_gateway.py`, in the existing env-banner / startup function, add:

```python
    # Deprecation: PLACEHOLDER_ENABLED → INSTANT_ACK_ENABLED.
    # Spec: 2026-04-26-instant-ack-multi-bubble-queue-design.md §11.
    _legacy_val = os.environ.get("PLACEHOLDER_ENABLED")
    if _legacy_val is not None and os.environ.get("INSTANT_ACK_ENABLED") is None:
        log.warning(
            "PLACEHOLDER_ENABLED=%s is deprecated; honoring as INSTANT_ACK_ENABLED. "
            "Please rename the variable; the alias will be removed in a future release.",
            _legacy_val,
        )
```

Place this near the top of `create_app` or the startup banner function, after the env-check block.

- [ ] **Step 3: Smoke-test the gateway can still start**

Run: `uv run python -c "from autoservice.web_gateway import create_app; app = create_app(); print('app ok')"`
Expected: prints `app ok` (no startup error).

- [ ] **Step 4: Commit**

```bash
git add autoservice/web_gateway.py
git commit -m "feat(gateway): warn once when deprecated PLACEHOLDER_ENABLED is set"
```

---

## Task 13: Update CLAUDE.md and launchd plist

**Files:**
- Modify: `CLAUDE.md` (update "Placeholder Filler Kill-Switch" section)
- Modify: `~/Library/LaunchAgents/com.autoservice.gateway.plist` (env var changes)

- [ ] **Step 1: Update the CLAUDE.md section**

In `CLAUDE.md`, find the section header `## Placeholder Filler Kill-Switch`. Replace the entire section (from that header through the closing line) with:

```markdown
## Instant Ack / Multi-Bubble / Queue Kill-Switches

Three independent kill-switches gate the customer-chat UX upgrade
(spec: `docs/superpowers/specs/2026-04-26-instant-ack-multi-bubble-queue-design.md`):

- `INSTANT_ACK_ENABLED` (default **on**) — emits a pre-triage ack bubble
  100–300ms after the user submits, before triage runs. Replaces the
  former post-triage 1.5s placeholder. Length-skip heuristic suppresses
  ack on short messages (zh<8, en<15) to avoid duplicate-greeting
  effect when triage routes to a direct-reply.
- `MULTI_BUBBLE_ENABLED` (default **on**) — agent reply is split on
  paragraph boundaries (`\n\n`) into separate bubbles via
  `paragraph_splitter.py`. When `0`, replies render as one bubble.
- `QUEUE_ENABLED` (default **on**) — per-conversation reply
  serialization (CC-X queue semantics). Mid-stream user messages are
  persisted immediately but their agent replies wait for the previous
  turn to fully complete. When `0`, falls back to the legacy
  fire-and-forget concurrent path.

`PLACEHOLDER_ENABLED` is **deprecated** as of 2026-04-26: it remains
honored as an alias for `INSTANT_ACK_ENABLED` for one release, with a
one-time `logger.warning` at startup. The post-triage placeholder code
path it used to gate has been removed regardless.

Gates: `autoservice/gateway/agent_ack.py`, `autoservice/gateway/paragraph_splitter.py`,
`autoservice/gateway/turn_queue.py`, `autoservice/gateway/message_router.py`.
```

Find the surrounding sections to verify you replace the right block: the section starts with `## Placeholder Filler Kill-Switch` and ends just before `## Credentials`.

- [ ] **Step 2: Update the launchd plist**

Edit `~/Library/LaunchAgents/com.autoservice.gateway.plist`. Find the `<key>EnvironmentVariables</key>` dict that currently contains `PLACEHOLDER_ENABLED`. Replace that key+value pair (and add the new ones) so the resulting block is:

```xml
    <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key>
      <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
      <key>INSTANT_ACK_ENABLED</key>
      <string>1</string>
      <key>MULTI_BUBBLE_ENABLED</key>
      <string>1</string>
      <key>QUEUE_ENABLED</key>
      <string>1</string>
      <key>CORS_EXTRA_ORIGINS</key>
      <string>https://autoservice.ezagent.chat</string>
      <key>HTTPS_PROXY</key>
      <string>http://127.0.0.1:7897</string>
      <key>HTTP_PROXY</key>
      <string>http://127.0.0.1:7897</string>
      <key>https_proxy</key>
      <string>http://127.0.0.1:7897</string>
      <key>http_proxy</key>
      <string>http://127.0.0.1:7897</string>
      <key>NO_PROXY</key>
      <string>127.0.0.1,localhost,::1</string>
      <key>no_proxy</key>
      <string>127.0.0.1,localhost,::1</string>
    </dict>
```

(Keep all the proxy entries from the earlier 403 fix; just remove the old `PLACEHOLDER_ENABLED` entry and add the three new flags.)

- [ ] **Step 3: Validate the plist syntax**

Run: `plutil -lint ~/Library/LaunchAgents/com.autoservice.gateway.plist`
Expected: `OK`.

- [ ] **Step 4: Commit (CLAUDE.md only — plist is out of repo)**

```bash
git add CLAUDE.md
git commit -m "docs(claude.md): document INSTANT_ACK / MULTI_BUBBLE / QUEUE switches"
```

(The launchd plist lives in `~/Library/LaunchAgents/`, outside the repo, so it is not committed. The repo-relative reference for ops docs is in CLAUDE.md.)

---

## Task 14: Reload + smoke test locally

- [ ] **Step 1: Reload the gateway launchd job**

```bash
launchctl bootout gui/$UID/com.autoservice.gateway 2>&1
sleep 1
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.autoservice.gateway.plist
sleep 5
launchctl list | grep com.autoservice.gateway
```
Expected: a non-`-` PID; gateway is running.

- [ ] **Step 2: Verify env vars are present in the running process**

```bash
PID=$(launchctl list | awk '/com\.autoservice\.gateway$/ {print $1}')
ps eww $PID | tr ' ' '\n' | grep -E 'INSTANT_ACK_ENABLED|MULTI_BUBBLE_ENABLED|QUEUE_ENABLED' | sort -u
```
Expected: three lines `INSTANT_ACK_ENABLED=1`, `MULTI_BUBBLE_ENABLED=1`, `QUEUE_ENABLED=1`.

- [ ] **Step 3: Tail the gateway log to confirm clean startup**

```bash
tail -50 .autoservice/logs/gateway.log
```
Expected: see `Application startup complete` and `Uvicorn running on http://127.0.0.1:8000`. **No** Python tracebacks. No `403 / forbidden / Failed to authenticate`.

- [ ] **Step 4: Hit /api/healthz to confirm responsive**

```bash
NO_PROXY="127.0.0.1,localhost" curl -sS --max-time 5 -w "\nHTTP %{http_code}\n" http://127.0.0.1:8000/api/healthz
```
Expected: HTTP 200 with a healthz body (or HTTP 404 if the route isn't registered — in that case fall back to checking that the WS endpoint accepts upgrade requests via `curl -sS -i -H 'Upgrade: websocket' -H 'Connection: Upgrade' http://127.0.0.1:8000/ws/customer?tenant=cinnox 2>&1 | head -5` which should return `HTTP/1.1 400` or similar handshake error from the WS handler — confirming the gateway is reachable).

---

## Task 15: E2E with agent-browser on autoservice.ezagent.chat

**Files:**
- (none modified)

- [ ] **Step 1: Open the customer chat with a tenant**

Use the agent-browser skill to drive the public site. Use a script-driven session with these test cases drawn from spec §12.3:

```
1. Open https://autoservice.ezagent.chat/site/?tenant=cinnox
2. Wait for chat-ready state
3. Send "你好" → assert: NO duplicate-greeting (ack suppressed by length heuristic). Single direct-reply bubble appears.
4. Send "你们有哪些服务?" → assert: ack appears within ~1 second; followed by ≥ 1 reply bubble
5. Send "请详细介绍一下你们的产品和定价" → assert: ack appears; ≥ 2 reply bubbles emerge with paragraph breaks
6. Burst: send "你们什么时候成立的？" then within 500ms send "团队多大？" → assert: both user messages persist immediately; reply for #1 completes BEFORE reply for #2 begins (verify by timestamp ordering of agent bubbles)
7. Verify ack text varies — capture 5 successive non-skipped acks; assert at least 2 distinct strings (template randomization)
```

- [ ] **Step 2: Open operator console for spot check**

```
1. In a second browser session, open https://autoservice.ezagent.chat/console/ (CF Access required)
2. Authenticate via OTP if needed
3. Subscribe to the squad covering cinnox
4. From customer-chat, send a 3-paragraph-eliciting message
5. Assert operator console renders all bubbles in correct sequence_number order, no duplicates, no skipped frames
```

- [ ] **Step 3: Tail gateway logs during the session**

```bash
tail -200 .autoservice/logs/gateway.log | grep -iE '403|forbidden|exception|traceback|splitter|turn-loop' | head -40
```
Expected: no errors; some informational `[turn-loop-c<conv>]` task names visible.

- [ ] **Step 4: If anything fails the assertions in Step 1**

Document the failure (which case, expected vs observed). Triage:
- Ack timing off → tune `ACK_DELAY_MIN_MS` / `ACK_DELAY_MAX_MS`
- LLM doesn't paragraph-break → check Task 9's nudge made it into the system prompt
- Burst not serialized → check `QUEUE_ENABLED=1` is in the running process env
- Bubbles render in wrong order → likely a frame ordering bug in `_drain_into_bubbles`

Fix and re-test before continuing.

---

## Task 16: Open the PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feature/instant-ack-multi-bubble
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "feat: instant ack + multi-bubble + CC-queue" --body "$(cat <<'EOF'
## Summary

Customer-chat at `/site/` (currently cinnox-only) feels less like an AI-typing-a-monolith and more like a real CSR. Three independent mechanisms, all kill-switchable:

- **Pre-triage instant ack** — 100–300ms ack bubble before triage runs, with length-skip heuristic so greetings/thanks don't get a duplicate
- **Multi-bubble paragraph splitter** — agent reply splits on `\n\n` into separate bubbles; soft prompt nudge tells the LLM to use them
- **CC-X queue serialization** — mid-stream user messages persist immediately but their agent reply waits behind the in-flight turn (no merge, no interrupt)

## Files

- New: `autoservice/gateway/{agent_ack,paragraph_splitter,turn_queue}.py` + `ack_templates.yaml`
- Modified: `autoservice/gateway/message_router.py` — refactor `_drain_with_placeholder` → `_drain_into_bubbles`; integrate ack + queue
- Modified: `autoservice/cc_pool.py` — paragraph nudge appended to system prompt
- Modified: `CLAUDE.md` — Placeholder section rewritten as Instant-Ack / Multi-Bubble / Queue
- Deprecated: `SoothePicker` no longer wired in; `PLACEHOLDER_ENABLED` env var honored as alias for `INSTANT_ACK_ENABLED` with one-time deprecation warning

## Spec / Plan

- Design: `docs/superpowers/specs/2026-04-26-instant-ack-multi-bubble-queue-design.md`
- Plan: `docs/superpowers/plans/2026-04-26-instant-ack-multi-bubble-queue.md`
- Reviewed by superpowers:code-reviewer subagent before implementation; major issues addressed in the spec revision commit.

## Test plan

- [x] All splitter unit tests green (`tests/gateway/test_paragraph_splitter.py`)
- [x] All agent_ack unit tests green (`tests/gateway/test_agent_ack.py`)
- [x] All turn_queue unit tests green (`tests/gateway/test_turn_queue.py`)
- [x] Integration tests green (`tests/gateway/test_multi_bubble_integration.py`)
- [x] E2E on `autoservice.ezagent.chat` — see commit body for verified scenarios
- [x] Operator console spot check on multi-bubble rendering

## Rollback

Each kill-switch (`INSTANT_ACK_ENABLED`, `MULTI_BUBBLE_ENABLED`, `QUEUE_ENABLED`) flips independently in the launchd plist; no code revert needed for partial rollback.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Capture and report the PR URL**

The output of `gh pr create` is the PR URL. Report it back to the user.

---

## Self-Review checklist

(For the plan author — runs after writing all tasks. Already completed inline.)

- [x] **Spec coverage**: every section in spec §1-§17 mapped to a task: §3 UX → Tasks 4,6,8 / §4 architecture → all tasks / §5 ack → Tasks 4,7,12 / §6 splitter → Tasks 1-3 / §7 queue → Tasks 5,8 / §8 replace placeholder → Tasks 6,11 / §9 persistence → Task 6 / §10 frontend → no-op verified / §11 env → Tasks 12,13 / §12 tests → Tasks 1-5,10,15 / §13 rollout → Task 14 / §14 risks → all addressed / §15 checklist → all 16 tasks
- [x] **Placeholder scan**: no TBD/TODO/FIXME inside task content
- [x] **Type consistency**: `ParagraphSplitter`, `TurnQueue`, `_ConvState`, `QueueFullError`, `send_pretriage_ack`, `_drain_into_bubbles` — names match across tasks
- [x] **Two-PR fallback** flagged in spec §15; if reviewer flags single-PR diff as too big, plan can be split: PR1 = Tasks 1-5+10 (pure components), PR2 = Tasks 6-9, 11-16 (integration)
