"""Tests for MorningPush — T4A.5.

8 tests covering instantiation, aggregation, push callback, and
should_push_now logic.
"""

from __future__ import annotations

import asyncio
import pytest


# ---------------------------------------------------------------------------
# Stub ProposalPipeline
# ---------------------------------------------------------------------------

class StubProposalPipeline:
    """Minimal stand-in for ProposalPipeline with canned proposals."""

    def __init__(self, proposals: list[dict] | None = None) -> None:
        self._proposals = proposals or []

    def list_proposals(self, status: str | None = None) -> list[dict]:
        if status is not None:
            return [p for p in self._proposals if p.get("status") == status]
        return list(self._proposals)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_proposal(
    *,
    category: str = "response_quality",
    priority: str = "medium",
    title: str = "Test proposal",
    idx: int = 0,
) -> dict:
    return {
        "id": f"prop_{idx:04d}",
        "created_at": f"2026-04-16T0{idx}:00:00+00:00",
        "category": category,
        "title": title,
        "priority": priority,
        "status": "draft",
        "description": "desc",
        "suggestion": "suggestion",
        "evidence": [],
        "source_conversations": [],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMorningPush:
    """MorningPush unit tests."""

    def test_import_and_instantiate(self):
        """T1: Can import and create a MorningPush instance."""
        from autoservice.morning_push import MorningPush

        stub = StubProposalPipeline()
        mp = MorningPush(stub)
        assert mp is not None

    @pytest.mark.asyncio
    async def test_aggregate_with_proposals(self):
        """T2: aggregate returns correct summary structure."""
        from autoservice.morning_push import MorningPush

        proposals = [_make_proposal(idx=i) for i in range(3)]
        stub = StubProposalPipeline(proposals)
        mp = MorningPush(stub)

        summary = await mp.aggregate()

        assert "date" in summary
        assert "total_proposals" in summary
        assert "by_category" in summary
        assert "by_priority" in summary
        assert "top_proposals" in summary
        assert "generated_at" in summary
        assert summary["total_proposals"] == 3

    @pytest.mark.asyncio
    async def test_aggregate_no_proposals(self):
        """T3: aggregate with no proposals returns zeros."""
        from autoservice.morning_push import MorningPush

        stub = StubProposalPipeline([])
        mp = MorningPush(stub)

        summary = await mp.aggregate()

        assert summary["total_proposals"] == 0
        assert summary["by_category"] == {}
        assert summary["by_priority"] == {}
        assert summary["top_proposals"] == []

    @pytest.mark.asyncio
    async def test_by_category_counts(self):
        """T4: by_category counts correctly."""
        from autoservice.morning_push import MorningPush

        proposals = [
            _make_proposal(category="response_quality", idx=0),
            _make_proposal(category="response_quality", idx=1),
            _make_proposal(category="tone", idx=2),
            _make_proposal(category="workflow", idx=3),
        ]
        stub = StubProposalPipeline(proposals)
        mp = MorningPush(stub)

        summary = await mp.aggregate()

        assert summary["by_category"]["response_quality"] == 2
        assert summary["by_category"]["tone"] == 1
        assert summary["by_category"]["workflow"] == 1

    @pytest.mark.asyncio
    async def test_by_priority_counts(self):
        """T5: by_priority counts correctly."""
        from autoservice.morning_push import MorningPush

        proposals = [
            _make_proposal(priority="high", idx=0),
            _make_proposal(priority="medium", idx=1),
            _make_proposal(priority="medium", idx=2),
            _make_proposal(priority="low", idx=3),
        ]
        stub = StubProposalPipeline(proposals)
        mp = MorningPush(stub)

        summary = await mp.aggregate()

        assert summary["by_priority"]["high"] == 1
        assert summary["by_priority"]["medium"] == 2
        assert summary["by_priority"]["low"] == 1

    @pytest.mark.asyncio
    async def test_top_proposals_limited_and_sorted(self):
        """T6: top_proposals limited to 5, sorted by priority."""
        from autoservice.morning_push import MorningPush

        proposals = [
            _make_proposal(priority="low", idx=0),
            _make_proposal(priority="medium", idx=1),
            _make_proposal(priority="high", idx=2),
            _make_proposal(priority="low", idx=3),
            _make_proposal(priority="medium", idx=4),
            _make_proposal(priority="high", idx=5),
            _make_proposal(priority="low", idx=6),
        ]
        stub = StubProposalPipeline(proposals)
        mp = MorningPush(stub)

        summary = await mp.aggregate()

        top = summary["top_proposals"]
        assert len(top) == 5
        # First two should be high priority
        assert top[0]["priority"] == "high"
        assert top[1]["priority"] == "high"
        # Next two should be medium
        assert top[2]["priority"] == "medium"
        assert top[3]["priority"] == "medium"

    @pytest.mark.asyncio
    async def test_push_invokes_callback(self):
        """T7: push invokes callback with summary."""
        from autoservice.morning_push import MorningPush

        received = []

        async def callback(summary: dict) -> None:
            received.append(summary)

        proposals = [_make_proposal(idx=0)]
        stub = StubProposalPipeline(proposals)
        mp = MorningPush(stub, push_callback=callback)

        result = await mp.push()

        assert len(received) == 1
        assert received[0] is result
        assert result["total_proposals"] == 1

    def test_should_push_now(self):
        """T8: should_push_now returns True before push_hour, False after."""
        from autoservice.morning_push import MorningPush

        stub = StubProposalPipeline()
        mp = MorningPush(stub, push_hour=9)

        assert mp.should_push_now(current_hour=7) is True
        assert mp.should_push_now(current_hour=8) is True
        assert mp.should_push_now(current_hour=9) is False
        assert mp.should_push_now(current_hour=10) is False
        assert mp.should_push_now(current_hour=0) is True
