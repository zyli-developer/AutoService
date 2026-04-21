# Batch M3-0 Kickoff · Contract Freeze

**Batch**: batch-0 · **Milestone**: M3-0 · **Target**: 2026-04-22 EOD · **Duration**: 4h

## Pre-checks
- [ ] M2 gate passed (v1.1.x tag on `dev`)
- [ ] docs/plans/m3/ artifacts reviewed (prd-structure, gap-analysis, tasks.yaml, execution-plan)
- [ ] 5 design specs read: [E1](../../superpowers/specs/2026-04-21-m3-e1-identity-rbac-design.md) · [E3](../../superpowers/specs/2026-04-21-m3-e3-triage-enhancement-design.md) · [E4](../../superpowers/specs/2026-04-21-m3-e4-compliance-country-filter-design.md) · [E5](../../superpowers/specs/2026-04-21-m3-e5-dream-extension-design.md) · [E6](../../superpowers/specs/2026-04-21-m3-e6-ops-gc-playwright-design.md)
- [ ] Default OQ values confirmed in [tasks.yaml §meta.default_oq_values](tasks.yaml)
- [ ] `mkdir docs/contracts/m3/`

## Tasks (4, parallel)

| ID | Name | Owner | Mode | Deliverable |
|---|---|---|---|---|
| T0S.1 | E1 auth/cookie/RBAC matrix contract | Dev1 | solo | `docs/contracts/m3/e1-auth-rbac.md` |
| T0S.2 | E3 SLA/handoff/classify_intent contract | subagent-1 | parallel | `docs/contracts/m3/e3-triage.md` |
| T0S.3 | E4 country registry contract | subagent-2 | parallel | `docs/contracts/m3/e4-compliance.md` |
| T0S.4 | E5 apply_proposal + CON-04 contract 🔒 | Dev1 | solo, code-reviewer required | `docs/contracts/m3/e5-dream.md` |

Total: 4 contract docs, each ~1-2 pages.

## Execution Order

1. Orchestrator starts T0S.1 solo AND dispatches subagent-1 for T0S.2, subagent-2 for T0S.3 (3 parallel lanes)
2. When T0S.1 + T0S.2 + T0S.3 done: orchestrator does T0S.4 solo (security-critical, needs full attention)
3. T0S.4 goes through code-reviewer subagent before commit

## Decision Points (apply defaults from [tasks.yaml](tasks.yaml) unless overruled)

- OQ-E1-1 admin cookie name: `auth_session` (keep M2 existing)
- OQ-E1-3 DB path: `auth.db` (keep M2 existing)
- OQ-E3-1 per-tenant metrics: `pool_wait_ms` + `first_reply_ms` only
- OQ-E4-1 empty `countries[]`: fail-closed + warning
- OQ-E5-1 apply handler: `mark_applied` only (audit-first)

## Contract Content Checklist (per doc)

Each contract doc must include:
- [ ] Reference to design spec section(s)
- [ ] Precise interface/schema (function signatures, SQL DDL, JSON shapes)
- [ ] Enforcement strategy (CON-04 for E5)
- [ ] Version string (v1.0 initial)
- [ ] "Don't do" list (E5: no status kwarg on emit_proposal; E4: no hot-reload)

## Gate

- [ ] 4 contract docs committed under `docs/contracts/m3/`
- [ ] T0S.4 code-reviewer APPROVED (pasted in commit body)
- [ ] task-status.md updated: 4 T0S.* rows → ✅ + batch-0 row → ✅
- [ ] Session Log: "batch-0 done · next: batch-1 T1S.1"
- [ ] Commit: `chore(m3): batch-0 contract freeze complete`

## Next

→ `/prd2impl:skill-8-batch-dispatch batch-1` (E1 Foundation starts with T1S.1 schema)
