# Contract · M3 Epic E1 · Identity & RBAC

**Version**: v1.0 · **Frozen**: 2026-04-21
**Design spec**: [docs/superpowers/specs/2026-04-21-m3-e1-identity-rbac-design.md](../../superpowers/specs/2026-04-21-m3-e1-identity-rbac-design.md)
**Stories covered**: E1.1, E1.2, E1.3, E1.4, E1.5, E1.6

## 1. Cookie Names (CON-08)

| Cookie | Role | Source | Notes |
|---|---|---|---|
| `auth_session` | Admin (tenant_admin / master_admin) | M2 existing ([auth.py:307](../../../autoservice/auth.py#L307)) | **Keep M2 name** (OQ-E1-1 default) |
| `operator_session` | Operator (new in M3) | M3 E1.1 | Separate from admin; must not cross-contaminate |

Both cookies: `HttpOnly`, `SameSite=Lax`, `Secure` when HTTPS available, no `Domain` attr.

## 2. Session Storage (CON-01)

- **DB file**: `.autoservice/database/auth.db` (M2 existing; **keep** per OQ-E1-3 default)
- **Engine**: SQLite (CON-01 forbids Redis)

### 2.1 Schema Delta

```sql
-- NEW in M3
CREATE TABLE operators (
    id              TEXT PRIMARY KEY,           -- uuid4
    tenant_id       TEXT NOT NULL,              -- scope: per-tenant
    email           TEXT NOT NULL,
    display_name    TEXT,
    role            TEXT NOT NULL CHECK(role IN ('viewer','responder','admin')),
    status          TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),
    created_at      INTEGER NOT NULL,
    created_by      TEXT,                       -- admin email who created this operator
    UNIQUE(tenant_id, email)
);

CREATE TABLE operator_sessions (
    token           TEXT PRIMARY KEY,           -- cookie value (opaque random 32B)
    operator_id     TEXT NOT NULL REFERENCES operators(id) ON DELETE CASCADE,
    tenant_id       TEXT NOT NULL,              -- denormalized for fast lookup
    issued_at       INTEGER NOT NULL,
    expires_at      INTEGER NOT NULL,           -- issued_at + 24h (OQ-E1-2)
    idle_at         INTEGER NOT NULL,           -- last activity; expires if now - idle_at > 30min
    ip_created      TEXT,
    user_agent      TEXT
);

CREATE INDEX ix_operator_sessions_operator ON operator_sessions(operator_id);
CREATE INDEX ix_operator_sessions_idle ON operator_sessions(idle_at);

-- EXTEND existing login_tokens table to carry role metadata
ALTER TABLE login_tokens ADD COLUMN role TEXT NOT NULL DEFAULT 'tenant_admin'
    CHECK(role IN ('tenant_admin','operator'));
ALTER TABLE login_tokens ADD COLUMN invited_by TEXT;
```

Migration path: on first M3 boot, create tables if absent; add columns if absent. Idempotent.

## 3. HTTP Endpoints

### 3.1 Operator Auth

```
POST /api/auth/operator/login
  body:    { email, password } OR { magic_link_token }
  success: Set-Cookie: operator_session=<32B-hex>; HttpOnly; SameSite=Lax
           → 200 { operator_id, tenant_id, role }
  failure: 401 { error: "invalid_credentials" | "expired_token" | "operator_disabled" }

POST /api/auth/operator/logout
  cookie:  operator_session
  success: Set-Cookie: operator_session=; Max-Age=0
           disconnects any open /ws/operator with this session
           → 200 { ok: true }
  failure: 401 if no valid session

GET /api/auth/operator/me
  cookie:  operator_session
  success: 200 { operator_id, tenant_id, email, role, expires_at }
```

### 3.2 Operator CRUD (E1.2)

All endpoints require `admin` role on target tenant (RBAC §5).

```
POST   /api/admin/{tenant_id}/operators           → 201 { operator }
GET    /api/admin/{tenant_id}/operators           → 200 { operators: [...] }
GET    /api/admin/{tenant_id}/operators/{id}      → 200 { operator }
PATCH  /api/admin/{tenant_id}/operators/{id}      → 200 { operator }  (role | status | display_name)
DELETE /api/admin/{tenant_id}/operators/{id}      → 204
```

### 3.3 Invites (E1.3, E1.6)

```
POST /api/admin/{tenant_id}/invites
  body: { email, role: 'operator' | 'tenant_admin' }
  success: 201 { invite_url }   # one-time magic-link URL

POST /api/auth/accept-invite
  body: { token, password? }
  success: 200 { redirect_url, cookie set for issued role }
```

## 4. WS Handshake (E1.1)

Replace current `operator_id`-in-JSON auth at [web_gateway.py:480-485](../../../autoservice/web_gateway.py#L480-L485) with cookie validation:

```
WS /ws/operator
  handshake: server reads operator_session cookie from upgrade request headers
  validates: session exists, not expired, not idle-timed-out
  rejects:   close code 1008 (policy violation) if cookie missing/invalid/expired
  accepts:   binds WS conn to (operator_id, tenant_id)
  side-effect: updates operator_sessions.idle_at on every inbound message
```

NFR-01: handshake failure rate <1% — measured via new metric `ws.operator.handshake_fail_count`.

## 5. RBAC Matrix (E1.4, CON-02)

Hardcoded in `autoservice/rbac.py`. **Not runtime config**. Decision P95 <5ms per NFR-02 via frozenset + request.state caching.

| Action | viewer | responder | admin |
|---|---|---|---|
| View own-tenant conversations | ✅ | ✅ | ✅ |
| View own-tenant SLA dashboard | ✅ | ✅ | ✅ |
| Send copilot suggestion (side channel) | ❌ | ✅ | ✅ |
| `/hijack` conversation (takeover) | ❌ | ✅ | ✅ |
| `/release` hijacked conversation | ❌ | ✅ | ✅ |
| CRUD operators | ❌ | ❌ | ✅ |
| Send invites | ❌ | ❌ | ✅ |
| Edit classify_intent keywords | ❌ | ❌ | ✅ |
| Approve/reject dream proposals | ❌ | ❌ | ✅ |
| Apply dream proposals | ❌ | ❌ | ✅ (platform admin only for platform_level) |
| View compliance scan results | ❌ | ✅ | ✅ |
| Edit tenant config | ❌ | ❌ | ✅ |

Implementation:

```python
# autoservice/rbac.py
PERMISSIONS: frozenset[tuple[str, str]] = frozenset({
    ('viewer', 'view_own_tenant_conversations'),
    ('responder', 'view_own_tenant_conversations'),
    ('responder', 'send_copilot_suggestion'),
    ('responder', 'hijack'),
    # ... full matrix
})

def check(role: str, action: str) -> bool:
    return (role, action) in PERMISSIONS  # O(1)
```

FastAPI dependency:
```python
def require(action: str):
    def dep(request: Request) -> None:
        role = getattr(request.state, 'role', None)
        if not role or not check(role, action):
            raise HTTPException(403)
    return dep
```

## 6. Multi-Admin (E1.5)

Schema already supports (no UNIQUE on `sessions.tenant_id`). Add CRUD endpoints for admin management:

```
GET    /api/admin/{tenant_id}/admins                  (list co-admins; admin role required)
POST   /api/admin/{tenant_id}/admins                  (invite — delegates to §3.3 with role=tenant_admin)
DELETE /api/admin/{tenant_id}/admins/{email}          (remove; cannot remove last admin)
```

## 7. "Don't Do" List

1. **Don't** accept `operator_id` from JSON payload in WS handshake (closes M2 spoof gap at [web_gateway.py:480-485](../../../autoservice/web_gateway.py#L480-L485))
2. **Don't** share cookie value between admin and operator sessions
3. **Don't** put RBAC matrix in config files or DB — must be source-level per CON-02
4. **Don't** extend matrix with fine-grained permissions in M3 — that's M4+
5. **Don't** delete the last admin on a tenant (would orphan it)
6. **Don't** rename `auth_session` or `auth.db` in M3 — breaks M2 regression

## 8. Open Questions (Defaults Applied)

| OQ | Default |
|---|---|
| OQ-E1-1 admin cookie name | `auth_session` (keep M2) |
| OQ-E1-2 session TTL / idle / logout-drops-WS | 24h / 30min / yes |
| OQ-E1-3 DB path | `auth.db` (keep M2) |
| OQ-E1-6 magic-link reuse mechanism | shared backend generator, distinct cookie on consumption |

## 9. Test Requirements

Per design spec §Test Strategy. Highlights:
- `tests/auth/test_rbac_matrix.py` — full matrix coverage
- `tests/auth/test_rbac_perf.py` — P95 <5ms benchmark (NFR-02)
- `tests/web_gateway/test_ws_operator_auth.py` — cookie validation + rejection cases
- `tests/auth/test_operator_login.py` — login flow + TTL + idle timeout boundaries
- Security tests: session fixation, cookie scope, role escalation attempts
