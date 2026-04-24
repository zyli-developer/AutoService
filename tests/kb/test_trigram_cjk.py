"""Regression: Chinese customer queries must return hits after KB unification."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoservice import dream_agent
from autoservice.kb_core import KBStore


@pytest.fixture
def seeded_kb(tmp_path: Path) -> Path:
    """Create a cinnox-like KB with one Chinese-content chunk at a sandbox path."""
    root = tmp_path / "sandbox"
    db = root / "cinnox" / "kb" / "kb.db"
    with KBStore(db) as store:
        store.save_chunk(
            {
                "id": "demo_0000",
                "source_id": "demo",
                "source_type": "md",
                "source_name": "cinnox Demo",
                "source_url": None,
                "file_path": None,
                "section": "Service Overview",
                "content": (
                    "CINNOX 提供什么服务：云联络中心、DID 号码、IVR 编排、"
                    "Omnichannel 路由、AI 语音机器人等企业级服务。"
                ),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "domain": "contact_center",
                "region": "global",
                "language": "zh",
                "page_number": None,
            }
        )
    return root


def test_chinese_query_returns_hits(seeded_kb):
    rows = dream_agent.kb_search(
        "cinnox", "你好，你们提供什么服务", top_k=3, sandbox_root=seeded_kb,
    )
    assert len(rows) >= 1
    assert "提供" in rows[0]["content"]


def test_chinese_4char_query_returns_hits(seeded_kb):
    """Trigram needs ≥3 char windows — a 4-char CJK query must match."""
    rows = dream_agent.kb_search(
        "cinnox", "提供什么", top_k=3, sandbox_root=seeded_kb,
    )
    assert len(rows) >= 1


def test_english_query_still_works(seeded_kb):
    rows = dream_agent.kb_search(
        "cinnox", "CINNOX services", top_k=3, sandbox_root=seeded_kb,
    )
    assert len(rows) >= 1


def test_mixed_query_returns_hits(seeded_kb):
    rows = dream_agent.kb_search(
        "cinnox", "CINNOX 提供 Omnichannel", top_k=3, sandbox_root=seeded_kb,
    )
    assert len(rows) >= 1


def test_punctuation_only_query_returns_empty(seeded_kb):
    rows = dream_agent.kb_search(
        "cinnox", "...", top_k=3, sandbox_root=seeded_kb,
    )
    assert rows == []


def test_very_short_query_returns_empty(seeded_kb):
    """Trigram requires ≥3 chars; a single-char query should short-circuit to []."""
    rows = dream_agent.kb_search(
        "cinnox", "a", top_k=3, sandbox_root=seeded_kb,
    )
    assert rows == []
