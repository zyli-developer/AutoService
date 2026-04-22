"""T5S.14 — run_dream must default to cc_pool's call_with_tools when
no explicit llm_send is passed.

Before T5S.14 the production path raised ``RuntimeError`` here — the
trigger endpoint could not drive a real Dream run.  This test pins the
new default-closure behaviour: when ``llm_send is None``, ``run_dream``
builds a closure around the acquired dream client's ``call_with_tools``
surface and proceeds through the normal tool-use loop.

Red-line CON-04: even on the default path the emitted proposal must
carry ``status='draft'`` — the test spot-checks that the written row
has that status, same as the explicit-injection code path.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from autoservice import dream_agent, dream_runs
from autoservice.memory_pool import MemoryPool
from autoservice.proposal_pipeline import apply_schema


@pytest.fixture()
def proposals_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    apply_schema(conn)
    yield conn
    conn.close()


@pytest.fixture()
def runs_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    dream_runs.init_schema(conn)
    yield conn
    conn.close()


@pytest.fixture()
def mempool(tmp_path) -> MemoryPool:
    mp = MemoryPool(db_path=tmp_path / "mem.db")
    yield mp
    mp.close()


@pytest.fixture()
def sandbox_root(tmp_path) -> Path:
    root = tmp_path / "sandbox"
    root.mkdir()
    return root


# ---------------------------------------------------------------------------
# Fake Dream client with call_with_tools — pretends to be a cc_pool client
# ---------------------------------------------------------------------------


class _FakeDreamClient:
    """Stand-in for a CCClient acquired from the dream pool.

    Exposes ``call_with_tools`` with the same ``(system, messages, tools)
    -> Message-shape dict`` contract the real cc_pool wrapper will
    produce.  Scripts responses so we can drive a deterministic loop.
    """

    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def call_with_tools(self, *, system: str, messages: list[dict], tools: list[dict]):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "tools": tools})
        if not self._responses:
            raise AssertionError("fake client ran out of scripted responses")
        return self._responses.pop(0)


class _FakePooledInstance:
    """Duck-types socialware.pool.PooledInstance — has .client and .id."""

    def __init__(self, client):
        self.client = client
        self.id = "fake-dream-1"


class _FakeCCPool:
    """Stand-in for autoservice.cc_pool.CCPool exposing acquire(role='dream').

    Returns an async context manager yielding a fake PooledInstance whose
    ``.client`` is a ``_FakeDreamClient``.  Tracks whether acquire was
    called so the test can assert the default-path actually went through
    the pool.
    """

    def __init__(self, dream_client):
        self._dream_client = dream_client
        self.acquire_calls: list[dict] = []

    def acquire(self, *, role: str, tenant_id: str | None = None, timeout: float | None = None):
        self.acquire_calls.append({"role": role, "tenant_id": tenant_id})

        @asynccontextmanager
        async def _cm():
            yield _FakePooledInstance(self._dream_client)

        return _cm()


def _tool_use_resp(tool_name: str, tool_input: dict, *, use_id: str = "tu_1") -> dict:
    return {
        "content": [
            {"type": "tool_use", "id": use_id, "name": tool_name, "input": tool_input},
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 15, "output_tokens": 4},
    }


def _text_resp(text: str = "done") -> dict:
    return {
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 8, "output_tokens": 3},
    }


def _emit_payload(**overrides) -> dict:
    base = {
        "category": "response_quality",
        "title": "Default-path probe",
        "description": "Evidence-based finding.",
        "suggestion": "Try X.",
        "evidence": "Observed in turn 3.",
        "risk_level": "low",
        "target_role": "customer",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_run_dream_no_llm_send_uses_cc_pool_surface(
    proposals_db, runs_db, mempool, sandbox_root,
):
    """llm_send=None must no longer raise — it must fall through to the
    cc_pool dream client's ``call_with_tools``."""
    responses = [
        _tool_use_resp("emit_proposal", _emit_payload(title="Found it")),
        _text_resp("done"),
    ]
    dream_client = _FakeDreamClient(responses)
    cc_pool = _FakeCCPool(dream_client)

    result = asyncio.run(dream_agent.run_dream(
        tenant_id="acme",
        cc_pool=cc_pool,
        mempool=mempool,
        proposals_db=proposals_db,
        runs_db=runs_db,
        max_tool_turns=10,
        sandbox_root=sandbox_root,
        llm_send=None,  # <-- the new default path under test
    ))

    # No RuntimeError (regression against the removed guard).
    assert result.status == "completed", (
        f"expected completed, got status={result.status} error={result.error}"
    )
    assert result.tool_calls == 1
    assert result.proposals_emitted == 1

    # The cc_pool was consulted with role='dream' and the loop's tenant_id.
    assert cc_pool.acquire_calls, "run_dream did not call cc_pool.acquire"
    first = cc_pool.acquire_calls[0]
    assert first["role"] == "dream"
    assert first["tenant_id"] == "acme"

    # call_with_tools was actually driven — at least once per turn.
    assert len(dream_client.calls) >= 2


def test_run_dream_default_path_writes_draft_proposal(
    proposals_db, runs_db, mempool, sandbox_root,
):
    """CON-04 spot check on the default path: emitted proposal is draft."""
    responses = [
        _tool_use_resp("emit_proposal", _emit_payload()),
        _text_resp("done"),
    ]
    dream_client = _FakeDreamClient(responses)
    cc_pool = _FakeCCPool(dream_client)

    asyncio.run(dream_agent.run_dream(
        tenant_id="acme_prod",
        cc_pool=cc_pool,
        mempool=mempool,
        proposals_db=proposals_db,
        runs_db=runs_db,
        max_tool_turns=10,
        sandbox_root=sandbox_root,
        llm_send=None,
    ))

    rows = proposals_db.execute(
        "SELECT id, status, tenant_id, data FROM proposals",
    ).fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "draft", "CON-04 — default path must write draft"
    assert row["tenant_id"] == "acme_prod"
    payload = json.loads(row["data"])
    assert payload["status"] == "draft"


def test_run_dream_default_path_tool_responses_flow_back(
    proposals_db, runs_db, mempool, sandbox_root,
):
    """The tool_result produced by the loop must reach the SECOND LLM call.

    Regression guard: if the default-closure drops the message history
    between rounds, the model would never see its own tool_use echoed
    back — the loop would stall or repeat the same tool call forever.
    """
    responses = [
        _tool_use_resp("kb_search", {"query": "refunds"}, use_id="tu_k"),
        _text_resp("thanks"),
    ]
    dream_client = _FakeDreamClient(responses)
    cc_pool = _FakeCCPool(dream_client)

    result = asyncio.run(dream_agent.run_dream(
        tenant_id="acme",
        cc_pool=cc_pool,
        mempool=mempool,
        proposals_db=proposals_db,
        runs_db=runs_db,
        max_tool_turns=10,
        sandbox_root=sandbox_root,
        llm_send=None,
    ))

    assert result.status == "completed"

    # The second call_with_tools invocation must have seen the
    # tool_result (a user message with a tool_result block) in its
    # messages — otherwise history was dropped between rounds.
    second = dream_client.calls[1]
    last_msg = second["messages"][-1]
    assert last_msg["role"] == "user"
    content = last_msg["content"]
    assert isinstance(content, list)
    assert any(b.get("type") == "tool_result" for b in content)
