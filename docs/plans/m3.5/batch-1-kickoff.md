# batch-1 · D2 Canary panel + 3-button Apply — Kickoff

> **Goal**: consolidate the M3 minimal Apply button (commit `2e50ac1` in [DreamTab.tsx](../../../frontend/packages/admin-portal/src/components/DreamTab.tsx)) into a full canary panel with progress bar + metric compare + rollback.
> **Duration**: Day 2 (2026-04-23) · 4h human / ~1h AI + review
> **Mode**: solo-yellow. Code-reviewer subagent APPROVED before Closing.

## Pre-checks

- [ ] batch-0 gate passed — D5 Dream LLM real-wire merged, `v1.2.1-dream-rc-d5` or similar tag if using incremental tags
- [ ] Frontend dev stack boots (`make run-web` + `pnpm dev` in `frontend/packages/admin-portal/`)
- [ ] Baseline `DreamTab.tsx` understood — the existing Apply button lives in the pending-proposals table; M3.5 removes it and replaces with canary-panel-scoped button

## Task

| ID | Name | Mode | Est |
|---|---|---|---|
| T5S.12 | 🟡 D2/U4 Canary panel w/ 3-button Apply | solo-yellow | 4h + review |

## Scope (from mini-sprint §1.3 + §5)

Build [canary-panel.tsx](../../../frontend/packages/admin-portal/src/components/dream/canary-panel.tsx) containing:

1. **Canary progress bar** — 5% → 25% → 100% stages; consumes `GET /api/canary/status`
2. **Advance / Rollback buttons** — `POST /api/canary/advance` and `POST /api/canary/rollback` with per-stage confirmation
3. **Metric compare panel** ([metric-compare.tsx](../../../frontend/packages/admin-portal/src/components/dream/metric-compare.tsx)) — CSAT + other metrics, pre/post canary
4. **3-button pattern** — `[Reject] [Approve] [🔒 Apply]`:
   - `Reject` / `Approve` via existing M3 APIs (already wired)
   - `Apply` enabled **only** when `proposal.status === 'accepted'`
   - `Apply` click → `POST /api/admin/proposals/{proposal_id}/apply` (T4S.3 endpoint, shipped in M3)
5. **Remove** the minimal Apply button from the pending-proposals table in `DreamTab.tsx` (single source of truth — must not ship both)

## Files

| Path | Action |
|---|---|
| `frontend/packages/admin-portal/src/components/dream/canary-panel.tsx` | new |
| `frontend/packages/admin-portal/src/components/dream/metric-compare.tsx` | new |
| `frontend/packages/admin-portal/src/__tests__/dream/canary-panel.test.tsx` | new |
| `frontend/packages/admin-portal/src/components/DreamTab.tsx` | edit — remove minimal Apply button, mount canary panel |

## Execution order

1. **TDD** — start with `canary-panel.test.tsx`: vitest spec covering
   - panel renders with `canary.stage = 5%` → advance button enabled
   - advance click → POST `/api/canary/advance` → stage = 25%
   - rollback click at any stage → POST `/api/canary/rollback` → stage = 0
   - Apply button **disabled** when `proposal.status === 'draft' | 'accepted_with_changes'`
   - Apply button **enabled** when `proposal.status === 'accepted'`
   - Apply click → POST `/api/admin/proposals/{id}/apply` (exclusively — no other status-mutating endpoint)
2. **Implement** canary-panel + metric-compare components. Re-use existing admin-portal primitives + api-client.
3. **Remove** minimal Apply button from DreamTab; mount canary panel in its place.
4. **Manual walkthrough** at `http://localhost:3000/admin/dream` — advance / rollback / apply cycle.
5. **Dispatch code-reviewer subagent** with the CON-04 checklist below.

## CON-04 code-reviewer checklist (YELLOW gate)

Reviewer must verify:

- **CON-04 §1 — single write path**: Apply button's click handler ONLY calls `/api/admin/proposals/{id}/apply`. It MUST NOT:
  - set `proposal.status` client-side
  - call any other mutation endpoint that writes `status`
  - bypass the existing server-side `status === 'accepted'` enable-gate
- **UX correctness**: 3-button pattern `[Reject] [Approve] [🔒 Apply]`; Apply disabled when `status != 'accepted'`; tooltip explains why
- **Migration correctness**: minimal Apply button at `DreamTab.tsx` pending-proposals table is REMOVED (not shipped alongside). Single source of truth.
- **Canary flow**: 5% → 25% → 100% advances via `/api/canary/advance`; rollback via `/api/canary/rollback`; stage state sourced from `/api/canary/status`.
- **No regressions**: other DreamTab surfaces (status card, 最近运行 table) unchanged.

Reviewer verdict: `APPROVED` / `APPROVED-WITH-FIXUP` / `CHANGES-REQUESTED`.

## Smoke test (batch gate)

```bash
# Vitest
pnpm -F @autoservice/admin-portal test -- canary-panel metric-compare
pnpm -F @autoservice/admin-portal test -- DreamTab   # regression — ensure Apply button removal didn't break status card / runs table

# Manual walkthrough
# 1. Navigate /admin/dream → select an accepted proposal → canary panel appears
# 2. Advance 5% → 25% → 100%; verify progress bar + stage label
# 3. Rollback at 25% → stage resets to 0
# 4. Apply button enabled ONLY when proposal.status = 'accepted' (try with draft/rejected to verify disable)
# 5. Apply click → network tab shows POST /api/admin/proposals/{id}/apply ONLY (no other status mutation)
# 6. Verify metric-compare panel shows CSAT pre/post numbers
```

## Closing

1. Update [task-status.md](task-status.md): T5S.12 → `done` + reviewer verdict.
2. Commit: `feat(m3.5 batch-1): D2/U4 canary panel w/ 3-button Apply; consolidate Apply button into canary flow` + reviewer approval in body.
3. Dispatch `batch-2` (M3.5 Dream-first gate).
