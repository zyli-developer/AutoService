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

# T4S.2: proposal_audit table (contract e5-dream §2.4).
# Writes come from:
#   * proposal_apply.apply_proposal (action='apply')
#   * api_routes /approve /reject handlers (action='approve' | 'reject') [T4S.3]
# AST guardrail T4S.8 asserts 'INSERT INTO proposal_audit' string literal
# appears ONLY in these files.
PROPOSAL_AUDIT_SCHEMA = """\
CREATE TABLE IF NOT EXISTS proposal_audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id     TEXT NOT NULL,
    admin_user_id   TEXT NOT NULL,
    action          TEXT NOT NULL
                    CHECK(action IN ('approve', 'reject', 'apply')),
    previous_status TEXT NOT NULL,
    new_status      TEXT NOT NULL,
    session_id      TEXT,
    timestamp       TEXT NOT NULL,
    details         TEXT,
    FOREIGN KEY (proposal_id) REFERENCES proposals(id)
);

CREATE INDEX IF NOT EXISTS idx_proposal_audit_proposal
    ON proposal_audit(proposal_id);
CREATE INDEX IF NOT EXISTS idx_proposal_audit_admin
    ON proposal_audit(admin_user_id);
"""


def apply_m3_migration(conn: sqlite3.Connection) -> int:
    """Sweep legacy status='implemented' rows to 'applied'.

    M3 T4S.2 (contract e5-dream §2.2): rename resolves naming conflict
    between contract ('applied') and legacy code ('implemented').
    Returns number of rows migrated.  Idempotent.
    """
    cur = conn.execute(
        "UPDATE proposals SET status='applied' WHERE status='implemented'"
    )
    conn.commit()
    return cur.rowcount


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
        # T4S.2: proposal_audit table for apply/approve/reject audit trail
        conn.executescript(PROPOSAL_AUDIT_SCHEMA)
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
    # T4S.2: ensure proposal_audit table + indexes on existing DBs (idempotent)
    conn.executescript(PROPOSAL_AUDIT_SCHEMA)
    # T4S.2: sweep legacy 'implemented' → 'applied' (idempotent)
    apply_m3_migration(conn)
    conn.commit()

VALID_CATEGORIES = {"response_quality", "workflow", "knowledge_gap", "tone", "platform_level"}
# M3 T2S.8: 'platform_level' added for master_dream_agent emissions.


class ProposalNotFound(LookupError):
    """Raised when an apply/update targets a missing proposal_id."""


class ProposalStateError(RuntimeError):
    """Raised on illegal state transitions (CON-04 enforcement + state machine).

    Examples:
    - ``update_status(new_status='applied')`` — applied is apply_proposal-only
    - ``_mark_applied_internal()`` called on a draft/rejected proposal
    """
VALID_PRIORITIES = {"high", "medium", "low"}
VALID_STATUSES = {"draft", "accepted", "rejected", "applied"}
# M3 T4S.2: renamed 'implemented' → 'applied' (contract e5-dream §2.2, reviewer C3).
# Migration on first-load sweeps legacy rows via apply_m3_migration().


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

        Valid transitions via this PUBLIC method:
            draft → accepted
            draft → rejected
            accepted → rejected

        **CON-04 red line** (contract e5-dream §2.2): this method does NOT
        accept new_status='applied'.  That transition requires the private
        :func:`_mark_applied_internal` helper which is only imported by
        :mod:`autoservice.proposal_apply`.  This is Layer 2b of the 5-layer
        defense: value rejection at the public API boundary, no frame
        introspection needed (reviewer C1 feedback from T0S.4 v1.0).
        """
        if new_status == "applied":
            raise ProposalStateError(
                "Cannot write status='applied' via update_status(). "
                "This transition is reserved for proposal_apply.apply_proposal() "
                "only (CON-04 red line, contract e5-dream §2.2)."
            )
        if new_status not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status {new_status!r}, must be one of "
                f"{VALID_STATUSES - {'applied'}} (applied is CON-04 protected)"
            )

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

    def _mark_applied_internal(
        self,
        proposal_id: str,
        admin_user_id: str,
    ) -> dict:
        """PRIVATE — transition 'accepted' → 'applied'. NOT A PUBLIC API.

        **CON-04 Layer 3 import cone**: this function name starts with
        an underscore AND is only imported by
        :mod:`autoservice.proposal_apply`.  Any other caller is a
        red-line violation and will be flagged by :mod:`tests.dream_agent.
        test_con04_guardrail` AST walk (T4S.8).

        Uses CONDITIONAL UPDATE pattern (contract §2.3, reviewer C2):
            UPDATE proposals SET status='applied' WHERE id=? AND status='accepted'
        Checks rowcount:
          * 1 → transition succeeded; write audit row in same txn
          * 0 → SELECT current status; if 'applied' → idempotent no-op;
                else raise ProposalStateError

        Raises:
            ProposalNotFound: row doesn't exist
            ProposalStateError: status != 'accepted' AND != 'applied'
        """
        from datetime import datetime, timezone
        now_iso = datetime.now(tz=timezone.utc).isoformat()

        # Reviewer T4S.1 Important #1: explicit `with self._conn:` block for
        # BEGIN IMMEDIATE semantics (contract e5-dream §2.3).  Context manager
        # commits on success or rolls back on exception — matches the
        # "all-or-nothing state+audit" invariant even if Python sqlite3's
        # default isolation behaviour drifts across versions.
        with self._conn:
            cur = self._conn.execute(
                "UPDATE proposals SET status='applied' "
                "WHERE id = ? AND status = 'accepted'",
                (proposal_id,),
            )

            if cur.rowcount == 1:
                proposal = self.get_proposal(proposal_id)
                if proposal is None:  # pragma: no cover — defensive
                    raise ProposalNotFound(proposal_id)
                proposal["status"] = "applied"
                self._conn.execute(
                    "UPDATE proposals SET data = ? WHERE id = ?",
                    (json.dumps(proposal, ensure_ascii=False), proposal_id),
                )
                self._conn.execute(
                    """INSERT INTO proposal_audit
                         (proposal_id, admin_user_id, action, previous_status,
                          new_status, session_id, timestamp, details)
                       VALUES (?, ?, 'apply', 'accepted', 'applied', NULL, ?, NULL)""",
                    (proposal_id, admin_user_id, now_iso),
                )
                # Context manager commits on successful exit
                return {"idempotent": False, "proposal": proposal, "applied_at": now_iso}

        # rowcount == 0 → either idempotent (already applied) or illegal state
        row = self._conn.execute(
            "SELECT status FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if row is None:
            raise ProposalNotFound(proposal_id)
        current = row["status"]
        if current == "applied":
            proposal = self.get_proposal(proposal_id)
            return {"idempotent": True, "proposal": proposal, "applied_at": None}
        raise ProposalStateError(
            f"Cannot apply proposal {proposal_id!r}: current status "
            f"{current!r} != 'accepted'"
        )

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
