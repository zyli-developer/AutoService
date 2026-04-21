# Batch M3-2 Kickoff · P2 Parallel Greens

**Batches**: batch-4, batch-5, batch-6 · **Milestone**: M3-2 · **Target**: 2026-04-26 EOD · **Duration**: ~17h

## Pre-checks (M3-1 gate)
- [ ] batch-3 gate passed; operator login + WS validation + invite e2e
- [ ] M2 regression still green
- [ ] T0S.2 / T0S.3 / T0S.4 contracts committed

---

## batch-4 · P2 Parallel Starters (8h, 3+1 lanes)

| ID | Name | Owner | Mode | Type |
|---|---|---|---|---|
| T2S.1 | RBAC matrix + decorator | Dev1 | solo + code-reviewer | 🟡 |
| T2S.3 | pool metrics on AsyncPool | subagent-1 | parallel | 🟢 |
| T2S.6 | country registry + validator | subagent-2 | parallel | 🟢 |
| T2S.8 | master dream skeleton + scheduler routing | Dev1 | solo_after_subagents + code-reviewer | 🟡 |

**Execution**: Orchestrator dispatches subagent-1 and subagent-2 immediately, does T2S.1 in parallel. After subagents return, does T2S.8.

**Yellow review focus**:
- T2S.1: NFR-02 P95<5ms benchmark verified (frozenset + request.state cache confirmed in impl)
- T2S.8: master_dream_agent correctly routes from DreamScheduler; emit_proposal signature lock intact (CON-04)

**Gate**: RBAC benchmark green · pool emits metrics · country registry rejects invalid codes · _master scheduler path works and produces `platform_level` draft proposal

---

## batch-5 · P2 Dependent Layer (6h, 3 lanes)

| ID | Name | Owner | Mode |
|---|---|---|---|
| T2S.2 | multi-admin CRUD (E1.5) | Dev1 | solo |
| T2S.4 | per-tenant SLA threshold | subagent-1 | parallel |
| T2S.7 | scan(countries=list) + deprecate region_filter | subagent-2 | parallel |

**Gate**: 2 admins on 1 tenant e2e · threshold boundary test · multi-region scan returns correct rules · `region_filter` kwarg marked @deprecated (not removed)

---

## batch-6 · Operator Alert Push 🟡 (3h, solo)

| ID | Name | Owner | Type |
|---|---|---|---|
| T2S.5 | operator-WS alert push | Dev1 + code-reviewer | 🟡 |

**Yellow review focus**: parallel push path to `_operator_connections` is tenant-scope filtered; no cross-tenant alert leak; reuses existing admin-push pattern from web_gateway.py:285-326.

**Gate (M3-2 milestone)**:
- [ ] 8 P2 tasks ✅
- [ ] NFR-02 RBAC P95 <5ms benchmark met
- [ ] Pool metrics + operator-WS alert e2e: breach → alert on correct operator WS only
- [ ] Master dream emits platform_level proposal with `status='draft'`
- [ ] M2 regression still green
- [ ] Smoke: `pytest tests/auth/test_rbac_matrix.py tests/auth/test_rbac_perf.py tests/sla/ tests/compliance/test_country_registry.py -v`

## Risks

- **T2S.1 RBAC P95 budget**: if benchmark fails, must iterate on cache strategy before Closing
- **T2S.8 master dream**: new cross-tenant code; review for privacy boundary (no tenant A data leak to tenant B dream context)

## Next

→ `/prd2impl:skill-10-smoke-test M3-2`
→ `/prd2impl:skill-8-batch-dispatch batch-7`
