"""Audio resampling utility for SIP voice path.

Doubao TTS outputs 24kHz; jambonz audio_fork expects 16kHz mono on the
return leg. We use audioop.ratecv (stdlib pre-3.13, audioop-lts shim
post-3.13) — fast enough for 16k↔24k mono. If profiling shows > 5ms
per 20ms frame, switch to scipy.signal.resample_poly.

Per-call ratecv state is keyed by call_sid. Without preserving state
across chunks, you get audible clicks at 20ms boundaries.
"""
import audioop

_state: dict[str, tuple] = {}


def resample_24k_to_16k(pcm_24k: bytes, key: str) -> bytes:
    """24kHz mono S16LE → 16kHz mono S16LE."""
    state = _state.get(key)
    out, new_state = audioop.ratecv(pcm_24k, 2, 1, 24000, 16000, state)
    _state[key] = new_state
    return out


def reset(key: str) -> None:
    """Drop ratecv state for a finished call."""
    _state.pop(key, None)
