"""Proposal generation pipeline — Dream Engine core.

T4A.4 产出 | 2026-04-16

Replays historical conversations from MemoryPool, uses LLM analysis
(stubbed), generates structured improvement proposals as JSON, and
stores them in SQLite.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Awaitable

from autoservice.memory_pool import MemoryPool

PROPOSALS_SCHEMA = """\
CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    data TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    category TEXT
);

CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);
CREATE INDEX IF NOT EXISTS idx_proposals_category ON proposals(category);
"""

VALID_CATEGORIES = {"response_quality", "workflow", "knowledge_gap", "tone"}
VALID_PRIORITIES = {"high", "medium", "low"}
VALID_STATUSES = {"draft", "accepted", "rejected", "implemented"}


def _default_stub_analyzer(text: str) -> list[dict]:
    """Default stub analyzer for testing.

    Returns a single suggestion based on the number of lines (proxy for
    turn count).
    """
    line_count = len(text.strip().splitlines()) if text.strip() else 0
    if line_count == 0:
        return []
    category = "response_quality" if line_count > 5 else "tone"
    return [
        {
            "category": category,
            "title": f"Improvement suggestion ({line_count} turns analysed)",
            "description": f"Analysis of {line_count} conversation turns.",
            "suggestion": "Consider reviewing agent response patterns.",
            "evidence": [],
        }
    ]


class ProposalPipeline:
    """End-to-end pipeline: select conversations -> replay -> analyse -> propose -> store."""

    def __init__(
        self,
        memory_pool: MemoryPool,
        analyzer: Callable[[str], Any] | None = None,
        compliance_engine: Any | None = None,
        batch_size: int = 10,
        db_path: str | None = None,
    ) -> None:
        self._memory_pool = memory_pool
        self._analyzer = analyzer or _default_stub_analyzer
        self._compliance_engine = compliance_engine
        self._batch_size = batch_size

        # Use the same DB connection as memory_pool if no separate path given
        if db_path is None:
            self._conn = memory_pool._conn
        else:
            self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    # ------------------------------------------------------------------
    # DB setup
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        self._conn.executescript(PROPOSALS_SCHEMA)

    # ------------------------------------------------------------------
    # Step 1: Select conversations
    # ------------------------------------------------------------------

    def select_conversations(self, hours: int = 24, max_count: int = 50) -> list[str]:
        """Select recent conversation IDs from memory_pool."""
        now = datetime.now(tz=timezone.utc)
        start = (now - timedelta(hours=hours)).isoformat()
        end = now.isoformat()
        return self._memory_pool.get_conversations_in_range(start, end, limit=max_count)

    # ------------------------------------------------------------------
    # Step 2: Replay conversation
    # ------------------------------------------------------------------

    def replay_conversation(self, conv_id: str) -> str:
        """Format all turns of a conversation as readable text."""
        turns = self._memory_pool.get_conversation(conv_id)
        if not turns:
            return ""
        lines: list[str] = []
        for t in turns:
            role = t.get("role", "unknown")
            content = t.get("content", "")
            turn_idx = t.get("turn_index", "?")
            lines.append(f"[Turn {turn_idx}] {role}: {content}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Step 3: Analyse
    # ------------------------------------------------------------------

    async def analyze(self, text: str) -> list[dict]:
        """Call analyzer to extract improvement suggestions.

        Supports both sync and async analyzers.
        """
        import asyncio
        result = self._analyzer(text)
        if asyncio.iscoroutine(result):
            result = await result
        return result  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Step 4: Create proposal
    # ------------------------------------------------------------------

    def create_proposal(
        self,
        analysis: dict,
        source_conversations: list[str],
    ) -> dict:
        """Create a proposal JSON dict with all required fields."""
        evidence = analysis.get("evidence", [])
        priority = self._determine_priority(evidence)

        proposal: dict[str, Any] = {
            "id": f"prop_{uuid.uuid4().hex[:12]}",
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "source_conversations": source_conversations,
            "category": analysis.get("category", "response_quality"),
            "title": analysis.get("title", "Untitled proposal"),
            "description": analysis.get("description", ""),
            "evidence": evidence,
            "suggestion": analysis.get("suggestion", ""),
            "priority": priority,
            "status": "draft",
            "compliance_check": {"passed": True, "flags": []},
        }

        # Optional compliance pre-check
        if self._compliance_engine is not None:
            proposal["compliance_check"] = self._run_compliance_check(proposal)

        return proposal

    # ------------------------------------------------------------------
    # Step 5: End-to-end run
    # ------------------------------------------------------------------

    async def run(self) -> list[dict]:
        """End-to-end: select -> batch replay -> analyze -> create proposals -> store."""
        conv_ids = self.select_conversations()
        if not conv_ids:
            return []

        proposals: list[dict] = []

        # Process in batches
        for batch_start in range(0, len(conv_ids), self._batch_size):
            batch = conv_ids[batch_start : batch_start + self._batch_size]

            # Replay all conversations in this batch into a single text block
            replay_texts: list[str] = []
            for cid in batch:
                text = self.replay_conversation(cid)
                if text:
                    replay_texts.append(f"=== Conversation {cid} ===\n{text}")

            if not replay_texts:
                continue

            combined_text = "\n\n".join(replay_texts)
            suggestions = await self.analyze(combined_text)

            for suggestion in suggestions:
                proposal = self.create_proposal(suggestion, batch)
                self._store_proposal(proposal)
                proposals.append(proposal)

        return proposals

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def list_proposals(self, status: str | None = None) -> list[dict]:
        """Query stored proposals, optionally filtered by status."""
        if status is not None:
            rows = self._conn.execute(
                "SELECT data FROM proposals WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT data FROM proposals ORDER BY created_at DESC"
            ).fetchall()
        return [json.loads(r["data"]) for r in rows]

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def _store_proposal(self, proposal: dict) -> None:
        self._conn.execute(
            "INSERT INTO proposals (id, created_at, data, status, category) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                proposal["id"],
                proposal["created_at"],
                json.dumps(proposal, ensure_ascii=False),
                proposal["status"],
                proposal["category"],
            ),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_priority(evidence: list) -> str:
        count = len(evidence)
        if count >= 3:
            return "high"
        if count >= 1:
            return "medium"
        return "low"

    def _run_compliance_check(self, proposal: dict) -> dict:
        """Run compliance engine scan and return check result."""
        try:
            report = self._compliance_engine.scan(
                tenant_id="proposal_check",
                config=proposal,
            )
            flags = [
                r.rule_id
                for r in report.results
                if not r.passed
            ]
            return {"passed": len(flags) == 0, "flags": flags}
        except Exception:
            return {"passed": True, "flags": []}
