"""Tests for channels/web/voice/resample.py — 24k↔16k mono S16LE.

Why these tests matter for SIP path:
  - State preservation across chunks prevents audible clicks at 20ms frame boundaries
    (jambonz audio_fork pushes one frame every 20ms)
  - Per-key isolation prevents cross-call corruption when N concurrent calls run
"""
from channels.web.voice import resample


def _make_pcm(num_samples: int) -> bytes:
    """Deterministic non-silent S16LE PCM."""
    buf = bytearray()
    for i in range(num_samples):
        sample = (i * 100) % 32000 - 16000
        buf.extend(sample.to_bytes(2, "little", signed=True))
    return bytes(buf)


def test_resample_24k_to_16k_reduces_size_by_two_thirds():
    """480 samples at 24k (20ms frame) → ~320 samples at 16k (640 bytes ±)."""
    pcm_24k = _make_pcm(480)  # 960 bytes
    try:
        out = resample.resample_24k_to_16k(pcm_24k, key="t1")
    finally:
        resample.reset("t1")
    # 480 * 16/24 = 320 samples = 640 bytes; ratecv may vary by ~1-2 samples at edges
    assert 600 <= len(out) <= 680, f"unexpected output length: {len(out)}"


def test_resample_state_preserved_across_chunks():
    """Sequential chunks with same key must equal one continuous call.

    Without ratecv state preservation, splitting at chunk boundaries
    introduces clicks/glitches. This test guarantees we preserve state.
    """
    full = _make_pcm(2400)  # 100ms @ 24k

    out_full = resample.resample_24k_to_16k(full, key="full")
    resample.reset("full")

    half = len(full) // 2
    out_a = resample.resample_24k_to_16k(full[:half], key="split")
    out_b = resample.resample_24k_to_16k(full[half:], key="split")
    resample.reset("split")

    assert out_a + out_b == out_full


def test_resample_per_key_isolation():
    """Two concurrent calls with different keys must not corrupt each other."""
    full = _make_pcm(2400)
    half = len(full) // 2

    # baseline: A processed alone in 2 chunks
    out_a1 = resample.resample_24k_to_16k(full[:half], key="iso_a")
    out_a2 = resample.resample_24k_to_16k(full[half:], key="iso_a")
    resample.reset("iso_a")

    # interleaved: A1 → B1 → A2; B's state must not touch A's state
    out_a1_int = resample.resample_24k_to_16k(full[:half], key="i_a")
    _ = resample.resample_24k_to_16k(full[:half], key="i_b")
    out_a2_int = resample.resample_24k_to_16k(full[half:], key="i_a")
    resample.reset("i_a")
    resample.reset("i_b")

    assert out_a1 + out_a2 == out_a1_int + out_a2_int


def test_resample_reset_is_idempotent_and_safe_on_unknown_key():
    """reset(key) is the cleanup hook called when a SIP call ends.

    Must be safe to call multiple times and on keys we never resampled
    (e.g., a call that connected then dropped before any TTS frame).
    """
    # Never-seen key
    resample.reset("never_seen_key")

    # Use a key, then reset twice
    resample.resample_24k_to_16k(b"\x00" * 100, key="x")
    resample.reset("x")
    resample.reset("x")  # second reset — must not raise


def test_resample_empty_input_yields_empty_output():
    """Edge: empty input should not raise."""
    try:
        out = resample.resample_24k_to_16k(b"", key="empty")
    finally:
        resample.reset("empty")
    assert out == b""
