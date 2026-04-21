"""Heuristic + langdetect language detection.

Spec: docs/superpowers/specs/2026-04-21-multi-role-triage-dispatch-design.md §2.2

Heuristic first for hot-path messages (0-cost, deterministic); langdetect
is imported lazily as the mixed-script fallback. Returns ISO code or
'unknown'.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("triage.lang")

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff]")
_KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
_LATIN_RE = re.compile(r"[a-zA-Z]")
_EN_STOPWORDS_RE = re.compile(r"\b(the|is|you|have|what|how|a|an|are|to|of|in)\b", re.I)


def detect_language(message: str) -> str:
    """Return an ISO code: zh / en / ja / ... or 'unknown'."""
    if message is None:
        return "unknown"
    stripped = message.strip()
    if not stripped:
        return "unknown"
    # Spec §2.2 short-text guard: <3 chars → unknown. Relaxed for CJK because
    # 2-char CJK (e.g. "你好") carries enough signal; but a *single* CJK/kana
    # char is too weak — require len >= 2 for the CJK exemption.
    # SPEC DEVIATION: original spec says <3 chars → unknown unconditionally;
    # we allow 2-char CJK through but reject single-char CJK/kana inputs.
    if len(stripped) < 2:
        return "unknown"
    if len(stripped) < 3 and not _CJK_RE.search(stripped):
        return "unknown"

    cjk_count = len(_CJK_RE.findall(stripped))
    latin_count = len(_LATIN_RE.findall(stripped))
    total = cjk_count + latin_count

    if total == 0:
        return _langdetect_fallback(stripped)

    cjk_ratio = cjk_count / total
    latin_ratio = latin_count / total

    if cjk_ratio > 0.8:
        if _KANA_RE.search(stripped):
            return "ja"
        return "zh"

    if latin_ratio > 0.8:
        if _EN_STOPWORDS_RE.search(stripped):
            return "en"
        return _langdetect_fallback(stripped)

    return _langdetect_fallback(stripped)


def _langdetect_fallback(message: str) -> str:
    try:
        from langdetect import detect, DetectorFactory
        DetectorFactory.seed = 0
        return detect(message)
    except ImportError:
        log.debug("langdetect not installed — returning 'unknown'")
        return "unknown"
    except Exception as exc:
        log.debug("langdetect failed for %r: %s", message[:30], exc)
        return "unknown"
