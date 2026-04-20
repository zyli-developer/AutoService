"""T3B.2 — unit tests for ``dream_agent.kb_search``.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §2.2

The Dream agent's ``kb_search`` tool wraps the per-tenant sandbox KB
FTS5 index. Behavioural requirements under test:

  * Missing / empty KB → ``[]``, not an exception.
  * Empty-string / punctuation-only query → ``[]`` without touching SQLite.
  * Populated KB → FTS5 hits returned with ``content / source_name /
    section / domain`` keys.
  * ``top_k`` bounds the result count.
  * Sandbox-path resolution prefers ``.autoservice/sandbox/<tid>/kb/kb.db``
    but falls back to ``plugins/<tid>/kb/kb.db`` for fork-side tenants
    (``_local_admin`` lives under ``plugins/``).
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoservice import dream_agent
from autoservice.onboarding import _init_sandbox_kb


# ── helpers ────────────────────────────────────────────────────────────────


def _seed_kb(
    db_path: Path,
    chunks: list[tuple[str, str, str, str]],
) -> None:
    """Write *(content, source_name, section, domain)* tuples into a fresh KB."""
    conn = _init_sandbox_kb(db_path)
    now = datetime.now(timezone.utc).isoformat()
    try:
        for content, source_name, section, domain in chunks:
            conn.execute(
                "INSERT INTO kb_chunks (id, content, source_name, section, domain, "
                "                       created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, content, source_name, section, domain, now),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def sandbox_root(tmp_path) -> Path:
    """Isolated sandbox root — keeps real ``.autoservice/`` untouched."""
    root = tmp_path / "sandbox"
    root.mkdir()
    return root


# ── missing / empty / degenerate input ─────────────────────────────────────


def test_kb_search_returns_empty_for_nonexistent_kb(sandbox_root):
    """No kb.db file at all → ``[]``, silently."""
    result = dream_agent.kb_search(
        "tenant_nonexistent", "product refund policy",
        sandbox_root=sandbox_root,
    )
    assert result == []


def test_kb_search_returns_empty_for_empty_kb(sandbox_root):
    """kb.db exists but has zero rows → ``[]``.

    This matches the bootstrap state for ``_master`` / ``_local_admin``
    before the admin has uploaded any KB content.
    """
    kb_path = sandbox_root / "tenant_a" / "kb" / "kb.db"
    _init_sandbox_kb(kb_path).close()

    result = dream_agent.kb_search(
        "tenant_a", "anything", sandbox_root=sandbox_root,
    )
    assert result == []


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
def test_kb_search_empty_query_short_circuits(sandbox_root, query):
    """Empty / whitespace-only queries must not raise and must return ``[]``.

    Avoids the sqlite error "fts5: syntax error near ''" that a naive
    passthrough would hit.
    """
    kb_path = sandbox_root / "tenant_a" / "kb" / "kb.db"
    _seed_kb(
        kb_path,
        [("Refund policy: 30 days no questions.", "policy.pdf", "§1", "policy")],
    )

    result = dream_agent.kb_search(
        "tenant_a", query, sandbox_root=sandbox_root,
    )
    assert result == []


# ── populated KB ───────────────────────────────────────────────────────────


def test_kb_search_returns_matching_rows(sandbox_root):
    kb_path = sandbox_root / "acme" / "kb" / "kb.db"
    _seed_kb(
        kb_path,
        [
            ("Refund policy: 30 days money back guarantee.",
             "policy.pdf", "Refunds", "legal"),
            ("Shipping: orders ship within 2 business days.",
             "faq.html", "Shipping", "ops"),
            ("Contact support via chat or email.",
             "faq.html", "Support", "ops"),
        ],
    )

    result = dream_agent.kb_search(
        "acme", "refund policy", sandbox_root=sandbox_root,
    )

    assert len(result) >= 1
    first = result[0]
    assert set(first.keys()) >= {"content", "source_name", "section", "domain"}
    assert "refund" in first["content"].lower()
    assert first["source_name"] == "policy.pdf"
    assert first["section"] == "Refunds"
    assert first["domain"] == "legal"


def test_kb_search_respects_top_k(sandbox_root):
    kb_path = sandbox_root / "acme" / "kb" / "kb.db"
    chunks = [
        (f"Refund case {i}: details about customer refund handling.",
         f"doc_{i}.txt", "§1", "policy")
        for i in range(10)
    ]
    _seed_kb(kb_path, chunks)

    result = dream_agent.kb_search(
        "acme", "refund", top_k=3, sandbox_root=sandbox_root,
    )
    assert len(result) <= 3


# ── path-resolution tolerance (sandbox vs plugins) ─────────────────────────


def test_kb_search_falls_back_to_plugins_dir(monkeypatch, tmp_path):
    """Fork-side tenants like ``_local_admin`` live under ``plugins/<tid>/``.

    If the sandbox candidate is missing, kb_search must try the plugins
    path. We point PROJECT_ROOT at a temp tree so we don't scribble into
    the real ``plugins/`` directory.
    """
    fake_project_root = tmp_path / "proj"
    fake_project_root.mkdir()
    monkeypatch.setattr(dream_agent, "PROJECT_ROOT", fake_project_root)

    plugins_kb = fake_project_root / "plugins" / "_local_admin" / "kb" / "kb.db"
    _seed_kb(
        plugins_kb,
        [("Admin helper note: approve proposals via /api/dream/approve.",
          "helper.md", "API", "admin")],
    )

    # sandbox_root deliberately points at an empty directory so only the
    # plugins fallback can succeed.
    empty_sandbox = tmp_path / "empty_sandbox"
    empty_sandbox.mkdir()

    result = dream_agent.kb_search(
        "_local_admin", "approve proposals",
        sandbox_root=empty_sandbox,
    )
    assert len(result) >= 1
    assert "approve" in result[0]["content"].lower()


def test_kb_search_prefers_sandbox_over_plugins(monkeypatch, tmp_path):
    """If BOTH sandbox and plugins have the tenant, sandbox wins.

    This matches the M2 design intent that the sandbox is the live
    workspace while plugins/ only holds published forks.
    """
    fake_project_root = tmp_path / "proj"
    fake_project_root.mkdir()
    monkeypatch.setattr(dream_agent, "PROJECT_ROOT", fake_project_root)

    sandbox = tmp_path / "sbx"
    sandbox.mkdir()

    # Sandbox KB has one marker, plugins KB has a different one.
    _seed_kb(
        sandbox / "dup" / "kb" / "kb.db",
        [("SANDBOX_MARKER refund", "sandbox.md", "", "")],
    )
    _seed_kb(
        fake_project_root / "plugins" / "dup" / "kb" / "kb.db",
        [("PLUGINS_MARKER refund", "plugins.md", "", "")],
    )

    result = dream_agent.kb_search(
        "dup", "refund", sandbox_root=sandbox,
    )
    assert len(result) == 1
    assert "SANDBOX_MARKER" in result[0]["content"]
    assert "PLUGINS_MARKER" not in result[0]["content"]
