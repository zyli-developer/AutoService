"""detect_language — §2.2 of the spec."""
from __future__ import annotations

import pytest

from autoservice.language_detect import detect_language


@pytest.mark.parametrize(
    "msg,expected",
    [
        ("你好", "zh"),
        ("我想买一个产品", "zh"),
        ("Hello, how are you?", "en"),
        ("What is the price?", "en"),
        ("こんにちは、お元気ですか", "ja"),
        ("hi", "unknown"),         # too short
        ("あ", "unknown"),          # single kana — weak signal
    ],
)
def test_detect_language_happy_path(msg, expected):
    assert detect_language(msg) == expected


def test_detect_language_handles_mixed_scripts_without_crash():
    # Should not raise even if langdetect mis-detects; return a string.
    result = detect_language("Hello 你好")
    assert isinstance(result, str)


def test_detect_language_empty_input():
    assert detect_language("") == "unknown"
    assert detect_language("   ") == "unknown"
