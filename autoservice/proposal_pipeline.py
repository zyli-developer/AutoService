"""Proposal generation pipeline — Dream Engine core.

T4A.4 产出 | 2026-04-16
T6E.10 — LLM-based analyzer replaces stub | 2026-04-17

Replays historical conversations from MemoryPool, uses LLM analysis
to extract talk-track suggestions and knowledge gaps, generates
structured improvement proposals as JSON, and stores them in SQLite.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Awaitable

try:
    import anthropic
except ImportError:  # pragma: no cover – allow import without SDK installed
    anthropic = None  # type: ignore[assignment]

from autoservice.memory_pool import MemoryPool

logger = logging.getLogger(__name__)

PROPOSALS_SCHEMA = """\
CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    data TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    category TEXT,
    tenant_id TEXT NOT NULL DEFAULT '_master'
);

CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);
CREATE INDEX IF NOT EXISTS idx_proposals_category ON proposals(category);
CREATE INDEX IF NOT EXISTS idx_proposals_tenant ON proposals(tenant_id);
"""


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create or migrate the ``proposals`` schema.

    Idempotent: safe to call on a brand-new DB, an M1 legacy DB (no ``tenant_id``
    column), or an already-migrated DB.

    T2B.1 (tenant sandbox M2, spec §2.4):
      - Fresh DB  -> ``PROPOSALS_SCHEMA`` is applied verbatim (includes
        ``tenant_id`` column + index).
      - Legacy DB -> ``ALTER TABLE … ADD COLUMN tenant_id TEXT NOT NULL
        DEFAULT '_master'`` backfills existing rows and the tenant index is
        created.
      - Already migrated -> no-op (all statements are ``CREATE … IF NOT EXISTS``
        or guarded by a ``PRAGMA table_info`` check).
    """
    existing_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='proposals'"
    ).fetchone()

    if existing_table is None:
        # Fresh DB — the full schema (including tenant_id) is created in one go.
        conn.executescript(PROPOSALS_SCHEMA)
        conn.commit()
        return

    # Table already present — inspect columns and add tenant_id if it's absent.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(proposals)").fetchall()}
    if "tenant_id" not in cols:
        conn.execute(
            "ALTER TABLE proposals ADD COLUMN tenant_id TEXT NOT NULL "
            "DEFAULT '_master'"
        )

    # Ensure all indexes exist (these are CREATE … IF NOT EXISTS, so idempotent).
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_proposals_category ON proposals(category)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_proposals_tenant ON proposals(tenant_id)"
    )
    conn.commit()

VALID_CATEGORIES = {"response_quality", "workflow", "knowledge_gap", "tone"}
VALID_PRIORITIES = {"high", "medium", "low"}
VALID_STATUSES = {"draft", "accepted", "rejected", "implemented"}


# ── LLM analyzer constants ────────────────────────────────────────────────

_ANALYZER_MODEL = "claude-sonnet-4-20250514"
_ANALYZER_MAX_TOKENS = 4096

_ANALYZER_SYSTEM_PROMPT = """\
You are a customer-service QA analyst. You receive transcripts of \
conversations between an AI agent and customers.

Analyse the conversation and return a JSON **array** of improvement \
proposals. Each element must have exactly these fields:

- "category": one of "response_quality", "workflow", "knowledge_gap", "tone"
- "title": short summary (≤80 chars)
- "description": 1-3 sentence explanation of the issue
- "suggestion": actionable recommendation for the agent team
- "evidence": list of strings — verbatim quotes from the transcript that \
  support the finding (may be empty if the finding is structural)

Focus on:
1. **Talk-track suggestions** — places where the agent's phrasing, flow, or \
   strategy could be improved.
2. **Knowledge blind spots** — questions the agent could not answer or \
   answered incorrectly / vaguely.

Return ONLY the JSON array, no markdown fences, no commentary.\
"""


def _llm_analyzer(text: str) -> list[dict]:
    """LLM-based analyzer: sends replay text to Claude, returns structured proposals.

    Falls back to a minimal stub result with a warning when the LLM is
    unavailable (SDK missing, auth error, network issue, etc.).
    """
    if not text.strip():
        return []

    line_count = len(text.strip().splitlines())

    # ── Fallback result used when LLM call cannot be made ──
    def _fallback(reason: str) -> list[dict]:
        logger.warning("LLM analyzer unavailable (%s) — returning stub result", reason)
        category = "response_quality" if line_count > 5 else "tone"
        return [
            {
                "category": category,
                "title": f"Improvement suggestion ({line_count} turns analysed)",
                "description": (
                    f"Analysis of {line_count} conversation turns. "
                    f"(LLM unavailable: {reason})"
                ),
                "suggestion": "Consider reviewing agent response patterns.",
                "evidence": [],
            }
        ]

    if anthropic is None:
        return _fallback("anthropic SDK not installed")

    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model=_ANALYZER_MODEL,
            max_tokens=_ANALYZER_MAX_TOKENS,
            temperature=0,
            system=_ANALYZER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
        raw = message.content[0].text.strip()

        # Parse the JSON array returned by the model
        proposals = json.loads(raw)
        if not isinstance(proposals, list):
            proposals = [proposals]

        # Validate / normalise each proposal
        validated: list[dict] = []
        for p in proposals:
            cat = p.get("category", "response_quality")
            if cat not in VALID_CATEGORIES:
                cat = "response_quality"
            validated.append({
                "category": cat,
                "title": str(p.get("title", "Untitled"))[:120],
                "description": str(p.get("description", "")),
                "suggestion": str(p.get("suggestion", "")),
                "evidence": list(p.get("evidence", [])),
            })

        return validated if validated else _fallback("LLM returned empty result")

    except json.JSONDecodeError as exc:
        return _fallback(f"JSON parse error: {exc}")
    except Exception as exc:  # noqa: BLE001 – intentional broad catch for resilience
        return _fallback(str(exc))


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
        self._analyzer = analyzer or _llm_analyzer
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
        # Route through ``apply_schema`` so the tenant_id migration (T2B.1)
        # runs automatically for any connection — fresh or legacy.
        apply_schema(self._conn)

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
        tenant_id: str = "_master",
    ) -> dict:
        """Create a proposal JSON dict with all required fields.

        ``tenant_id`` defaults to ``"_master"`` for backwards compatibility with
        M1 callers; the tenant sandbox migration (T2B.1) records it on the
        proposal and on the SQLite row.
        """
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
            "tenant_id": tenant_id,
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

    def get_proposal(self, proposal_id: str) -> dict | None:
        """Get a single proposal by ID. Returns None if not found."""
        row = self._conn.execute(
            "SELECT data FROM proposals WHERE id = ?", (proposal_id,),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["data"])

    def update_status(self, proposal_id: str, new_status: str) -> dict | None:
        """Update a proposal's status. Returns the updated proposal or None if not found.

        Valid transitions: draft → accepted | rejected, accepted → implemented.
        """
        if new_status not in VALID_STATUSES:
            raise ValueError(f"Invalid status {new_status!r}, must be one of {VALID_STATUSES}")

        proposal = self.get_proposal(proposal_id)
        if proposal is None:
            return None

        proposal["status"] = new_status
        self._conn.execute(
            "UPDATE proposals SET status = ?, data = ? WHERE id = ?",
            (new_status, json.dumps(proposal, ensure_ascii=False), proposal_id),
        )
        self._conn.commit()
        return proposal

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
        # ``tenant_id`` falls back to ``"_master"`` to stay compatible with
        # proposals that predate the T2B.1 sandbox migration.
        tenant_id = proposal.get("tenant_id", "_master")
        self._conn.execute(
            "INSERT INTO proposals (id, created_at, data, status, category, tenant_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                proposal["id"],
                proposal["created_at"],
                json.dumps(proposal, ensure_ascii=False),
                proposal["status"],
                proposal["category"],
                tenant_id,
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
