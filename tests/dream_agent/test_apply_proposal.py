"""Tests for ``autoservice.proposal_apply`` — CON-04 🔒 security-critical (M3 T4S.1).

Contract: docs/contracts/m3/e5-dream.md v1.1 §2 + §4.

Coverage areas (reviewer T0S.4 v2 checklist):
- Pre-condition: status must be 'accepted' (conditional UPDATE pattern)
- Idempotent on already-applied (no raise; returns idempotent=True)
- Admin user id required
- Platform-level category requires tier-0 admin (inside function, not just HTTP)
- Audit row written atomically with state change
- CON-04 import cone: proposal_apply imports nothing from dream modules
- Race-safety: concurrent apply on same pid — exactly one transitions
"""
from __future__ import annotations

import ast
import inspect
import sqlite3
import threading

import pytest

from autoservice import proposal_apply
from autoservice.proposal_apply import ApplyResult, apply_proposal
from autoservice.proposal_pipeline import (
    ProposalNotFound,
    ProposalPipeline,
    ProposalStateError,
    apply_schema,
)


class _StubPipeline(ProposalPipeline):
    """ProposalPipeline bound to an in-memory conn (bypass MemoryPool req for unit tests)."""
    def __init__(self, conn):  # type: ignore[override]
        self._memory_pool = None
        self._analyzer = None
        self._compliance_engine = None
        self._batch_size = 10
        self._conn = conn
        self._conn.row_factory = sqlite3.Row
        apply_schema(self._conn)


@pytest.fixture()
def pipeline():
    conn = sqlite3.connect(":memory:")
    yield _StubPipeline(conn=conn)
    conn.close()


def _seed_proposal(
    pipeline, *, tenant_id="acme", category="response_quality",
    status="accepted", pid="p-1",
):
    """Insert a proposal directly (bypass dream_agent for test setup)."""
    import json
    data = {
        "id": pid, "tenant_id": tenant_id, "category": category,
        "status": status, "title": "t", "description": "d", "suggestion": "s",
        "evidence": "e", "risk_level": "low", "target_role": "dream",
        "created_at": "2026-04-21T00:00:00+00:00",
    }
    pipeline._conn.execute(
        "INSERT INTO proposals (id, created_at, data, status, category, tenant_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (pid, data["created_at"], json.dumps(data), status, category, tenant_id),
    )
    pipeline._conn.commit()
    return pid


# ──────────────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────────────


def test_apply_accepted_proposal_transitions_to_applied(pipeline):
    pid = _seed_proposal(pipeline, status="accepted")
    result = apply_proposal(
        pipeline, proposal_id=pid, admin_user_id="admin@acme.com"
    )
    assert isinstance(result, ApplyResult)
    assert result.previous_status == "accepted"
    assert result.new_status == "applied"
    assert result.admin_user_id == "admin@acme.com"
    assert result.idempotent is False
    assert result.applied_at is not None

    # DB state actually changed
    row = pipeline._conn.execute(
        "SELECT status FROM proposals WHERE id = ?", (pid,)
    ).fetchone()
    assert row["status"] == "applied"


def test_audit_row_written_atomically(pipeline):
    pid = _seed_proposal(pipeline, status="accepted")
    apply_proposal(
        pipeline, proposal_id=pid, admin_user_id="admin@acme.com"
    )
    audit = pipeline._conn.execute(
        "SELECT action, previous_status, new_status, admin_user_id "
        "FROM proposal_audit WHERE proposal_id = ?",
        (pid,),
    ).fetchall()
    assert len(audit) == 1
    assert audit[0]["action"] == "apply"
    assert audit[0]["previous_status"] == "accepted"
    assert audit[0]["new_status"] == "applied"
    assert audit[0]["admin_user_id"] == "admin@acme.com"


# ──────────────────────────────────────────────────────────────────────────
# Pre-condition errors
# ──────────────────────────────────────────────────────────────────────────


def test_apply_empty_admin_user_id_rejected(pipeline):
    pid = _seed_proposal(pipeline)
    with pytest.raises(ValueError, match="admin_user_id is required"):
        apply_proposal(pipeline, proposal_id=pid, admin_user_id="")
    with pytest.raises(ValueError):
        apply_proposal(pipeline, proposal_id=pid, admin_user_id="   ")


def test_apply_missing_proposal_raises(pipeline):
    with pytest.raises(ProposalNotFound):
        apply_proposal(
            pipeline, proposal_id="ghost", admin_user_id="admin@acme.com"
        )


def test_apply_draft_status_rejected(pipeline):
    pid = _seed_proposal(pipeline, status="draft")
    with pytest.raises(ProposalStateError, match="!= 'accepted'"):
        apply_proposal(
            pipeline, proposal_id=pid, admin_user_id="admin@acme.com"
        )


def test_apply_rejected_status_blocked(pipeline):
    pid = _seed_proposal(pipeline, status="rejected")
    with pytest.raises(ProposalStateError):
        apply_proposal(
            pipeline, proposal_id=pid, admin_user_id="admin@acme.com"
        )


# ──────────────────────────────────────────────────────────────────────────
# Idempotent on already-applied
# ──────────────────────────────────────────────────────────────────────────


def test_apply_on_already_applied_is_idempotent(pipeline):
    pid = _seed_proposal(pipeline, status="accepted")
    first = apply_proposal(
        pipeline, proposal_id=pid, admin_user_id="admin@acme.com"
    )
    assert first.idempotent is False

    second = apply_proposal(
        pipeline, proposal_id=pid, admin_user_id="admin2@acme.com"
    )
    assert second.idempotent is True
    assert second.previous_status == "applied"
    assert second.new_status == "applied"
    assert second.applied_at is None  # no new timestamp; unchanged

    # Exactly ONE audit row — idempotent call doesn't double-write
    audit = pipeline._conn.execute(
        "SELECT COUNT(*) AS n FROM proposal_audit WHERE proposal_id = ?",
        (pid,),
    ).fetchone()
    assert audit["n"] == 1


# ──────────────────────────────────────────────────────────────────────────
# Platform-level → tier-0 admin required (inside function)
# ──────────────────────────────────────────────────────────────────────────


def test_platform_level_requires_tier_zero_admin(pipeline):
    pid = _seed_proposal(
        pipeline, category="platform_level", tenant_id="_master",
    )
    with pytest.raises(PermissionError, match="platform_level"):
        apply_proposal(
            pipeline, proposal_id=pid, admin_user_id="tenant-admin@acme.com",
            is_platform_admin=False,
        )


def test_platform_level_allowed_for_platform_admin(pipeline):
    pid = _seed_proposal(
        pipeline, category="platform_level", tenant_id="_master",
    )
    result = apply_proposal(
        pipeline, proposal_id=pid, admin_user_id="platform@example.com",
        is_platform_admin=True,
    )
    assert result.new_status == "applied"


def test_regular_category_tenant_admin_ok(pipeline):
    pid = _seed_proposal(pipeline, category="workflow")
    result = apply_proposal(
        pipeline, proposal_id=pid, admin_user_id="tenant-admin@acme.com",
        is_platform_admin=False,
    )
    assert result.new_status == "applied"


# ──────────────────────────────────────────────────────────────────────────
# CON-04 Layer 3: import cone (🔒 critical invariant)
# ──────────────────────────────────────────────────────────────────────────


def test_con04_import_cone_no_dream_imports():
    """🔒 CON-04 Layer 3 — proposal_apply has ZERO imports from dream modules.

    This test walks the AST of proposal_apply.py and asserts no Import or
    ImportFrom node references ``dream_agent`` or ``master_dream_agent``.
    Complement to the broader AST guardrail in T4S.8.
    """
    src = inspect.getsource(proposal_apply)
    tree = ast.parse(src)

    forbidden = {"dream_agent", "master_dream_agent", "autoservice.dream_agent",
                 "autoservice.master_dream_agent"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden, (
                    f"🔒 CON-04 VIOLATION: proposal_apply imports {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert mod not in forbidden, (
                f"🔒 CON-04 VIOLATION: proposal_apply imports from {mod}"
            )
            # Also check 'from autoservice import dream_agent'
            for alias in node.names:
                assert alias.name not in ("dream_agent", "master_dream_agent"), (
                    f"🔒 CON-04 VIOLATION: proposal_apply imports name "
                    f"{alias.name} from {mod}"
                )


def test_con04_apply_only_writer_of_applied_status(pipeline):
    """🔒 Only proposal_apply → _mark_applied_internal can write 'applied'.

    Verify the public update_status rejects 'applied' outright (Layer 2b).
    """
    pid = _seed_proposal(pipeline, status="accepted")
    with pytest.raises(ProposalStateError, match="CON-04"):
        pipeline.update_status(pid, "applied")


def test_con04_update_status_still_accepts_other_transitions(pipeline):
    """Sanity: Layer 2b doesn't over-block — draft→accepted still works."""
    pid = _seed_proposal(pipeline, status="draft")
    result = pipeline.update_status(pid, "accepted")
    assert result is not None
    assert result["status"] == "accepted"


# ──────────────────────────────────────────────────────────────────────────
# Race safety — reviewer T0S.4 v2 C2 requirement
# ──────────────────────────────────────────────────────────────────────────


def test_concurrent_apply_same_pid_exactly_one_transitions():
    """Two threads apply() same pid concurrently → exactly 1 real + 1 idempotent.

    Verifies atomic conditional UPDATE (T4S.2 _mark_applied_internal):
    UPDATE ... WHERE id=? AND status='accepted' → rowcount=1 for first,
    rowcount=0 for second (which then sees 'applied' → idempotent).
    """
    # Use a shared file-based DB to allow 2 connections with separate transactions
    import tempfile
    from pathlib import Path

    tmpdir = tempfile.mkdtemp()
    db_path = Path(tmpdir) / "race.db"
    try:
        # Setup seed on one conn
        seed_conn = sqlite3.connect(str(db_path))
        seed_pipeline = _StubPipeline(conn=seed_conn)
        _seed_proposal(seed_pipeline, status="accepted", pid="race-1")
        seed_conn.close()

        results: list[ApplyResult] = []
        errors: list[BaseException] = []

        def worker():
            try:
                c = sqlite3.connect(str(db_path))
                p = _StubPipeline(conn=c)
                r = apply_proposal(
                    p, proposal_id="race-1", admin_user_id="admin@acme.com"
                )
                results.append(r)
                c.close()
            except BaseException as e:  # pragma: no cover
                errors.append(e)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start(); t2.start()
        t1.join(timeout=5); t2.join(timeout=5)

        assert not errors, f"workers raised: {errors}"
        assert len(results) == 2

        # Exactly one transitioned, the other was idempotent
        idempotent_count = sum(1 for r in results if r.idempotent)
        assert idempotent_count == 1, (
            f"expected 1 idempotent + 1 transition; got idempotent={idempotent_count}"
        )

        # Final DB state: applied, exactly ONE audit row
        check_conn = sqlite3.connect(str(db_path))
        check_conn.row_factory = sqlite3.Row
        status = check_conn.execute(
            "SELECT status FROM proposals WHERE id='race-1'"
        ).fetchone()["status"]
        assert status == "applied"
        audit_count = check_conn.execute(
            "SELECT COUNT(*) AS n FROM proposal_audit WHERE proposal_id='race-1'"
        ).fetchone()["n"]
        assert audit_count == 1, f"expected 1 audit row, got {audit_count}"
        check_conn.close()
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


# ──────────────────────────────────────────────────────────────────────────
# Result dataclass immutability
# ──────────────────────────────────────────────────────────────────────────


def test_apply_result_is_frozen():
    result = ApplyResult(
        proposal_id="x", previous_status="accepted", new_status="applied",
        admin_user_id="a", applied_at="t", handler_result={}, idempotent=False,
    )
    with pytest.raises(Exception):
        result.new_status = "hacked"  # type: ignore[misc]
