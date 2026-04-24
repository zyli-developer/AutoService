"""T3B.1 — unit tests for ``dream_agent.emit_proposal``.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §2.2, §2.3

Red-line CON-04 is enforced here: the proposal row MUST land with
``status='draft'`` every time, and there's no way for the caller to raise
the status via this tool. The rest of the cases cover input validation
(risk_level / target_role) and tenant-scoped persistence.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from autoservice import dream_agent
from autoservice.proposal_pipeline import apply_schema
from autoservice.soul_generator import AGENT_ROLES


# ── fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """In-memory proposals DB with schema pre-applied."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    apply_schema(c)
    yield c
    c.close()


def _valid_kwargs(**overrides) -> dict:
    """A baseline set of valid emit_proposal kwargs, overridable per-test."""
    base = dict(
        tenant_id="acme",
        category="response_quality",
        title="Greeting reads too cold",
        description="The customer agent opens every conversation with a flat 'Hello.'",
        suggestion="Use brand-voice warmer opener.",
        evidence="Turn 0: 'Hello.' (observed in 8/10 sampled chats)",
        risk_level="low",
        target_role="customer",
    )
    base.update(overrides)
    return base


# ── red-line: status hard-coded to draft (CON-04) ──────────────────────────


def test_emit_proposal_forces_status_draft(conn):
    """The SQLite row AND the JSON payload must both say status='draft'."""
    pid = dream_agent.emit_proposal(conn, **_valid_kwargs())

    row = conn.execute(
        "SELECT status, data FROM proposals WHERE id = ?", (pid,)
    ).fetchone()
    assert row is not None
    assert row["status"] == "draft"

    payload = json.loads(row["data"])
    assert payload["status"] == "draft", (
        "JSON payload status must also be 'draft' — red-line CON-04"
    )


def test_emit_proposal_signature_has_no_status_kwarg():
    """The function signature must NOT accept a status kwarg.

    This locks in CON-04 at the API-shape level: even a well-intentioned
    future edit cannot accept an override without showing up in a diff of
    this test.
    """
    import inspect
    sig = inspect.signature(dream_agent.emit_proposal)
    assert "status" not in sig.parameters, (
        "emit_proposal must never accept a status kwarg — red-line CON-04."
    )


# ── validation ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["", "critical", "LOW", "none", None])
def test_emit_proposal_rejects_invalid_risk_level(conn, bad):
    """Invalid risk_level must raise ValueError before any row is written."""
    with pytest.raises(ValueError, match="risk_level"):
        dream_agent.emit_proposal(conn, **_valid_kwargs(risk_level=bad))

    # Confirm nothing was written.
    count = conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
    assert count == 0


@pytest.mark.parametrize("bad", ["", "admin", "Customer", "root", None])
def test_emit_proposal_rejects_invalid_target_role(conn, bad):
    """Invalid target_role must raise ValueError; row must not be written."""
    with pytest.raises(ValueError, match="target_role"):
        dream_agent.emit_proposal(conn, **_valid_kwargs(target_role=bad))

    count = conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
    assert count == 0


def test_emit_proposal_accepts_all_agent_roles(conn):
    """Every AGENT_ROLES member must be a valid target_role.

    The Dream agent itself targets ``customer`` / ``translate`` / ``lead``
    / ``triage`` in practice, and may self-propose governance changes
    (``dream``) as an escape hatch. All 5 roles are accepted at the API
    layer; spec §2.3 anti-patterns remind the *soul* not to propose
    dream-on-dream changes, but that's a soul-prompt concern, not a
    schema-level rejection.
    """
    for role in AGENT_ROLES:
        pid = dream_agent.emit_proposal(conn, **_valid_kwargs(target_role=role))
        assert pid.startswith("prop_")


# ── tenant scoping ─────────────────────────────────────────────────────────


def test_emit_proposal_persists_tenant_id_on_row_and_payload(conn):
    pid = dream_agent.emit_proposal(conn, **_valid_kwargs(tenant_id="tenant_xyz"))

    row = conn.execute(
        "SELECT tenant_id, data FROM proposals WHERE id = ?", (pid,)
    ).fetchone()
    assert row["tenant_id"] == "tenant_xyz"

    payload = json.loads(row["data"])
    assert payload["tenant_id"] == "tenant_xyz", (
        "JSON payload must echo tenant_id so the admin-portal renderer "
        "doesn't need to JOIN against the column."
    )


def test_emit_proposal_returns_id_usable_with_get_proposal(tmp_path):
    """The returned id must round-trip through ProposalPipeline.get_proposal.

    This guards against a subtle shape mismatch — the Dream tool writes a
    slightly different JSON payload than the M1 pipeline (risk_level,
    target_role, origin), but the admin-portal reads rows through
    ``get_proposal`` which just JSON-loads the ``data`` column. If we ever
    switch to a second column or stop writing the whole payload, this test
    fails fast.
    """
    from autoservice.proposal_pipeline import ProposalPipeline

    db_path = tmp_path / "props.db"
    seed = sqlite3.connect(str(db_path))
    apply_schema(seed)
    seed.close()

    class _StubMemoryPool:
        def __init__(self, conn): self._conn = conn

    mp_conn = sqlite3.connect(str(tmp_path / "mp.db"))
    pipeline = ProposalPipeline(
        memory_pool=_StubMemoryPool(mp_conn), db_path=str(db_path)
    )

    pid = dream_agent.emit_proposal(pipeline._conn, **_valid_kwargs(tenant_id="acme"))

    round_tripped = pipeline.get_proposal(pid)
    assert round_tripped is not None
    assert round_tripped["id"] == pid
    assert round_tripped["status"] == "draft"
    assert round_tripped["tenant_id"] == "acme"
    assert round_tripped["target_role"] == "customer"
    assert round_tripped["origin"] == "dream_agent"

    mp_conn.close()


def test_emit_proposal_records_full_payload(conn):
    """All Dream-specific fields must be persisted verbatim."""
    kwargs = _valid_kwargs(
        tenant_id="t1",
        category="knowledge_gap",
        title="Missing refund policy details",
        description="Agent answers refund questions with a generic template.",
        suggestion="Ingest the refund policy PDF into KB.",
        evidence="Conv conv_42 turn 3: agent said 'I'll check and get back to you.'",
        risk_level="medium",
        target_role="customer",
    )
    pid = dream_agent.emit_proposal(conn, **kwargs)

    row = conn.execute(
        "SELECT data FROM proposals WHERE id = ?", (pid,)
    ).fetchone()
    payload = json.loads(row["data"])
    for k, v in kwargs.items():
        assert payload[k] == v, f"field {k} not persisted verbatim"
    assert payload["id"] == pid
    assert "created_at" in payload
    assert payload["origin"] == "dream_agent"
