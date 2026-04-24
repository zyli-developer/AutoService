# AutoService — Cloudflare Tunnel Demo Deployment Design

**Date:** 2026-04-24
**Target:** expose AutoService to the public Internet for small-scale
demo/trial use at `https://autoservice.ezagent.chat`.
**Host:** Mac Studio (personal), portable to Linux server later (M3 path).
**Status:** tunnel already created and running; Caddy + gateway wiring
pending implementation.

## 1. Scope and non-goals

In scope:
- Serve three existing React/Vite apps (`customer-chat`, `operator-console`,
  `admin-portal`) from a single public hostname using subpath mounting.
- Reverse-proxy `/api/*` and `/ws/*` to the existing FastAPI WebSocket
  gateway (`autoservice/web_gateway.py`).
- Magic-link login via Feishu Mail SMTP for admin and operator accounts.
- Cloudflare Access policies on admin/operator surface (path-selective).
- launchd supervision of gateway + Caddy + cloudflared on Mac Studio.
- One-command redeploy (`make public-reload`) that rebuilds frontends,
  restarts gateway, and restarts the tunnel.

Out of scope:
- Production-grade backup, SLO, on-call, CDN caching, multi-region, or
  active-active HA.
- Rewriting the backend's authorization model. We close the hole at the
  edge (Cloudflare Access) rather than auditing every endpoint.
- Replacing the existing `ezagent-voice` tunnel's behavior.
- Migrating the backend auth scheme away from cookies (`Path=/` stays).

## 2. Final decisions (recorded here so they don't drift)

| Decision | Choice | Notes |
|---|---|---|
| URL scheme | subpath under one hostname | `/site/`, `/console/`, `/admin/`; `/api/*`; `/ws/*` |
| Host | `autoservice.ezagent.chat` | CNAME flattening at CF edge |
| Deploy mode | built artifacts (D2) | `pnpm build` → `dist/`; Caddy serves static |
| Machine | Mac Studio (M3 path) | Linux-portable via documented diffs |
| Admin/operator auth | magic-link + SMTP, **plus per-email password login** | Feishu Mail; passwords auto-generated into `.autoservice/passwords.json` (temporary; scope revisable later) |
| Dangerous-endpoint gate | Cloudflare Access policy (X), managed via REST API | path-selective list below |
| CF Access management | config-as-code (`deploy/cloudflare-access/allowlist.yml` + `scripts/apply-cf-access.sh`) | cloudflared CLI does not manage Access; the CF REST API does |
| Tunnel | named `autoservice`, UUID `389c95d2-6066-437e-854f-8a09b2481259` | already created; independent config file |
| Caddy port | `CADDY_PORT=18080` on `127.0.0.1` | env-var; not 80/443 (coexist with pre-existing Caddy) |
| Gateway port | `8000` on `127.0.0.1` | dropped from `0.0.0.0`; public access only via Caddy |
| Process supervision | launchd user agents | auto-start, auto-restart |
| Redeploy semantics | one command = rebuild + restart gateway + restart cloudflared | ensures code and long-lived WS both cycle |

## 3. Architecture

```
Public Internet
      │
      ▼
autoservice.ezagent.chat           (Cloudflare edge TLS)
      │
      ▼
┌──────────────────────────────────┐
│ Cloudflare Access                │   policy: email allowlist for
│ (path-selective enforcement)     │   /admin, /console, /ws/{operator,admin}
└──────────────┬───────────────────┘   and dangerous /api/* prefixes
               │
               ▼
┌──────────────────────────────────┐
│ cloudflared  (named: autoservice)│   config: ~/.cloudflared/autoservice.yml
│ launchd: com.autoservice.cloudflared.plist
│ metrics:  127.0.0.1:20242       │
│ origin:   http://127.0.0.1:18080│
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────┐
│ Caddy (v2.11.2, /usr/local/bin/caddy)                │
│ Listen: http://127.0.0.1:${CADDY_PORT=18080}         │
│ admin off      auto_https off                        │
│ ──────────────────────────────────────────────────── │
│ /           → 302 /site/                             │
│ /site*      → file_server customer-chat/dist         │
│ /console*   → file_server operator-console/dist      │
│ /admin*     → file_server admin-portal/dist          │
│ /api/*      → reverse_proxy 127.0.0.1:8000           │
│ /ws/*       → reverse_proxy 127.0.0.1:8000           │
│ /robots.txt → "User-agent: *\nDisallow: /"           │
│ /_caddy_health → "ok"                                │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
          ┌────────────────────────────────┐
          │ uvicorn gateway                │
          │ bind 127.0.0.1:8000            │
          │ launchd: com.autoservice.gateway.plist
          │ AUTH_DEV_MODE unset            │
          │ PLACEHOLDER_ENABLED=0          │
          │ CORS_EXTRA_ORIGINS=https://autoservice.ezagent.chat
          │ --proxy-headers --forwarded-allow-ips=127.0.0.1
          └────────────────────────────────┘
```

### 3.1 Why `/console` not `/tenant`

`/tenant/<tid>/...` is an established in-app path in all three SPAs
(`customer-chat/src/main.tsx:121`, `operator-console/src/main.tsx:122`,
`admin-portal/src/App.tsx:68-77`, plus the gateway's
`TenantContextMiddleware` at `autoservice/web_gateway.py:347-367`).
Mounting the operator-console SPA at `/tenant/*` would shadow every
in-app `/tenant/<tid>/...` link in the customer and admin apps. We
use `/console/` instead; each SPA keeps its internal router rooted
at the mount path (`basename="/site"`, `"/console"`, `"/admin"`), so
internal navigation to `/tenant/<tid>/chat` resolves as
`/site/tenant/<tid>/chat` etc.

### 3.2 Why loopback alone does not protect the backend

A request to `https://autoservice.ezagent.chat/api/master/tenants`
traverses: client → CF edge → cloudflared → Caddy → `reverse_proxy
127.0.0.1:8000`. Every hop stays on the machine, and uvicorn receives
the request over loopback exactly as if a local client had dialed
it. Binding uvicorn to `127.0.0.1` prevents LAN peers from reaching
`8000` directly; it does **not** prevent public requests that arrive
through Caddy.

Therefore we must gate dangerous paths at the edge (Cloudflare Access)
because the existing backend has a large surface of admin/master
endpoints with no authentication (`api_routes.py` 405, 1466, 1499,
1548, 1882, etc., and `web_gateway.py:727-728` for `/ws/admin`).

## 4. Cloudflare Tunnel

### 4.1 Config file — `~/.cloudflared/autoservice.yml`

```yaml
tunnel: 389c95d2-6066-437e-854f-8a09b2481259
credentials-file: /Users/h2oslabs/.cloudflared/389c95d2-6066-437e-854f-8a09b2481259.json
metrics: 127.0.0.1:20242
logfile: /Users/h2oslabs/Workspace/AutoService/.autoservice/logs/cloudflared.log
loglevel: info

ingress:
  - hostname: autoservice.ezagent.chat
    service: http://127.0.0.1:18080
    originRequest:
      noTLSVerify: true
      connectTimeout: 30s
  - service: http_status:404
```

Coexists with pre-existing `ezagent-voice` tunnel (UUID `ef0247e4-...`)
that uses `~/.cloudflared/config.yml` (default path) for `voice.ezagent.chat`.
Explicit `metrics:` binding prevents the two cloudflared processes from
racing for an auto-picked port.

### 4.2 DNS

CNAME `autoservice.ezagent.chat` → `389c95d2-6066-437e-854f-8a09b2481259.cfargotunnel.com`,
established via `cloudflared tunnel route dns --overwrite-dns 389c95d2-... autoservice.ezagent.chat`.

Note: always refer to tunnels by UUID, not name. The cloudflared name cache
has a known quirk where a freshly-created tunnel's name can resolve to a
sibling UUID on the first few calls.

### 4.3 Cloudflare Access — path-selective

A single Cloudflare Access application covers the hostname with
path matchers. Access policy: "email is in allowlist", with
identity providers = email OTP (minimum) or Google SSO.

Paths **with** Access enforcement (must authenticate to reach Caddy):
- `/admin*`
- `/console*`
- `/ws/operator`, `/ws/admin`
- `/api/master/*`, `/api/admin/*`, `/api/management/*`,
  `/api/proposals/*`, `/api/dream/*`, `/api/onboard/*`,
  `/api/canary/*`, `/api/compliance/*`, `/api/rehearsal/*`,
  `/api/billing/*`, `/api/metrics/*`, `/api/cc_pool/*`,
  `/api/sla/*`, `/api/conversations/active`

Paths **without** Access (fully public):
- `/site*`
- `/api/auth/*` — magic-link request/verify endpoints
- `/api/tenants/*` — customer sandbox reads
- `/ws/customer`

The Access application is managed via **config-as-code**, not the
Cloudflare dashboard. `cloudflared` CLI does not manage Access
applications or policies; it only manages tunnels. The CF REST API
does, and we wrap it:

- `deploy/cloudflare-access/allowlist.yml` — tracked in git; lists
  guarded paths, identity provider preference (email OTP), session
  duration, and the authorized email list (see §4.5).
- `scripts/apply-cf-access.sh` — reads the yml plus `.cf-access.env`
  (which holds `CF_API_TOKEN`, `CF_ACCOUNT_ID`, `CF_ZONE_ID`),
  idempotently upserts the Access application and its single policy
  via `POST/PUT /accounts/{id}/access/apps` and `.../policies`.
- `make access-apply` — the Makefile target users invoke after
  editing the yml.
- Degraded mode: if `CF_API_TOKEN` is unset, the script prints the
  equivalent `curl` commands for manual execution or instructs the
  user to complete the change in the dashboard. The yml file remains
  the source of truth either way.

Required CF API token scope: `Account: Access: Apps and Policies:
Edit`, plus `Zone: Zone: Read` for the account hosting
`ezagent.chat`. Stored in `.cf-access.env` (added to `.gitignore`).

### 4.4 Identity model — always email, never password

The backend has no password-based login. `autoservice/operator_routes.py:9`
documents this explicitly ("Magic-link only for M3 operator login (no
password field)"), and a grep across all three frontends shows zero
`password` input fields. Both CF Access and the in-app magic-link
flow key off email:

| Gate | Purpose | How it learns the email |
|---|---|---|
| Cloudflare Access | Decides "can this request even reach Caddy?" | User enters email on CF's login page, receives OTP, clicks confirm. CF forwards the email to origin via `Cf-Access-Authenticated-User-Email` header and a signed `Cf-Access-Jwt-Assertion` JWT. |
| In-app magic-link | Decides "does this user get an `admin_session` / `operator_session` cookie?" | User enters email on `/admin/login` or `/console/login`, backend emails a single-use link, click mints the cookie. Email must be in `.autoservice/config.local.yaml` `auth.admin_emails`. |

A trial-customer admin must therefore be added to **two** allowlists:

1. **CF Access policy** — Cloudflare Zero Trust dashboard → Access →
   Applications → `autoservice.ezagent.chat` → Edit Policy → add email.
   (Instant; no redeploy.)
2. **`auth.admin_emails`** in `.autoservice/config.local.yaml` —
   then `make public-reload` so the gateway rereads the config.

The customer-chat surface (`/site*`, `/api/auth/*`, `/api/tenants/*`,
`/ws/customer`) is intentionally ungated: anonymous visitors can chat
with support, which is the core demo experience. No email is captured
for these users.

This double-allowlist is documented step-by-step in
`docs/deploy/public-tunnel-runbook.md` (Adding a trial customer).

### 4.5 Initial email allowlist

Both CF Access policy and `auth.admin_emails` start with this set:

```
lin.yilun@h2oslabs.com
huang.jiajia@h2oslabs.com
yao.shengyue@h2oslabs.com
chen.ruihua@h2oslabs.com
autoservice@h2oslabs.com
```

`autoservice@h2oslabs.com` is a shared Feishu-forwarded alias that
reaches the whole team. It also holds the dev password credential
described in §7.6.

### 4.6 Password login — per-email, auto-generated, file-backed (temporary)

Speeds up dev/QA and gives trial customers a fallback path when
Feishu Mail delivery is slow or blocked by their corporate filter.
Every email on `auth.admin_emails` gets a password.

**Storage — `.autoservice/passwords.json`** (new file, mode 0600,
under an already-gitignored directory):

```json
{
  "version": 1,
  "updated_at": "2026-04-24T14:15:00Z",
  "entries": [
    {
      "email": "lin.yilun@h2oslabs.com",
      "password_bcrypt": "$2b$12$...",
      "generated_at": "2026-04-24T14:15:00Z"
    }
  ]
}
```

This file is deliberately separate from `config.local.yaml` so
(a) rotating passwords does not touch the SMTP / CF config, and
(b) a future migration to a real user table (`users` + `password_hash`
column) only has to read the file once and discard it.

**Bootstrap script — `scripts/generate-admin-passwords.sh`:**
- Reads `auth.admin_emails` from `config.local.yaml`.
- For every email WITHOUT an existing entry in `passwords.json`:
  generates an ≥ 16-char random password, bcrypt-hashes (cost 12),
  appends an entry.
- **Prints all newly-generated plaintext passwords to stdout once,
  with a warning that they will not be shown again.**
- Leaves already-existing entries untouched (idempotent).
- Creates `.autoservice/passwords.json` with mode 0600 if it does
  not exist.

**Endpoint — `POST /api/auth/password-login`:**

- Body: `{"email": str, "password": str}`.
- If `passwords.json` is absent → 404 (feature disabled).
- If the email is not in `entries` → run a dummy bcrypt check
  (constant-time defense) and return 401.
- If the email is in `entries` but bcrypt verify fails → 401,
  increment per-IP failed-attempt counter.
- If ≥ 5 failures in a 10-minute window for the client IP → 429.
- Success → mint an `auth_session` cookie identical in attributes
  to the magic-link flow (`HttpOnly`, `Secure`, `SameSite=Lax`,
  `path=/`, 7-day TTL).

**Frontend** (`admin-portal/src/components/auth/LoginPage.tsx`):
- Magic-link remains the primary action at the top of the form.
- Below it, a collapsible "Password login" section with email +
  password fields. No email is pre-filled (user types their own).

**Rationale:**
- "All admins can use passwords" is the user's explicit scope
  decision: for trial customers this removes SMTP as a critical
  path dependency during demos.
- Storage in a standalone JSON file is a deliberate stub, intended
  to be replaced by a proper `users` table with password column
  after the demo phase. The on-disk file is trivial to read once
  and migrate.
- Rate limiting per IP mitigates brute-force; lockout is still
  coarse (per-IP, not per-account) — acceptable for demo scale.

**Operator console** (`/console/*`) still does NOT get password
login — magic-link only. Rationale: operator accounts are per-tenant
and per-user; a shared password would defeat attribution and is not
aligned with how operator sessions are expected to be audited.

## 5. Caddy

### 5.1 Coexistence with existing Caddy

`/usr/local/bin/caddy` v2.11.2 is already running on this Mac (PID 54798
at design time) listening on `*:80`, `*:443`, and `127.0.0.1:2019` (admin API),
plus `*:6697`. That instance belongs to unrelated services and must not be
disturbed. Our new Caddy runs as a second process with:

- `admin off` in the global block — does not claim `:2019`.
- `auto_https off` — does not claim `:80`/`:443` and does not attempt ACME.
- Binds only `127.0.0.1:${CADDY_PORT}` — cloudflared is the only client.

### 5.2 Caddyfile — `deploy/caddy/Caddyfile.public`

```caddyfile
{
    admin off
    auto_https off
    log {
        output file {env.AUTOSERVICE_ROOT}/.autoservice/logs/caddy.log {
            roll_size 10mb
            roll_keep 10
        }
        format json
    }
}

http://:{env.CADDY_PORT} {
    encode zstd gzip

    @root path /
    redir @root /site/ 302

    handle /robots.txt {
        respond "User-agent: *\nDisallow: /\n" 200
    }

    handle /_caddy_health {
        respond "ok" 200
    }

    handle_path /site/* {
        root * {env.AUTOSERVICE_ROOT}/frontend/apps/customer-chat/dist
        try_files {path} /index.html
        file_server
    }
    redir /site /site/ 308

    handle_path /console/* {
        root * {env.AUTOSERVICE_ROOT}/frontend/apps/operator-console/dist
        try_files {path} /index.html
        file_server
    }
    redir /console /console/ 308

    handle_path /admin/* {
        root * {env.AUTOSERVICE_ROOT}/frontend/apps/admin-portal/dist
        try_files {path} /index.html
        file_server
    }
    redir /admin /admin/ 308

    handle /api/* {
        reverse_proxy 127.0.0.1:8000 {
            header_up X-Forwarded-Host {host}
            header_up X-Forwarded-Proto https
        }
    }

    handle /ws/* {
        reverse_proxy 127.0.0.1:8000 {
            header_up X-Forwarded-Host {host}
            header_up X-Forwarded-Proto https
        }
    }

    handle {
        respond "not found" 404
    }
}
```

The `redir /admin /admin/ 308` companions are necessary because
`handle_path /admin/*` does not match `GET /admin` (without the
trailing slash); Vite's built `index.html` references assets at
`/admin/assets/...` and the browser needs to be on a `/admin/` URL
for relative resolution to work cleanly.

### 5.3 Environment required at launch

- `CADDY_PORT=18080`
- `AUTOSERVICE_ROOT=/Users/h2oslabs/Workspace/AutoService`

## 6. Frontend build

### 6.1 Vite `base` parameterization

Each of the three `vite.config.ts` files adds one line:

```ts
base: process.env.VITE_MOUNT_PATH ?? '/',
```

Set via environment at build time:

```bash
VITE_MOUNT_PATH=/site/    pnpm --filter @autoservice/customer-chat    build
VITE_MOUNT_PATH=/console/ pnpm --filter @autoservice/operator-console build
VITE_MOUNT_PATH=/admin/   pnpm --filter @autoservice/admin-portal     build
```

Local dev (`make dev-start`) does not set `VITE_MOUNT_PATH`, so
`base` stays `'/'` and the existing Vite dev proxy continues to work
unchanged.

### 6.2 React Router basename

Each app's top-level `<BrowserRouter>` (or equivalent) reads
`import.meta.env.BASE_URL` (Vite injects this from `base`) as
`basename`. Existing in-app routes like `/tenant/:tenantId/chat`
continue to resolve as `{basename}/tenant/<tid>/chat`.

### 6.3 Hardcoded-URL cleanup (required)

Three files hardcode `:8000`. Replace with same-origin relative
fetches / location-derived WS URLs:

| File | Current | Change |
|---|---|---|
| `frontend/apps/admin-portal/src/api.ts:4` | `const API_BASE = \`http://${window.location.hostname}:8000\`` | `const API_BASE = import.meta.env.VITE_API_BASE ?? ''` |
| `frontend/apps/admin-portal/src/components/wizard/SandboxReady.tsx:36` | same pattern | same replacement |
| `frontend/apps/operator-console/src/components/WorkspacePage.tsx:20` | `ws://${hostname}:8000/ws/operator?...` | mirror `customer-chat/src/App.tsx`'s `resolveWsBase()` pattern — read `VITE_WS_BASE`, fall back to `${proto}//${host}` |

Public build leaves both `VITE_API_BASE` and `VITE_WS_BASE` unset →
fetches become `'/api/...'` (same-origin), WS becomes
`wss://autoservice.ezagent.chat/ws/operator` — both traverse Caddy.

### 6.4 Robots / noindex

Append `<meta name="robots" content="noindex, nofollow">` to all
three `index.html` files so even if Caddy's `/robots.txt` is ignored,
the pages themselves opt out of indexing.

## 7. Backend

### 7.1 Bind loopback; trust CF tunnel

Add a new Makefile target `run-gateway-public`:

```makefile
run-gateway-public:
	@mkdir -p .autoservice/logs
	PLACEHOLDER_ENABLED=0 \
	CORS_EXTRA_ORIGINS=https://autoservice.ezagent.chat \
	uv run uvicorn autoservice.web_gateway:create_app \
		--factory --host 127.0.0.1 --port $${DEMO_PORT:-8000} \
		--proxy-headers --forwarded-allow-ips="127.0.0.1" \
		--log-level info \
		2>&1 | tee -a .autoservice/logs/gateway.log
```

`--proxy-headers --forwarded-allow-ips="127.0.0.1"` is required so
that `request.url.scheme` reflects `https` (from Caddy's
`X-Forwarded-Proto`) and `Secure` cookie attributes are set correctly.

### 7.2 CORS parameterization

`autoservice/web_gateway.py:57-59` currently hardcodes
`localhost:5173..5179`. Add env append:

```python
_CORS_ORIGINS = [f"http://localhost:{p}" for p in range(5173, 5180)]
_extra = os.environ.get("CORS_EXTRA_ORIGINS", "").strip()
if _extra:
    _CORS_ORIGINS.extend(o.strip() for o in _extra.split(",") if o.strip())
```

Public deploy sets `CORS_EXTRA_ORIGINS=https://autoservice.ezagent.chat`.
Subpath B scheme is same-origin so browser CORS usually isn't
triggered; this is belt-and-suspenders for any fetches that may be
upgraded to cross-origin later.

### 7.3 `AUTH_DEV_MODE` leak defenses

Three layers:
- `scripts/public-up.sh` opens with `unset AUTH_DEV_MODE` before any
  service is started.
- The launchd plist declares `EnvironmentVariables` explicitly; it
  does not inherit the login shell's environment. `AUTH_DEV_MODE` is
  simply not in the list.
- Gateway import-time check (`api_routes.py:2041`) already freezes
  `DEV_MODE_ENABLED` at start; in the public target we verify at
  `/api/admin/info` startup probe that `AUTH_DEV_MODE` disabled is
  reflected (`/api/auth/dev-mode` returns 404 or `{"enabled": false}`).

### 7.4 SMTP and admin config — `.autoservice/config.local.yaml`

Rendered by `scripts/install-smtp-config.sh` from `.smtp.env`:

```yaml
auth:
  admin_emails:
    - lin.yilun@h2oslabs.com
    - huang.jiajia@h2oslabs.com
    - yao.shengyue@h2oslabs.com
    - chen.ruihua@h2oslabs.com
    - autoservice@h2oslabs.com
    # add trial-customer admin emails here (sync with CF Access allowlist)
  smtp:
    host: smtp.feishu.cn
    port: 587
    user: autoservice@h2oslabs.com
    password: <from .smtp.env>
    from: "AutoService <autoservice@h2oslabs.com>"
    starttls: true
```

Passwords are stored in a separate file, `.autoservice/passwords.json`
(see §4.6). That separation exists so rotating passwords does not
touch SMTP / CF / tenant config and so the eventual migration to a
database `users` table is clean.

The script reads `.smtp.env`, expands into the YAML, and writes with
`chmod 600`. `.autoservice/` is already `.gitignore`'d, and `.smtp.env`
is now `.gitignore`'d too.

### 7.5 `scripts/generate-admin-passwords.sh`

Idempotent password bootstrap:

1. Read `.autoservice/config.local.yaml::auth.admin_emails`.
2. Load existing `.autoservice/passwords.json` if present; else start
   from `{"version": 1, "entries": []}`.
3. For each email not already in `entries`: generate a random password
   using `python -c 'import secrets; print(secrets.token_urlsafe(16))'`
   (≥ 21 chars after base64 encoding), bcrypt-hash it (cost 12), and
   append an entry with `generated_at=<UTC ISO>`.
4. Write `passwords.json` with mode 0600.
5. **Print the plaintext passwords once**, grouped by email, with a
   prominent banner: "NOT SHOWN AGAIN — distribute securely".
6. Emit "run `make public-reload` if the gateway is already up".

Passwords for emails already on the list are never regenerated by
this script. A separate (future) `scripts/rotate-admin-password.sh`
can delete a single entry and re-run generation if forced rotation
is needed.

### 7.6 Cookie `Path=/` retained

Every endpoint that sets cookies today uses `path="/"` (6 call
sites in `operator_routes.py` and `api_routes.py`). We do not change
this. Rationale: same-origin subpath deployment means admin, operator,
and customer JS all share cookies, but Cloudflare Access (§4.3)
prevents unauthenticated JS running on `/admin`/`/console` in the
first place, and `autoservice/rbac.py:118-164` provides the
least-privilege fallback at the route layer.

If we migrate to subdomains later (A scheme), cookie `Path=/admin`,
`Path=/console` become necessary to prevent cross-app cookie reads.
That migration remains a follow-up; the design path-parameterizes
Vite `base` so the frontend half of the migration is zero code change.

## 8. Process supervision

### 8.1 launchd agents (phase 1)

Three user agents, installed into `~/Library/LaunchAgents/` by
`make public-install`:

- `com.autoservice.gateway.plist` — runs `make run-gateway-public`
- `com.autoservice.caddy.plist` — runs `/usr/local/bin/caddy run --config deploy/caddy/Caddyfile.public`
  with `CADDY_PORT=18080` and `AUTOSERVICE_ROOT=<repo>` in
  `EnvironmentVariables`
- `com.autoservice.cloudflared.plist` — runs
  `/opt/homebrew/bin/cloudflared tunnel --config ~/.cloudflared/autoservice.yml run 389c95d2-6066-437e-854f-8a09b2481259`

Common plist fields:
- `RunAtLoad = true`
- `KeepAlive = true` (restart on crash)
- `WorkingDirectory = <repo root>` (so relative paths in Caddyfile resolve)
- `EnvironmentVariables` explicit whitelist — never inherits shell env
- `StandardOutPath` / `StandardErrorPath` → `.autoservice/logs/<svc>.err.log`

Templates live in `deploy/launchd/*.plist.template` with
`{{AUTOSERVICE_ROOT}}` and `{{USER}}` placeholders; `make public-install`
renders and `launchctl bootstrap gui/$(id -u)`-loads them.

### 8.2 Reload semantics

`make public-reload` sequence:
1. `make public-build` — rebuild all three frontends
2. `launchctl kickstart -k gui/$(id -u)/com.autoservice.gateway`
   — restart gateway (picks up new Python code if present)
3. Caddy does NOT need restart — new static files are picked up
   on next request because `file_server` reads from disk
4. `launchctl kickstart -k gui/$(id -u)/com.autoservice.cloudflared`
   — restart tunnel, per user requirement: long-lived WS sessions
   must be dropped so clients reconnect against the new gateway

### 8.3 Panic-off

`make public-panic`: stops cloudflared immediately, which makes the
hostname unreachable on the public Internet within ~2 seconds
(CF edge loses the origin). Gateway and Caddy may stay up for
post-mortem inspection.

## 9. Makefile surface

New targets:

| Target | Purpose |
|---|---|
| `public-build` | `pnpm build` × 3 with `VITE_MOUNT_PATH` set |
| `public-install` | Install launchd plists (idempotent) |
| `public-uninstall` | Unload + remove launchd plists |
| `public-up` | Bootstrap the three agents (no plists needed; PID files instead; useful for debugging before committing to launchd) |
| `public-down` | Kill PIDs cleanly |
| `public-reload` | Rebuild + restart gateway + restart cloudflared |
| `public-panic` | Stop cloudflared only |
| `public-smoke` | HTTP + WS smoke checks against the public hostname |
| `public-status` | launchctl print + pgrep summary |
| `access-apply` | Apply `deploy/cloudflare-access/allowlist.yml` to CF (degrades gracefully without token) |
| `generate-admin-passwords` | Interactive wrapper for `scripts/generate-admin-passwords.sh` |

Logs stay in `.autoservice/logs/{gateway,caddy,cloudflared}.log`;
runbook documents `tail -F` commands rather than wrapping them.

## 10. Rollout procedure

1. Refactor frontend: Vite `base`, three hardcoded-`:8000` fixes.
2. `pnpm test && pnpm typecheck` — confirm no regressions.
3. `make dev-start` sanity — localhost flow still works.
4. Render `.autoservice/config.local.yaml` from `.smtp.env`.
5. Configure Cloudflare Access application on the dashboard
   (path matchers per §4.3; email allowlist at least includes
   `allen.woods@outlook.com`).
6. `make public-build`.
7. `make public-install` (loads launchd agents).
8. `make public-smoke` — expect all 200/101 except the
   access-gated paths which should 302 to CF Access login.
9. Manual QA via `agent-browser`:
   - `https://autoservice.ezagent.chat/site/` — customer chat loads,
     can send a message, WS receives agent reply.
   - `https://autoservice.ezagent.chat/admin/` — CF Access login
     prompt, after email OTP the admin UI loads, magic-link login
     succeeds (real SMTP email received), admin dashboard renders.

## 11. Portability (M3 → Linux)

When we later migrate off Mac Studio to a Linux box:

| Component | Mac Studio | Linux |
|---|---|---|
| cloudflared | Homebrew, `/opt/homebrew/bin/cloudflared` | `cloudflared` deb, `/usr/bin/cloudflared` |
| Caddy | `/usr/local/bin/caddy` (manual install) | `apt install caddy`, `/usr/bin/caddy` |
| Process supervisor | launchd user agents | systemd user units |
| `AUTOSERVICE_ROOT` | `/Users/h2oslabs/Workspace/AutoService` | `/opt/autoservice` (suggested) |
| cloudflared tunnel UUID | unchanged | unchanged (tunnel lives on CF side) |
| cloudflared credentials JSON | copy file | copy file |
| Cloudflare Access policy | unchanged | unchanged |

Caddyfile, cloudflared config, and Makefile all use
environment-variable-driven paths, so the only touchpoints are
the binary paths and the plist-→-unit translation. Estimated
migration cost: half a day.

## 12. Risks and open items

| # | Risk / Item | Mitigation |
|---|---|---|
| R1 | CF Access allowlist maintenance as trial customers join | Runbook step; each new admin email added via CF dashboard |
| R2 | Cookie `Path=/` means cross-app cookie sharing on the same origin | Accepted for demo; CF Access prevents unauthenticated JS from being served on admin/console paths, closing the realistic exploit path |
| R3 | Cloudflare WS idle timeout (~100s on free) | uvicorn default `ws_ping_interval=20s` keeps connection alive; verify under load |
| R4 | `AUTH_DEV_MODE=1` leaking from user shell into launchd | Triple-defended (§7.3): script unset, plist explicit env, gateway import-time freeze |
| R5 | SQLite DBs (`conversations.db`, `auth.db`) not backed up | Out of scope for this design; future addition via launchd hourly `sqlite3 .backup` job |
| R6 | Log growth unbounded for gateway/cloudflared | Caddy handles its own rotation (`roll_size 10mb roll_keep 10`); gateway + cloudflared logs require separate `newsyslog` / manual rotation — noted in runbook |
| R7 | CF dashboard rate-limit configuration for `/api/dream/trigger`, `/api/auth/request-login` | Documented in runbook; tuned post-first-load |
| R8 | Frontend test suites may still reference old URL patterns | `make public-build` blocks on tests; pre-push run enforces green |
| R9 | cloudflared CLI "already configured to route to your tunnel" bug when querying by name | Runbook mandates UUID-based invocation always |

## 13. Known deviations from code-reviewer recommendations

The code-reviewer (agent run on 2026-04-24) flagged these that we
knowingly chose not to adopt for this phase:

- **Per-path cookie scoping** (reviewer §2 / §6.4 walk-back): deferred
  to subdomain migration. CF Access is our primary control for
  admin/console surface.
- **Dedicated `run-gateway-lan`** (reviewer §11): not needed; public
  deploy uses `run-gateway-public`, dev continues to use `run-gateway`
  as-is (`0.0.0.0` binding is a known LAN exposure on dev machines
  and out of scope here).
- **In-app `PublicModeGuardMiddleware`** (reviewer option Y): rejected
  in favor of CF Access. Rationale: a CF policy tweak is faster to
  iterate on than a Python middleware during the trial.
- **SQLite hourly backup** (reviewer §A): deferred — demo does not
  persist irreplaceable state.
- **Rate limiting at CF dashboard level** (reviewer §F): runbook item,
  not design-enforced — trial traffic is low and we tune reactively.

## 14. File manifest

New:
- `deploy/caddy/Caddyfile.public`
- `deploy/cloudflared/autoservice.yml.example` — checked-in template
  (real file at `~/.cloudflared/autoservice.yml`, outside git)
- `deploy/cloudflare-access/allowlist.yml` — path matchers + email list
- `deploy/launchd/com.autoservice.gateway.plist.template`
- `deploy/launchd/com.autoservice.caddy.plist.template`
- `deploy/launchd/com.autoservice.cloudflared.plist.template`
- `scripts/public-build.sh`
- `scripts/public-up.sh`
- `scripts/public-down.sh`
- `scripts/public-reload.sh`
- `scripts/public-smoke.sh`
- `scripts/public-panic.sh`
- `scripts/install-launchd.sh`
- `scripts/uninstall-launchd.sh`
- `scripts/install-smtp-config.sh`
- `scripts/apply-cf-access.sh`
- `scripts/generate-admin-passwords.sh`
- `docs/deploy/public-tunnel-runbook.md`

Backend additions:
- `autoservice/password_login.py` — the `/api/auth/password-login`
  route + bcrypt verify + lockout logic.
- Router wiring in `autoservice/web_gateway.py` to include it.
- One new dep in `pyproject.toml`: `bcrypt>=4,<5` (pure-Python fallback
  available; no native build needed).

Modified:
- `frontend/apps/customer-chat/vite.config.ts`
- `frontend/apps/operator-console/vite.config.ts`
- `frontend/apps/admin-portal/vite.config.ts`
- `frontend/apps/admin-portal/src/api.ts`
- `frontend/apps/admin-portal/src/components/wizard/SandboxReady.tsx`
- `frontend/apps/admin-portal/src/components/auth/LoginPage.tsx` — add collapsed password-login section
- `frontend/apps/operator-console/src/components/WorkspacePage.tsx`
- `frontend/apps/*/index.html` (× 3, add robots meta)
- `autoservice/web_gateway.py` (CORS_EXTRA_ORIGINS, router include)
- `Makefile` (new public-* targets + access-apply + generate-admin-passwords)
- `.gitignore` (+ `.cf-access.env`)

Not in git:
- `~/.cloudflared/autoservice.yml`
- `~/.cloudflared/389c95d2-6066-437e-854f-8a09b2481259.json`
- `.smtp.env`
- `.cf-access.env`
- `.autoservice/config.local.yaml` (rendered from `.smtp.env`)
- `~/Library/LaunchAgents/com.autoservice.*.plist`
