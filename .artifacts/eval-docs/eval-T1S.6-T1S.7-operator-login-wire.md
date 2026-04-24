# Eval: T1S.6 + T1S.7 · Operator-console LoginPage rewire (M3-1 carry-over)

> **Mode**: verify (post-incident gap capture) · **Owner**: Dev1 · **Date**: 2026-04-21

Contract: [docs/contracts/m3/e1-auth-rbac.md §3-§4](../../docs/contracts/m3/e1-auth-rbac.md)
Related: T1S.2 (operator HTTP login) · T1S.3 (WS strict cookie) · M2 T2B.1 (operator-console SPA)

---

## 1. Why this doc exists (discovered gap)

After T1S.3 landed (WS strict `operator_session` cookie validation) and the service was restarted, the live operator-console could no longer connect:

```
gateway.log:
  WebSocket /ws/operator?tenant=11 [accepted]
  connection open
  connection closed        ← immediate, looping ~90 times
browser WS error frame:
  {code: "4011_AUTH", message: "operator_session cookie required",
   details: {reason: "invalid_or_missing_session"}}
```

Root cause (verified, not guessed):

1. **Backend** ([autoservice/web_gateway.py:558-578](../../autoservice/web_gateway.py#L558-L578)): T1S.3 strict handshake closes with 1008 when the cookie is missing/invalid/expired/disabled.
2. **Frontend** ([frontend/apps/operator-console/src/components/LoginPage.tsx](../../frontend/apps/operator-console/src/components/LoginPage.tsx), pre-fix): a M2-era stub that **only writes to the Zustand store** and never calls `/api/auth/operator/request-login` or `/verify`. No cookie is ever set, so the browser always presents no `operator_session` to the WS handshake.
3. **Dev bypass**: admin has `AUTH_DEV_MODE=1 → POST /api/auth/dev-login` ([autoservice/api_routes.py:2045-2117](../../autoservice/api_routes.py#L2045-L2117)), operator has **no parallel**. Without email delivery wired, local dev can't mint `operator_session` at all.
4. **Direct evidence**: on the affected environment `.autoservice/database/auth.db` contained only `login_tokens` + `sessions` — **neither `operators` nor `operator_sessions` had ever been created**, proving no operator had ever completed login on this install.

The M3 plan (tasks.yaml) does not cover the frontend side of T1S.3. T1S.2/T1S.3/T1S.5 delivered backend endpoints + WS validation; no task made the operator-console SPA consume them. This doc records the gap and splits the recovery into two tracks.

---

## 2. Split

### 2.1 T1S.6 — hotfix (unblock local dev) · **done in this session**

| Aspect | Value |
|---|---|
| Type | 🟢 green |
| Phase | P1 (M3-1 carry-over, post-gate) |
| Depends on | T1S.2, T1S.3 |
| Deliverables | `autoservice/operator_routes.py` (+ `POST /api/auth/operator/dev-login`) · `tests/auth/test_operator_dev_login.py` (12 tests) · `frontend/apps/operator-console/src/components/LoginPage.tsx` · `frontend/apps/operator-console/src/__tests__/LoginPage.test.tsx` · `frontend/apps/operator-console/src/__tests__/integration.test.tsx` · `frontend/packages/i18n/src/locales/{en,zh-CN}.json` |
| Verification | 12/12 new backend tests green · 263/263 tests/auth+tests/gateway regression green · 5/5 LoginPage vitest · integration.test.tsx pre-existing `input-squad-id` rot (2 failures) unchanged by this task |
| Scope | Minimal addition — parallel to admin dev-login, same `.autoservice/logs/auth-devmail.jsonl` audit log with `kind="operator_dev_login"`. |

### 2.2 T1S.7 — formal magic-link LoginPage (production path) · **pending**

| Aspect | Value |
|---|---|
| Type | 🟢 green |
| Phase | P1 (carry-over) |
| Depends on | T1S.2, T1S.6 |
| Deliverables (planned) | LoginPage.tsx dev-mode probe + dual-mode UI (dev form ↔ magic-link form) · "check your email" intermediate screen · error states for unknown/disabled operators · vitest fixture covering both modes |
| Verification (planned) | POST `/api/auth/operator/request-login` called with `{email, tenant_id}` → UI flips to "sent" state · `GET /api/auth/operator/verify?token=…` 302 redirect → operator lands on `/operator` with cookie · existing dev path continues to work unchanged · playwright smoke in T5S.1 covers the dev variant |
| Scope | No backend changes (T1S.2 endpoints already exist). |

---

## 3. Expected behaviour (T1S.6 — what shipped)

### 3.1 `POST /api/auth/operator/dev-login`

Gated by `AUTH_DEV_MODE=1`. When disabled → 404 `{"error":"not found"}`, no endpoint surface advertised.

When enabled:

| Input | Output |
|---|---|
| `{email, tenant_id}` unknown operator | 200 · upserts `operators` row with `role="responder"` · mints `operator_session` row + cookie · audit JSONL line |
| `{email, tenant_id}` existing active operator | 200 · reuses `operator_id` · new session row · audit JSONL |
| `{email, tenant_id}` existing disabled operator | 401 `{"error":"operator disabled"}` · **no session minted** |
| Missing / blank `email` or `tenant_id` | 400 `{"error": "<field> is required"}` |
| Email case difference (e.g. `ALICE@X.COM` vs stored `alice@x.com`) | lookup is case-insensitive (normalised before lookup/upsert) |

Response body (200):

```json
{"ok": true, "redirect": "/operator",
 "operator_id": "...", "tenant_id": "acme", "email": "alice@acme.com"}
```

Cookie:

```
operator_session=<opaque-token>; Path=/; HttpOnly; SameSite=Lax;
Max-Age=86400; [Secure if https]
```

### 3.2 Operator-console LoginPage

- Fields: `email` (type="email") + `tenant_id`.
- Submit disabled until both are non-blank.
- On submit: `fetch('/api/auth/operator/dev-login', {credentials:'include'})`.
  - 200 → `useOperatorStore.login(operator_id, '')` → App flips to `WorkspacePage`, `useOperatorWS` opens `/ws/operator` with the freshly-minted cookie.
  - 404 → `operator.login.error_dev_disabled` surfaced (tells user magic-link flow — T1S.7 — is the production path).
  - Other non-2xx → backend `error` field or `HTTP <code>` surfaced via `operator.login.error_generic`.

---

## 4. Key invariants

- **Dev bypass hidden in prod**: `AUTH_DEV_MODE` unset ⇒ `/api/auth/operator/dev-login` returns 404 and does not touch the DB. Verified by `test_operator_dev_login_returns_404_when_env_unset` (no operator row, no session row, no cookie).
- **Cookie parity with magic-link `/verify`**: same TTL (`DEFAULT_OPERATOR_SESSION_TTL_HOURS`), same attributes (HttpOnly, Lax, Path=/, Secure iff https), same cookie name — WS handshake doesn't need to know which path minted it.
- **No token leakage to logs**: only `session_token_prefix` (first 8 chars) is audited. Verified by `test_operator_dev_login_writes_audit_jsonl_entry`.
- **Disabled operator cannot revive via dev-login**: parity with `/verify` — 401 "operator disabled", no session minted. Verified by `test_operator_dev_login_rejects_disabled_operator`.
- **Email normalisation**: lowercased before lookup *and* upsert so `ALICE@X.COM` ≠ new row. Verified by `test_operator_dev_login_email_is_case_insensitive`.
- **End-to-end trust**: cookie issued by dev-login satisfies `/api/auth/operator/me`. Verified by `test_operator_dev_login_cookie_satisfies_me_endpoint`.

---

## 5. Out of scope (tracked elsewhere)

- Full magic-link UX in LoginPage → **T1S.7** (this doc §2.2).
- Tenant-picker dropdown / persona list (as admin dev-login does via `/api/auth/dev-mode`) — deferred to T1S.7; current LoginPage accepts free-text tenant_id to keep the hotfix minimal.
- Playwright coverage of the login → WS handshake path → T5S.1 (`batch-11`).
- Fixing pre-existing frontend test rot (`input-squad-id` absent from current WorkspacePage, 2 integration tests failing since M2) — unrelated to this task; not owned here.

---

## 6. Why "正规流程" and not hand-written note

User guidance (2026-04-21): carry-over tasks must produce the standard four-artefact set — eval-doc (this file) → `tasks.yaml` entry → `task-status.md` row → session-log line — so the `task-status.md authoritative-truth` rule from [CLAUDE.md §/autorun conventions](../../CLAUDE.md#/autorun-&-batch-execution-conventions) is upheld even for post-gate additions.
