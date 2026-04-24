# Public Tunnel Runbook — autoservice.ezagent.chat

Day-2 operations for the Cloudflare-Tunnel demo deployment.

- Spec: `docs/superpowers/specs/2026-04-24-cloudflare-tunnel-demo-deploy-design.md`
- Plan: `docs/superpowers/plans/2026-04-24-cloudflare-tunnel-demo-deploy.md`

## Architecture (TL;DR)

```
Public → CF edge → cloudflared (tunnel "autoservice") → Caddy 127.0.0.1:18080
                                                                  ├── /site/*    → customer-chat/dist
                                                                  ├── /console/* → operator-console/dist
                                                                  ├── /admin/*   → admin-portal/dist
                                                                  ├── /api/*     → uvicorn 127.0.0.1:8000
                                                                  └── /ws/*      → uvicorn 127.0.0.1:8000
```

CF Access policy gates `/admin*`, `/console*`, `/ws/{operator,admin}`, and
the dangerous `/api/*` prefixes (`master`, `admin`, `management`, `proposals`,
`dream`, `onboard`, `canary`, `compliance`, `rehearsal`, `billing`, `metrics`,
`cc_pool`, `sla`, `conversations/active`). The customer-chat surface is
fully public.

## First-time setup (fresh clone)

```bash
# 1. Framework setup (plugin skills, runtime dirs).
make setup

# 2. Cloudflared config. This must live at ~/.cloudflared/autoservice.yml
#    (NOT the default config.yml, which belongs to the ezagent-voice tunnel).
#    Template: deploy/cloudflared/autoservice.yml.example.
#    Credentials JSON: ~/.cloudflared/<uuid>.json (downloaded during
#    `cloudflared tunnel create autoservice`).

# 3. DNS route. Always use UUID, not name (cloudflared has a name-cache bug).
cloudflared tunnel route dns --overwrite-dns \
    389c95d2-6066-437e-854f-8a09b2481259 autoservice.ezagent.chat

# 4. SMTP credentials. Create .smtp.env (gitignored):
#       SMTP_HOST=smtp.feishu.cn
#       SMTP_PORT=587
#       SMTP_USER=autoservice@h2oslabs.com
#       SMTP_FROM=autoservice@h2oslabs.com
#       SMTP_PASSWORD=<Feishu mail password>
#       SMTP_STARTTLS=true
make install-smtp-config

# 5. Admin passwords (auto-generated; plaintext shown once — save them):
make generate-admin-passwords

# 6. CF Access policy. Create .cf-access.env (gitignored):
#       CF_API_TOKEN=cfat_...
#       CF_ACCOUNT_ID=<account uuid>
#       CF_ZONE_ID=<zone uuid for ezagent.chat>
#    Then:
make access-apply
# If you don't have an API token, the script prints curl commands for
# the dashboard-based path (see §"Applying CF Access manually").

# 7. Build static assets for public mounting.
make public-build

# 8. Launch (manual mode while you iterate):
make public-up
# OR install launchd agents for auto-restart + reboot-survivability:
make public-install

# 9. Acceptance checks.
make public-smoke
```

## Adding a trial customer

Two allowlists must match, or the user is either stopped at the edge or
denied inside the app.

1. **Cloudflare Access** — edit `deploy/cloudflare-access/allowlist.yml`,
   add the email under `allowed_emails:`, then `make access-apply`.
2. **In-app admin allowlist** — edit `.autoservice/config.local.yaml`,
   add the email under `auth.admin_emails:`.
3. **(Optional) Password login** — `make generate-admin-passwords` creates
   a password for the new email (idempotent; existing entries untouched).
4. **Reload** — `make public-reload` so the gateway rereads the config.
5. **Notify** the customer:
   - URL: `https://autoservice.ezagent.chat/admin/`
   - First visit: CF emails an OTP; entering it lands them on the admin
     login page.
   - Login: either the magic-link path (email → click) or the collapsed
     "Password login" section using the password you distributed.

## Reload after code merge

```bash
git pull
make public-reload
make public-smoke
```

`public-reload` restarts gateway **and** cloudflared. The tunnel restart
drops long-lived WS sessions so clients reconnect against the new code —
without this, old `/ws/customer` sockets could linger and serve stale
behavior.

## Emergency stop

- `make public-panic` — stops cloudflared only. The hostname returns
  5xx from the CF edge within ~2 seconds. Caddy and gateway stay up
  for post-mortem.
- `make public-down` — stops all three services cleanly.

## Logs

- `.autoservice/logs/gateway.log` — uvicorn
- `.autoservice/logs/caddy.log` — Caddy JSON access log (rotated at 10 MB × 10 via Caddyfile)
- `.autoservice/logs/caddy-stdout.log` — Caddy stderr / startup
- `.autoservice/logs/cloudflared.log` — cloudflared JSON
- `.autoservice/logs/cloudflared-stdout.log` — cloudflared stderr

`make public-logs` tails gateway + caddy + cloudflared logs with follow.

## Known-good versions

- cloudflared 2026.3.0 (Homebrew `/opt/homebrew/bin/cloudflared`)
- Caddy 2.11.2 (`/usr/local/bin/caddy`, manual install)
- Node 20.x, pnpm 10.20.0
- Python 3.12 via uv; `bcrypt>=4,<5`, `email-validator`

## Applying CF Access manually (no API token)

1. Open the Cloudflare dashboard → Zero Trust → Access → Applications.
2. Add application:
   - Name: `autoservice`
   - Domain: `autoservice.ezagent.chat`
   - Session duration: `720h`
   - Type: `Self-hosted`
3. Add an **Allow policy**: decision = `allow`, include = Emails in
   `deploy/cloudflare-access/allowlist.yml::allowed_emails`.
4. For each public path (`/site/*`, `/api/auth/*`, `/api/tenants/*`,
   `/ws/customer`, `/robots.txt`, `/_caddy_health`, `/api/healthz`)
   create a separate Access application with the same domain and a
   more-specific path matcher, decision = `bypass`. Cloudflare
   evaluates most-specific-path first.
5. Save and verify with `make public-smoke`.

## Troubleshooting

- **502 at the hostname** — cloudflared is up but Caddy is down (or on
  the wrong port). Check `lsof -iTCP:18080` and
  `.autoservice/logs/caddy-stdout.log`.
- **Long WS connections drop around 100 s** — Cloudflare free-plan WS
  idle cap. uvicorn's default `ws_ping_interval=20s` should prevent
  this; if you see it, verify uvicorn version and gateway ping logs.
- **Magic link never arrives** — check `.autoservice/logs/gateway.log`
  for SMTP errors. Feishu Mail requires STARTTLS on port 587. An
  `SMTPAuthenticationError` means `SMTP_USER` doesn't match the
  actual Feishu-hosted mailbox.
- **New email added to yml but user can't log in** — did you run
  `make access-apply`? Also check `auth.admin_emails` in
  `config.local.yaml` and run `make generate-admin-passwords` for
  the password.
- **`cloudflared tunnel info autoservice` returns a different tunnel** —
  known name-cache bug. Always use the UUID (`389c95d2-6066-...`).
- **Caddy won't start: port already in use** — another Caddy or
  service is already on `$CADDY_PORT`. `lsof -iTCP:18080` identifies
  the process. Pick a different port: `CADDY_PORT=18081 make public-up`.
- **launchd agent won't stay up** — inspect `launchctl print
  gui/$(id -u)/com.autoservice.<svc>`; the `last exit status` field
  explains why. Common cause: a typo in the plist's
  `ProgramArguments` → `exec: command not found`.

## Linux migration

When moving off Mac Studio to a Linux box:

| Component | Mac | Linux |
|---|---|---|
| cloudflared | `/opt/homebrew/bin/cloudflared` | `/usr/bin/cloudflared` (deb) |
| Caddy | `/usr/local/bin/caddy` (manual) | `/usr/bin/caddy` (apt) |
| Process supervisor | launchd agents | systemd user units |
| AUTOSERVICE_ROOT | `/Users/<you>/Workspace/AutoService` | `/opt/autoservice` (suggested) |
| Tunnel UUID / creds | portable (tunnel lives on CF side) | copy `~/.cloudflared/<uuid>.json` over |
| CF Access policy | unchanged | unchanged |

Caddyfile, cloudflared yaml, and the scripts all use env vars for
paths — only `deploy/launchd/*.plist.template` needs translation
into systemd unit files. Estimated migration cost: half a day.
