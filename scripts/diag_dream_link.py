"""Dream link diagnostic — one-shot.

Runs two isolated probes and prints raw results:

1. STUB probe: calls ``api_routes._run_dev_stub_dream`` against temp sqlite DBs.
   Confirms write path (proposals + dream_runs schema) and counts rows.

2. LIVE probe: spins up a minimal dream-role CC client through ``cc_pool``
   and invokes ``call_with_tools`` once with the master_dream system prompt
   and a LEADING user message that should make any sane model emit an
   ``emit_proposal`` tool_use.  Prints content blocks, stop_reason, usage.

Safe to run while the web gateway is up — uses a separate pool config and
separate proposals.db under a tmp dir. No prod rows created.
"""
from __future__ import annotations

import asyncio
import io
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from autoservice import dream_runs
from autoservice.proposal_pipeline import apply_schema as _proposals_apply_schema


SYS_PROMPT = (
    "You are the platform-level Dream agent. You observe cross-tenant "
    "aggregate signals and propose improvements.\n"
    "\n"
    "Available tools:\n"
    "- emit_proposal: file a draft finding. Use category='platform_level'.\n"
    "- kb_search / list_souls: inspect KB or soul snippets.\n"
    "\n"
    "When you have a finding, call emit_proposal once per finding."
)

# A: leading user message with a concrete finding — wire-up probe.  If the
# tool_use pipe works at all this *should* produce an emit_proposal block.
USER_MSG_LEADING = (
    "## Platform-level dream — cross-tenant observation\n"
    "\n"
    "- tenant_count: 3\n"
    "- total_proposal_count: 12\n"
    "- finding: AGGREGATE CSAT DROPPED 15% IN THE LAST 24H ACROSS ALL TENANTS.\n"
    "- finding: POOL EXHAUSTION DETECTED on dream pool 4 times in the last hour.\n"
    "\n"
    "Call emit_proposal once for the CSAT drop finding — title='aggregate "
    "csat drop 15%', category='platform_level', risk_level='medium', "
    "target_role='customer', description='<your description>', "
    "suggestion='<your suggestion>', evidence='<your evidence>'."
)

# B: production-shaped user message — only the aggregate numbers that
# gather_platform_signals() actually surfaces today.  No concrete finding.
# This mirrors what _master runs on the gateway are seeing.
USER_MSG_PRODUCTION = (
    "## Platform-level dream — cross-tenant observation\n"
    "\n"
    "The following signals summarise the current platform state.\n"
    "- tenant_count: 3\n"
    "- total_proposal_count: 12\n"
    "- pool_metrics_attached: yes\n"
    "- snapshot_ts_ms: 1745430000000\n"
    "\n"
    "Observe these signals. If they suggest a platform-wide pattern "
    "(aggregate CSAT drop, cross-tenant KB gap, SLA breach trend, "
    "pool exhaustion), call `emit_proposal` with "
    "`category='platform_level'` and a descriptive title + evidence. "
    "Otherwise respond with a brief summary and stop."
)

TOOL_SCHEMAS = [
    {
        "name": "emit_proposal",
        "description": "File a draft proposal. All proposals persist with status='draft' — admin review is mandatory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "suggestion": {"type": "string"},
                "evidence": {"type": "string"},
                "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
                "target_role": {"type": "string"},
                "category": {"type": "string"},
            },
            "required": ["title", "category", "risk_level"],
        },
    },
]


async def probe_stub() -> None:
    from autoservice import api_routes
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        proposals_path = td_path / "proposals.db"
        runs_path = td_path / "dream_runs.db"
        pconn = sqlite3.connect(str(proposals_path))
        pconn.row_factory = sqlite3.Row
        _proposals_apply_schema(pconn)
        rconn = dream_runs.open_connection(runs_path)
        try:
            api_routes.DREAM_DEV_STUB_DELAY_SEC = 0
            await api_routes._run_dev_stub_dream("_master", pconn, rconn)
            prop_count = pconn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
            rows = rconn.execute(
                "SELECT id, status, proposals_emitted, tool_calls FROM dream_runs"
            ).fetchall()
            print(f"[STUB] proposals written = {prop_count}")
            for r in rows:
                print(f"[STUB] run row: id={r[0]!r} status={r[1]} "
                      f"proposals={r[2]} tool_calls={r[3]}")
        finally:
            pconn.close()
            rconn.close()


async def probe_live() -> None:
    from autoservice import cc_pool
    from autoservice.dream_tools_mcp import build_dream_tools_mcp_server

    pool_cfg = cc_pool.PoolConfig(
        cwd=str(REPO),
        min_size=0,
        max_size=1,
        permission_mode="bypassPermissions",
    )
    # Respect the local dream_model knob if present (claude-opus-4-7 in our config).
    try:
        loaded = cc_pool.load_pool_config(str(REPO))
        for k in ("model", "slow_model", "dream_model", "cli_path"):
            v = getattr(loaded, k, None)
            if v:
                setattr(pool_cfg, k, v)
    except Exception as exc:  # noqa: BLE001
        print(f"[LIVE] warn: load_pool_config failed: {exc}")

    # Override the auto-wired MCP server with one pointed at a tmp
    # proposals DB so we don't touch the production table.
    td = tempfile.mkdtemp(prefix="diag_dream_")
    proposals_path = Path(td) / "proposals.db"
    pconn_seed = sqlite3.connect(str(proposals_path))
    _proposals_apply_schema(pconn_seed)
    pconn_seed.close()
    dream_server = build_dream_tools_mcp_server(
        tenant_id="_master",
        proposals_db_path=proposals_path,
    )
    print(f"[LIVE] temp proposals DB: {proposals_path}")

    client = await cc_pool.create_cc_client(
        pool_cfg,
        role="dream",
        tenant_id="_master",
        mcp_servers={"autoservice_dream_tools": dream_server},
    )

    async def _one_turn(label: str, user_msg: str) -> None:
        print(f"\n[LIVE:{label}] sending turn...")
        resp = await client.call_with_tools(
            system=SYS_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
            tools=TOOL_SCHEMAS,
        )
        blocks = resp.get("content", [])
        print(f"[LIVE:{label}] stop_reason = {resp.get('stop_reason')!r}")
        print(f"[LIVE:{label}] usage      = {resp.get('usage')}")
        print(f"[LIVE:{label}] block count = {len(blocks)}  "
              f"({sum(1 for b in blocks if b.get('type')=='tool_use')} tool_use)")
        for i, b in enumerate(blocks):
            btype = b.get("type")
            if btype == "tool_use":
                print(f"  [{i}] tool_use name={b.get('name')!r} "
                      f"input_keys={list((b.get('input') or {}).keys())}")
            elif btype == "text":
                text = (b.get("text") or "").strip()
                preview = text[:400].replace("\n", " | ")
                print(f"  [{i}] text[{len(text)}ch]: {preview}")
            else:
                print(f"  [{i}] type={btype!r} raw={b!r}")

    try:
        print("[LIVE] dream client connected (MCP autoservice_dream_tools wired)")
        await _one_turn("LEADING", USER_MSG_LEADING)
        await _one_turn("PRODUCTION", USER_MSG_PRODUCTION)

        # Check what actually landed in the temp proposals DB — this is
        # the single question that matters: did the MCP handler fire?
        pconn = sqlite3.connect(str(proposals_path))
        try:
            rows = pconn.execute(
                "SELECT id, tenant_id, category, status, "
                "json_extract(data,'$.title') AS title "
                "FROM proposals"
            ).fetchall()
        finally:
            pconn.close()
        print(f"\n[LIVE] proposals landed = {len(rows)}")
        for r in rows:
            print(f"  row: id={r[0]!r} tenant={r[1]!r} "
                  f"category={r[2]!r} status={r[3]!r} title={r[4]!r}")
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def main() -> None:
    print("=== STUB probe ===")
    await probe_stub()
    print()
    print("=== LIVE probe ===")
    await probe_live()


if __name__ == "__main__":
    asyncio.run(main())
