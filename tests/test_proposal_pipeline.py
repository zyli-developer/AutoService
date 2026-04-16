"""Tests for ProposalPipeline (T4A.4).

15 test cases covering instantiation, selection, replay, analysis,
proposal creation, end-to-end run, storage, querying, edge cases,
compliance integration, batching, categories, and priority logic.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from autoservice.memory_pool import MemoryPool
from autoservice.proposal_pipeline import ProposalPipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_memory_pool(tmp_path: Path) -> MemoryPool:
    """Create an in-memory-like MemoryPool using a temp file."""
    return MemoryPool(db_path=tmp_path / "mem.db")


def _seed_conversations(mp: MemoryPool, count: int = 5, turns: int = 3) -> list[str]:
    """Seed *count* conversations with *turns* each. Returns conv_ids."""
    conv_ids: list[str] = []
    for i in range(count):
        cid = f"conv_{i:03d}"
        conv_ids.append(cid)
        for t in range(turns):
            role = "user" if t % 2 == 0 else "assistant"
            mp.record_turn(cid, role, f"Message {t} of conv {i}")
    return conv_ids


def _stub_analyzer(text: str) -> list[dict]:
    """Simple sync stub: returns one suggestion."""
    return [
        {
            "category": "response_quality",
            "title": "Stub suggestion",
            "description": "Stub description",
            "suggestion": "Stub fix",
            "evidence": [],
        }
    ]


def _stub_analyzer_with_evidence(text: str) -> list[dict]:
    """Stub that returns evidence items."""
    return [
        {
            "category": "workflow",
            "title": "Workflow issue",
            "description": "Detected workflow issue",
            "suggestion": "Fix workflow",
            "evidence": [
                {"conversation_id": "c1", "turn": 1, "quote": "q1"},
                {"conversation_id": "c2", "turn": 2, "quote": "q2"},
                {"conversation_id": "c3", "turn": 3, "quote": "q3"},
            ],
        }
    ]


def _stub_analyzer_empty(text: str) -> list[dict]:
    return []


def _stub_analyzer_categories(text: str) -> list[dict]:
    return [
        {"category": "tone", "title": "Tone issue", "description": "d", "suggestion": "s", "evidence": []},
        {"category": "knowledge_gap", "title": "KB gap", "description": "d", "suggestion": "s", "evidence": [{"conversation_id": "x", "turn": 1, "quote": "q"}]},
    ]


async def _async_stub_analyzer(text: str) -> list[dict]:
    return _stub_analyzer(text)


# ---------------------------------------------------------------------------
# Fake compliance engine
# ---------------------------------------------------------------------------

class _FakeRuleResult:
    def __init__(self, rule_id: str, passed: bool):
        self.rule_id = rule_id
        self.passed = passed


class _FakeReport:
    def __init__(self, results: list[_FakeRuleResult]):
        self.results = results


class _FakeCompliancePass:
    def scan(self, tenant_id, config):
        return _FakeReport([_FakeRuleResult("R1", True)])


class _FakeComplianceFail:
    def scan(self, tenant_id, config):
        return _FakeReport([
            _FakeRuleResult("R1", True),
            _FakeRuleResult("R2", False),
            _FakeRuleResult("R3", False),
        ])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProposalPipeline:
    """15 required test cases."""

    # 1. Import and instantiate
    def test_instantiate(self, tmp_path):
        mp = _make_memory_pool(tmp_path)
        pp = ProposalPipeline(mp)
        assert pp is not None
        assert pp._batch_size == 10

    # 2. select_conversations returns recent conv_ids (max_count respected)
    def test_select_conversations_max_count(self, tmp_path):
        mp = _make_memory_pool(tmp_path)
        _seed_conversations(mp, count=10)
        pp = ProposalPipeline(mp)
        result = pp.select_conversations(hours=24, max_count=5)
        assert len(result) <= 5
        assert all(isinstance(cid, str) for cid in result)

    # 3. replay_conversation formats turns as text
    def test_replay_conversation(self, tmp_path):
        mp = _make_memory_pool(tmp_path)
        _seed_conversations(mp, count=1, turns=4)
        pp = ProposalPipeline(mp)
        text = pp.replay_conversation("conv_000")
        assert "[Turn 0]" in text
        assert "[Turn 3]" in text
        assert "user:" in text
        assert "assistant:" in text

    # 4. analyze with stub returns suggestions
    def test_analyze_stub(self, tmp_path):
        mp = _make_memory_pool(tmp_path)
        pp = ProposalPipeline(mp, analyzer=_stub_analyzer)
        result = asyncio.get_event_loop().run_until_complete(
            pp.analyze("some conversation text")
        )
        assert len(result) == 1
        assert result[0]["category"] == "response_quality"

    # 5. create_proposal produces valid JSON structure
    def test_create_proposal_structure(self, tmp_path):
        mp = _make_memory_pool(tmp_path)
        pp = ProposalPipeline(mp)
        analysis = {
            "category": "tone",
            "title": "Test title",
            "description": "Test desc",
            "suggestion": "Test suggestion",
            "evidence": [],
        }
        proposal = pp.create_proposal(analysis, ["conv_001", "conv_002"])
        assert proposal["id"].startswith("prop_")
        assert proposal["status"] == "draft"
        assert proposal["category"] == "tone"
        assert proposal["source_conversations"] == ["conv_001", "conv_002"]
        assert "created_at" in proposal
        assert proposal["compliance_check"]["passed"] is True
        # Verify it's JSON-serializable
        json.dumps(proposal)

    # 6. End-to-end run produces proposals
    def test_run_end_to_end(self, tmp_path):
        mp = _make_memory_pool(tmp_path)
        _seed_conversations(mp, count=3)
        pp = ProposalPipeline(mp, analyzer=_stub_analyzer, batch_size=10)
        proposals = asyncio.get_event_loop().run_until_complete(pp.run())
        assert len(proposals) >= 1
        assert all(p["status"] == "draft" for p in proposals)

    # 7. Proposals stored in SQLite
    def test_proposals_stored_in_sqlite(self, tmp_path):
        mp = _make_memory_pool(tmp_path)
        _seed_conversations(mp, count=2)
        pp = ProposalPipeline(mp, analyzer=_stub_analyzer)
        asyncio.get_event_loop().run_until_complete(pp.run())
        # Query directly from DB
        rows = pp._conn.execute("SELECT COUNT(*) AS cnt FROM proposals").fetchone()
        assert rows["cnt"] >= 1

    # 8. list_proposals queries by status
    def test_list_proposals_by_status(self, tmp_path):
        mp = _make_memory_pool(tmp_path)
        _seed_conversations(mp, count=2)
        pp = ProposalPipeline(mp, analyzer=_stub_analyzer)
        asyncio.get_event_loop().run_until_complete(pp.run())
        drafts = pp.list_proposals(status="draft")
        assert len(drafts) >= 1
        assert all(p["status"] == "draft" for p in drafts)
        # No accepted proposals
        accepted = pp.list_proposals(status="accepted")
        assert len(accepted) == 0

    # 9. Empty memory_pool → run returns []
    def test_empty_memory_pool(self, tmp_path):
        mp = _make_memory_pool(tmp_path)
        pp = ProposalPipeline(mp, analyzer=_stub_analyzer)
        proposals = asyncio.get_event_loop().run_until_complete(pp.run())
        assert proposals == []

    # 10. Analyzer returns no suggestions → empty proposals
    def test_analyzer_no_suggestions(self, tmp_path):
        mp = _make_memory_pool(tmp_path)
        _seed_conversations(mp, count=2)
        pp = ProposalPipeline(mp, analyzer=_stub_analyzer_empty)
        proposals = asyncio.get_event_loop().run_until_complete(pp.run())
        assert proposals == []

    # 11. Compliance check passed
    def test_compliance_check_passed(self, tmp_path):
        mp = _make_memory_pool(tmp_path)
        pp = ProposalPipeline(mp, compliance_engine=_FakeCompliancePass())
        analysis = {
            "category": "response_quality",
            "title": "T",
            "description": "D",
            "suggestion": "S",
            "evidence": [],
        }
        proposal = pp.create_proposal(analysis, ["c1"])
        assert proposal["compliance_check"]["passed"] is True
        assert proposal["compliance_check"]["flags"] == []

    # 12. Compliance check failed (flags populated)
    def test_compliance_check_failed(self, tmp_path):
        mp = _make_memory_pool(tmp_path)
        pp = ProposalPipeline(mp, compliance_engine=_FakeComplianceFail())
        analysis = {
            "category": "response_quality",
            "title": "T",
            "description": "D",
            "suggestion": "S",
            "evidence": [],
        }
        proposal = pp.create_proposal(analysis, ["c1"])
        assert proposal["compliance_check"]["passed"] is False
        assert "R2" in proposal["compliance_check"]["flags"]
        assert "R3" in proposal["compliance_check"]["flags"]

    # 13. Batch processing (30 convs, batch_size=10)
    def test_batch_processing(self, tmp_path):
        mp = _make_memory_pool(tmp_path)
        _seed_conversations(mp, count=30, turns=2)
        pp = ProposalPipeline(mp, analyzer=_stub_analyzer, batch_size=10)
        proposals = asyncio.get_event_loop().run_until_complete(pp.run())
        # 30 convs / batch_size=10 = 3 batches, 1 suggestion per batch = 3
        assert len(proposals) == 3
        # Each proposal should reference 10 conversations
        for p in proposals:
            assert len(p["source_conversations"]) == 10

    # 14. Category correctly populated from analyzer
    def test_category_from_analyzer(self, tmp_path):
        mp = _make_memory_pool(tmp_path)
        _seed_conversations(mp, count=2)
        pp = ProposalPipeline(mp, analyzer=_stub_analyzer_categories, batch_size=50)
        proposals = asyncio.get_event_loop().run_until_complete(pp.run())
        categories = {p["category"] for p in proposals}
        assert "tone" in categories
        assert "knowledge_gap" in categories

    # 15. Priority auto-determined by evidence count
    def test_priority_by_evidence_count(self, tmp_path):
        mp = _make_memory_pool(tmp_path)
        pp = ProposalPipeline(mp)

        # No evidence → low
        p_low = pp.create_proposal(
            {"category": "tone", "title": "T", "description": "D", "suggestion": "S", "evidence": []},
            ["c1"],
        )
        assert p_low["priority"] == "low"

        # 1 evidence → medium
        p_med = pp.create_proposal(
            {"category": "tone", "title": "T", "description": "D", "suggestion": "S",
             "evidence": [{"conversation_id": "c1", "turn": 1, "quote": "q"}]},
            ["c1"],
        )
        assert p_med["priority"] == "medium"

        # 2 evidence → medium
        p_med2 = pp.create_proposal(
            {"category": "tone", "title": "T", "description": "D", "suggestion": "S",
             "evidence": [
                 {"conversation_id": "c1", "turn": 1, "quote": "q"},
                 {"conversation_id": "c2", "turn": 2, "quote": "q"},
             ]},
            ["c1"],
        )
        assert p_med2["priority"] == "medium"

        # 3 evidence → high
        p_high = pp.create_proposal(
            {"category": "tone", "title": "T", "description": "D", "suggestion": "S",
             "evidence": [
                 {"conversation_id": "c1", "turn": 1, "quote": "q"},
                 {"conversation_id": "c2", "turn": 2, "quote": "q"},
                 {"conversation_id": "c3", "turn": 3, "quote": "q"},
             ]},
            ["c1"],
        )
        assert p_high["priority"] == "high"
