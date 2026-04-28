"""Unit tests for VoiceEngineBridge.

Covers the bridge's contract with cc_pool.session_query — a single user
turn yields the concatenated text from all AssistantMessage content
blocks; non-text blocks (tool use, etc.) are dropped; timeout raises
asyncio.TimeoutError.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from channels.web.voice.voice_engine_bridge import VoiceEngineBridge


def _text_block(text: str):
    return SimpleNamespace(text=text)


def _tool_block():
    # No `text` attr → bridge should ignore it.
    return SimpleNamespace(name="some_tool", input={})


def _assistant_msg(*blocks):
    return SimpleNamespace(content=list(blocks))


class _FakeCcPool:
    """Minimal cc_pool double exposing only session_query as an async iter."""

    def __init__(self, *messages_per_turn):
        self.messages_per_turn = list(messages_per_turn)
        self.calls: list[dict] = []

    def session_query(self, chat_id, prompt, *, tenant_id=None, tier=None, **kwargs):
        self.calls.append({
            "chat_id": chat_id, "prompt": prompt,
            "tenant_id": tenant_id, "tier": tier,
            "session_id": kwargs.get("session_id"),
        })
        messages = self.messages_per_turn.pop(0) if self.messages_per_turn else []

        async def _iter():
            for m in messages:
                yield m

        return _iter()


def _async_get_pool(pool):
    """Wrap a fake pool in an `async def` so it matches the real
    `autoservice.cc_pool.get_pool` signature (an awaitable)."""
    async def _factory(*args, **kwargs):
        return pool
    return _factory


async def test_bridge_query_concatenates_text_blocks_in_order():
    fake_pool = _FakeCcPool([
        _assistant_msg(_text_block("Hello, ")),
        _assistant_msg(_text_block("how can I help you?")),
    ])
    bridge = VoiceEngineBridge(
        conversation_id="conv_x", tenant_id="tnt_a", tier="fast",
    )
    with patch("autoservice.cc_pool.get_pool", _async_get_pool(fake_pool)):
        result = await bridge.query("hi", timeout=5.0)
    assert result == "Hello, how can I help you?"
    assert len(fake_pool.calls) == 1
    call = fake_pool.calls[0]
    assert call["chat_id"] == "conv_x"
    assert call["prompt"] == "hi"
    assert call["tenant_id"] == "tnt_a"
    assert call["tier"] == "fast"
    # session_id is generated per-bridge — just check it's set.
    assert call["session_id"] == bridge._cc_session_id


async def test_bridge_query_skips_non_text_blocks():
    fake_pool = _FakeCcPool([
        _assistant_msg(_text_block("Result: "), _tool_block(), _text_block("done.")),
    ])
    bridge = VoiceEngineBridge(conversation_id="c", tier="fast")
    with patch("autoservice.cc_pool.get_pool", _async_get_pool(fake_pool)):
        result = await bridge.query("query", timeout=5.0)
    assert result == "Result: done."


async def test_bridge_query_respects_timeout():
    class _SlowPool:
        def session_query(self, *args, **kwargs):
            async def _iter():
                await asyncio.sleep(10)
                yield _assistant_msg(_text_block("never"))
            return _iter()

    bridge = VoiceEngineBridge(conversation_id="c")
    slow_pool = _SlowPool()
    with patch("autoservice.cc_pool.get_pool", _async_get_pool(slow_pool)):
        with pytest.raises(asyncio.TimeoutError):
            await bridge.query("hi", timeout=0.05)


async def test_bridge_query_streams_chunks_via_on_chunk_callback():
    """on_chunk is awaited for each text fragment as it arrives so the
    caller (VoiceSession._run_query) can stream chat_tts_text to Doubao
    instead of waiting for the full reply."""
    fake_pool = _FakeCcPool([
        _assistant_msg(_text_block("Hello, ")),
        _assistant_msg(_text_block("how can ")),
        _assistant_msg(_text_block("I help?")),
    ])
    chunks: list[str] = []

    async def _on_chunk(chunk: str) -> None:
        chunks.append(chunk)

    bridge = VoiceEngineBridge(conversation_id="c", tier="fast")
    with patch("autoservice.cc_pool.get_pool", _async_get_pool(fake_pool)):
        result = await bridge.query("hi", timeout=5.0, on_chunk=_on_chunk)
    assert result == "Hello, how can I help?"
    assert chunks == ["Hello, ", "how can ", "I help?"]


async def test_bridge_query_returns_empty_string_on_no_messages():
    fake_pool = _FakeCcPool([])  # no messages
    bridge = VoiceEngineBridge(conversation_id="c")
    with patch("autoservice.cc_pool.get_pool", _async_get_pool(fake_pool)):
        result = await bridge.query("hi", timeout=5.0)
    assert result == ""


async def test_bridge_injects_voice_soul_prefix_on_first_turn_only(tmp_path, monkeypatch):
    """First user turn gets a voice-mode prefix from
    customer_soul.voice.md so Claude switches to short-sentence /
    no-markdown / ≤ 15 s replies. Subsequent turns rely on Claude's
    sticky-session memory and skip the prefix to save tokens."""
    monkeypatch.chdir(tmp_path)
    soul_dir = tmp_path / ".autoservice" / "sandbox" / "tnt_voice" / "souls"
    soul_dir.mkdir(parents=True)
    soul_path = soul_dir / "customer_soul.voice.md"
    soul_path.write_text("VOICE_RULES_FIXTURE", encoding="utf-8")

    fake_pool = _FakeCcPool(
        [_assistant_msg(_text_block("answer 1"))],
        [_assistant_msg(_text_block("answer 2"))],
    )
    bridge = VoiceEngineBridge(
        conversation_id="conv_voice",
        tenant_id="tnt_voice",
        tier="fast",
    )
    with patch("autoservice.cc_pool.get_pool", _async_get_pool(fake_pool)):
        # First turn — voice soul prefix must be wrapped around the user text.
        r1 = await bridge.query("hi", timeout=5.0)
        assert r1 == "answer 1"
        first_prompt = fake_pool.calls[0]["prompt"]
        assert "VOICE_RULES_FIXTURE" in first_prompt
        # User text MUST appear at the end of the prefix-wrapped prompt
        # (exact wording around it is implementation detail).
        assert first_prompt.rstrip().endswith("hi")

        # Second turn — sticky session retains the constraint, so the prefix
        # must NOT be re-injected (otherwise we burn tokens every turn).
        r2 = await bridge.query("how are you", timeout=5.0)
        assert r2 == "answer 2"
        second_prompt = fake_pool.calls[1]["prompt"]
        assert second_prompt == "how are you"
        assert "VOICE_RULES_FIXTURE" not in second_prompt


async def test_bridge_no_prefix_when_voice_soul_missing(tmp_path, monkeypatch):
    """Without a customer_soul.voice.md the bridge sends prompts as-is."""
    monkeypatch.chdir(tmp_path)
    fake_pool = _FakeCcPool([_assistant_msg(_text_block("ok"))])
    bridge = VoiceEngineBridge(
        conversation_id="conv_no_soul",
        tenant_id="tnt_no_voice",
    )
    with patch("autoservice.cc_pool.get_pool", _async_get_pool(fake_pool)):
        await bridge.query("ping", timeout=5.0)
    assert fake_pool.calls[0]["prompt"] == "ping"


async def test_bridge_strips_leaked_system_reminder_tags():
    """Claude occasionally appends `</system-reminder>` (and similar
    XML-style closing tags) when the prompt resembles a system block.
    The bridge MUST strip these before returning so they don't get
    spoken aloud by Doubao TTS or rendered into the chat bubble."""
    fake_pool = _FakeCcPool([
        _assistant_msg(_text_block(
            "您好，我是 CINNOX 的 AI 助手。 </system-reminder>"
        )),
    ])
    bridge = VoiceEngineBridge(conversation_id="c", tier="fast")
    with patch("autoservice.cc_pool.get_pool", _async_get_pool(fake_pool)):
        result = await bridge.query("hi", timeout=5.0)
    assert result == "您好，我是 CINNOX 的 AI 助手。"
    assert "</system-reminder>" not in result
    assert "<system-reminder>" not in result


async def test_bridge_strips_multiple_tag_variants():
    """Catches alternate spellings/cases the model emits: opening forms,
    snake/dash/no-separator, voice_mode_rules, ip_reminder."""
    fake_pool = _FakeCcPool([
        _assistant_msg(_text_block(
            "<system_reminder>ignore me</system_reminder>"
            "Real reply text."
            "<voice-mode-rules>foo</voice-mode-rules>"
            "<IP_REMINDER>bar</IP_REMINDER>"
        )),
    ])
    bridge = VoiceEngineBridge(conversation_id="c2")
    with patch("autoservice.cc_pool.get_pool", _async_get_pool(fake_pool)):
        result = await bridge.query("hi", timeout=5.0)
    # Tags removed; surrounding text preserved (note: content between an
    # opening and closing tag pair is NOT stripped — only the tags
    # themselves — but the user-visible artifact is the dangling tag,
    # so this is acceptable for our purpose).
    assert "<system" not in result
    assert "</system" not in result
    assert "<voice" not in result
    assert "</voice" not in result
    assert "<IP" not in result
    assert "Real reply text." in result


async def test_bridge_uses_unique_cc_session_id_per_instance():
    """Each VoiceEngineBridge generates its own cc_session_id so a
    disconnect+reconnect for the same conversation_id starts a fresh
    Claude conversation thread. Without this, the previous unfinished
    bot reply lingers in Claude's per-session history and the next
    voice call's first turn echoes / continues it."""
    fake_pool = _FakeCcPool(
        [_assistant_msg(_text_block("call 1 reply"))],
        [_assistant_msg(_text_block("call 2 reply"))],
    )
    bridge_a = VoiceEngineBridge(conversation_id="conv_shared")
    bridge_b = VoiceEngineBridge(conversation_id="conv_shared")
    assert bridge_a._cc_session_id != bridge_b._cc_session_id

    with patch("autoservice.cc_pool.get_pool", _async_get_pool(fake_pool)):
        await bridge_a.query("first call", timeout=5.0)
        await bridge_b.query("second call", timeout=5.0)

    sid_a = fake_pool.calls[0]["session_id"]
    sid_b = fake_pool.calls[1]["session_id"]
    assert sid_a == bridge_a._cc_session_id
    assert sid_b == bridge_b._cc_session_id
    assert sid_a != sid_b
    # conv_id (sticky binding key) is shared so we still hit the warm
    # tenant-pinned instance — only the Claude thread is fresh.
    assert fake_pool.calls[0]["chat_id"] == fake_pool.calls[1]["chat_id"] == "conv_shared"


async def test_bridge_keeps_session_id_stable_across_turns_within_one_call():
    """Within a single voice call the session_id must NOT change between
    turns — otherwise multi-turn voice loses Claude's per-thread memory
    of what the user just asked."""
    fake_pool = _FakeCcPool(
        [_assistant_msg(_text_block("turn 1"))],
        [_assistant_msg(_text_block("turn 2"))],
        [_assistant_msg(_text_block("turn 3"))],
    )
    bridge = VoiceEngineBridge(conversation_id="conv_x")
    with patch("autoservice.cc_pool.get_pool", _async_get_pool(fake_pool)):
        await bridge.query("hi", timeout=5.0)
        await bridge.query("how are you", timeout=5.0)
        await bridge.query("ok bye", timeout=5.0)

    session_ids = {c["session_id"] for c in fake_pool.calls}
    assert len(session_ids) == 1
    assert session_ids.pop() == bridge._cc_session_id


async def test_bridge_close_is_safe_when_pool_lacks_end_session():
    class _PoolNoEndSession:
        pass
    bridge = VoiceEngineBridge(conversation_id="c")
    pool_stub = _PoolNoEndSession()
    with patch("autoservice.cc_pool.get_pool", _async_get_pool(pool_stub)):
        await bridge.close()  # must not raise
