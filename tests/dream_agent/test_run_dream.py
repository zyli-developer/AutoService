"""T3B.4 — unit tests for :func:`autoservice.dream_agent.run_dream`.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §2.2 / §2.4.

Red-line CON-04 is enforced here at the loop level: every proposal the
Dream LLM emits lands with ``status='draft'`` and on the requested
tenant's row — even when the LLM asks for something else. The other
cases pin behaviour on the turn cap, natural termination, exception
mapping, tool dispatch, dream-soul fallback, and initial-context shape.

All LLM interaction is mocked via ``llm_send`` — no network, no
Anthropic SDK dependency.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any, Callable

import pytest

from autoservice import dream_agent, dream_runs
from autoservice.memory_pool import MemoryPool
from autoservice.proposal_pipeline import apply_schema
from autoservice.soul_generator import _FALLBACK_DREAM_SOUL


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def proposals_db() -> sqlite3.Connection:
    """In-memory proposals DB with M2 tenant_id-aware schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    apply_schema(conn)
    yield conn
    conn.close()


@pytest.fixture()
def runs_db() -> sqlite3.Connection:
    """In-memory dream_runs DB with schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    dream_runs.init_schema(conn)
    yield conn
    conn.close()


@pytest.fixture()
def mempool(tmp_path) -> MemoryPool:
    """File-backed MemoryPool under *tmp_path* (sqlite doesn't allow
    :memory: with an external schema script and our fixtures expect a
    path-based constructor). The tmp_path fixture scopes the DB per-test."""
    mp = MemoryPool(db_path=tmp_path / "mem.db")
    yield mp
    mp.close()


@pytest.fixture()
def sandbox_root(tmp_path) -> Path:
    """Root of a per-test sandbox tree — no real ``.autoservice/`` writes."""
    root = tmp_path / "sandbox"
    root.mkdir()
    return root


# ── LLM mock helpers ──────────────────────────────────────────────────────


def _text_response(text: str = "done", stop_reason: str = "end_turn") -> dict:
    """Build a fake Anthropic message response that returns plain text."""
    return {
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "usage": {"input_tokens": 10, "output_tokens": 3},
    }


def _tool_use_response(
    tool_name: str,
    tool_input: dict,
    *,
    use_id: str = "tu_1",
    tokens_in: int = 20,
    tokens_out: int = 5,
) -> dict:
    """Build a fake Anthropic message response that asks for one tool call."""
    return {
        "content": [
            {
                "type": "tool_use",
                "id": use_id,
                "name": tool_name,
                "input": tool_input,
            }
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out},
    }


def _scripted_llm(responses: list[dict]) -> Callable:
    """Return a sync llm_send callable that yields *responses* in order.

    Once the list is exhausted the callable raises AssertionError — this
    is deliberately loud so tests fail fast if the loop runs further
    than the test expects.
    """
    state = {"i": 0}
    calls: list[dict] = []

    def send(*, system: str, messages: list[dict], tools: list[dict]):
        calls.append({
            "system": system,
            "messages": [dict(m) for m in messages],
            "tools": tools,
        })
        i = state["i"]
        if i >= len(responses):
            raise AssertionError(
                f"llm_send called {i+1} times, only {len(responses)} "
                "responses scripted — loop did not terminate as expected"
            )
        state["i"] += 1
        return responses[i]

    send.calls = calls  # type: ignore[attr-defined]
    return send


def _emit_payload(**overrides) -> dict:
    """Baseline valid emit_proposal input, overridable per-test."""
    base = {
        "category": "response_quality",
        "title": "Greeting is flat",
        "description": "Agent opens with 'Hello.' every time.",
        "suggestion": "Use warmer, brand-appropriate opener.",
        "evidence": "Turn 0 of 8/10 sampled chats reads 'Hello.'",
        "risk_level": "low",
        "target_role": "customer",
    }
    base.update(overrides)
    return base


# ── Tests (behaviour under §2.2 / §2.4) ───────────────────────────────────


def test_max_tool_turns_cap_triggers_overrun(
    proposals_db, runs_db, mempool, sandbox_root,
):
    """A model that calls a tool every turn must be stopped at the cap.

    We script 11 tool_use responses; with ``max_tool_turns=10`` the
    loop must break *before* consuming the 11th (which would raise the
    ``AssertionError`` baked into :func:`_scripted_llm`).
    """
    # 11 kb_search responses — more than the cap, so any off-by-one in
    # the cap check will either raise (too greedy) or under-count.
    responses = [
        _tool_use_response("kb_search", {"query": f"q{i}"}, use_id=f"tu_{i}")
        for i in range(11)
    ]
    send = _scripted_llm(responses)

    result = asyncio.run(dream_agent.run_dream(
        tenant_id="acme",
        cc_pool=None,
        mempool=mempool,
        proposals_db=proposals_db,
        runs_db=runs_db,
        max_tool_turns=10,
        sandbox_root=sandbox_root,
        llm_send=send,
    ))

    assert result.status == "overrun"
    assert result.tool_calls == 10
    assert result.proposals_emitted == 0
    # Exactly 10 LLM calls (one per turn; cap is tested *before* the 11th).
    assert len(send.calls) == 10  # type: ignore[attr-defined]


def test_natural_termination_records_completed(
    proposals_db, runs_db, mempool, sandbox_root,
):
    """A model that stops calling tools after 2 turns gets status='completed'."""
    responses = [
        _tool_use_response("kb_search", {"query": "hello"}),
        _tool_use_response(
            "list_souls", {}, use_id="tu_2",
        ),
        _text_response("all observations done"),
    ]
    send = _scripted_llm(responses)

    result = asyncio.run(dream_agent.run_dream(
        tenant_id="acme",
        cc_pool=None,
        mempool=mempool,
        proposals_db=proposals_db,
        runs_db=runs_db,
        max_tool_turns=10,
        sandbox_root=sandbox_root,
        llm_send=send,
    ))

    assert result.status == "completed"
    assert result.tool_calls == 2
    assert result.proposals_emitted == 0


def test_dream_runs_row_persisted(
    proposals_db, runs_db, mempool, sandbox_root,
):
    """End-to-end: dream_runs table has a terminal row after run_dream."""
    send = _scripted_llm([
        _tool_use_response(
            "emit_proposal", _emit_payload(title="First"), use_id="tu_a",
        ),
        _text_response("done"),
    ])

    result = asyncio.run(dream_agent.run_dream(
        tenant_id="tenant_X",
        cc_pool=None,
        mempool=mempool,
        proposals_db=proposals_db,
        runs_db=runs_db,
        max_tool_turns=10,
        sandbox_root=sandbox_root,
        llm_send=send,
    ))

    row = runs_db.execute(
        "SELECT tenant_id, status, tool_calls, proposals_emitted, "
        "started_at, ended_at, tokens_in, tokens_out "
        "FROM dream_runs WHERE id = ?",
        (result.run_id,),
    ).fetchone()
    assert row is not None
    assert row["tenant_id"] == "tenant_X"
    assert row["status"] == "completed"
    assert row["tool_calls"] == 1
    assert row["proposals_emitted"] == 1
    assert row["started_at"]
    assert row["ended_at"], "ended_at must be stamped on terminal row"
    # Usage totals come from the mock response's usage block.
    assert row["tokens_in"] >= 0
    assert row["tokens_out"] >= 0


def test_proposals_are_draft_and_tenant_scoped(
    proposals_db, runs_db, mempool, sandbox_root,
):
    """Red-line CON-04: emit_proposal row must be draft AND tenant-scoped.

    Even if the LLM's input carried another tenant_id, the loop uses
    its own — this test also pins that behaviour by including a bogus
    ``tenant_id`` key in the tool input which must be ignored.
    """
    bogus_input = dict(_emit_payload())
    bogus_input["tenant_id"] = "attacker"  # must be ignored by the loop
    send = _scripted_llm([
        _tool_use_response("emit_proposal", bogus_input),
        _text_response("done"),
    ])

    await_tenant = "legit_tenant"
    result = asyncio.run(dream_agent.run_dream(
        tenant_id=await_tenant,
        cc_pool=None,
        mempool=mempool,
        proposals_db=proposals_db,
        runs_db=runs_db,
        max_tool_turns=10,
        sandbox_root=sandbox_root,
        llm_send=send,
    ))

    assert result.proposals_emitted == 1

    rows = proposals_db.execute(
        "SELECT id, status, tenant_id, data FROM proposals"
    ).fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "draft", "red-line CON-04 — never non-draft"
    assert row["tenant_id"] == await_tenant, (
        "red-line CON-04 — tenant_id comes from the loop, not the LLM"
    )
    # And the JSON payload agrees with the column.
    payload = json.loads(row["data"])
    assert payload["status"] == "draft"
    assert payload["tenant_id"] == await_tenant


def test_llm_exception_records_failed(
    proposals_db, runs_db, mempool, sandbox_root,
):
    """An LLM-layer exception must map to status='failed' with error captured."""
    def boom(*, system, messages, tools):
        raise RuntimeError("network down")

    result = asyncio.run(dream_agent.run_dream(
        tenant_id="acme",
        cc_pool=None,
        mempool=mempool,
        proposals_db=proposals_db,
        runs_db=runs_db,
        max_tool_turns=10,
        sandbox_root=sandbox_root,
        llm_send=boom,
    ))

    assert result.status == "failed"
    assert result.error is not None
    assert "network down" in result.error

    row = runs_db.execute(
        "SELECT status, error FROM dream_runs WHERE id = ?", (result.run_id,),
    ).fetchone()
    assert row["status"] == "failed"
    assert "network down" in (row["error"] or "")


def test_kb_search_and_list_souls_callable_from_loop(
    proposals_db, runs_db, mempool, sandbox_root,
):
    """Both non-emit tools dispatch correctly with the loop's tenant_id.

    We install a fake tenant sandbox with 5 soul files so ``list_souls``
    returns a non-empty list, then assert the tool_result the loop fed
    back into the LLM (as the next user message) matches what the tools
    would produce standalone.
    """
    tid = "acme"
    souls_dir = sandbox_root / tid / "souls"
    souls_dir.mkdir(parents=True)
    for role in ("customer", "translate", "lead", "triage", "dream"):
        (souls_dir / f"{role}_soul.md").write_text(
            f"# {role.title()} soul\nBody.\n", encoding="utf-8"
        )

    send = _scripted_llm([
        _tool_use_response("kb_search", {"query": "pricing"}, use_id="tu_a"),
        _tool_use_response("list_souls", {}, use_id="tu_b"),
        _text_response("summary"),
    ])

    result = asyncio.run(dream_agent.run_dream(
        tenant_id=tid,
        cc_pool=None,
        mempool=mempool,
        proposals_db=proposals_db,
        runs_db=runs_db,
        max_tool_turns=10,
        sandbox_root=sandbox_root,
        llm_send=send,
    ))

    assert result.status == "completed"
    assert result.tool_calls == 2
    assert result.proposals_emitted == 0

    # Inspect the second LLM call's messages — the tool_result for
    # kb_search must be present with an empty list (no KB db on disk).
    second_call = send.calls[1]  # type: ignore[attr-defined]
    tool_result_msg = second_call["messages"][-1]
    assert tool_result_msg["role"] == "user"
    blocks = tool_result_msg["content"]
    assert any(b["type"] == "tool_result" for b in blocks)
    kb_result_block = next(b for b in blocks if b["tool_use_id"] == "tu_a")
    assert json.loads(kb_result_block["content"]) == []  # no KB file exists

    # The third call must include the list_souls tool_result: 4 entries
    # (dream excluded by default).
    third_call = send.calls[2]  # type: ignore[attr-defined]
    tool_result_msg2 = third_call["messages"][-1]
    blocks2 = tool_result_msg2["content"]
    souls_block = next(b for b in blocks2 if b["tool_use_id"] == "tu_b")
    souls = json.loads(souls_block["content"])
    assert len(souls) == 4
    assert {s["role"] for s in souls} == {
        "customer", "translate", "lead", "triage",
    }


def test_fallback_soul_used_when_soul_file_missing(
    proposals_db, runs_db, mempool, sandbox_root,
):
    """No dream_soul.md on disk → the LLM system prompt is the fallback."""
    tid = "green_tenant"
    # Intentionally do NOT create souls/dream_soul.md — the tenant's
    # root itself is also absent so ``_resolve_tenant_root`` returns None.

    send = _scripted_llm([_text_response("no findings")])

    result = asyncio.run(dream_agent.run_dream(
        tenant_id=tid,
        cc_pool=None,
        mempool=mempool,
        proposals_db=proposals_db,
        runs_db=runs_db,
        max_tool_turns=10,
        sandbox_root=sandbox_root,
        llm_send=send,
    ))

    assert result.status == "completed"
    first_call = send.calls[0]  # type: ignore[attr-defined]
    system = first_call["system"]
    assert system == _FALLBACK_DREAM_SOUL, (
        "With no soul file, the fallback constant must be the system prompt"
    )
    # And a fallback-marker sanity check so a future refactor of the
    # fallback content still triggers this assertion.
    assert "Dream Engine Agent" in system
    assert "Fallback template" in system


def test_context_includes_recent_memory_and_history(
    proposals_db, runs_db, mempool, sandbox_root,
):
    """The initial user message must include seeded memory + history."""
    tid = "sunny_tenant"
    # Seed 3 memory turns.
    mempool.record_turn(
        "conv_01", "user", "hi there", tenant_id=tid,
    )
    mempool.record_turn(
        "conv_01", "assistant", "Hello, how can I help?", tenant_id=tid,
    )
    mempool.record_turn(
        "conv_01", "user", "i want a refund", tenant_id=tid,
    )

    # Seed 2 historical proposals (one accepted, one rejected).
    for pid, status, title in (
        ("prop_hist_a", "accepted", "Tone adjustment rolled out"),
        ("prop_hist_b", "rejected", "Over-aggressive upsell prompt"),
    ):
        payload = {
            "id": pid,
            "tenant_id": tid,
            "category": "tone",
            "title": title,
            "suggestion": "adjust copy",
            "status": status,
        }
        proposals_db.execute(
            "INSERT INTO proposals "
            "(id, created_at, data, status, category, tenant_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (pid, "2026-04-20T00:00:00+00:00",
             json.dumps(payload), status, "tone", tid),
        )
    proposals_db.commit()

    send = _scripted_llm([_text_response("nothing to add")])

    asyncio.run(dream_agent.run_dream(
        tenant_id=tid,
        cc_pool=None,
        mempool=mempool,
        proposals_db=proposals_db,
        runs_db=runs_db,
        max_tool_turns=10,
        sandbox_root=sandbox_root,
        llm_send=send,
    ))

    initial_msg = send.calls[0]["messages"][0]["content"]  # type: ignore[attr-defined]
    # Memory turns — look for at least one seeded content fragment.
    assert "i want a refund" in initial_msg
    assert "Hello, how can I help?" in initial_msg
    # Historical proposals — titles should appear.
    assert "Tone adjustment rolled out" in initial_msg
    assert "Over-aggressive upsell prompt" in initial_msg
    # Dream config section — default risk_threshold marker.
    assert "risk_threshold" in initial_msg


# ── Extra guards the spec / red-line imply ─────────────────────────────────


def test_zero_max_tool_turns_yields_overrun_immediately(
    proposals_db, runs_db, mempool, sandbox_root,
):
    """``max_tool_turns=0`` is a defensible edge: first tool request trips cap.

    If the model tries to call any tool on the very first turn and the
    cap is zero, we record ``overrun`` without executing the tool. If
    the model does not call a tool, the run completes normally — tested
    implicitly by ``test_natural_termination_records_completed``.
    """
    send = _scripted_llm([
        _tool_use_response("kb_search", {"query": "x"}),
    ])

    result = asyncio.run(dream_agent.run_dream(
        tenant_id="acme",
        cc_pool=None,
        mempool=mempool,
        proposals_db=proposals_db,
        runs_db=runs_db,
        max_tool_turns=0,
        sandbox_root=sandbox_root,
        llm_send=send,
    ))

    assert result.status == "overrun"
    assert result.tool_calls == 0
    # The LLM was never called because the cap is checked first.
    assert len(send.calls) == 0  # type: ignore[attr-defined]


def test_tool_validation_error_becomes_tool_result_not_crash(
    proposals_db, runs_db, mempool, sandbox_root,
):
    """Invalid risk_level from the LLM must degrade to tool_result is_error.

    Previously the ``ValueError`` from ``emit_proposal`` would bubble;
    we now convert it to an ``is_error=True`` tool_result so the model
    can observe and retry within the turn budget.
    """
    bad_input = _emit_payload(risk_level="critical")  # not in VALID_RISK_LEVELS
    send = _scripted_llm([
        _tool_use_response("emit_proposal", bad_input, use_id="tu_bad"),
        _text_response("giving up"),
    ])

    result = asyncio.run(dream_agent.run_dream(
        tenant_id="acme",
        cc_pool=None,
        mempool=mempool,
        proposals_db=proposals_db,
        runs_db=runs_db,
        max_tool_turns=10,
        sandbox_root=sandbox_root,
        llm_send=send,
    ))

    assert result.status == "completed"
    assert result.tool_calls == 1
    assert result.proposals_emitted == 0  # invalid — nothing written
    rows = proposals_db.execute("SELECT * FROM proposals").fetchall()
    assert rows == []

    # And the second call must have seen an is_error tool_result.
    second_call = send.calls[1]  # type: ignore[attr-defined]
    blocks = second_call["messages"][-1]["content"]
    err_block = next(b for b in blocks if b["tool_use_id"] == "tu_bad")
    assert err_block.get("is_error") is True
    body = json.loads(err_block["content"])
    assert "error" in body
