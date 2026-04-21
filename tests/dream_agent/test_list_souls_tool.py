"""T3B.3 — unit tests for ``dream_agent.list_souls``.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §2.2

Behavioural requirements under test:

  * ``exclude_self=True`` (default) filters out the dream soul because the
    Dream agent never self-modifies (spec §2.2 + CON-04).
  * ``exclude_self=False`` returns all 5 souls for diagnostic / admin-portal
    side-by-side views.
  * Missing ``souls/`` directory → ``[]`` (graceful — e.g. freshly
    bootstrapped tenant before soul_generator ran).
  * Excerpts are trimmed to :data:`_SOUL_EXCERPT_CHARS` (500 chars).
  * Role is correctly derived from ``<role>_soul.md`` filename.
  * Plugins-dir fallback works (parity with :func:`kb_search`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autoservice import dream_agent
from autoservice.soul_generator import AGENT_ROLES


# ── helpers ────────────────────────────────────────────────────────────────


def _write_souls(souls_dir: Path, roles: list[str], content_prefix: str = "") -> None:
    """Create ``<role>_soul.md`` files in *souls_dir* for each role."""
    souls_dir.mkdir(parents=True, exist_ok=True)
    for role in roles:
        path = souls_dir / f"{role}_soul.md"
        path.write_text(
            f"{content_prefix}# {role.title()} Agent · Soul\n\n"
            f"Role-specific content for {role}.\n"
            f"{'x' * 600}",  # padding so excerpt trimming is observable
            encoding="utf-8",
        )


@pytest.fixture()
def sandbox_root(tmp_path) -> Path:
    root = tmp_path / "sandbox"
    root.mkdir()
    return root


# ── enumeration cases ─────────────────────────────────────────────────────


def test_list_souls_excludes_self_by_default(sandbox_root):
    """All 5 souls on disk; exclude_self=True → 4 non-dream souls."""
    tenant_dir = sandbox_root / "acme"
    _write_souls(tenant_dir / "souls", list(AGENT_ROLES))

    result = dream_agent.list_souls("acme", sandbox_root=sandbox_root)

    assert len(result) == 4
    roles = {entry["role"] for entry in result}
    assert roles == {"customer", "translate", "lead", "triage"}
    assert "dream" not in roles, (
        "Dream soul must be excluded by default — Dream agent never "
        "self-modifies (spec §2.2 anti-pattern)."
    )


def test_list_souls_includes_all_when_flag_false(sandbox_root):
    tenant_dir = sandbox_root / "acme"
    _write_souls(tenant_dir / "souls", list(AGENT_ROLES))

    result = dream_agent.list_souls(
        "acme", exclude_self=False, sandbox_root=sandbox_root,
    )
    assert len(result) == 5
    roles = {entry["role"] for entry in result}
    assert roles == set(AGENT_ROLES)


# ── graceful fallback for missing state ────────────────────────────────────


def test_list_souls_empty_when_tenant_missing(sandbox_root):
    """Tenant root doesn't exist → ``[]`` (no exception)."""
    assert dream_agent.list_souls(
        "ghost_tenant", sandbox_root=sandbox_root,
    ) == []


def test_list_souls_empty_when_souls_dir_missing(sandbox_root):
    """Tenant root exists but has no ``souls/`` yet → ``[]``.

    Matches bootstrap state between ``/upload`` and the soul_generator run.
    """
    (sandbox_root / "partial_tenant").mkdir()
    assert dream_agent.list_souls(
        "partial_tenant", sandbox_root=sandbox_root,
    ) == []


def test_list_souls_empty_when_souls_dir_has_no_md(sandbox_root):
    """Empty ``souls/`` dir → ``[]``."""
    (sandbox_root / "tenant_b" / "souls").mkdir(parents=True)
    assert dream_agent.list_souls(
        "tenant_b", sandbox_root=sandbox_root,
    ) == []


# ── excerpt shape & content ────────────────────────────────────────────────


def test_list_souls_excerpt_trimmed_to_500_chars(sandbox_root):
    tenant_dir = sandbox_root / "acme"
    _write_souls(tenant_dir / "souls", ["customer"])

    result = dream_agent.list_souls(
        "acme", exclude_self=False, sandbox_root=sandbox_root,
    )
    assert len(result) == 1
    entry = result[0]
    assert entry["role"] == "customer"
    assert len(entry["excerpt"]) <= 500
    # Excerpt must start with the file's actual content, not truncated
    # arbitrarily from the middle.
    assert entry["excerpt"].startswith("# Customer Agent"), (
        f"Excerpt should preserve the file head; got {entry['excerpt'][:50]!r}"
    )


def test_list_souls_excerpt_exact_length_when_file_shorter(sandbox_root):
    """A soul file shorter than 500 chars → excerpt == full file content."""
    tenant_dir = sandbox_root / "acme"
    souls = tenant_dir / "souls"
    souls.mkdir(parents=True)
    short_text = "# Tiny Soul\n\nJust one paragraph."
    (souls / "customer_soul.md").write_text(short_text, encoding="utf-8")

    result = dream_agent.list_souls(
        "acme", exclude_self=False, sandbox_root=sandbox_root,
    )
    assert len(result) == 1
    assert result[0]["excerpt"] == short_text


def test_list_souls_path_is_absolute_and_points_to_file(sandbox_root):
    tenant_dir = sandbox_root / "acme"
    _write_souls(tenant_dir / "souls", ["customer"])

    result = dream_agent.list_souls(
        "acme", exclude_self=False, sandbox_root=sandbox_root,
    )
    entry = result[0]
    p = Path(entry["path"])
    assert p.is_file()
    assert p.name == "customer_soul.md"


# ── plugins fallback ───────────────────────────────────────────────────────


def test_list_souls_falls_back_to_plugins_dir(monkeypatch, tmp_path):
    """Fork-side ``_local_admin`` lives under ``plugins/<tid>/souls/``."""
    fake_project_root = tmp_path / "proj"
    fake_project_root.mkdir()
    monkeypatch.setattr(dream_agent, "PROJECT_ROOT", fake_project_root)

    plugins_souls = fake_project_root / "plugins" / "_local_admin" / "souls"
    _write_souls(plugins_souls, ["customer", "translate", "lead", "triage", "dream"])

    # Empty sandbox dir so the plugins fallback is the only path that can
    # succeed.
    empty_sandbox = tmp_path / "sbx"
    empty_sandbox.mkdir()

    result = dream_agent.list_souls(
        "_local_admin", sandbox_root=empty_sandbox,
    )
    assert len(result) == 4  # 5 on disk, minus dream (excluded by default)
    assert {e["role"] for e in result} == {"customer", "translate", "lead", "triage"}
