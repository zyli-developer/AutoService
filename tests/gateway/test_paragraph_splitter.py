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
