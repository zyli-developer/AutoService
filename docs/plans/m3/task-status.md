# M3 Task Status · Authoritative Truth

> **IMPORTANT**: This file is the authoritative record of M3 progress. Per [CLAUDE.md §/autorun conventions](../../../CLAUDE.md#L120), update this file at **every batch boundary** (same commit as code, or trailing `chore(m3):` commit). TodoWrite is NOT authoritative.

**Initialized**: 2026-04-21 · [prd2impl:skill-4-plan-schedule]
**Plan**: [execution-plan.md](execution-plan.md) · **Tasks**: [tasks.yaml](tasks.yaml)
**Scope**: 39 tasks across 7 phases · Epic E2 DEFERRED_M4

---

## Overall Progress

| Metric | Value |
|---|---|
| Total tasks | 39 |
| ✅ Completed | 7 |
| 🏃 In progress | 0 |
| ⏸️ Blocked | 0 |
| ⏳ Pending | 32 |
| Progress | 18% |
| Current milestone | M3-0 ready to start (M2 gate passed 2026-04-21) |
| Current batch | batch-0 ready (pre-check satisfied) |

---

## Phase Progress

| Phase | Name | Tasks | Done | Progress |
|---|---|---|---|---|
| P0 | Contract Freeze | 4 | 4 | 100% ✅ |
| P1 | E1 P0 Foundation | 5 | 3 | 60% |
| P2 | E1 P1 + Parallel Greens | 8 | 0 | 0% |
| P3 | E3 Tail + E1 Close | 6 | 0 | 0% |
| P4 | E5/E6/E4/E3 Remainders | 8 | 0 | 0% |
| P5 | Playwright (deferrable M3.5) | 5 | 0 | 0% |
| P6 | M3 Gate | 3 | 0 | 0% |

---

## Batch Progress

| Batch | Milestone | Tasks | Status |
|---|---|---|---|
| batch-0 | M3-0 | T0S.1, T0S.2, T0S.3, T0S.4 | ✅ done 2026-04-21 (gate: 4 contracts committed; T0S.4 reviewer APPROVED after v1.1 revision) |
| batch-1 | M3-1 | T1S.1 | ✅ done 2026-04-21 (14 tests green; full auth regression 65/65) |
| batch-2 | M3-1 | T1S.2, T1S.4 | ✅ done 2026-04-21 (43 new tests green; 108/108 auth regression) |
| batch-3 | M3-1 | T1S.3, T1S.5 | ⏳ pending |
| batch-4 | M3-2 | T2S.1, T2S.3, T2S.6, T2S.8 | ⏳ pending |
| batch-5 | M3-2 | T2S.2, T2S.4, T2S.7 | ⏳ pending |
| batch-6 | M3-2 | T2S.5 | ⏳ pending |
| batch-7 | M3-3 | T3S.1, T3S.3, T4S.7 | ⏳ pending |
| batch-8 | M3-3 | T3S.2, T3S.4, T4S.1🔒, T4S.2 | ⏳ pending |
| batch-9 | M3-3 | T3S.5, T3S.6, T4S.3, T4S.8🔒 | ⏳ pending |
| batch-10 | M3-3 | T4S.4, T4S.5, T4S.6 | ⏳ pending |
| batch-11 | M3-4 | T5S.1 | ⏳ pending |
| batch-12 | M3-4 | T5S.2, T5S.3, T5S.4, T5S.5 | ⏳ pending |
| batch-13 | gate | T6S.1 | ⏳ pending |
| batch-14 | gate | T6S.2, T6S.3 | ⏳ pending |

---

## Session Log

_Append at each batch closure. Format: date · batch · summary · next._

| Date | Batch | Summary | Next Candidate |
|---|---|---|---|
| 2026-04-21 | — | M3 planning artifacts generated (prd-structure, gap-analysis, 5 design specs, tasks.yaml, execution-plan). Epic E2 descoped to M4+ per PRD §8.1 Errata. | Await M2 gate → kickoff batch-0 |
| 2026-04-21 | — | M2 gate passed (7/7/1-skip/0-fail; evidence in e2e-evidence/fork-sim-m2/). project.yaml.plans_dir switched m2→m3. M3 status → ready. | kickoff batch-0 (user decision pending: direct dispatch / autorun / other) |
| 2026-04-21 | batch-0 | M3-0 Contract Freeze done. 4 contracts under docs/contracts/m3/ (e1-auth-rbac.md · e3-triage.md · e4-compliance.md · e5-dream.md v1.1). T0S.4 E5/🔒 CON-04 reviewer: CHANGES_REQUESTED v1.0 with 4 Critical findings → revised to v1.1 (import cone + value reject, race-safe conditional UPDATE, implemented→applied rename + migration, AST audit-write guard) → APPROVED. CON-04 now 5-layer defense (was 4). | batch-1 T1S.1 operators schema (first E1 code task) |
| 2026-04-21 | batch-1 | T1S.1 done: autoservice/operators.py schema (operators + operator_sessions tables) + migrate_login_tokens_add_role. 14/14 new tests green; 65/65 full auth regression green (M2 51 + M3 T1S.1 14). Contract deviation: created autoservice/operators.py as sibling module rather than autoservice/auth/operators_schema.py (avoid auth.py package refactor). | batch-2: T1S.2 operator login + T1S.4 CRUD (parallel) |
| 2026-04-21 | batch-2 | T1S.2 + T1S.4 done. operators.py extended with 14 helpers (CRUD + sessions + magic-link role-gated consume). operator_routes.py new (9 endpoints: request-login/verify/logout/me/list/get/create/patch/delete) mounted via api_routes.py bottom. 43 new tests (21 helper + 22 route) all green; 108/108 auth regression. Magic-link role gate proven: admin token rejected for operator-verify. Anti-enumeration: unknown operator returns same shape. T1S.4 disable-operator path also revokes all sessions (defense-in-depth beyond FK cascade). | batch-3: T1S.3 WS cookie 🟡 + T1S.5 invite |

---

## Task Detail (grouped by phase)

### P0 · Contract Freeze (4 tasks)

| ID | Name | Type | Effort | Depends | Status | Owner | Artifacts |
|---|---|---|---|---|---|---|---|
| T0S.1 | E1 contracts (auth + RBAC) | 🟢 | S | — | ✅ | Dev1 | [docs/contracts/m3/e1-auth-rbac.md](../../contracts/m3/e1-auth-rbac.md) |
| T0S.2 | E3 contracts (SLA + handoff + classify_intent) | 🟢 | S | — | ✅ | Dev1 | [docs/contracts/m3/e3-triage.md](../../contracts/m3/e3-triage.md) |
| T0S.3 | E4 contract (country registry) | 🟢 | S | — | ✅ | Dev1 | [docs/contracts/m3/e4-compliance.md](../../contracts/m3/e4-compliance.md) |
| T0S.4 | E5 contract (apply_proposal + CON-04) | 🟡 | S | — | ✅ | Dev1 + superpowers:code-reviewer (APPROVED v1.1 after 4 Critical findings in v1.0 → revise) | [docs/contracts/m3/e5-dream.md](../../contracts/m3/e5-dream.md) v1.1 |

### P1 · E1 P0 Foundation (5 tasks)

| ID | Name | Type | Effort | Depends | Status | Owner | Artifacts |
|---|---|---|---|---|---|---|---|
| T1S.1 | operators schema | 🟢 | M | T0S.1 | ✅ | Dev1 | [autoservice/operators.py](../../../autoservice/operators.py) · [tests/auth/test_operators_schema.py](../../../tests/auth/test_operators_schema.py) |
| T1S.2 | operator HTTP login + cookie | 🟢 | M | T1S.1 | ✅ | Dev1 | [autoservice/operators.py](../../../autoservice/operators.py) · [autoservice/operator_routes.py](../../../autoservice/operator_routes.py) · [tests/auth/test_operators_helpers.py](../../../tests/auth/test_operators_helpers.py) (21) · [tests/auth/test_operator_routes.py](../../../tests/auth/test_operator_routes.py) (22) |
| T1S.3 | WS handshake cookie validation | 🟡 | M | T1S.2 | ⏳ | — | — |
| T1S.4 | operator CRUD API | 🟢 | S | T1S.1 | ✅ | Dev1 | routes in [operator_routes.py](../../../autoservice/operator_routes.py) · tests in [test_operator_routes.py](../../../tests/auth/test_operator_routes.py) §CRUD |
| T1S.5 | operator invite (magic-link role ext) | 🟢 | M | T1S.2 | ⏳ | — | — |

### P2 · E1 P1 + Parallel Greens (8 tasks)

| ID | Name | Type | Effort | Depends | Status | Owner | Artifacts |
|---|---|---|---|---|---|---|---|
| T2S.1 | RBAC matrix + decorator | 🟡 | M | T1S.2 | ⏳ | — | — |
| T2S.2 | multi-admin CRUD | 🟢 | S | T2S.1 | ⏳ | — | — |
| T2S.3 | pool metrics | 🟢 | S | T0S.2 | ⏳ | — | — |
| T2S.4 | per-tenant SLA threshold | 🟢 | M | T2S.3 | ⏳ | — | — |
| T2S.5 | operator-WS alert push | 🟡 | S | T2S.4, T1S.3 | ⏳ | — | — |
| T2S.6 | country registry | 🟢 | S | T0S.3 | ⏳ | — | — |
| T2S.7 | scan(countries=list) | 🟢 | S | T2S.6 | ⏳ | — | — |
| T2S.8 | master dream skeleton | 🟡 | M | T0S.4 | ⏳ | — | — |

### P3 · E3 Tail + E1 Close (6 tasks)

| ID | Name | Type | Effort | Depends | Status | Owner | Artifacts |
|---|---|---|---|---|---|---|---|
| T3S.1 | handoff parser | 🟡 | S | T0S.2 | ⏳ | — | — |
| T3S.2 | role-switch orchestrator | 🟡 | M | T3S.1, T4S.7 | ⏳ | — | — |
| T3S.3 | classify_intent DB | 🟢 | M | T0S.2 | ⏳ | — | — |
| T3S.4 | classify_intent CRUD + hot-reload | 🟢 | M | T3S.3 | ⏳ | — | — |
| T3S.5 | keyword editor UI | 🟢 | M | T3S.4 | ⏳ | — | — |
| T3S.6 | admin-to-admin invite (E1.6) | 🟢 | S | T2S.1, T1S.5 | ⏳ | — | — |

### P4 · E5/E6/E4/E3 Remainders (8 tasks)

| ID | Name | Type | Effort | Depends | Status | Owner | Artifacts |
|---|---|---|---|---|---|---|---|
| T4S.1 | apply_proposal 🔒 CON-04 | 🟡 | M | T0S.4 | ⏳ | — | — |
| T4S.2 | audit table + state machine | 🟢 | S | T0S.4 | ⏳ | — | — |
| T4S.3 | Apply button + endpoint | 🟡 | S | T4S.1, T4S.2 | ⏳ | — | — |
| T4S.4 | platform dream signals | 🟡 | M | T2S.8, T2S.4 | ⏳ | — | — |
| T4S.5 | sandbox GC + TTL | 🟢 | M | — | ⏳ | — | — |
| T4S.6 | JP/SG/AU rulesets | 🟢 | S | T2S.7 | ⏳ | — | — |
| T4S.7 | history compressor | 🟡 | M | T0S.2 | ⏳ | — | — |
| T4S.8 | CON-04 AST guardrail 🔒 | 🟡 | S | T4S.1, T4S.2 | ⏳ | — | — |

### P5 · Playwright (5 tasks — may defer M3.5)

| ID | Name | Type | Effort | Depends | Status | Owner | Artifacts |
|---|---|---|---|---|---|---|---|
| T5S.1 | Playwright scaffold | 🟢 | M | T1S.2, T1S.3 | ⏳ | — | — |
| T5S.2 | Epic1 Onboarding | 🟢 | M | T5S.1 | ⏳ | — | — |
| T5S.3 | Epic2 Realtime-chat | 🟢 | L | T5S.1 | ⏳ | — | — |
| T5S.4 | Epic3 Dashboards | 🟢 | M | T5S.1 | ⏳ | — | — |
| T5S.5 | Epic4 Dream-learning | 🟢 | M | T5S.1, T4S.3 | ⏳ | — | — |

### P6 · M3 Gate (3 tasks)

| ID | Name | Type | Effort | Depends | Status | Owner | Artifacts |
|---|---|---|---|---|---|---|---|
| T6S.1 | M2 regression (NFR-04) | 🟢 | S | T3S.6, T4S.8, T2S.5 | ⏳ | — | — |
| T6S.2 | M3 smoke test | 🟢 | M | T6S.1 | ⏳ | — | — |
| T6S.3 | Tag v1.2.0-mvp | 🟢 | S | T6S.2 | ⏳ | — | — |

---

## Status Legend

- ⏳ pending · ⏸️ blocked · 🏃 in_progress · ✅ done · ❌ failed
- 🟢 Green (AI-independent) · 🟡 Yellow (code-reviewer required) · 🔴 Red (none in M3)
- 🔒 CON-04 security-critical
- Effort: S <2h · M 2-8h · L >8h

---

## Update Rules

1. **Batch boundary**: Update "Batch Progress" table + "Session Log" entry + per-task status + artifacts path
2. **Milestone gate**: Update "Overall Progress" percentages + add gate evidence link to Session Log
3. **Task completion**: Update task-row status + add artifact paths (link to .artifacts/ if produced)
4. **Blocker**: Set task to ⏸️ + session-log a one-line reason

This file is committed alongside the code change that advanced its state. Never batch status updates — commit each batch's state change in the same commit or a trailing `chore(m3):` commit in the same session.
