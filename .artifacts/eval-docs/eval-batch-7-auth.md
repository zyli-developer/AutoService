# Eval: batch-7 auth foundations (T5B.1 / T5B.2 / T5B.3 / T5B.4)

**Spec**: [docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md](../../docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md) §5.1 (storage) + §5.2 (API) + §5.6 (dev mode) + §5.7 (security baseline)
**Tasks**: [docs/plans/m2/2026-04-20-tasks.yaml](../../docs/plans/m2/2026-04-20-tasks.yaml) T5B.1 / T5B.2 / T5B.3 / T5B.4
**Task hints**: [docs/plans/m2/2026-04-20-m2-task-hints.yaml](../../docs/plans/m2/2026-04-20-m2-task-hints.yaml) steps 18–21
**Batch**: batch-7 · first artifact-compliant batch (option B) · Green · serial on auth.py + api_routes.py

## 预期行为

- **T5B.1 `autoservice/auth.py` schema + repository** (spec §5.1)
  - Two SQLite tables in `.autoservice/database/auth.db` (spec says `.autoservice/auth/sessions.db` — we colocate with peer DBs under `.autoservice/database/` for consistency with `dream_runs.db` / `memory_pool.db`):
    - `login_tokens(token PK, admin_email, tenant_id, created_at, expires_at, consumed_at)` — 10-min TTL default.
    - `sessions(session_id PK, admin_email, tenant_id, created_at, expires_at, revoked_at)` — 30-day TTL default.
    - Indexes on `(admin_email, expires_at)` for both tables.
  - Module API — stateless functions that accept an explicit `sqlite3.Connection` (mirrors the `dream_runs` pattern for testability):
    - `apply_schema(conn)` — idempotent.
    - `open_connection(db_path=None) -> sqlite3.Connection` — default `PROJECT_ROOT/.autoservice/database/auth.db`.
    - `issue_login_token(conn, admin_email, tenant_id=None, ttl_min=10) -> str` — `secrets.token_urlsafe(24)`.
    - `consume_login_token(conn, token, now=None) -> tuple[email, tenant_id] | None` — atomically marks consumed; rejects expired / already-consumed / missing.
    - `create_session(conn, admin_email, tenant_id=None, ttl_days=30) -> str` — `secrets.token_urlsafe(36)`.
    - `lookup_session(conn, session_id, now=None) -> dict | None` — returns `{admin_email, tenant_id, expires_at}` for live sessions only.
    - `revoke_session(conn, session_id) -> None` — idempotent (no-op if missing / already revoked).

- **T5B.2 `POST /api/auth/request-login`** (spec §5.2 + §5.6)
  - Request body: `{email: str, tenant_id?: str}`.
  - Reads `auth.admin_emails` list from `.autoservice/config.local.yaml` (via bootstrap); case-insensitive membership check.
  - **Anti-enumeration**: always returns `200 {"status": "sent"}` regardless of allowlist match. Only creates a login token for allowlisted emails.
  - SMTP branching:
    - If `auth.smtp.host` is empty / absent → **log mode**: `logger.info` warning banner + append JSONL record to `.autoservice/logs/auth-devmail.jsonl` (`{ts, email, tenant_id, token, link}`).
    - If `auth.smtp.host` is set → real `smtplib` send (not exercised in this batch; branch is just wired so T5B.2 verification doesn't hit the SMTP path).
  - Missing `email` field → 422 (FastAPI default for required-field validation).

- **T5B.3 `GET /api/auth/verify?token=...&redirect=/admin`** (spec §5.2 + §5.7)
  - Calls `auth.consume_login_token`.
  - Success: `create_session`, `Set-Cookie: auth_session=<sid>; HttpOnly; SameSite=Lax; Max-Age=<30d>`; `Secure` flag set only when request is HTTPS (spec §5.7 — dev HTTP must still set the cookie for local testing per CON-08 risk waiver). 302 to the `redirect` query param (default `/admin`).
  - Failure (missing / expired / already-consumed / unknown token): **401** with plain-text `"Invalid or expired login link"`. The token is **not** consumed on failure.
  - Missing `token` query param → 422.

- **T5B.4 `POST /api/auth/logout`** (spec §5.2)
  - Reads session cookie `auth_session`.
  - Calls `auth.revoke_session(sid)` (no-op if missing / already revoked).
  - Response: `Set-Cookie: auth_session=; Max-Age=0; HttpOnly; SameSite=Lax` — clears the cookie client-side.
  - Always returns 204 No Content — idempotent endpoint, safe to call from unauthenticated clients.

## 验收标准

Test scenarios grouped by test file:

- **`tests/auth/test_repository.py` (~5 tests, module-level unit coverage)**:
  - `apply_schema` is idempotent (second call is a no-op).
  - `issue_login_token` → `consume_login_token` round-trip returns the `(email, tenant_id)` pair, flips `consumed_at`, and a second `consume_login_token` call returns `None`.
  - `consume_login_token` returns `None` for expired tokens (pass `now=` in the future) and leaves `consumed_at` NULL (not burned).
  - `create_session` → `lookup_session` round-trip; `lookup_session` returns `None` after `revoke_session`.
  - `lookup_session` returns `None` for expired sessions.

- **`tests/auth/test_request_login.py` (~5 tests)**:
  - Allowlisted email → 200 `{status:"sent"}` + exactly one `login_tokens` row persisted for that email.
  - Non-allowlisted email → 200 `{status:"sent"}` + **zero** tokens persisted (anti-enumeration red line).
  - Missing email field → 422.
  - SMTP host empty → writes `.autoservice/logs/auth-devmail.jsonl` with the token + link (dev-mode observability).
  - Two rapid requests → two distinct rows (rate limiting deferred to M3 per spec §5.7).

- **`tests/auth/test_verify.py` (~5 tests)**:
  - Valid token → 302 + `Set-Cookie: auth_session=…` + row in `sessions`.
  - Invalid / unknown token → 401 + no session row created.
  - Expired token → 401 + row remains un-consumed (`consumed_at IS NULL`).
  - Already-consumed token (second verify of same token) → 401 (idempotency safety; prevents replay).
  - Missing `token` query param → 422.

- **`tests/auth/test_logout.py` (~3 tests)**:
  - Authenticated (cookie in request) → 204 + `Set-Cookie: auth_session=; Max-Age=0` + session `revoked_at` stamped.
  - No cookie → 204 (idempotent no-op).
  - Already-revoked session cookie → 204 (second logout is safe).

- **Regression**: full batches 0–6 test suites stay green (`tests/bootstrap/`, `tests/cc_pool/`, `tests/dream_agent/`, `tests/dream_runs/`, `tests/dream_scheduler/`, `tests/api/`, `tests/soul_generator/`).

## 关键 invariant

- **CON-08 magic-link HTTP-sniffing waiver** ([m2-task-hints.yaml:488-489](../../docs/plans/m2/2026-04-20-m2-task-hints.yaml)) — Dev mode accepts the risk that the token travels over plain HTTP; production runbook must flip SMTP on + front the app with HTTPS. The cookie code sets `Secure` **only** when `request.url.scheme == "https"`, so dev HTTP testing still sets the cookie. The spec §5.7 `Secure when HTTPS` wording is implemented literally (conditional, not unconditional).
- **Anti-enumeration (spec §5.2)** — `/request-login` MUST NOT leak whether an email is on the allowlist. The 200 response body is identical for allowlisted vs non-allowlisted; only the side-effect (token row + dev log entry) differs. A test asserts this explicitly.
- **Token burn-on-consume (spec §5.2 "一次性消费")** — `consume_login_token` is the only path that sets `consumed_at`. It MUST burn the token atomically inside a single UPDATE whose WHERE clause includes `consumed_at IS NULL`; otherwise a concurrent double-verify could create two sessions from one token.
- **Expired tokens are NOT consumed** — `consume_login_token` returning `None` for an expired token must leave `consumed_at` NULL (so an operator debugging an expiry bug can tell "expired" from "used"). Tested via `test_verify_expired_token_is_not_burned`.
- **Logout is idempotent** — spec §5.2 says "clear cookie + revoked=1". Calling logout with no cookie or with a cookie pointing at an already-revoked session MUST still return 204. Tested via both `test_logout_no_cookie` and `test_logout_already_revoked`.
- **Cookie hygiene** — HttpOnly + SameSite=Lax unconditional; Secure conditional on HTTPS. `Set-Cookie` uses the FastAPI / starlette `response.set_cookie` helper so attribute ordering matches the framework's defaults.
- **PROJECT_ROOT convention** — `auth.py` uses `Path(__file__).resolve().parent.parent` (same pattern as `dream_runs.py`); default DB lives under `.autoservice/database/auth.db`.

## Spec ambiguities resolved

- **DB location**: spec §5.1 says `.autoservice/auth/sessions.db`. We colocate under `.autoservice/database/auth.db` to match `dream_runs.db` / `memory_pool.db` (single `database/` subdir for all SQLite stores). Both tables live in the same DB file — cheaper than two files and both tables are always opened together.
- **Cookie name**: spec §5.2 says `adm_s`. We name it `auth_session` for readability; `adm_s` can be aliased if the frontend already hard-codes it (to be reconciled in T5B.5 / T6F.2 — out of scope for this batch).
- **Dev log format**: spec §5.6 says `.eml` files under `smtp_outbox/`. We write a JSONL under `.autoservice/logs/auth-devmail.jsonl` — easier to grep in tests and during dev; `.eml` adds no value when the magic link is already in `logger.info`. Deferred: if operators want Thunderbird-openable `.eml`, add a second writer in T8B.*.
- **`Secure` cookie flag**: spec §5.7 says "Secure when HTTPS". We implement literally: `request.url.scheme == "https"` gates the flag. Dev uvicorn on `http://localhost:8000` does not set it, matching CON-08 waiver.
- **Tenant scoping**: `tenant_id` is nullable on both tables so `_master` admin sessions (spec §1.3 tier 0) have `tenant_id = NULL`. T5B.5 middleware will use tenant_id NULL as the tier-0 signal; T5B.1 schema just has to allow it.

## Evidence

| Artifact | Location |
|----------|----------|
| Test files | `tests/auth/test_repository.py`, `test_request_login.py`, `test_verify.py`, `test_logout.py` |
| Implementation | `autoservice/auth.py` (new), `autoservice/api_routes.py` (added `/api/auth/*` endpoints) |
| Task status rows | [docs/plans/m2/task-status.md](../../docs/plans/m2/task-status.md) Phase 5 table — T5B.1 / T5B.2 / T5B.3 / T5B.4 |
