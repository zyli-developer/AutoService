"""Dream Agent — tools + ``run_dream`` agent loop (spec §2.2).

T3B.1 / T3B.2 / T3B.3 : tools (emit_proposal, kb_search, list_souls).
T3B.4               : ``run_dream`` async agent loop (this file).

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §2.2 / §2.3 / §2.4.

The three tools are plain sync helpers so they can be unit-tested without
spinning up an LLM. :func:`run_dream` wraps them in Claude tool-use schemas
and runs the full observe → tool → emit lifecycle end-to-end.

All tools are tenant-scoped — every call takes an explicit ``tenant_id``.

Red-line CON-04 (spec §2.3): ``emit_proposal`` always writes ``status='draft'``.
A proposal row NEVER auto-applies; the platform admin must explicitly accept
before any production mutation. The status parameter is intentionally absent
from the public signature so no caller — LLM or human — can bypass this.
``run_dream`` honours that at the loop level by calling ``emit_proposal``
directly (no override path exists).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from autoservice import dream_runs
from autoservice.soul_generator import AGENT_ROLES, _FALLBACK_DREAM_SOUL

logger = logging.getLogger(__name__)


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


_FTS_SPLIT_RE = re.compile(
    # FTS5 metacharacters + ASCII and CJK punctuation + whitespace, all treated
    # as token separators. Splitting on these produces the base fragments we
    # then quote as phrases and optionally fan out into trigram windows.
    r'["\(\)\*:\^，。；！？、：“”‘’「」『』\s,.;!?]+'
)


def _tokenize_fts_query(query: str) -> str:
    """Format *query* for FTS5 MATCH against a trigram-tokenised index.

    The KB uses the ``trigram`` FTS5 tokenizer (see KBStore._migrate_fts_tokenizer),
    which indexes every 3-character substring of content. The old unicode61
    strategy — whitespace-split and OR-join plain tokens — works for short
    ASCII words but falls over on long CJK runs because a natural-language
    query rarely appears verbatim in content (e.g. a user asks "你好，你们
    提供什么服务" but the KB only contains "提供什么服务").

    This is a hybrid tokenizer that works against **both** tokenizer backends
    the codebase currently uses (trigram on KBStore-migrated KBs; unicode61 on
    legacy ``_init_sandbox_kb`` fixtures):

      1. Split the query on FTS5 metacharacters, ASCII punctuation, CJK
         punctuation, and whitespace — producing a list of fragments.
      2. Drop fragments shorter than 2 chars.
      3. For every fragment, emit it as a quoted phrase (this is what lets
         unicode61 find ``refund`` from query ``refund`` and lets trigram
         match any substring ≤ ~4 chars).
      4. For fragments longer than 4 chars, ALSO emit overlapping 3-char
         windows so trigram can catch partial-substring matches when the full
         fragment doesn't appear verbatim in content.
      5. OR-join all emitted terms.

    Returns an empty string when no usable fragment survives; callers
    short-circuit to ``[]`` in that case.
    """
    raw_fragments = _FTS_SPLIT_RE.split(query)
    fragments = [f for f in raw_fragments if len(f) >= 2]
    if not fragments:
        return ""

    terms: list[str] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        if term and term not in seen:
            seen.add(term)
            terms.append(term)

    for frag in fragments:
        # Keep the whole fragment as a phrase first — this is what makes
        # unicode61 match short ASCII words (e.g. phrase "refund" matches
        # token "refund" under unicode61, which phrase-level matches ignore
        # case after remove_diacritics).
        _add(frag)
        # Fan out long fragments into trigram windows so partial-substring
        # matching works on the trigram-tokenised KB even when the whole
        # fragment doesn't appear as a contiguous substring of any chunk.
        if len(frag) > 4:
            for i in range(len(frag) - 2):
                _add(frag[i : i + 3])

    # Quote every term so FTS5 MATCH treats it as a literal phrase, avoiding
    # any further tokenization of CJK content or metachar-adjacent strings.
    return " OR ".join(f'"{term}"' for term in terms)


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


# ═══════════════════════════════════════════════════════════════════════════
# T3B.4 · run_dream agent loop (spec §2.2 / §2.4)
# ═══════════════════════════════════════════════════════════════════════════


#: Anthropic model used by the Dream agent. Spec §2.5 calls for the long-
#: context Opus variant (`claude-opus-4-7[1m]`) because Dream runs may
#: ingest 20 memory turns + 5 historical proposals in a single call. The
#: exact constant is kept module-local so the LLM shim can override for
#: tests via monkeypatching :data:`DREAM_MODEL`.
DREAM_MODEL = "claude-opus-4-7[1m]"

#: Max tokens the Dream LLM may emit per turn. Generous — the loop cap is
#: on *tool turns*, not tokens.
DREAM_MAX_TOKENS = 4096


# ── Tool schemas (Claude tool-use shape) ───────────────────────────────────

#: Tool schemas exposed to the Dream LLM. Kept next to the implementation
#: so reviewers can see at a glance that the three tools the LLM is told
#: about are exactly the three the dispatcher in :func:`_execute_tool_call`
#: handles. Anthropic's tool-use contract: ``name``, ``description``,
#: ``input_schema`` (JSON-Schema subset).
_TOOL_SCHEMAS: list[dict] = [
    {
        "name": "kb_search",
        "description": (
            "Search the tenant's knowledge base (FTS5) for text relevant "
            "to a natural-language query. Returns at most `top_k` chunks "
            "with source / section metadata."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language query string.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maximum chunks to return (default 5).",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_souls",
        "description": (
            "Enumerate the other agent souls for this tenant "
            "(customer / translate / lead / triage) with a short excerpt "
            "from each. The Dream agent's own soul is never returned — "
            "Dream never self-modifies (red-line CON-04 anti-pattern)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "emit_proposal",
        "description": (
            "Persist a single improvement proposal for platform-admin "
            "review. ALWAYS writes status='draft' — proposals never "
            "auto-apply (red-line CON-04)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": (
                        "Free-form category label (e.g. 'response_quality', "
                        "'knowledge_gap', 'workflow', 'tone')."
                    ),
                },
                "title": {
                    "type": "string",
                    "description": "Short summary (≤120 chars).",
                },
                "description": {
                    "type": "string",
                    "description": "1–3 sentence explanation of the finding.",
                },
                "suggestion": {
                    "type": "string",
                    "description": "Actionable recommendation for the admin.",
                },
                "evidence": {
                    "type": "string",
                    "description": (
                        "Supporting evidence — conversation excerpt, KB "
                        "chunk, or metric snippet. Single string; "
                        "multi-line allowed."
                    ),
                },
                "risk_level": {
                    "type": "string",
                    "enum": sorted(VALID_RISK_LEVELS),
                    "description": "Risk tier for this change.",
                },
                "target_role": {
                    "type": "string",
                    "enum": sorted(AGENT_ROLES),
                    "description": (
                        "Which agent role this proposal targets. Dream "
                        "never targets itself (CON-04)."
                    ),
                },
            },
            "required": [
                "category",
                "title",
                "description",
                "suggestion",
                "evidence",
                "risk_level",
                "target_role",
            ],
        },
    },
]


# ── Result dataclass ──────────────────────────────────────────────────────


@dataclass
class DreamRunResult:
    """Summary of a single :func:`run_dream` invocation.

    Mirrors the ``dream_runs`` row plus a couple of derived fields
    (``duration_ms``) so callers that want to log the run do not need a
    second DB read. All fields are plain scalars / None so the dataclass
    is JSON-serialisable.
    """

    run_id: str
    status: str                 # 'completed' | 'overrun' | 'failed'
    tool_calls: int
    proposals_emitted: int
    tokens_in: int
    tokens_out: int
    duration_ms: int
    error: str | None = None


# ── Soul / context helpers ─────────────────────────────────────────────────


def _load_dream_soul(
    tenant_id: str, sandbox_root: Path | None = None
) -> str:
    """Return the dream soul markdown for *tenant_id*, falling back if absent.

    Resolution order matches :func:`_resolve_tenant_root`:
      1. ``<sandbox>/<tid>/souls/dream_soul.md``
      2. ``plugins/<tid>/souls/dream_soul.md``
      3. :data:`soul_generator._FALLBACK_DREAM_SOUL`

    Returning the fallback rather than raising is deliberate: a freshly
    bootstrapped tenant may not yet have a generated dream soul, and the
    fallback is a stable, well-formed prompt (spec §2.3 "LLM 失败时回退").
    """
    tenant_root = _resolve_tenant_root(tenant_id, sandbox_root=sandbox_root)
    if tenant_root is not None:
        soul_path = tenant_root / "souls" / "dream_soul.md"
        try:
            if soul_path.is_file():
                return soul_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(
                "Dream soul read failed (%s) — using fallback for tenant %s",
                exc, tenant_id,
            )
    return _FALLBACK_DREAM_SOUL


def _load_tenant_dream_cfg(
    tenant_id: str, sandbox_root: Path | None = None
) -> dict:
    """Return the ``dream`` block from the tenant's ``config.json``.

    Best-effort: if the config is missing or malformed we return an empty
    dict and let the caller default the fields. This keeps ``run_dream``
    resilient on freshly seeded tenants that have not yet activated.
    """
    tenant_root = _resolve_tenant_root(tenant_id, sandbox_root=sandbox_root)
    if tenant_root is None:
        return {}
    cfg_path = tenant_root / "config.json"
    try:
        if not cfg_path.is_file():
            return {}
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "Tenant config unreadable (%s) for tenant %s", exc, tenant_id,
        )
        return {}
    dream = data.get("dream")
    return dream if isinstance(dream, dict) else {}


def _recent_historical_proposals(
    proposals_db: sqlite3.Connection,
    tenant_id: str,
    limit: int = 5,
) -> list[dict]:
    """Return the most recent accepted/rejected proposals for *tenant_id*.

    Shape mirrors the JSON payload stored in ``proposals.data`` plus a
    ``status`` field promoted from the column for quick consumption.
    Defensive against legacy rows lacking a ``tenant_id`` column by
    using ``sqlite3.Error`` as the only non-propagating failure mode.
    """
    try:
        rows = proposals_db.execute(
            "SELECT data, status FROM proposals "
            "WHERE tenant_id = ? AND status IN ('accepted', 'rejected') "
            "ORDER BY created_at DESC LIMIT ?",
            (tenant_id, int(limit)),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("Historical proposals query failed: %s", exc)
        return []

    out: list[dict] = []
    for row in rows:
        try:
            # Support both tuple- and Row-style connections.
            data_raw = row["data"] if hasattr(row, "keys") else row[0]
            status = row["status"] if hasattr(row, "keys") else row[1]
            payload = json.loads(data_raw)
        except (json.JSONDecodeError, TypeError, KeyError, IndexError):
            continue
        payload["status"] = status
        out.append(payload)
    return out


def _build_initial_context(
    tenant_id: str,
    mempool,
    proposals_db: sqlite3.Connection,
    sandbox_root: Path | None = None,
) -> str:
    """Construct the opening user message for the Dream LLM.

    Spec §2.2 step 2: recent N=20 memory turns + last M=5 historical
    proposals (accepted/rejected) + dream.risk_threshold / coverage from
    tenant config.

    Formatted as plain Markdown so the LLM can read it without extra
    parsing prompt engineering. The sections are deliberately named and
    ordered so a future agent variant can tolerate missing sections by
    regex-probing.
    """
    parts: list[str] = []

    # Recent conversation turns — mempool.recent returns newest-first dicts.
    try:
        turns = mempool.recent(tenant_id, limit=20)
    except Exception as exc:  # noqa: BLE001 — tolerate pool failures
        logger.warning("mempool.recent failed: %s", exc)
        turns = []
    parts.append("## Recent conversation turns (newest first)")
    if not turns:
        parts.append("_(no recent conversation turns recorded)_")
    else:
        for t in turns:
            role = t.get("role", "unknown")
            content = t.get("content", "")
            ts = t.get("timestamp", "")
            parts.append(f"- [{ts}] {role}: {content}")

    # Historical proposals.
    parts.append("")
    parts.append("## Historical proposals (last 5 accepted / rejected)")
    history = _recent_historical_proposals(proposals_db, tenant_id, limit=5)
    if not history:
        parts.append("_(no historical proposals)_")
    else:
        for p in history:
            parts.append(
                f"- [{p.get('status')}] {p.get('category')}: "
                f"{p.get('title')} — {p.get('suggestion', '')}"
            )

    # Tenant dream config knobs.
    parts.append("")
    parts.append("## Tenant dream configuration")
    cfg = _load_tenant_dream_cfg(tenant_id, sandbox_root=sandbox_root)
    parts.append(
        f"- risk_threshold: {cfg.get('risk_threshold', 'medium')}"
    )
    parts.append(f"- coverage: {cfg.get('coverage', 'all')}")

    parts.append("")
    parts.append(
        "## Instructions\n"
        "Observe the material above. You MAY call `kb_search` and "
        "`list_souls` to gather more context. When you have findings, "
        "call `emit_proposal` once per finding. When you are done (or "
        "have nothing to propose) respond with a brief summary and stop "
        "calling tools."
    )

    return "\n".join(parts)


# ── LLM client adapter ────────────────────────────────────────────────────


async def _acquire_dream_client(cc_pool, tenant_id: str, system_prompt: str):
    """Acquire a Claude client suitable for the Dream agent loop.

    Spec §2.5 / CON-06: ``cc_pool.acquire(role="dream", tenant_id=...)``
    yields a CC client from the deployment-level dream pool (size=1,
    independent from the customer pool) with the tenant's
    ``dream_soul.md`` injected as the system prompt. This adapter is the
    single call site; T3B.5 landed the pool-side surface, so no fallback
    is needed.

    Returns the async-context-manager handed back by the pool. The caller
    must use it in an ``async with`` block — the pool's checkin / release
    fires on exit and routes the instance back to the dream pool.

    .. note::
       Tests mock the LLM end-to-end via the ``llm_send`` seam; this
       adapter is only exercised by integration paths.
    """
    return cc_pool.acquire(role="dream", tenant_id=tenant_id)


# ── Agent loop ────────────────────────────────────────────────────────────


class _ToolOutcome:
    """Lightweight carrier for a single tool invocation's result."""

    __slots__ = ("content", "is_error", "proposals_delta")

    def __init__(
        self,
        content: str,
        *,
        is_error: bool = False,
        proposals_delta: int = 0,
    ) -> None:
        self.content = content
        self.is_error = is_error
        self.proposals_delta = proposals_delta


def _execute_tool_call(
    tool_name: str,
    tool_input: dict,
    *,
    tenant_id: str,
    proposals_db: sqlite3.Connection,
    sandbox_root: Path | None = None,
) -> _ToolOutcome:
    """Dispatch a single tool_use block to the matching helper.

    Tenant-id is threaded from the loop (NOT from the LLM input) so a
    misbehaving model cannot ask to emit a proposal into another tenant's
    table. The red-line CON-04 guarantee comes from two places: this
    function always passes the loop's ``tenant_id`` and always calls the
    plain :func:`emit_proposal` helper (which hard-codes ``status='draft'``).

    Errors from the tool layer (e.g. invalid ``risk_level``) are turned
    into ``is_error=True`` tool_result blocks rather than propagating —
    the LLM can observe and retry or self-correct within the turn cap.
    """
    try:
        if tool_name == "kb_search":
            query = str(tool_input.get("query", "") or "")
            top_k = int(tool_input.get("top_k", 5) or 5)
            results = kb_search(
                tenant_id, query, top_k=top_k, sandbox_root=sandbox_root,
            )
            return _ToolOutcome(json.dumps(results, ensure_ascii=False))

        if tool_name == "list_souls":
            results = list_souls(tenant_id, sandbox_root=sandbox_root)
            return _ToolOutcome(json.dumps(results, ensure_ascii=False))

        if tool_name == "emit_proposal":
            # Red-line CON-04: tenant_id is the loop's, not the LLM's.
            # `status` is not extractable — emit_proposal has no status kwarg.
            proposal_id = emit_proposal(
                proposals_db,
                tenant_id=tenant_id,
                category=str(tool_input.get("category", "")),
                title=str(tool_input.get("title", "")),
                description=str(tool_input.get("description", "")),
                suggestion=str(tool_input.get("suggestion", "")),
                evidence=str(tool_input.get("evidence", "")),
                risk_level=str(tool_input.get("risk_level", "")),
                target_role=str(tool_input.get("target_role", "")),
            )
            return _ToolOutcome(
                json.dumps({"proposal_id": proposal_id, "status": "draft"}),
                proposals_delta=1,
            )

        return _ToolOutcome(
            json.dumps({"error": f"unknown tool {tool_name!r}"}),
            is_error=True,
        )
    except ValueError as exc:
        # Validation errors from the tool (bad risk_level / target_role).
        return _ToolOutcome(
            json.dumps({"error": str(exc)}), is_error=True,
        )
    except Exception as exc:  # noqa: BLE001 — defensive
        logger.exception("Dream tool %s raised: %s", tool_name, exc)
        return _ToolOutcome(
            json.dumps({"error": f"internal error: {exc}"}), is_error=True,
        )


def _extract_tool_uses(response: Any) -> list[dict]:
    """Pull ``tool_use`` blocks out of an Anthropic Message response.

    The Anthropic SDK returns ``response.content`` as a list of blocks
    where each block has a ``type`` field (``text`` / ``tool_use``).
    Mock responses in tests may use dicts with the same shape. We accept
    both — ``getattr`` with dict fallback.
    """
    content = getattr(response, "content", None)
    if content is None and isinstance(response, dict):
        content = response.get("content", [])
    if not content:
        return []

    out: list[dict] = []
    for block in content:
        btype = getattr(block, "type", None)
        if btype is None and isinstance(block, dict):
            btype = block.get("type")
        if btype != "tool_use":
            continue
        # Normalise to a plain dict so the rest of the loop has one shape.
        bid = getattr(block, "id", None) or (
            block.get("id") if isinstance(block, dict) else None
        )
        bname = getattr(block, "name", None) or (
            block.get("name") if isinstance(block, dict) else None
        )
        binput = getattr(block, "input", None)
        if binput is None and isinstance(block, dict):
            binput = block.get("input", {})
        out.append({"id": bid, "name": bname, "input": binput or {}})
    return out


def _response_tokens(response: Any) -> tuple[int, int]:
    """Return ``(tokens_in, tokens_out)`` for an Anthropic message response.

    Works for the SDK's ``Usage`` object and for plain dicts used in tests.
    Missing fields degrade to 0 rather than raising.
    """
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return 0, 0
    tin = getattr(usage, "input_tokens", None)
    tout = getattr(usage, "output_tokens", None)
    if tin is None and isinstance(usage, dict):
        tin = usage.get("input_tokens")
    if tout is None and isinstance(usage, dict):
        tout = usage.get("output_tokens")
    return int(tin or 0), int(tout or 0)


def _response_stop_reason(response: Any) -> str | None:
    """Extract ``stop_reason`` from a Message response (SDK or dict)."""
    sr = getattr(response, "stop_reason", None)
    if sr is None and isinstance(response, dict):
        sr = response.get("stop_reason")
    return sr


async def _call_llm(
    llm_send: Callable[..., Any],
    *,
    system: str,
    messages: list[dict],
    tools: list[dict],
) -> Any:
    """Invoke the injected LLM send callable, awaiting if it returns a coro.

    The callable may be sync (Anthropic SDK's ``messages.create`` is sync)
    or async (tests may prefer an ``async def`` mock). We handle both by
    inspecting the return value. Keeping this layer here — rather than
    forcing the caller to wrap — makes the loop uniform.
    """
    result = llm_send(system=system, messages=messages, tools=tools)
    if asyncio.iscoroutine(result):
        result = await result
    return result


async def _run_agent_loop(
    *,
    llm_send: Callable[..., Any],
    system_prompt: str,
    initial_user_msg: str,
    tenant_id: str,
    proposals_db: sqlite3.Connection,
    runs_db: sqlite3.Connection,
    run_id: str,
    max_tool_turns: int,
    sandbox_root: Path | None = None,
) -> tuple[str, int, int, int, int]:
    """Drive the tool-use loop.

    Returns ``(status, tool_calls, proposals_emitted, tokens_in, tokens_out)``.
    ``status`` is ``'completed'`` when the model terminates naturally
    (``stop_reason != 'tool_use'``) or ``'overrun'`` when we hit the
    ``max_tool_turns`` hard cap. Exceptions from the LLM or tool layer
    propagate — the caller (:func:`run_dream`) maps them to
    ``status='failed'``.

    Infinite-loop guarantee: every iteration either (a) receives no
    ``tool_use`` blocks and breaks, or (b) increments ``tool_turns`` and
    re-enters the loop. ``max_tool_turns`` is an exclusive upper bound on
    iterations; the count-and-break check sits at the top of each
    iteration, so even a model that returns only ``tool_use`` blocks
    cannot cause an unbounded loop.
    """
    messages: list[dict] = [
        {"role": "user", "content": initial_user_msg},
    ]
    tool_calls = 0
    proposals_emitted = 0
    tokens_in = 0
    tokens_out = 0
    tool_turns = 0
    status = "completed"

    while True:
        if tool_turns >= max_tool_turns:
            status = "overrun"
            logger.warning(
                "Dream run %s hit max_tool_turns=%d — terminating with "
                "status='overrun'",
                run_id, max_tool_turns,
            )
            break

        response = await _call_llm(
            llm_send,
            system=system_prompt,
            messages=messages,
            tools=_TOOL_SCHEMAS,
        )

        tin, tout = _response_tokens(response)
        tokens_in += tin
        tokens_out += tout

        tool_uses = _extract_tool_uses(response)
        stop_reason = _response_stop_reason(response)

        # Natural termination: no tool_use blocks OR an explicit end_turn
        # with nothing to do. The SDK usually pairs ``tool_use`` stops
        # with at least one ``tool_use`` block; we treat "no tool blocks"
        # as authoritative regardless of stop_reason for mock-friendliness.
        if not tool_uses:
            status = "completed"
            break

        # Append the assistant's turn verbatim so the next request sees
        # the tool_use blocks the model emitted (Anthropic requires the
        # assistant turn be echoed back when returning tool_result).
        messages.append({
            "role": "assistant",
            "content": getattr(response, "content", None)
                if not isinstance(response, dict)
                else response.get("content", []),
        })

        tool_results: list[dict] = []
        for use in tool_uses:
            tool_calls += 1
            outcome = _execute_tool_call(
                use.get("name") or "",
                use.get("input") or {},
                tenant_id=tenant_id,
                proposals_db=proposals_db,
                sandbox_root=sandbox_root,
            )
            proposals_emitted += outcome.proposals_delta
            block: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": use.get("id"),
                "content": outcome.content,
            }
            if outcome.is_error:
                block["is_error"] = True
            tool_results.append(block)

        messages.append({"role": "user", "content": tool_results})

        # Incremental persistence: update the runs row so an external
        # observer can see progress even if the process is killed mid-run.
        try:
            dream_runs.update_run(
                runs_db,
                run_id,
                tool_calls=tool_calls,
                proposals_emitted=proposals_emitted,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        except sqlite3.Error as exc:
            logger.warning("dream_runs.update_run failed: %s", exc)

        tool_turns += 1

        # Defence-in-depth: if the model signalled end_turn but also sent
        # tool_use blocks we have already executed them — break so we do
        # not keep prompting for tool_results after the model wanted out.
        if stop_reason not in (None, "tool_use"):
            status = "completed"
            break

    return status, tool_calls, proposals_emitted, tokens_in, tokens_out


# ── Public entry point ────────────────────────────────────────────────────


async def run_dream(
    tenant_id: str,
    cc_pool,
    mempool,
    proposals_db: sqlite3.Connection,
    runs_db: sqlite3.Connection,
    max_tool_turns: int = 10,
    *,
    sandbox_root: Path | None = None,
    llm_send: Callable[..., Any] | None = None,
) -> DreamRunResult:
    """Run the Dream agent once for *tenant_id*.

    Lifecycle (spec §2.2):
      1. Open a ``dream_runs`` row (status='running').
      2. Load the tenant's ``dream_soul.md`` (fallback to the inlined
         constant when missing) — this is the LLM system prompt.
      3. Acquire a Dream CC client via ``cc_pool``; gracefully degrades
         if the pool's ``acquire()`` signature predates T3B.5.
      4. Build initial context (recent memory + historical proposals +
         dream config knobs) and run the tool-use loop with a
         ``max_tool_turns`` hard cap.
      5. Terminal status:
            - ``'completed'`` — model stopped calling tools.
            - ``'overrun'``  — turn cap hit (spec §2.2 step 4b).
            - ``'failed'``   — any exception during setup or the loop;
              the error message is persisted on the row.
      6. Stamp ``ended_at`` on the runs row and return a
         :class:`DreamRunResult` summarising the run.

    Args:
        tenant_id: Tenant this run is scoped to. Threaded into every
            tool call (including ``emit_proposal``) so the LLM cannot
            cross tenants.
        cc_pool: :class:`autoservice.cc_pool.CCPool`-like object. Only
            its ``acquire()`` method is touched; we do not assume any
            other surface so tests can pass a lightweight mock.
        mempool: :class:`autoservice.memory_pool.MemoryPool`. We only
            use ``.recent(tenant_id, limit)``.
        proposals_db: sqlite3 connection with the proposals schema
            applied. Tool calls ``emit_proposal`` write here.
        runs_db: sqlite3 connection with ``dream_runs`` schema applied.
        max_tool_turns: Hard cap on the number of tool-use iterations.
            Defaults to 10 per spec §2.2 step 4. Setting to 0 means no
            tool turns at all — the LLM's first response is immediately
            treated as terminal.
        sandbox_root: Override for sandbox path resolution (tests only).
        llm_send: Injection seam for the Anthropic call. Signature is
            ``(system: str, messages: list, tools: list) -> Message``
            (or coroutine thereof). At T3B.4 time this **must** be
            supplied — the pool-side tool-use surface lands with T3B.5,
            so passing ``None`` currently raises ``RuntimeError`` after
            a best-effort acquire/release of the pool instance. Tests
            supply a mock; production code should supply an Anthropic-
            backed closure. Once T3B.5 lands, this will default to a
            closure that speaks tool-use via the acquired CC client.

    Returns:
        A :class:`DreamRunResult`. Even on failure a row is persisted
        and the result is returned — we never let an exception escape
        once the run row has been opened.
    """
    t0 = time.monotonic()
    run_id = dream_runs.start_run(runs_db, tenant_id)
    status = "failed"
    tool_calls = 0
    proposals_emitted = 0
    tokens_in = 0
    tokens_out = 0
    error_msg: str | None = None

    try:
        system_prompt = _load_dream_soul(tenant_id, sandbox_root=sandbox_root)
        initial_user_msg = _build_initial_context(
            tenant_id, mempool, proposals_db, sandbox_root=sandbox_root,
        )

        # Acquire a Dream client — honoured by tests via the llm_send
        # injection seam, so we only touch the pool in production paths.
        # Keeping the acquire inside the try block means a pool failure
        # is captured as status='failed' rather than propagating.
        if llm_send is None:
            cm = await _acquire_dream_client(
                cc_pool, tenant_id, system_prompt,
            )
            # Default client-side path: use the pool's CC client. The CC
            # client surface does not yet natively speak Anthropic
            # tool-use — calling it would bypass the tool loop. To avoid
            # silently producing wrong behaviour, we require callers to
            # supply ``llm_send`` when cc_pool-side tool-use is not
            # implemented. T3B.5 will close this gap.
            if hasattr(cm, "__aenter__"):
                # Try to release cleanly even though we will not use it.
                async with cm:
                    pass
            raise RuntimeError(
                "run_dream requires an explicit llm_send callable until "
                "cc_pool exposes a tool-use surface (T3B.5). See spec §2.5."
            )

        status, tool_calls, proposals_emitted, tokens_in, tokens_out = (
            await _run_agent_loop(
                llm_send=llm_send,
                system_prompt=system_prompt,
                initial_user_msg=initial_user_msg,
                tenant_id=tenant_id,
                proposals_db=proposals_db,
                runs_db=runs_db,
                run_id=run_id,
                max_tool_turns=max_tool_turns,
                sandbox_root=sandbox_root,
            )
        )
    except Exception as exc:  # noqa: BLE001 — map to run row + keep going
        logger.exception("Dream run %s for tenant %s failed", run_id, tenant_id)
        status = "failed"
        error_msg = f"{type(exc).__name__}: {exc}"

    # Final persistence — always write one terminal row so observers can
    # distinguish crashed runs from silently-orphaned 'running' rows.
    try:
        dream_runs.update_run(
            runs_db,
            run_id,
            tool_calls=tool_calls,
            proposals_emitted=proposals_emitted,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        dream_runs.end_run(
            runs_db,
            run_id,
            status=status,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            error=error_msg,
        )
    except Exception as exc:  # noqa: BLE001 — last-ditch logging
        logger.exception("Failed to finalise dream_runs row %s: %s", run_id, exc)

    duration_ms = int((time.monotonic() - t0) * 1000)

    return DreamRunResult(
        run_id=run_id,
        status=status,
        tool_calls=tool_calls,
        proposals_emitted=proposals_emitted,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        duration_ms=duration_ms,
        error=error_msg,
    )


__all__ = [
    "VALID_RISK_LEVELS",
    "DREAM_MODEL",
    "DreamRunResult",
    "emit_proposal",
    "kb_search",
    "list_souls",
    "run_dream",
]
