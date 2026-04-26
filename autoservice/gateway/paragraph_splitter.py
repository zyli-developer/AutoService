"""Streaming paragraph splitter for agent reply multi-bubble support.

Spec: docs/superpowers/specs/2026-04-26-instant-ack-multi-bubble-queue-design.md §6
"""
from __future__ import annotations


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
