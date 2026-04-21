---
title: M3 Epic E1 · Identity & RBAC
status: draft
date: 2026-04-21
authors: [Claude Opus 4.7 (orchestrator)]
prd_refs: [docs/prd/AutoService-M3-PRD.md §2 E1, §5 decisions 1-3]
stories: [E1.1, E1.2, E1.3, E1.4, E1.5, E1.6]
---

# M3 Epic E1 · Identity & RBAC

## 1. Context & Problem Statement

PRD §1.2 gives M3 as "让 M2 MVP 能真正开门做生意". Its first goal is literally
**生产就绪：operator 鉴权 + RBAC + 团队邀请（无此则任何商户都不敢部署）**. Everything
else in M3 (country filter, triage SLA, dream extensions) is a quality bump on
an unshippable MVP until Epic E1 lands. Gap analysis (`docs/plans/m3/2026-04-21-gap-analysis.yaml`)
marks `GAP-E1.1` as the **primary blocker of the M3 critical path** — it fans
out to E1.2/E1.3/E1.4/E1.5/E1.6 and transitively into E6.2 (Playwright needs a
logged-in operator). After the Epic E2 descope (PRD §8.1 Errata), E1 is the
largest remaining work surface in M3 and, with E4.1 + E3.1, a direct input to
the **v1.2.0-mvp tag**.

The shape of the problem:

- M2 delivered magic-link admin auth — `auth.py`, `sessions` table, cookie
  wiring — but **operator** is still a WS-only concept, trusted on the client's
  word via a JSON field in `client_hello.payload.operator_id`.
  (`autoservice/web_gateway.py:480-485`).
- Operators therefore cannot be enumerated, permissioned, invited, logged out,
  or audited. This is the floor that has to be raised before any tenant
  deployment.
- RBAC as currently in-tree is **conversation-scoped** (`ParticipantRole`
  enum at `autoservice/conversation_engine/types.py:25-30`), which is a chat
  persona model, NOT a tenant-authorization model. There is no
  viewer/responder/admin tier today.
- Multiple design constraints have already been fixed by the PRD (CON-01
  SQLite, CON-02 hardcoded matrix, CON-08 separate cookie) — this spec
  commits to one concrete realisation of each.

## 2. Current State (M2 baseline)

| Capability | Status | Evidence |
|---|---|---|
| Magic-link admin login | **Works** | `autoservice/auth.py:116-140` `issue_login_token` |
| `login_tokens` table (single-use, 10-min TTL) | **Works** | `autoservice/auth.py:54-71` schema |
| `sessions` table (30-day TTL, revoke) | **Works** | `autoservice/auth.py:64-71`, `188-216` |
| Admin session cookie | **Works — named `auth_session`** (not `admin_session`) | `autoservice/auth.py:304-307`, `autoservice/api_routes.py:1641` |
| `require_tenant_access` FastAPI dep | **Works** | `autoservice/auth.py:431-449` |
| Multi-admin rows per tenant schema-allowed | **Works** | `autoservice/auth.py:64-71` + `375-392` (no UNIQUE on `(tenant_id, admin_email)`) |
| Operator HTTP login | **MISSING** | — no endpoint exists — |
| Operator session persistence | **MISSING** | only `_operator_sessions: dict[str, set[str]]` in-memory (`web_gateway.py:58-59`) |
| WS handshake identity validation | **Ephemeral & spoofable** | `web_gateway.py:479-485` trusts `client_hello.payload.operator_id` as-is |
| Operator CRUD API | **MISSING** | — |
| Operator invite flow | **MISSING** | magic-link infra present but has no `role` column (`auth.py:57-62`) |
| Tenant-scoped RBAC (viewer/responder/admin) | **MISSING** | conversation-scoped `ParticipantRole` is the only role construct |
| `/hijack` RBAC gate | **MISSING** | takeover-release spec leaves gating to E1.4 |
| Admin-to-admin invite | **MISSING** | — |
| Offline-watcher graceful degrade for operators | **Works** | `autoservice/gateway/offline_watcher.py` (uses operator_id regardless of trust level) |

**Critical finding:** the cookie name actually used in M2 is `auth_session`, not
`admin_session` as the PRD's CON-08 phrasing implies. CON-08 is still
satisfied as long as the two cookies have **distinct names and distinct
scopes**; this spec keeps the existing `auth_session` name for the admin flow
and introduces `operator_session` for the new flow. (Open Question OQ-1 below.)

## 3. Design Decisions (per-story)

Stories are addressed in dependency order: E1.1 → {E1.2, E1.3, E1.4, E1.5} → E1.6.

### 3.1 E1.1 · Operator login + session + WS handshake [P0]

**Acceptance (PRD §2 E1.1 / §6.1 / §6.2):**

- Operator logs in, receives `operator_session` cookie.
- WS handshake enforces operator identity (failure rate <1%, NFR-01).
- Session persisted in `.autoservice/database/sessions.db` (CON-01).

**Chosen approach — "shared auth.db, extended schema, separate cookie":**

1. **Storage.** Extend `autoservice/auth.py` rather than create a parallel
   `operator_auth.py`. Add columns to existing tables plus one new table:

   ```sql
   -- schema delta (run via apply_schema idempotent script)
   ALTER TABLE login_tokens ADD COLUMN role TEXT NOT NULL DEFAULT 'admin';
   --   role ∈ {'admin', 'operator', 'tenant_admin_invite'}
   ALTER TABLE sessions ADD COLUMN role TEXT NOT NULL DEFAULT 'admin';
   --   role ∈ {'admin', 'operator'}
   ALTER TABLE sessions ADD COLUMN rbac_tier TEXT;
   --   filled for role='operator' sessions with tenant RBAC (§3.4)

   CREATE TABLE IF NOT EXISTS operators (
       operator_id   TEXT PRIMARY KEY,       -- op_<ulid>
       tenant_id     TEXT NOT NULL,
       email         TEXT NOT NULL,
       display_name  TEXT NOT NULL,
       password_hash TEXT,                   -- NULL until first-login sets one
       rbac_tier     TEXT NOT NULL DEFAULT 'responder',
       status        TEXT NOT NULL DEFAULT 'active',  -- active|invited|disabled
       created_at    TEXT NOT NULL,
       created_by    TEXT NOT NULL,          -- inviter admin_email
       last_login_at TEXT
   );
   CREATE UNIQUE INDEX idx_operators_email_tenant
       ON operators(tenant_id, email);
   ```

   The file path is the existing `.autoservice/database/auth.db` so CON-01 is
   respected by reuse, not by a new DB. Migration is idempotent (runs every
   process start via `apply_schema`; SQLite `ALTER TABLE ADD COLUMN` is a
   trivial metadata update).

2. **Cookie.** New constant
   `OPERATOR_SESSION_COOKIE_NAME = "operator_session"` in `auth.py`, mirror
   of `AUTH_SESSION_COOKIE_NAME`. Both cookies set with `HttpOnly;
   SameSite=Lax; Path=/` (same domain, same path → **cannot** be isolated by
   Path alone; see §4.4 for our cross-contamination guarantee).

3. **HTTP endpoints** (added to `autoservice/api_routes.py`):

   | Method | Path | Purpose |
   |---|---|---|
   | `POST` | `/api/auth/operator/login` | Email + password → `operator_session` cookie |
   | `POST` | `/api/auth/operator/logout` | Revoke session, clear cookie |
   | `GET`  | `/api/auth/operator/me` | Return `{operator_id, tenant_id, rbac_tier, display_name}` from cookie |
   | `POST` | `/api/auth/operator/accept-invite` | Consume invite token (GAP-E1.3), set password, issue cookie |

   Rate-limiting the login POST is deferred to M4 (M2 deferred it too — see
   `auth.py:131` "M2 does not rate-limit").

4. **WS handshake validation (the failure-rate NFR).**
   Today `web_gateway.py:480-485` trusts whatever the client puts in
   `client_hello.payload.operator_id`. Replace with:

   ```python
   # pseudocode in web_gateway._handle_connection, before session_id issued
   if viewer_role == "operator":
       sid = ws.cookies.get(OPERATOR_SESSION_COOKIE_NAME)
       if not sid:
           await ws.close(code=4401)  # policy violation — no session
           return
       session = auth.lookup_operator_session(conn, sid)
       if session is None:
           await ws.close(code=4401)
           return
       operator_id = session["operator_id"]  # from DB, NOT from payload
       tenant_id   = session["tenant_id"]
   ```

   `operator_id` from the JSON payload is **ignored** going forward (a warn log
   if the client still sends one — helps find stale frontends). The
   `_operator_sessions` in-memory index stays as a routing convenience; it is
   now keyed from the DB lookup, so spoofing is impossible even with a stale
   dict.

5. **Session TTL & idle.** Reuse M2's 30-day `expires_at` for operators;
   idle timeout (e.g. 30-min no-activity revoke) is an Open Question (OQ-2).
   A lightweight cleanup job runs on process start and once per hour: delete
   rows where `expires_at < now() - 7d` (purge, not just filter).

**Alternatives considered:**

| Alternative | Why rejected |
|---|---|
| Separate `operator_auth.db` file | Doubles the migration + backup surface; violates CON-01 spirit ("sessions.db single source"). |
| Reuse `auth_session` cookie with a `role` claim inside | Violates CON-08 (explicit separation mandate) and makes CSRF / logout asymmetric. |
| JWT-style stateless session | Introduces signing key rotation story M3 has no time for; M2 already chose server-side sessions. |
| Keep JSON-passed `operator_id` but add HMAC | HMAC key distribution story is not cheaper than cookie+DB, and cookies compose with existing admin flow. |

**Integration notes:**

- **E6.2 Playwright** needs a `POST /api/auth/operator/login` fixture (see
  `docs/plans/batches-M1-to-M5-kickoff.md` 17-story ref) — unblocked by this.
- **Takeover-release** (`docs/superpowers/specs/2026-04-17-takeover-release-design.md`)
  reads `operator_id` for `conv.takeover_operator_id`; since that ID now comes
  from the validated session it **gains trust at zero code cost** but callers
  in `local_engine.handle_command("/hijack")` must be audited for any
  `operator_id` that still originates from the frame body.
- **Offline watcher** (`autoservice/gateway/offline_watcher.py`) continues to
  receive `operator_id` on connect/disconnect; no change needed because the
  identifier is the same string, just now trusted.

### 3.2 E1.2 · Per-tenant operator CRUD API [P0]

**Acceptance (PRD §2 E1.2):** tenant_admin can C/R/U/D operators scoped to own
tenant; list endpoint enforces tenant-scoped filter.

**Chosen approach — four thin REST routes under the existing `/api/admin/{tenant_id}/` tree:**

| Method | Path | Auth | Body / Response |
|---|---|---|---|
| `POST`   | `/api/admin/{tenant_id}/operators` | `require_tenant_access` + RBAC `admin` | `{email, display_name, rbac_tier?, send_invite?}` → creates operator row (status='invited' if `send_invite`) |
| `GET`    | `/api/admin/{tenant_id}/operators` | same | `[{operator_id, email, display_name, rbac_tier, status, last_login_at}]` |
| `PATCH`  | `/api/admin/{tenant_id}/operators/{operator_id}` | same | partial update of `display_name`, `rbac_tier`, `status` |
| `DELETE` | `/api/admin/{tenant_id}/operators/{operator_id}` | same | sets `status='disabled'` (soft delete); revokes all live sessions for that operator |

**Authorization is done twice**, by design:

1. `require_tenant_access` (existing `auth.py:431-449`) rejects
   cross-tenant access (returns 403).
2. The new `require_rbac("admin")` dependency (§3.4) additionally rejects
   non-admin callers (e.g. a responder-tier co-worker who somehow held a
   valid session).

**Soft delete over hard delete** because operator_id is referenced from audit
rows (proposal_audit later, takeover history implicitly via
`conv.takeover_operator_id`); hard delete would orphan them.

**Alternatives considered:**

| Alternative | Why rejected |
|---|---|
| Hard delete | Orphans audit trails; operators need recoverable status. |
| Admin-email auto-create (no explicit CRUD) | CRUD is a PRD acceptance criterion (§6.1), and no-invite creation breaks operator-side password setup. |
| Separate `/api/operator-admin/` tree outside `/api/admin/` | Fractures auth-middleware placement; existing `require_tenant_access` already matches `tenant_id` path param. |

**Integration notes:**

- Admin-portal UI (`docs/superpowers/specs/2026-04-18-admin-portal-web-layout-design.md`)
  adds an **"Operators"** tab on TenantLayout — list + invite button.

### 3.3 E1.3 · Operator team invite via magic-link [P0]

**Acceptance (PRD §2 E1.3 / §6.1):** admin generates magic-link invite for
operator role; invitee completes signup and lands in correct tenant.

**Chosen approach — reuse magic-link backend with role metadata:**

1. `login_tokens.role` column (added in §3.1) distinguishes
   `'admin' | 'operator' | 'tenant_admin_invite'`.
2. New function `auth.issue_invite_token(role, tenant_id, email,
   inviter_admin_email, ttl_hours=72)` — same generator as
   `issue_login_token`, 72-hour TTL instead of 10 minutes, optional display
   name carried in extra JSON (new column
   `login_tokens.invite_payload TEXT` or — preferred — a prefilled
   `operators` row with `status='invited'`).
3. Admin-portal "Invite Operator" button → `POST /api/admin/{tenant_id}/
   operators/{id}/invite-link` returns the token (and sends email if SMTP
   configured per M2 `config.local.yaml.auth.smtp`).
4. Invitee URL: `/invite/operator?token=<t>` → landing page → operator chooses
   password → `POST /api/auth/operator/accept-invite` burns the token,
   promotes `operators.status` to `active`, sets `password_hash`, issues
   `operator_session` cookie.

**Alternatives considered:**

| Alternative | Why rejected |
|---|---|
| Dedicated `invite_tokens` table | Duplicates 80% of `login_tokens` schema; atomic consume logic already lives there. |
| Password-less operators (magic-link only) | Short-TTL link every time is hostile to shift-worker UX; password + occasional re-auth is industry-standard. |
| Invite delivers raw password | Anti-security; no modern stack does this. |

**Integration notes:** E1.6 (admin-to-admin) uses the same infra with
`role='tenant_admin_invite'` — see §3.6.

### 3.4 E1.4 · Coarse 3-tier RBAC [P1]

**Acceptance (PRD §2 E1.4 / §6.2 / §7):** permission matrix hardcoded (CON-02),
RBAC decision P95 <5ms (NFR-02), viewer cannot `/hijack`, responder cannot
invite, admin can both.

**Chosen approach — hardcoded dict + FastAPI dependency:**

1. **Matrix lives in source.** New file `autoservice/rbac.py`:

   ```python
   # autoservice/rbac.py (sketch)
   from typing import Literal
   Tier = Literal["viewer", "responder", "admin"]
   Action = Literal[
       "conversation.view", "conversation.reply",
       "conversation.hijack", "conversation.release",
       "operator.crud", "operator.invite",
       "admin.invite",
       "proposal.approve", "proposal.apply",
       "tenant.config.write",
   ]

   # CON-02: matrix lives in code, not DB, not yaml.
   _MATRIX: dict[Tier, frozenset[Action]] = {
       "viewer":    frozenset({"conversation.view"}),
       "responder": frozenset({"conversation.view", "conversation.reply",
                               "conversation.hijack", "conversation.release"}),
       "admin":     frozenset({ *all_actions }),   # superset
   }

   def can(tier: Tier, action: Action) -> bool:
       return action in _MATRIX[tier]
   ```

2. **Permission matrix (authoritative):**

   | Action | viewer | responder | admin |
   |---|---|---|---|
   | `conversation.view` | yes | yes | yes |
   | `conversation.reply` | no | yes | yes |
   | `conversation.hijack` | no | yes | yes |
   | `conversation.release` | no | yes | yes |
   | `operator.crud` | no | no | yes |
   | `operator.invite` | no | no | yes |
   | `admin.invite` | no | no | yes |
   | `proposal.approve` | no | no | yes |
   | `proposal.apply` | no | no | yes (+platform admin only for platform-level) |
   | `tenant.config.write` | no | no | yes |

   `admin` means **tenant_admin** here; platform-admin (`_master`) is
   represented by `tier_of_session == 0` (nullable `tenant_id`, existing
   M2 concept from `auth.py:327-333`) and implicitly dominates all
   rows.

3. **Enforcement — FastAPI dependency, route-level.**

   ```python
   def require_rbac(action: Action):
       def dep(ctx: AuthContext = Depends(require_tenant_access)) -> AuthContext:
           tier = _resolve_tier(ctx)  # 'admin' for admin sessions, session.rbac_tier for operators
           if not can(tier, action):
               raise HTTPException(403, {"error": "forbidden", "action": action})
           return ctx
       return dep
   ```

   Rationale for **dependency over decorator over middleware:**
   - Middleware is blind to route metadata (would need path-regex table — brittle).
   - Class-level decorator doesn't compose with FastAPI's sub-routers.
   - `Depends(...)` is the idiomatic shape, composes with `require_tenant_access`, is unit-testable in isolation.

4. **NFR-02 budget (P95 <5ms).**
   - `can()` is a frozenset membership check — ~50 ns hot-path. Safe.
   - The dependency cost is dominated by the `require_tenant_access` DB hit
     (already in budget for admin routes). To meet <5ms at P95 we
     **cache session→tier resolution** in-process per request state
     (`request.state.rbac_tier`) so a single request can call `require_rbac`
     repeatedly without re-hitting SQLite.
   - Microbenchmark lives in `tests/rbac/test_rbac_latency.py` (1e4 iterations,
     assert P95 < 5ms on CI reference hardware).

5. **`/hijack` gating (takeover-release integration).**
   The `/hijack` path today lands through `message_router._process_frame`
   (WS command), not a REST endpoint, so the RBAC dep does not apply
   directly. Gate there:

   ```python
   # message_router._process_frame (pseudocode), before local_engine.handle_command
   if env.payload.get("command") == "/hijack":
       tier = ws.state.rbac_tier  # set at handshake from operator_session
       if not rbac.can(tier, "conversation.hijack"):
           return [error_frame(ERR_FORBIDDEN, "viewer cannot hijack")]
   ```

**Alternatives considered:**

| Alternative | Why rejected |
|---|---|
| Fine-grained permission list per endpoint, stored in YAML | Violates CON-02 explicitly. |
| Boolean flags on `operators` row (`can_hijack`, `can_invite`) | Doesn't scale; PRD wants a 3-tier abstraction not bag-of-flags. |
| Role=single-string in session + `if role == 'admin'` sprinkled through routes | Decentralised; hard to audit; no single source of truth for matrix. |
| Runtime-loadable policy (e.g. Casbin) | Overkill for 3 tiers × ~10 actions; ships slower. |

### 3.5 E1.5 · Multi-admin per tenant [P1]

**Acceptance (PRD §2 E1.5 / §6.1):** ≥2 admins per tenant, all see same view
and perform same actions.

**Chosen approach — leverage existing sessions schema, add list+manage API:**

Gap analysis confirms the schema already permits it (`auth.py:64-71` has
no UNIQUE on `(tenant_id, admin_email)`). Missing pieces are purely API +
UI:

| Method | Path | Notes |
|---|---|---|
| `GET`    | `/api/admin/{tenant_id}/admins` | List active admin sessions + admin_emails known to that tenant |
| `DELETE` | `/api/admin/{tenant_id}/admins/{admin_email}` | Revoke all live sessions + remove from allowlist |
| `PATCH`  | `/api/admin/{tenant_id}/admins/{admin_email}` | Currently no editable fields — reserved for M4+ when per-admin flags exist |

**PRD §2 E1.5 explicitly requires "permissions consistent"** — no first-admin /
co-admin distinction. Therefore there is **no ownership transfer flow** in M3;
any admin can revoke any other admin. This is intentional simplicity (A
confirmed at PRD write-time); a later flow (primary admin + secondary) is M4+.

**Alternatives considered:** a `primary_admin` flag was briefly considered
but rejected because PRD requires identical permissions; introducing a flag
you then don't honor is dead weight.

### 3.6 E1.6 · Admin-to-admin magic-link invite [P2]

**Acceptance (PRD §2 E1.6):** admin invite link promotes invitee to
`tenant_admin` role on acceptance.

**Chosen approach — E1.3 infra with `role='tenant_admin_invite'`:**

- `auth.issue_invite_token(role='tenant_admin_invite', tenant_id, email,
  inviter_admin_email, ttl_hours=72)` — identical mechanism to operator
  invite; different landing page (`/invite/admin?token=<t>`).
- On accept: burn token → allowlist invitee's email in tenant admin roster
  → issue magic-link login email to invitee (one-time bridge; they then go
  through the normal magic-link flow and receive an `auth_session` cookie).
- **Cannot escalate**: invite consumer only gets `tenant_admin`, never
  `platform_admin` — the invite has `tenant_id` stamped in it.

**Alternatives considered:** auto-login after accept (no intermediate
magic-link) was rejected — magic-link-on-accept means the operator_session
and auth_session flows stay symmetric and email ownership gets verified
twice (invite and first login).

## 4. Cross-Cutting Design Topics

### 4.1 Session storage schema (additions)

```
                ┌───────────────────────────────────┐
                │ .autoservice/database/auth.db     │  (CON-01; reused, not split)
                └───────────────────────────────────┘
                                 │
    ┌─────────────────┬──────────┴──────────┬────────────────────┐
    ▼                 ▼                     ▼                    ▼
┌─────────────┐  ┌──────────────┐  ┌──────────────────┐  ┌─────────────┐
│ login_tokens│  │ sessions     │  │ operators        │  │ (future)    │
│  (M2 base)  │  │  (M2 base)   │  │   (NEW)          │  │ audit_log   │
│ +role col   │  │  +role col   │  │  operator_id PK  │  │   deferred  │
│ +invite_pld │  │  +rbac_tier  │  │  tenant_id FK    │  │   to E5.2   │
└─────────────┘  └──────────────┘  │  email, pw_hash  │  └─────────────┘
                                   │  rbac_tier       │
                                   │  status          │
                                   └──────────────────┘
```

Schema delta summary:

- `login_tokens`: `+role TEXT NOT NULL DEFAULT 'admin'`, optionally
  `+invite_payload TEXT` (JSON blob for display_name etc.).
- `sessions`: `+role TEXT NOT NULL DEFAULT 'admin'`, `+rbac_tier TEXT` (NULL
  for `role='admin'`).
- `operators`: new table (see §3.1).

No change to file path (`.autoservice/database/auth.db`). Two DB files may
coexist logically (`auth.db` and `sessions.db` both referenced in PRD
CON-01); current code uses `auth.db` exclusively, so we treat **that** as the
canonical "sessions DB" and note this path-name reconciliation under OQ-3.

### 4.2 RBAC permission matrix

See §3.4 table. Hardcoded as `frozenset` literals in `autoservice/rbac.py`.
**Any PR that introduces a new action** (e.g. when E3.1 SLA alert mute is
wired) adds the action to the `Action` Literal and to **every** tier's set
(defaulting to `admin`-only); the matrix is the single place RBAC policy
lives.

### 4.3 Middleware / dependency placement

- `require_tenant_access` (existing, M2) — auth + tenant-scope.
- `require_rbac(action)` (new, E1.4) — layered on top. Returns `AuthContext`.
- `require_operator_session` (new, E1.1) — parallel to `require_tenant_access`
  for routes that accept operator cookies only (e.g. `/api/auth/operator/me`).
- WS handshake validation lives **inline** in `web_gateway._handle_connection`
  because the cookie is read from `ws.cookies` (FastAPI dep injection is
  per-endpoint; there is no DI for `@websocket_route`).

### 4.4 Cookie isolation — how CON-08 is enforced

**The two cookies share Domain and Path.** CON-08 requires they not
cross-contaminate; this is achieved by **distinct names + distinct
server-side session tables (via `role` column)**, not by Path/Domain
isolation. Concretely:

1. `operator_session` lookups go through a function that only returns rows
   where `sessions.role = 'operator'`; an attacker who substituted their
   `operator_session` cookie value into the `auth_session` slot would miss
   the name-match entirely (different cookie name → different `request.cookies.get(...)`).
2. `auth_session` lookups enforce `sessions.role = 'admin'` symmetrically.
3. CSRF: SameSite=Lax is sufficient for the login/logout POSTs given the
   admin portal is same-origin with the API. Double-submit CSRF tokens are
   out of scope for M3 (deferred to M4 when third-party embeds matter).
4. **Logout isolation:** `POST /api/auth/logout` (admin) revokes only
   `role='admin'` sessions by admin_email; `/api/auth/operator/logout`
   revokes only `role='operator'` sessions by operator_id.

Threat model (the question "can an operator become an admin?"):

- Must forge a `sessions` row with `role='admin'` and matching
  `admin_email` — can only be done by writing to `auth.db`, which is
  file-system-level attack (outside HTTP surface).
- Cannot reuse an operator session ID as an admin session because (a)
  different cookie name, (b) `role` column mismatch rejects lookup.

### 4.5 WS handshake migration

Transition steps:

1. **Add** cookie-based validation (§3.1 pseudocode) **alongside** the
   existing JSON `operator_id` path, feature-flagged off by default.
2. Admin-portal's TenantLayout operator view ships the login form and starts
   setting `operator_session`; E6.2 Playwright uses the login endpoint.
3. Flip the feature flag; the JSON path logs a deprecation warning, continues
   to work for 1 release.
4. In a follow-up (B-M3-7 tail or M3.5), delete the JSON path. The Feishu
   channel (`channels/feishu/channel.py`) is unaffected — it does not use
   operator WS.

## 5. Test Strategy

| Story | Test type | Where | Notes |
|---|---|---|---|
| E1.1 | unit | `tests/auth/test_operator_login.py` (new) | token issue, burn, session create, cookie round-trip |
| E1.1 | integration | `tests/auth/test_operator_ws_handshake.py` (new) | valid cookie → accepts; missing/expired → close(4401); JSON operator_id ignored |
| E1.1 | NFR-01 (handshake <1% failure) | `tests/web_gateway/test_handshake_reliability.py` | 1000 iterations, assert success rate ≥99% |
| E1.2 | integration | `tests/auth/test_operator_crud.py` (new) | cross-tenant CRUD returns 403; self-tenant works |
| E1.2 | security | same file | non-admin-tier operator gets 403 on `DELETE /operators/{id}` |
| E1.3 | integration | `tests/auth/test_operator_invite.py` (new) | token burn atomicity reuses M2 tests; role='operator' enforced on accept |
| E1.4 | unit | `tests/rbac/test_matrix.py` (new) | exhaustive action×tier table match §3.4 |
| E1.4 | NFR-02 (P95 <5ms) | `tests/rbac/test_rbac_latency.py` (new) | 10k iterations, assert P95 < 5ms (timer.perf_counter, no DB) |
| E1.4 | integration | `tests/rbac/test_hijack_gate.py` (new) | viewer WS → `/hijack` → error frame; responder → accepted |
| E1.5 | integration | `tests/auth/test_multi_admin.py` (new) | ≥2 admin rows per tenant_id; both auth and see same routes |
| E1.6 | integration | `tests/auth/test_admin_invite.py` (new) | invite token role='tenant_admin_invite'; accept promotes to admin |
| E1 (full) | e2e (Playwright, E6.2) | `tests/e2e/playwright/specs/operator-login.spec.ts` | login → conversation list → reply → logout |
| Auth-security | unit | `tests/auth/test_cookie_isolation.py` (new) | swapping `operator_session` into `auth_session` slot yields 401 |
| Auth-security | unit | `tests/auth/test_role_escalation.py` (new) | cannot forge `sessions.role='admin'` row via any exposed endpoint |
| Auth-security | unit | `tests/auth/test_session_fixation.py` (new) | login rotates session id; logout revokes; revoked id rejected |

Regression: must not break M2 magic-link tests (`tests/auth/test_verify.py`,
`test_logout.py`, `test_request_login.py`, `test_require_tenant_access.py`,
`test_session_mode.py`). Schema deltas are additive (`ALTER TABLE ADD
COLUMN` with DEFAULT) so M2 rows remain valid.

## 6. Open Questions (need A confirmation before coding)

- **OQ-1 — Cookie name reconciliation.** PRD CON-08 writes
  `admin_session vs operator_session`; code reality is `auth_session` vs
  `operator_session`. Options: (a) keep `auth_session` (no rename, one-line
  PRD errata); (b) rename to `admin_session` in one release (cost: admin
  portal + M2 tests). Recommend (a); flag for explicit A sign-off.
- **OQ-2 — Session TTL & idle timeout.** Admin sessions are 30d TTL (M2). Is
  operator 30d also fine, or shorter (e.g. 7d)? Idle-timeout (revoke after
  30m of no HTTP/WS activity) — in scope for M3 or M4+?
- **OQ-3 — Auth DB path name.** PRD CON-01 names
  `.autoservice/database/sessions.db`; code uses `auth.db`. Reconcile via
  PRD errata (keep `auth.db`) or rename file + schema migration?
- **OQ-4 — Operator password policy.** Minimum length, complexity rules,
  rotation? Punt to M4 with a hardcoded 12-char minimum for M3?
- **OQ-5 — Operator logout behavior on live WS.** When
  `/api/auth/operator/logout` runs, do we also `ws.close()` any open WS
  tied to that operator, or just invalidate future handshakes? Recommend
  active close (cleaner UX; drives offline-watcher immediately).
- **OQ-6 — RBAC tier assignment on invite.** Invite creator sets tier (admin
  choice at invite time) vs always default `responder` and edit after?
- **OQ-7 — `platform_admin` tier in matrix.** Do we represent it as a 4th tier
  in `Tier` Literal or keep it implicit (tier_of_session == 0 bypass in
  `require_tenant_access`)? Recommend implicit to keep matrix 3-row.
- **OQ-8 — Multi-admin delete-self guard.** Should an admin be blocked from
  deleting the last admin of a tenant? (Self-lockout risk.) Recommend **yes,
  with HTTP 409** — simple and matches every other SaaS.

## 7. Non-goals for M3

Per PRD §1.3 explicitly, and clarified here:

- OAuth / SSO / SAML / 2FA / passkey — M4+.
- Fine-grained permission matrix (e.g. per-conversation ACLs, per-skill
  grants, time-boxed permissions) — CON-02 locks M3 to 3-tier hardcoded; M4+.
- Password reset self-service flow via email — M4 (invite-link replacement is
  the M3 bridge; admin can re-invite on lockout).
- Rate limiting / brute-force lockout on login — M4 (same deferral as M2
  `auth.py:131`).
- Audit log surface (who invited whom, who hijacked when) — M4; E5.2
  introduces `proposal_audit` but not the full audit DB.
- Cross-tenant operator (one human with accounts in multiple tenants) —
  M4+; M3 assumes 1 operator row per (tenant, email).
- CSRF double-submit tokens / Origin checking beyond `SameSite=Lax` — M4.
- `/api/auth/operator/me` field extension for UI branding/avatar — M4.
- Admin-portal operator seat-count billing display — N/A in M3 (tier_2
  billing was DEFERRED_M4 with Epic E2).

---

*Design spec draft v0.1 · 2026-04-21 · blocks B-M3-1 dispatch until OQ-1..OQ-8
resolved or explicitly waived.*
