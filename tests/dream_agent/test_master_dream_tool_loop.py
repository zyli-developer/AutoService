"""T5S.14 / T4S.4b — master_dream_agent.run_platform_dream must drive a
real LLM tool loop (not the static seed emit).

Before T5S.14 the master path at
``autoservice/master_dream_agent.py:102-121`` emitted one fabricated
proposal with title starting ``"[platform dream]"`` — a skeleton that
never actually called the LLM.  This test pins the post-T5S.14
behaviour:

1. ``run_platform_dream`` invokes the same ``_run_agent_loop`` helper
   the per-tenant dream uses, so cross-tenant signals reach the LLM
   as part of the prompt.
2. The emitted proposal's title comes from the LLM, not from the
   static template — its title does NOT start with ``"[platform dream]"``
   (the old skeleton marker).
3. CON-04 is preserved: ``emit_proposal`` is still called with
   ``status='draft'`` (hardcoded string, never a variable).

LLM traffic is mocked via an injected closure — zero network.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from autoservice import (
    bootstrap,
    dream_runs,
    master_dream_agent,
    proposal_pipeline,
)


@pytest.fixture()
def proposals_conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    proposal_pipeline.apply_schema(c)
    yield c
    c.close()


@pytest.fixture()
def runs_conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(dream_runs.SCHEMA)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Fake dream client + fake pool for the tool loop
# ---------------------------------------------------------------------------


class _FakeDreamClient:
    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def call_with_tools(self, *, system: str, messages: list[dict], tools: list[dict]):
        self.calls.append(
            {"system": system, "messages": [dict(m) for m in messages], "tools": tools}
        )
        if not self._responses:
            raise AssertionError("fake client out of scripted responses")
        return self._responses.pop(0)


class _FakePooledInstance:
    def __init__(self, client):
        self.client = client
        self.id = "fake-master-dream-1"


class _FakeCCPool:
    def __init__(self, dream_client):
        self._dream_client = dream_client
        self.acquire_calls: list[dict] = []

    def acquire(self, *, role: str, tenant_id: str | None = None, timeout: float | None = None):
        self.acquire_calls.append({"role": role, "tenant_id": tenant_id})

        @asynccontextmanager
        async def _cm():
            yield _FakePooledInstance(self._dream_client)

        return _cm()


def _tool_use_resp(tool_name: str, tool_input: dict, *, use_id: str = "tu_m") -> dict:
    return {
        "content": [
            {"type": "tool_use", "id": use_id, "name": tool_name, "input": tool_input},
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 22, "output_tokens": 6},
    }


def _text_resp(text: str = "analysis complete") -> dict:
    return {
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 9, "output_tokens": 3},
    }


# The OLD static emit used this title marker.  The new loop-driven path
# must emit something different (supplied by the mocked LLM).
_OLD_STUB_TITLE_MARKER = "[platform dream]"

# The LLM's "real" suggestion — deliberately different from the stub.
_LLM_EMIT_INPUT = {
    "category": "platform_level",
    "title": "Cross-tenant CSAT drop on billing scenarios",
    "description": "Detected a 12-point CSAT drop on billing across 3 tenants.",
    "suggestion": "Refresh billing KB and re-run soul drafts.",
    "evidence": "{\"tenants_affected\": 3, \"csat_delta\": -12}",
    "risk_level": "medium",
    "target_role": "dream",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_platform_dream_drives_tool_loop_not_static_emit(
    proposals_conn, runs_conn,
):
    """Post-T5S.14: master dream runs a real tool loop.

    Scripts a 2-round exchange: tool_use(emit_proposal) → text end_turn.
    After the loop, exactly one proposal must be persisted AND its title
    must match the LLM-driven input — NOT the legacy "[platform dream]"
    stub marker.
    """
    responses = [
        _tool_use_resp("emit_proposal", _LLM_EMIT_INPUT, use_id="tu_p1"),
        _text_resp(),
    ]
    dream_client = _FakeDreamClient(responses)
    cc_pool = _FakeCCPool(dream_client)

    ids = await master_dream_agent.run_platform_dream(
        tenant_id=bootstrap.MASTER_TENANT_ID,
        cc_pool=cc_pool,
        mempool=None,
        proposals_conn=proposals_conn,
        runs_conn=runs_conn,
        max_tool_turns=5,
    )

    assert len(ids) == 1, f"expected 1 LLM-emitted proposal, got {len(ids)}"

    # Tool loop actually hit the LLM at least twice (one tool_use + one
    # terminating text turn).
    assert len(dream_client.calls) >= 2

    # Proposal in DB has the LLM-provided title, not the old stub's marker.
    row = proposals_conn.execute(
        "SELECT title_from_data.data AS data FROM proposals, "
        "(SELECT data FROM proposals WHERE id = ?) AS title_from_data "
        "WHERE proposals.id = ?",
        (ids[0], ids[0]),
    ).fetchone()
    # Simpler query:
    row = proposals_conn.execute(
        "SELECT data FROM proposals WHERE id = ?", (ids[0],),
    ).fetchone()
    payload = json.loads(row["data"])
    assert not payload["title"].startswith(_OLD_STUB_TITLE_MARKER), (
        f"title starts with legacy skeleton marker — tool loop not driving: "
        f"{payload['title']!r}"
    )
    assert payload["title"] == _LLM_EMIT_INPUT["title"]


@pytest.mark.asyncio
async def test_run_platform_dream_still_writes_draft_con04(
    proposals_conn, runs_conn,
):
    """Even on the new tool-loop path, emit_proposal locks status='draft'."""
    responses = [
        _tool_use_resp("emit_proposal", _LLM_EMIT_INPUT, use_id="tu_draft"),
        _text_resp(),
    ]
    dream_client = _FakeDreamClient(responses)
    cc_pool = _FakeCCPool(dream_client)

    ids = await master_dream_agent.run_platform_dream(
        tenant_id=bootstrap.MASTER_TENANT_ID,
        cc_pool=cc_pool,
        mempool=None,
        proposals_conn=proposals_conn,
        runs_conn=runs_conn,
        max_tool_turns=5,
    )

    row = proposals_conn.execute(
        "SELECT status, category, tenant_id FROM proposals WHERE id = ?",
        (ids[0],),
    ).fetchone()
    assert row["status"] == "draft"
    assert row["category"] == "platform_level"
    assert row["tenant_id"] == bootstrap.MASTER_TENANT_ID


@pytest.mark.asyncio
async def test_run_platform_dream_feeds_signals_into_prompt(
    proposals_conn, runs_conn,
):
    """Cross-tenant signals (gathered by gather_platform_signals) must
    reach the LLM as part of the prompt — otherwise the master dream
    is blind and degrades to the skeleton behaviour."""
    # Seed two tenants with proposals so gather_platform_signals returns
    # non-zero counts.
    for tid, n in [("acme", 2), ("beta", 3)]:
        for i in range(n):
            proposals_conn.execute(
                "INSERT INTO proposals (id, created_at, data, status, category, tenant_id) "
                "VALUES (?, ?, ?, 'draft', 'workflow', ?)",
                (f"{tid}-{i}", "2026-04-22T00:00:00",
                 json.dumps({"id": f"{tid}-{i}"}), tid),
            )
    proposals_conn.commit()

    responses = [
        # LLM decides to just wrap up — but the signals must have been in
        # its first-turn prompt so we can assert on them.
        _text_resp("observed; nothing to propose this cycle"),
    ]
    dream_client = _FakeDreamClient(responses)
    cc_pool = _FakeCCPool(dream_client)

    await master_dream_agent.run_platform_dream(
        tenant_id=bootstrap.MASTER_TENANT_ID,
        cc_pool=cc_pool,
        mempool=None,
        proposals_conn=proposals_conn,
        runs_conn=runs_conn,
        max_tool_turns=3,
    )

    # The first call's initial user message must contain the signal
    # snapshot — tenant count and aggregate proposal count at minimum.
    first = dream_client.calls[0]
    initial = first["messages"][0]["content"]
    # Accept either a compact JSON or a readable markdown rendering —
    # either way the numbers must be present.
    assert "2" in initial, "tenant_count=2 signal not threaded into prompt"
    assert "5" in initial, "total_proposal_count=5 signal not threaded into prompt"
