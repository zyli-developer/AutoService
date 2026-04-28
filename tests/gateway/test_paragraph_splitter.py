"""Unit tests for ParagraphSplitter — pure-function streaming state machine."""
from __future__ import annotations

import pytest

from autoservice.gateway.paragraph_splitter import ParagraphSplitter


def test_empty_input_yields_no_segments():
    s = ParagraphSplitter()
    assert s.feed("") == []
    assert s.flush() is None
    assert s.segment_count == 0


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
    s = ParagraphSplitter()  # default max=5, min=5
    # Use all-long paragraphs so every boundary is accepted.
    payload = (
        "Para A is here.\n\nPara B is here.\n\nPara C is here.\n\n"
        "Para D is here.\n\nPara E is here.\n\nPara F is here."
    )
    out = s.feed(payload)
    # 4 mid-stream emissions (max-1), 5th ("Para E") and 6th ("Para F")
    # collapse into the flushed tail.
    assert out == ["Para A is here.", "Para B is here.", "Para C is here.", "Para D is here."]
    assert s.flush() == "Para E is here.\n\nPara F is here."
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
