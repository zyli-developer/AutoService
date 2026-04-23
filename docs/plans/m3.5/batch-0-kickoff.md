# batch-0 · D5 Dream LLM real-wire — Kickoff

> **Goal**: make the production Dream trigger path actually hit an LLM (per-tenant cinnox + master).
> **Duration**: Day 1 (2026-04-22) · 8-12h human / ~2-3h AI
> **Mode**: solo-opus. Isolated batch because cc_pool surface expansion has blast radius beyond Dream role.
> **Yellow flag**: CON-04 red-line — code-reviewer subagent APPROVED required before merge.

## Pre-checks

- [ ] M3 gate passed (`v1.2.0-mvp` shipped 2026-04-22; PR #74)
- [ ] Branch `dev-a` clean (`git status` shows only expected triage polish if any)
- [ ] `ANTHROPIC_API_KEY` present in env (for opt-in `pytest -m live` runs)
- [ ] Baseline regression green: `pytest tests/dream_agent tests/dream_runs tests/dream tests/api/test_dream_api.py`
- [ ] Read the source: [mini-sprint §1.4](../m3.5-mini-sprint.md#14-dream-engine-llm-real-wire-backend--promoted-2026-04-22)

## Task

| ID | Name | Mode | Est |
|---|---|---|---|
| T5S.14 | 🟡 D5 Dream LLM real-wire (T3B.5 + T4S.4b) | solo-opus | 8-12h + review |

## Scope breakdown (from mini-sprint §1.4)

1. **`cc_pool` tool-use surface (T3B.5 core)**
   - Expose `client.call_with_tools(system, messages, tools) -> Message` on acquired Dream role clients
   - Implementation hint: JSON-in/JSON-out only (tools are `emit_proposal` / `kb_search` / `list_souls`); thin Anthropic SDK wrapper bound to acquired client's key, not full CC tool-use delegation
   - Scope strictly to Dream role — customer/operator/triage paths unchanged

2. **`dream_agent` default `llm_send`** ([dream_agent.py:1117-1134](../../../autoservice/dream_agent.py#L1117-L1134))
   - Remove `RuntimeError: run_dream requires an explicit llm_send callable...` guard
   - When `llm_send is None`, build a closure from the acquired pool client
   - Tests continue to inject mocks via existing seam — **no signature change**

3. **`master_dream_agent` T4S.4b finish** ([master_dream_agent.py:102-121](../../../autoservice/master_dream_agent.py#L102-L121))
   - Replace the static `emit_proposal` call with a real tool-loop using the same `_run_agent_loop` helper
   - Use cross-tenant signals already gathered by `gather_platform_signals`

4. **`api_routes` wiring**
   - Drop `DREAM_DEV_STUB` branch from the default production path in `_run_and_mark`
   - Keep env gate so `DREAM_DEV_STUB=1` still skips the LLM (CI / offline dev fallback)
   - Document in `CLAUDE.md § Dev Auth Bypass` neighbourhood

5. **Tests**
   - Unit: VCR-recorded Anthropic responses for deterministic `run_dream` + `run_platform_dream` (no network at default `pytest`)
   - Integration: 1 live-API test per agent, `@pytest.mark.live` — skipped by default, opt-in via `pytest -m live`
   - Regression: all 102 existing dream tests must stay green

## Execution order

1. **TDD baseline**: write VCR cassette placeholders + integration test skeletons first (`tests/cc_pool/test_call_with_tools.py`, `tests/dream_agent/test_run_dream_llm_default.py`, `tests/dream_agent/test_master_dream_tool_loop.py`, `tests/dream_agent/test_live_llm.py` marked `live`).
2. **Implement cc_pool** `call_with_tools` thin wrapper. Record VCR fixture.
3. **Implement dream_agent** default `llm_send` closure. Use new VCR. Remove RuntimeError.
4. **Implement master_dream_agent** real tool loop. Record second VCR.
5. **Rewire api_routes** `_run_and_mark`. Keep `DREAM_DEV_STUB=1` env gate for offline.
6. **Run full suite** — mock + VCR. All green before requesting review.
7. **Opt-in live run** — `pytest -m live`. Cost ~$1-2 per full live sweep.
8. **Dispatch code-reviewer subagent** with the CON-04 checklist below.

## CON-04 code-reviewer checklist (YELLOW gate)

The 5-layer defence must remain unaltered:

1. **Signature lock** — `emit_proposal` signature unchanged (no new kwargs, no `status` parameter).
2. **`'draft'` hardcode** — every call site passes the literal string `'draft'`, not a variable.
3. **Value rejection** — if anyone attempts to pass a non-`'draft'` status, the function rejects (existing guard).
4. **Import cone** — `emit_proposal` is the ONLY write path for proposal creation. No new imports outside the allowed set.
5. **AST guardrail T4S.8** — `pytest tests/guardrails/test_ast_emit_proposal.py` stays green.

Additional D5-specific review:
- `cc_pool.client.call_with_tools` is NOT exposed on non-Dream role clients (customer/operator/triage)
- `DREAM_DEV_STUB` env gate removed from default path but still honoured when set (test both branches)
- VCR cassettes committed; live tests default-skipped (`@pytest.mark.live`)

Reviewer verdict: `APPROVED` / `APPROVED-WITH-FIXUP` / `CHANGES-REQUESTED`.

## Smoke test (batch gate)

```bash
# Mock + VCR sweep (mandatory green)
pytest tests/dream_agent tests/dream_runs tests/dream tests/api/test_dream_api.py tests/cc_pool

# AST guardrail
pytest tests/guardrails/test_ast_emit_proposal.py

# Live opt-in (at least one successful run before closing)
pytest -m live tests/dream_agent/test_live_llm.py

# Production trigger smoke (real LLM, DREAM_DEV_STUB unset)
curl -X POST http://localhost:8000/api/dream/trigger -H 'Content-Type: application/json' \
  -d '{"tenant_id":"cinnox"}'
# Expect: run row closes status=completed, tokens_in > 0, tokens_out > 0,
# emitted proposal.title does NOT start with '[dev stub]'

# Offline dev fallback (still works)
DREAM_DEV_STUB=1 pytest tests/api/test_dream_api.py::test_dev_stub_path
```

## Risks

- **Anthropic API cost at CI** — mitigated by `@pytest.mark.live` default-skip
- **First live cinnox run may surface soul-prompt quality issues** — budget 1-2h prompt iteration on `plugins/cinnox/skills/*/customer_soul.md`
- **cc_pool blast radius** — `call_with_tools` is a new surface; mitigate by scoping to Dream role only

## Closing

Per [CLAUDE.md § /autorun conventions](../../../CLAUDE.md) — at batch boundary:

1. Update [task-status.md](task-status.md): T5S.14 → `done` + reviewer verdict + commit hashes in session log.
2. Stage code + status together; commit: `feat(m3.5 batch-0): D5 dream LLM real-wire (T3B.5 cc_pool tool-use + T4S.4b master + per-tenant loop)` + reviewer approval in body.
3. Dispatch `batch-1` (D2 canary panel).
