"""Tests for SipVoiceController — MINIMAL version per 08 doc.

08 deliberately ships without comfort / barge-in / streaming TTS.
The controller is a sequential state machine: greeting → listen →
think → speak → listen → ... Tests verify only that contract.

Optimizations (comfort, barge-in, streaming) are 06's job, post-PoC.
"""
import asyncio

import pytest

from channels.web.voice.sip_controller import SipVoiceController, State


# ──────────────────────────────── Fakes ────────────────────────────────


class _FakeASR:
    """Yields scripted events. Records audio chunks pumped to it."""

    def __init__(self, events: list[dict]):
        self._events = events
        self.audio_chunks: list[bytes] = []
        self.closed = False

    async def connect(self) -> None:
        pass

    async def send_audio(self, chunk: bytes) -> None:
        self.audio_chunks.append(chunk)

    async def receive(self):
        for ev in self._events:
            yield ev

    async def close(self) -> None:
        self.closed = True


class _FakeTTS:
    """Records synthesize() calls; yields a fixed PCM chunk."""

    def __init__(self):
        self.synth_calls: list[str] = []
        self.closed = False

    async def connect(self) -> None:
        pass

    async def synthesize(self, text: str):
        self.synth_calls.append(text)
        yield b"\x00\x00" * 240

    async def close(self) -> None:
        self.closed = True


class _FakeCC:
    def __init__(self, reply: str = "default reply", raises: Exception | None = None):
        self._reply = reply
        self._raises = raises
        self.send_calls: list[str] = []
        self.closed = False

    async def connect(self) -> None:
        pass

    async def send(self, text: str) -> str:
        self.send_calls.append(text)
        if self._raises is not None:
            raise self._raises
        return self._reply

    async def close(self) -> None:
        self.closed = True


class _FakeWS:
    """iter_bytes mirrors a real WebSocket: yields scripted chunks, then
    blocks until the surrounding task is cancelled."""

    def __init__(self, inbound: list[bytes] | None = None):
        self._inbound = inbound or []
        self.bytes_sent: list[bytes] = []

    async def iter_bytes(self):
        for c in self._inbound:
            yield c
        await asyncio.Future()  # block until cancelled by run()'s cleanup

    async def send_bytes(self, b: bytes) -> None:
        self.bytes_sent.append(b)


def _make_controller(*, asr=None, tts=None, cc=None, ws=None) -> SipVoiceController:
    return SipVoiceController(
        call_sid="call-test",
        caller="+85212345678",
        callee="+85287654321",
        ws=ws or _FakeWS(),
        asr=asr or _FakeASR([]),
        tts=tts or _FakeTTS(),
        cc=cc or _FakeCC(),
    )


# ──────────────────────────────── Tests ────────────────────────────────


@pytest.mark.asyncio
async def test_run_speaks_greeting_then_transitions_to_listening():
    """On startup: connect upstreams, speak greeting, settle into LISTENING."""
    tts = _FakeTTS()
    asr = _FakeASR([])  # no events → handler returns immediately after greeting
    controller = _make_controller(tts=tts, asr=asr)

    await controller.run()

    assert len(tts.synth_calls) == 1
    assert tts.synth_calls[0]  # greeting text non-empty
    assert controller.state == State.LISTENING


@pytest.mark.asyncio
async def test_full_turn_calls_cc_and_speaks_reply_sequentially():
    """ASR final → cc.send → speak reply. No comfort, no parallel work."""
    tts = _FakeTTS()
    cc = _FakeCC(reply="iPhone 15 起售价 5999 元。")
    asr = _FakeASR([
        {"type": "conversation.item.input_audio_transcription.completed",
         "transcript": "iPhone 15 多少钱"},
    ])
    controller = _make_controller(tts=tts, asr=asr, cc=cc)

    await controller.run()

    assert cc.send_calls == ["iPhone 15 多少钱"]
    # Exactly two TTS calls: greeting + reply (NO comfort)
    assert len(tts.synth_calls) == 2
    assert tts.synth_calls[1] == "iPhone 15 起售价 5999 元。"
    assert controller.state == State.LISTENING


@pytest.mark.asyncio
async def test_speech_started_event_is_ignored():
    """08 minimal explicitly does NOT do barge-in. speech_started events
    must be silently ignored (no crash, no state change)."""
    tts = _FakeTTS()
    cc = _FakeCC()
    asr = _FakeASR([
        {"type": "input_audio_buffer.speech_started"},
        {"type": "input_audio_buffer.speech_started"},
    ])
    controller = _make_controller(tts=tts, asr=asr, cc=cc)

    await controller.run()  # must not raise

    # Only greeting was spoken; no cc.send fired
    assert len(tts.synth_calls) == 1
    assert cc.send_calls == []


@pytest.mark.asyncio
async def test_empty_transcript_is_ignored():
    """ASR final with empty/whitespace transcript → no cc.send."""
    tts = _FakeTTS()
    cc = _FakeCC()
    asr = _FakeASR([
        {"type": "conversation.item.input_audio_transcription.completed",
         "transcript": "   "},
        {"type": "conversation.item.input_audio_transcription.completed",
         "transcript": ""},
    ])
    controller = _make_controller(tts=tts, asr=asr, cc=cc)

    await controller.run()

    assert cc.send_calls == []
    # Only greeting spoken
    assert len(tts.synth_calls) == 1


@pytest.mark.asyncio
async def test_cc_error_speaks_fallback_message():
    """cc.send raises → controller speaks a fallback so caller hears something."""
    tts = _FakeTTS()
    cc = _FakeCC(raises=RuntimeError("pool unreachable"))
    asr = _FakeASR([
        {"type": "conversation.item.input_audio_transcription.completed",
         "transcript": "hi"},
    ])
    controller = _make_controller(tts=tts, asr=asr, cc=cc)

    await controller.run()

    assert cc.send_calls == ["hi"]
    # Two TTS calls: greeting + fallback
    assert len(tts.synth_calls) == 2
    assert "抱歉" in tts.synth_calls[1]


@pytest.mark.asyncio
async def test_pump_forwards_inbound_audio_to_asr():
    """Bytes received on ws.iter_bytes() are forwarded to asr.send_audio()."""
    tts = _FakeTTS()
    asr = _FakeASR([])
    ws = _FakeWS(inbound=[b"frame1" * 80, b"frame2" * 80])
    controller = _make_controller(tts=tts, asr=asr, ws=ws)

    await controller.run()

    assert b"frame1" * 80 in asr.audio_chunks
    assert b"frame2" * 80 in asr.audio_chunks


@pytest.mark.asyncio
async def test_shutdown_closes_all_upstream_clients():
    tts = _FakeTTS()
    cc = _FakeCC()
    asr = _FakeASR([])
    controller = _make_controller(tts=tts, asr=asr, cc=cc)

    await controller.run()
    await controller.shutdown()

    assert tts.closed
    assert cc.closed
    assert asr.closed


@pytest.mark.asyncio
async def test_shutdown_continues_when_one_client_close_raises():
    """One failing close() must not skip the others (resource leak otherwise)."""

    class BadASR(_FakeASR):
        async def close(self):
            raise RuntimeError("asr stuck")

    bad_asr = BadASR([])
    tts = _FakeTTS()
    cc = _FakeCC()
    controller = _make_controller(tts=tts, asr=bad_asr, cc=cc)

    await controller.run()
    await controller.shutdown()  # must not raise

    assert tts.closed, "TTS close must run even if ASR close failed"
    assert cc.closed, "CC close must run even if ASR close failed"
