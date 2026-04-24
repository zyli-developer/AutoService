"""🔒 CON-04 AST Guardrail (M3 T4S.8) — CI-blocking defensive test.

Contract: docs/contracts/m3/e5-dream.md v1.1 §3 (Layer 4).

Enforces that status-write string literals appear ONLY in approved files:
* ``'applied'`` / ``"applied"`` as a status WRITE (INSERT/UPDATE)
* ``"INSERT INTO proposal_audit"`` — audit WRITE

Any drift (new code adding a status-write or audit-write outside approved
locations) fails CI, catching attempts to bypass the apply_proposal path.

This test walks the AST of autoservice/ source files and checks string
literal nodes in SQL-write contexts.  It is intentionally strict —
false-positives are preferred over false-negatives for a security gate.

**If this test fails after a legitimate refactor**:
1. Verify the new code path really should write applied / audit rows.
2. If yes, add the file to the allow-list below (and update this
   docstring) AND confirm with an independent code review.
3. Do NOT disable the test.
"""
from __future__ import annotations

import ast
import pathlib
from typing import Iterator


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_AUTOSERVICE = _REPO_ROOT / "autoservice"


# ──────────────────────────────────────────────────────────────────────────
# Allow-lists
# ──────────────────────────────────────────────────────────────────────────


# Files permitted to write `status='applied'` (either as string literal in
# SQL or as a Python string that flows into SQL or audit).  Everything else
# is a CON-04 violation.
ALLOWED_APPLIED_WRITE_FILES: set[str] = {
    # The ONLY files allowed to write 'applied' as a status transition:
    "autoservice/proposal_apply.py",          # T4S.1 apply_proposal
    "autoservice/proposal_pipeline.py",       # _mark_applied_internal + migration
}


# Files permitted to INSERT INTO proposal_audit.
# T4S.3 adds api_routes.py for approve/reject audit writes — keep in sync.
ALLOWED_AUDIT_INSERT_FILES: set[str] = {
    "autoservice/proposal_pipeline.py",   # _mark_applied_internal (actual SQL)
    "autoservice/proposal_apply.py",      # docstring refs "INSERT INTO proposal_audit"
    # T4S.3 will add: "autoservice/api_routes.py" for approve/reject audit
    # T4S.3 will add: "autoservice/operator_routes.py" if approve moves there
}


def _iter_py_files() -> Iterator[pathlib.Path]:
    """All .py files under autoservice/, excluding __pycache__."""
    for path in _AUTOSERVICE.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def _relative(path: pathlib.Path) -> str:
    """Repo-relative path with forward slashes for stable comparisons."""
    return path.relative_to(_REPO_ROOT).as_posix()


# ──────────────────────────────────────────────────────────────────────────
# Literal scanners
# ──────────────────────────────────────────────────────────────────────────


def _find_applied_status_writes(tree: ast.AST) -> list[int]:
    """Return line numbers where ``'applied'`` appears in SQL-write contexts.

    Heuristic: match string constants that contain BOTH:
      * ``status='applied'`` (or whitespace variant)
      * AND an SQL write verb: ``UPDATE`` / ``INSERT`` / ``SET``

    This rejects docstring prose mentions (which don't carry SQL verbs)
    while catching real SQL statements.  Keeps the canary meta-test
    honest — a fake file with pure SQL still fails.
    """
    lines: list[int] = []
    sql_write_markers = ("UPDATE", "SET", "INSERT")
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value
            compact = s.replace(" ", "")
            if "status='applied'" not in compact:
                continue
            s_upper = s.upper()
            if any(marker in s_upper for marker in sql_write_markers):
                lines.append(node.lineno)
    return lines


def _find_audit_insert_writes(tree: ast.AST) -> list[int]:
    """Return line numbers where ``INSERT INTO proposal_audit`` appears."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value.upper().replace("\n", " ")
            # Collapse whitespace for robust matching
            normalized = " ".join(s.split())
            if "INSERT INTO PROPOSAL_AUDIT" in normalized:
                lines.append(node.lineno)
    return lines


# ──────────────────────────────────────────────────────────────────────────
# The actual guard test
# ──────────────────────────────────────────────────────────────────────────


def test_applied_status_write_only_in_allowed_files():
    """🔒 CON-04 Layer 4: `status='applied'` literal in source code
    appears ONLY in ALLOWED_APPLIED_WRITE_FILES."""
    violations: list[tuple[str, int]] = []
    for path in _iter_py_files():
        rel = _relative(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue  # skip unparseable (shouldn't happen in autoservice/)
        hits = _find_applied_status_writes(tree)
        if hits and rel not in ALLOWED_APPLIED_WRITE_FILES:
            for line in hits:
                violations.append((rel, line))

    assert not violations, (
        f"🔒 CON-04 VIOLATION: 'status=applied' SQL write found outside "
        f"allow-listed files.  Each match is a potential red-line breach.\n"
        f"Violations: {violations}\n"
        f"Allow-list: {sorted(ALLOWED_APPLIED_WRITE_FILES)}\n"
        f"If the new code path legitimately writes applied status: "
        f"update ALLOWED_APPLIED_WRITE_FILES + require code review."
    )


def test_audit_insert_only_in_allowed_files():
    """🔒 CON-04 Layer 4: `INSERT INTO proposal_audit` literal appears
    ONLY in ALLOWED_AUDIT_INSERT_FILES."""
    violations: list[tuple[str, int]] = []
    for path in _iter_py_files():
        rel = _relative(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        hits = _find_audit_insert_writes(tree)
        if hits and rel not in ALLOWED_AUDIT_INSERT_FILES:
            for line in hits:
                violations.append((rel, line))

    assert not violations, (
        f"🔒 CON-04 VIOLATION: 'INSERT INTO proposal_audit' found outside "
        f"allow-listed files.  Audit writes are trust-anchor operations.\n"
        f"Violations: {violations}\n"
        f"Allow-list: {sorted(ALLOWED_AUDIT_INSERT_FILES)}\n"
        f"If the new caller legitimately writes audit rows: "
        f"update ALLOWED_AUDIT_INSERT_FILES + require code review."
    )


def test_no_dream_module_writes_applied_status():
    """Explicit verification: dream_agent.py + master_dream_agent.py do NOT
    contain 'status=applied' — belt-and-suspenders across Layer 1/2a/4.
    """
    for fname in ("dream_agent.py", "master_dream_agent.py"):
        path = _AUTOSERVICE / fname
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        hits = _find_applied_status_writes(tree)
        assert not hits, (
            f"🔒 CON-04 RED LINE BREACH: {fname} contains "
            f"'status=applied' literal at line(s) {hits}. "
            f"Dream agents MUST NEVER write non-draft proposal status."
        )


def test_no_dream_module_writes_accepted_status():
    """Accepted status is also not a dream-agent-writable field.

    Only /approve handlers (HTTP layer) write 'accepted'.  Dream modules
    must never write it.
    """
    for fname in ("dream_agent.py", "master_dream_agent.py"):
        path = _AUTOSERVICE / fname
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        # Check substring presence — accepted in SQL literal would be a red flag
        normalized = src.replace(" ", "")
        assert "status='accepted'" not in normalized, (
            f"🔒 CON-04 RED LINE BREACH: {fname} contains "
            f"status='accepted' SQL write.  Only /approve HTTP handler may "
            f"write accepted."
        )


def test_allow_list_files_actually_exist():
    """Sanity check the allow-list itself — typos in paths would silently
    widen the allow-list to every file (because set membership fails closed
    but the INTENT was to narrow)."""
    all_paths = ALLOWED_APPLIED_WRITE_FILES | ALLOWED_AUDIT_INSERT_FILES
    for p in all_paths:
        full = _REPO_ROOT / p
        assert full.exists(), f"Allow-list stale: {p} does not exist"


def test_guardrail_actually_catches_violations(tmp_path, monkeypatch):
    """Meta-test: inject a fake file with 'status=applied' literal into
    autoservice/ and verify the guardrail fails.

    This proves the scanner isn't silently passing due to a bug.
    """
    fake_file = _AUTOSERVICE / "_guardrail_canary_delete_me.py"
    fake_file.write_text(
        "# canary file — should trigger CON-04 guardrail\n"
        "SQL = \"UPDATE proposals SET status='applied' WHERE id=?\"\n",
        encoding="utf-8",
    )
    try:
        import pytest
        with pytest.raises(AssertionError, match="CON-04 VIOLATION"):
            test_applied_status_write_only_in_allowed_files()
    finally:
        fake_file.unlink(missing_ok=True)
