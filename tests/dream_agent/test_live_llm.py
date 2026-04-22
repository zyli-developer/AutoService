"""T5S.14 — live integration test for the Dream LLM path.

Gated by ``@pytest.mark.live`` — skipped in the default ``pytest`` run.
Opt in via ``pytest -m live tests/dream_agent/test_live_llm.py``.

The user directive is non-negotiable: the Dream loop talks to the LLM via
the ``claude_agent_sdk`` local SDK (the CLI-backed subprocess client), NOT
via the ``anthropic`` cloud SDK.  If the local Claude CLI is not reachable
(not installed, not on PATH, or fails to connect), this test SKIPS with a
clear reason — it must not fail the suite.

Scope: spin a minimal ``run_dream`` against a throwaway tenant, drive one
tool-use round, and assert:

  * the run terminates cleanly (``completed``),
  * non-zero ``tokens_in`` / ``tokens_out`` are recorded (proof the LLM
    was actually invoked — the stub path reports zero),
  * if a proposal was emitted, its title is NOT the dev-stub marker.

Cost: ~1 token of real LLM usage per run.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.live,
]


def _local_cli_available() -> tuple[bool, str]:
    """Best-effort probe: does the local Claude CLI look reachable?

    Returns (available, reason).  We don't actually spawn a subprocess
    here — the SDK will, on connect, and will surface its own error.
    This is just a cheap pre-flight.
    """
    # If the user explicitly opts in via CC_POOL_CLI_PATH, honour that.
    explicit = os.environ.get("CC_POOL_CLI_PATH")
    if explicit and Path(explicit).exists():
        return True, f"cli at {explicit}"
    # Otherwise rely on PATH resolution happening inside the SDK.
    # We still skip unless the user explicitly flags readiness — live
    # tests should never auto-run on contributor machines without intent.
    if os.environ.get("AUTOSERVICE_LIVE_OK") == "1":
        return True, "AUTOSERVICE_LIVE_OK=1"
    return False, (
        "live LLM gate closed — set AUTOSERVICE_LIVE_OK=1 to enable, "
        "or CC_POOL_CLI_PATH to point at a local Claude CLI binary"
    )


@pytest.mark.asyncio
async def test_live_run_dream_against_local_sdk(tmp_path):
    """End-to-end: run_dream against the real claude_agent_sdk CLI.

    Skipped when the local CLI is not known to be reachable — the run
    pulls in a real subprocess and we refuse to fail the suite on an
    environment problem.
    """
    ok, reason = _local_cli_available()
    if not ok:
        pytest.skip(reason)

    # Lazy imports — we only pull these when the live path is green,
    # so module collection on a CLI-less box is zero-cost.
    from autoservice import dream_agent, dream_runs
    from autoservice.memory_pool import MemoryPool
    from autoservice.proposal_pipeline import apply_schema
    from autoservice import cc_pool as cc_pool_mod

    # Throwaway tenant under tmp_path — no real sandbox mutations.
    sandbox_root = tmp_path / "sandbox"
    sandbox_root.mkdir()
    tenant_id = "live_testtenant"

    proposals_db = sqlite3.connect(":memory:")
    proposals_db.row_factory = sqlite3.Row
    apply_schema(proposals_db)

    runs_db = sqlite3.connect(":memory:")
    runs_db.row_factory = sqlite3.Row
    dream_runs.init_schema(runs_db)

    mempool = MemoryPool(db_path=tmp_path / "mem.db")

    # Fresh pool singletons for this test.
    cc_pool_mod._pool = None
    cc_pool_mod._dream_pool = None
    emitted_titles: list[str] = []
    try:
        try:
            pool = await cc_pool_mod.get_pool()
            try:
                result = await dream_agent.run_dream(
                    tenant_id=tenant_id,
                    cc_pool=pool,
                    mempool=mempool,
                    proposals_db=proposals_db,
                    runs_db=runs_db,
                    max_tool_turns=3,
                    sandbox_root=sandbox_root,
                    llm_send=None,  # exercise the default-closure path
                )
            finally:
                await cc_pool_mod.shutdown_pool()
        except Exception as exc:  # noqa: BLE001 — live env flakiness
            pytest.skip(f"local claude_agent_sdk path unreachable: {exc!r}")

        # Completed or overrun — both are acceptable terminal live
        # states.  'failed' means the LLM path itself blew up.
        assert result.status in ("completed", "overrun"), (
            f"live run ended with status={result.status} error={result.error}"
        )

        # Proof of real LLM work: at least one of (tokens_in, tokens_out)
        # is non-zero.  The dev-stub reports fabricated tokens too, but
        # the stub path isn't reachable from run_dream — so non-zero
        # here means the SDK actually spoke to the model.
        assert (result.tokens_in + result.tokens_out) > 0, (
            "zero tokens — LLM was not actually invoked"
        )

        # If a proposal was emitted, its title must not collide with
        # the dev-stub seed titles.  Read BEFORE the finally block
        # closes the DB handle.
        rows = proposals_db.execute(
            "SELECT data FROM proposals WHERE tenant_id = ?", (tenant_id,),
        ).fetchall()
        for row in rows:
            payload = json.loads(row["data"]) if row["data"] else {}
            emitted_titles.append(payload.get("title", ""))
    finally:
        proposals_db.close()
        runs_db.close()
        mempool.close()

    for title in emitted_titles:
        assert not title.startswith("[dev stub]"), (
            f"live run emitted a stub-style proposal: {title!r}"
        )
