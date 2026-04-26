"""Unit tests for ParagraphSplitter — pure-function streaming state machine."""
from __future__ import annotations

import pytest

from autoservice.gateway.paragraph_splitter import ParagraphSplitter


def test_empty_input_yields_no_segments():
    s = ParagraphSplitter()
    assert s.feed("") == []
    assert s.flush() is None
    assert s.segment_count == 0
