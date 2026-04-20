"""Dream Agent tools — emit_proposal / kb_search / list_souls (spec §2.2).

T3B.1 / T3B.2 / T3B.3 | 2026-04-20
Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §2.2, §2.3

These are the three tools the Dream LLM agent loop can call during ``run_dream``
(implemented in T3B.4). They are standalone sync helpers here so they can be
unit-tested without spinning up an LLM; T3B.4 will wrap them in tool schemas
for Claude's tool-use API.

All tools are tenant-scoped — every call takes an explicit ``tenant_id``.

Red-line CON-04 (spec §2.3): ``emit_proposal`` always writes ``status='draft'``.
A proposal row NEVER auto-applies; the platform admin must explicitly accept
before any production mutation. The status parameter is intentionally absent
from the public signature so no caller — LLM or human — can bypass this.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autoservice.soul_generator import AGENT_ROLES


# ── Constants ──────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: Valid risk levels a Dream agent may assign to a proposal.
VALID_RISK_LEVELS: frozenset[str] = frozenset({"low", "medium", "high"})

#: Excerpt length used by :func:`list_souls` (first N chars of each soul).
_SOUL_EXCERPT_CHARS = 500


# ── Path resolution ────────────────────────────────────────────────────────


def _resolve_tenant_root(
    tenant_id: str, sandbox_root: Path | None = None
) -> Path | None:
    """Return the on-disk root for *tenant_id*, or ``None`` if neither exists.

    Master-side tenants (including ``_master`` and sandbox-wizard tenants)
    live under ``.autoservice/sandbox/<tid>/``. Fork-side tenants — notably
    ``_local_admin`` on a B-fork deployment — live under ``plugins/<tid>/``.
    Rather than making the caller know which deployment mode applies, we try
    the sandbox path first and fall back to ``plugins/`` on miss. This keeps
    the Dream tools portable between master and fork deployments without
    threading ``deployment_mode`` through every call.

    If ``sandbox_root`` is supplied it overrides the default sandbox base —
    used by tests so they don't write into the real ``.autoservice/`` tree.
    Plugin-side lookup is always relative to ``PROJECT_ROOT / "plugins"``
    because the plugin directory is a fixed repo layout, not runtime state.
    """
    sbx_base = sandbox_root or (PROJECT_ROOT / ".autoservice" / "sandbox")
    candidate = sbx_base / tenant_id
    if candidate.exists():
        return candidate

    plugin_candidate = PROJECT_ROOT / "plugins" / tenant_id
    if plugin_candidate.exists():
        return plugin_candidate

    return None


# ── FTS helpers ────────────────────────────────────────────────────────────


def _tokenize_fts_query(query: str) -> str:
    """Convert a natural-language query to a broad FTS5 OR query.

    Duplicated from :func:`autoservice.soul_generator._tokenize_fts_query` on
    purpose: per the T3B.4 design, the Dream tools are a self-contained
    surface that T3B.4 will wrap for Claude tool-use. Pulling the helper in
    via an internal import would couple the tool layer to soul generation's
    private API — which the spec explicitly wants to keep decoupled so the
    tools can be extracted into their own package later (spec §2.5 notes
    "dream tools may run in a separate process from soul_generator").
    """
    clean = re.sub(r'["\(\)\*\:\^]', " ", query)
    tokens = [t for t in clean.split() if len(t) >= 2]
    if not tokens:
        return query
    return " OR ".join(tokens)


def _sandbox_kb_path(tenant_id: str, sandbox_root: Path | None = None) -> Path | None:
    """Return the ``kb.db`` path for *tenant_id*, trying sandbox then plugins.

    Returns ``None`` when neither candidate file exists. Callers that need
    the tenant root directory (not the KB file) should use
    :func:`_resolve_tenant_root` instead.
    """
    sbx_base = sandbox_root or (PROJECT_ROOT / ".autoservice" / "sandbox")
    candidate = sbx_base / tenant_id / "kb" / "kb.db"
    if candidate.exists():
        return candidate

    plugin_candidate = PROJECT_ROOT / "plugins" / tenant_id / "kb" / "kb.db"
    if plugin_candidate.exists():
        return plugin_candidate

    return None


# ── T3B.1 · emit_proposal ──────────────────────────────────────────────────


def emit_proposal(
    conn: sqlite3.Connection,
    *,
    tenant_id: str,
    category: str,
    title: str,
    description: str,
    suggestion: str,
    evidence: str,
    risk_level: str,
    target_role: str,
) -> str:
    """Write a draft proposal row into the proposals table.

    This is the **only** path the Dream LLM has to persist a proposal. The
    returned ``proposal_id`` can be read back via
    :meth:`ProposalPipeline.get_proposal` or a direct SELECT on the row.

    Red-line CON-04 (spec §2.3): the ``status`` column is hard-coded to
    ``'draft'``. There is no ``status`` kwarg on this function — that's
    deliberate. Even if the Dream LLM asks to emit an accepted / implemented
    proposal, the status cannot be raised here. The only path to a non-draft
    state is the admin-portal reviewer flow.

    Args:
        conn:        SQLite connection with the ``proposals`` schema applied
                     (via :func:`proposal_pipeline.apply_schema`).
        tenant_id:   The tenant this proposal belongs to. Persisted on the
                     SQLite row (``tenant_id`` column) and inside the JSON
                     blob so both the index and the payload agree.
        category:    Free-form category string (e.g.
                     ``"response_quality"``, ``"knowledge_gap"``, etc.).
        title:       Short summary (≤120 chars recommended).
        description: 1-3 sentence explanation of the finding.
        suggestion:  Actionable recommendation for the admin.
        evidence:    Supporting evidence — typically a conversation
                     excerpt, KB chunk, or metric snippet. A single string
                     (not a list) to keep the Claude tool schema shallow;
                     multi-item evidence can be newline-joined upstream.
        risk_level:  One of ``"low"`` / ``"medium"`` / ``"high"``.
        target_role: The agent whose soul / config this proposal targets.
                     Must be in :data:`AGENT_ROLES`.

    Returns:
        The freshly-minted proposal id (``prop_<hex12>``).

    Raises:
        ValueError: If ``risk_level`` is not in :data:`VALID_RISK_LEVELS` or
            ``target_role`` is not in :data:`AGENT_ROLES`. Raised *before*
            any write, so invalid calls never leave a partial row behind.
    """
    if risk_level not in VALID_RISK_LEVELS:
        raise ValueError(
            f"Invalid risk_level {risk_level!r}; "
            f"must be one of {sorted(VALID_RISK_LEVELS)}"
        )
    if target_role not in AGENT_ROLES:
        raise ValueError(
            f"Invalid target_role {target_role!r}; "
            f"must be one of {sorted(AGENT_ROLES)}"
        )

    proposal_id = f"prop_{uuid.uuid4().hex[:12]}"
    created_at = datetime.now(tz=timezone.utc).isoformat()

    # Compose the JSON payload. The Dream proposal schema intentionally
    # mirrors the M1 proposal_pipeline shape (see create_proposal) so the
    # admin-portal renderer doesn't need to branch on origin.
    payload: dict[str, Any] = {
        "id": proposal_id,
        "created_at": created_at,
        "tenant_id": tenant_id,
        "category": category,
        "title": title,
        "description": description,
        "suggestion": suggestion,
        "evidence": evidence,
        "risk_level": risk_level,
        "target_role": target_role,
        "status": "draft",  # red-line CON-04 — never overridable
        "origin": "dream_agent",
    }

    conn.execute(
        "INSERT INTO proposals (id, created_at, data, status, category, tenant_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            proposal_id,
            created_at,
            json.dumps(payload, ensure_ascii=False),
            "draft",          # red-line CON-04 — status column hard-coded
            category,
            tenant_id,
        ),
    )
    conn.commit()
    return proposal_id


# ── T3B.2 · kb_search ──────────────────────────────────────────────────────


def kb_search(
    tenant_id: str,
    query: str,
    top_k: int = 5,
    sandbox_root: Path | None = None,
) -> list[dict]:
    """Search *tenant_id*'s KB for *query* using FTS5, returning the top K rows.

    Each result is a dict with keys ``content`` / ``source_name`` / ``section``
    / ``domain`` — the same shape :func:`autoservice.soul_generator._search_kb`
    returns, so downstream prompt-formatters can share code paths.

    Resolution order for the KB file:
      1. ``<sandbox_root or .autoservice/sandbox>/<tenant_id>/kb/kb.db``
      2. ``plugins/<tenant_id>/kb/kb.db``

    Args:
        tenant_id:    Tenant whose KB to search. Bootstrapped internal
                      tenants (``_master``, ``_local_admin``) start with
                      an empty KB — this function returns ``[]`` in that
                      case, not an error.
        query:        Natural-language query. Gets tokenised to an OR-style
                      FTS5 expression via :func:`_tokenize_fts_query`; if
                      that yields no usable tokens (e.g. ``""`` or only
                      punctuation) we short-circuit to ``[]``.
        top_k:        Max rows returned. Default 5, matching the Dream
                      agent's tool-use default.
        sandbox_root: Override the sandbox base path (tests only).

    Returns:
        A list of dicts. Empty list when the KB file is missing, the KB is
        empty, the query has no usable tokens, or the FTS statement raises.
        Gracefully degrading to empty is preferable to raising because the
        Dream agent's tool-use loop treats an empty result as "KB doesn't
        cover this scenario" — a legitimate signal, not a bug.
    """
    # Empty / whitespace-only query → no point touching SQLite.
    if not query or not query.strip():
        return []

    kb_path = _sandbox_kb_path(tenant_id, sandbox_root=sandbox_root)
    if kb_path is None:
        return []

    fts_query = _tokenize_fts_query(query)
    if not fts_query.strip():
        return []

    conn = sqlite3.connect(str(kb_path))
    conn.row_factory = sqlite3.Row
    try:
        # Primary path: content-synced FTS where ``kb_fts.rowid`` aligns
        # with ``kb_chunks.rowid`` (spec §2.4 / onboarding._init_sandbox_kb
        # declares ``content=kb_chunks, content_rowid=rowid``). Note the
        # JOIN is on ROWIDs, NOT on ``kb_chunks.id`` (which is a TEXT uuid).
        try:
            rows = conn.execute(
                """
                SELECT c.content, c.source_name, c.section, c.domain
                FROM kb_fts f
                JOIN kb_chunks c ON c.rowid = f.rowid
                WHERE kb_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, int(top_k)),
            ).fetchall()
            if rows:
                return [dict(r) for r in rows]
        except sqlite3.Error:
            pass  # Fall through to standalone-FTS path (test fixtures).

        # Standalone FTS fallback (mirrors soul_generator._search_kb).
        try:
            rows = conn.execute(
                """
                SELECT f.content,
                       '' AS source_name, '' AS section, '' AS domain
                FROM kb_fts f
                WHERE kb_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, int(top_k)),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error:
            return []
    finally:
        conn.close()


# ── T3B.3 · list_souls ─────────────────────────────────────────────────────


def list_souls(
    tenant_id: str,
    exclude_self: bool = True,
    sandbox_root: Path | None = None,
) -> list[dict]:
    """Enumerate *tenant_id*'s soul.md files and return an excerpt of each.

    Per spec §2.2 the Dream agent tool ``list_souls()`` returns "the 4 agent
    soul 摘要（不含自己）" — i.e. customer / translate / lead / triage, but
    NOT dream itself, because the dream agent never self-modifies (CON-04 +
    dream_soul.md "Anti-Patterns: No self-modification").

    Args:
        tenant_id:    Tenant whose souls dir to scan. Resolves the same way
                      :func:`kb_search` does — sandbox first, plugins next.
        exclude_self: When ``True`` (default) filters out ``dream_soul.md``.
                      Pass ``False`` in diagnostics / admin-portal views
                      where we want to show all 5 souls side-by-side.
        sandbox_root: Override the sandbox base path (tests only).

    Returns:
        List of ``{role, path, excerpt}`` dicts. ``role`` is derived from
        the filename (``<role>_soul.md`` → ``role``). ``excerpt`` is the
        first :data:`_SOUL_EXCERPT_CHARS` characters of the file. Returns
        ``[]`` when the tenant root or the ``souls/`` dir is missing —
        gracefully, so the Dream agent sees "no peers to inspect" rather
        than an exception.
    """
    tenant_root = _resolve_tenant_root(tenant_id, sandbox_root=sandbox_root)
    if tenant_root is None:
        return []

    souls_dir = tenant_root / "souls"
    if not souls_dir.is_dir():
        return []

    results: list[dict] = []
    # Sort for deterministic output — tests rely on this and the admin-portal
    # renderer likes a stable ordering.
    for soul_path in sorted(souls_dir.glob("*.md")):
        name = soul_path.name
        # Derive role from filename: "<role>_soul.md" is the canonical form
        # produced by save_drafts; tolerate other *.md files by stripping
        # the extension only.
        if name.endswith("_soul.md"):
            role = name[: -len("_soul.md")]
        else:
            role = soul_path.stem

        if exclude_self and role == "dream":
            continue

        try:
            content = soul_path.read_text(encoding="utf-8")
        except OSError:
            # Unreadable file — skip rather than fail the whole listing.
            continue

        excerpt = content[:_SOUL_EXCERPT_CHARS]
        results.append(
            {
                "role": role,
                "path": str(soul_path),
                "excerpt": excerpt,
            }
        )

    return results


__all__ = [
    "VALID_RISK_LEVELS",
    "emit_proposal",
    "kb_search",
    "list_souls",
]
