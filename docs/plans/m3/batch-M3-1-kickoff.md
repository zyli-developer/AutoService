# Batch M3-1 Kickoff · E1 Auth Foundation

**Batches**: batch-1, batch-2, batch-3 · **Milestone**: M3-1 · **Target**: 2026-04-24 EOD · **Duration**: ~15h

## Pre-checks (M3-0 gate)
- [ ] batch-0 gate passed (4 contracts committed)
- [ ] T0S.1 E1 contract frozen
- [ ] `.autoservice/database/auth.db` exists and M2 regression green
- [ ] [cc-prompt-templates.md §1](cc-prompt-templates.md) Opening procedure followed per task

---

## batch-1 · E1 Schema (3h, solo)

| ID | Name | Owner | Deliverables |
|---|---|---|---|
| T1S.1 | operators + operator_sessions tables | Dev1 | `autoservice/auth/operators_schema.py`, `tests/auth/test_operators_schema.py` |

**Verification**: `pytest tests/auth/test_operators_schema.py -v`
**Gate**: Tables + migration idempotent; no M2 regression

---

## batch-2 · Login + CRUD (6h, 2 lanes)

| ID | Name | Owner | Mode | Deliverables |
|---|---|---|---|---|
| T1S.2 | operator login + cookie | Dev1 | solo | `autoservice/auth/operator_login.py`, test |
| T1S.4 | operator CRUD API | subagent-1 | parallel | `autoservice/api_routes.py` edit, test |

**Default OQ applied**: cookie `operator_session`, TTL 24h, idle 30min
**Gate**: curl login → cookie in response → session row in DB; CRUD cross-tenant negative test passes

---

## batch-3 · WS + Invite 🟡 (6h, 2 lanes)

| ID | Name | Owner | Mode | Yellow Reason |
|---|---|---|---|---|
| T1S.3 | WS cookie validation 🟡 | Dev1 | solo + code-reviewer | Security: closes spoof gap at web_gateway.py:480-485 |
| T1S.5 | operator invite (magic-link ext) | subagent-1 | parallel | — |

**Yellow review focus (T1S.3)**:
- No operator_id accepted from JSON payload anymore
- Cookie value validated against DB session row
- Invalid/expired cookie → WS 1008 close
- M2 admin WS still works (regression must stay green)

**Gate (M3-1 milestone)**:
- [ ] 5 E1 P0 tasks ✅
- [ ] Operator can log in + WS handshake validates cookie
- [ ] Magic-link invite e2e: admin generates → invitee signs up → operator_session set
- [ ] M2 regression: `pytest tests/` + `pytest -m e2e tests/e2e/test_m2_acceptance.py` both green
- [ ] Smoke: `pytest tests/auth/ tests/web_gateway/test_ws_operator_auth.py -v`

## Risks

- **T1S.3 WS security**: incorrect cookie validation could break all operator sessions in prod. Mitigation: comprehensive invalid-cookie test matrix (expired, malformed, wrong tenant, no cookie).
- **T1S.2 ↔ T1S.4 parallel file conflict**: both may touch `autoservice/api_routes.py`. Mitigation: T1S.4 only adds routes, T1S.2 only adds cookie-setting route; explicit non-overlap in `may_touch`.

## Next

→ `/prd2impl:skill-10-smoke-test M3-1` (milestone gate)
→ then `/prd2impl:skill-8-batch-dispatch batch-4` (P2 parallel fan-out)
