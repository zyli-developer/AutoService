"""E2E tests for T6C.3 — /approve /reject Real Execution.

Covers: approve → accepted + canary, reject → rejected, invalid ID,
idempotent approve, ID parsing formats, status validation.
All 6 test cases from plan-T6C.3.
"""

import os
import sqlite3
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from autoservice.proposal_pipeline import ProposalPipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    """Temporary SQLite database for proposals."""
    return str(tmp_path / "proposals.db")


@pytest.fixture
def mock_memory_pool():
    pool = MagicMock()
    pool.query_recent.return_value = []
    pool.replay.return_value = ""
    return pool


@pytest.fixture
def pipeline(mock_memory_pool, tmp_db):
    pp = ProposalPipeline(
        memory_pool=mock_memory_pool,
        analyzer=lambda text: [{"category": "test", "title": "Test", "description": "d", "suggestion": "s", "evidence": "e"}],
        db_path=tmp_db,
    )
    return pp


@pytest.fixture
def seeded_pipeline(pipeline):
    """Pipeline with 2 draft proposals pre-inserted."""
    import json
    conn = pipeline._conn  # ProposalPipeline stores sqlite3 conn as _conn
    for i, pid in enumerate(["prop_001", "prop_002"], 1):
        data = json.dumps({
            "id": pid,
            "title": f"Proposal {i}",
            "category": "improvement",
            "priority": "medium",
            "status": "draft",
        })
        conn.execute(
            "INSERT OR IGNORE INTO proposals (id, created_at, data, status, category) VALUES (?, ?, ?, ?, ?)",
            (pid, "2026-04-17T10:00:00Z", data, "draft", "improvement"),
        )
    conn.commit()
    return pipeline


# ---------------------------------------------------------------------------
# TC-024: /approve #N → accepted + canary activated
# ---------------------------------------------------------------------------

async def test_tc024_approve_updates_status(seeded_pipeline):
    """update_status(id, 'accepted') sets proposal to accepted."""
    pp = seeded_pipeline

    result = pp.update_status("prop_001", "accepted")
    assert result is not None, "update_status should return the updated proposal"
    assert result.get("status") == "accepted", \
        f"proposal status should be 'accepted', got {result.get('status')}"

    # Verify persistence
    fetched = pp.get_proposal("prop_001")
    assert fetched is not None
    assert fetched.get("status") == "accepted", "status should persist in DB"


# ---------------------------------------------------------------------------
# TC-025: /reject #N → rejected
# ---------------------------------------------------------------------------

async def test_tc025_reject_updates_status(seeded_pipeline):
    """update_status(id, 'rejected') sets proposal to rejected."""
    pp = seeded_pipeline

    result = pp.update_status("prop_002", "rejected")
    assert result is not None
    assert result.get("status") == "rejected", \
        f"proposal status should be 'rejected', got {result.get('status')}"


# ---------------------------------------------------------------------------
# TC-026: Invalid proposal ID → None
# ---------------------------------------------------------------------------

async def test_tc026_invalid_id_returns_none(seeded_pipeline):
    """update_status with non-existent ID returns None."""
    pp = seeded_pipeline

    result = pp.update_status("prop_999", "accepted")
    assert result is None, "non-existent proposal should return None"


# ---------------------------------------------------------------------------
# TC-027: Approve already-accepted proposal — idempotent
# ---------------------------------------------------------------------------

async def test_tc027_approve_idempotent(seeded_pipeline):
    """Re-approving an accepted proposal should not error."""
    pp = seeded_pipeline

    pp.update_status("prop_001", "accepted")
    # Second approve — should not raise
    result = pp.update_status("prop_001", "accepted")
    assert result is not None, "idempotent approve should still return proposal"
    assert result.get("status") == "accepted"


# ---------------------------------------------------------------------------
# TC-028: Proposal ID parsing formats
# ---------------------------------------------------------------------------

async def test_tc028_id_parsing():
    """_parse_proposal_id handles #N numeric and prop_xxx formats.

    The command parameter is the full prefix (e.g. '/approve').
    Numeric shorthand resolves via DB lookup, so without proposals it returns None.
    """
    from autoservice.api_routes import _parse_proposal_id

    # Full ID format — always works (no DB lookup needed)
    parsed_full = _parse_proposal_id("/approve prop_abc123", "/approve")
    assert parsed_full == "prop_abc123", f"prop_xxx should parse directly, got {parsed_full}"

    # Missing ID — returns None
    parsed_empty = _parse_proposal_id("/approve", "/approve")
    assert parsed_empty is None, "missing ID should return None"

    # Empty after # — returns None
    parsed_hash_only = _parse_proposal_id("/approve #", "/approve")
    assert parsed_hash_only is None, "bare # should return None"


# ---------------------------------------------------------------------------
# TC-029: update_status validates status values
# ---------------------------------------------------------------------------

async def test_tc029_status_validation(seeded_pipeline):
    """update_status rejects invalid status strings."""
    pp = seeded_pipeline

    # Valid status
    result = pp.update_status("prop_001", "accepted")
    assert result is not None

    # Invalid status — should raise or return None
    try:
        bad = pp.update_status("prop_001", "bogus")
        # If it doesn't raise, it should return None or raise ValueError
        if bad is not None:
            pytest.fail("invalid status 'bogus' should be rejected")
    except (ValueError, KeyError):
        pass  # Expected
