---
title: M3 Epic E6 · Operations & Deployment (Sandbox GC + Playwright E2E)
status: draft
date: 2026-04-21
prd_refs: [docs/prd/AutoService-M3-PRD.md §2 E6, §5 decision 7, §6.1 verification]
stories: [E6.1, E6.2]
depends_on: [E1.1, E1.2, E1.3]  # Playwright needs operator login
may_defer_to_M3_5: [E6.2]
---

# M3 Epic E6 · Operations & Deployment

**Date:** 2026-04-21 · **Status:** Draft · **Scope:** Make AutoService safe to run
at internal-beta scale (5-10 tenants). Two mostly-independent P2 stories.

| Story | Title | Effort | Gate-blocker? |
|---|---|---|---|
| E6.1 | Sandbox GC (auto-archive >30d unpublished) | Small | Yes |
| E6.2 | Playwright E2E (17-story automation) | Large | No — may slip to M3.5 per CON-13 |

---

## 1 · Context & Problem Statement

### 1.1 Why Sandbox GC (E6.1)

M2 gave every tenant a live `.autoservice/sandbox/<tid>/` directory containing
souls, KB extracts, config.json and SQLite state. In internal-beta conditions
(5-10 tenants) we expect a long tail of **abandoned** sandboxes — onboarding
started but never published. Today these directories stay live forever: they
consume disk, churn inside the Master tenant directory listing, and confuse
operations ("is tenant_id `foo_bar` still in use or stale?"). There is no TTL
job. `archive_sandbox()` fires only when an admin explicitly publishes. M3's
target of 5-10 tenants × multiple onboarding attempts per tenant means this
will matter within the first month.

### 1.2 Why Playwright (E6.2)

The existing pytest e2e suite (`tests/e2e/test_m2_acceptance.py`) covers backend
flows — TestClient into the FastAPI router — with excellent depth for engine /
gateway / publish / auth / dream. It does **not** cover the frontend. When an
admin-portal or operator-console regression lands (selector change, route
reshuffle, state-management bug) it slips through M2 gate and is caught only by
manual `e2e-evidence/` screenshot runs. With three SPAs (customer-chat,
operator-console, admin-portal) now in scope and E1 adding a new operator-login
flow, manual-only coverage is no longer sustainable. Playwright gives us
scripted, repeatable UI regression for the 17 PRD user stories.

### 1.3 Scope constraints

- **CON-13** (PRD §5 decision 7): E6.2 may slip to M3.5 without blocking the M3
  gate. E6.1 remains in-gate.
- PRD §6.1 verification rows: "沙盒 30 天未发布自动归档 (E6.1)" and "Playwright
  17 story 全绿或明确退 M3.5 (E6.2)" — the latter explicitly allows deferral.

---

## 2 · Current State (evidence)

### 2.1 Archive mechanism (E6.1 baseline)

- `autoservice/publish.py:914-941` — `archive_sandbox(tenant_id, ts=None)`
  moves `.autoservice/sandbox/<tid>/` → `.autoservice/archived/<tid>_<ts>/`
  and stamps `config.status = 'archived'`. Collision-safe (suffix counter).
- `autoservice/publish.py:944-1009` — `unfreeze(tenant_id, reason)` inverse
  path; restores newest archive back to sandbox/, rewrites publish record.
- `autoservice/api_routes.py:312-380` — `/master/tenants` listing enumerates
  both `.autoservice/sandbox/` and `.autoservice/archived/`, forcing
  `status=archived` for the latter.
- `.autoservice/sandbox/<tid>/config.json` — source of truth for status
  (`sandbox` | `published_pending_fork` | `archived`).

**Gap:** no scheduled job. `archive_sandbox()` is only invoked from the
publish flow. Nothing scans by mtime or config age.

### 2.2 Existing scheduler pattern (for E6.1 reuse)

- `autoservice/dream_scheduler.py:1-80` — asyncio loop; `poll_interval_sec`
  enumerates active tenants, evaluates a pure decision function per tenant,
  spawns work. Uses `refresh()` to re-read per-tenant config. This is the
  reference pattern for the sandbox GC job.

### 2.3 pytest e2e (E6.2 baseline)

- `tests/e2e/test_m2_acceptance.py` — M2 acceptance (8 steps: wizard/publish,
  fork, browser chat, magic-link, dream idle, master chat, proposal
  approve/reject). Requires `ANTHROPIC_API_KEY` + live uvicorn. Marked `e2e`.
- `tests/e2e/conftest.py:1-50` — path-isolation + LLM stub fixtures. NOT
  Playwright; runs in-process via TestClient.
- `package.json` at repo root: absent. Only `frontend/package.json` (pnpm
  monorepo, React 18, Vite). No `playwright.config.*` anywhere — confirmed.

### 2.4 FLAG-03 (recently resolved)

M2 regression commands are `pytest tests/` + `pytest -m e2e
tests/e2e/test_m2_acceptance.py` (gap-analysis.yaml NFR-04). Playwright will
**add a third command** (`pnpm e2e` or `make e2e-playwright`), not replace
either pytest suite.

---

## 3 · Design — E6.1 Sandbox GC

### 3.1 Job runner

**New module:** `autoservice/sandbox_gc.py`.

**Pattern:** copy DreamScheduler — a single asyncio task started during gateway
startup, looping `poll_interval_sec`. Rejected alternatives:

| Option | Verdict |
|---|---|
| APScheduler | No — adds a dep for a 1-function loop |
| OS cron | No — breaks single-process deploy story (`make run-gateway`) |
| In-process asyncio loop (DreamScheduler pattern) | **Chosen** — matches existing code, zero new deps, testable with `asyncio.sleep` mocks |

**Invocation:** piggyback on the existing gateway startup. In
`autoservice/web_gateway.py` lifespan: instantiate `SandboxGC(scan_interval_sec,
…)` and `await gc.start()`; on shutdown `await gc.stop()`. Same process as the
web gateway (not a separate daemon). Rationale: (a) simplifies deploy —
operators learn one `make run-gateway` entrypoint; (b) GC work is cheap (file
stat + occasional shutil.move); (c) matches DreamScheduler precedent. If future
multi-host deployment lands (explicit non-goal for M3), extract to a daemon
then.

### 3.2 Scan frequency

**Chosen: every 6h** (balance). Tradeoffs considered:

| Interval | Latency to archive | Resource cost |
|---|---|---|
| 1h | Fastest | 24 scans/day across all tenants — fine at N≤10, waste for most runs |
| **6h** | **max 6h over threshold** | **4 scans/day — trivial cost** |
| 24h | Up to 24h late | Could miss same-day re-org if GC runs at 00:01 |

Per-tenant override is not needed for interval (sweep is global). The **TTL
threshold** is per-tenant overridable (§3.4). First scan fires 60s after
startup (so `make run-gateway` developers see GC activity in logs promptly).

### 3.3 TTL logic

Per-scan, enumerate `.autoservice/sandbox/<tid>/` directories. For each:

```
cfg = read_json(sandbox/<tid>/config.json)   # skip if missing/unreadable
status = cfg.get("status", "sandbox")
if status != "sandbox":
    skip                          # published_pending_fork / archived: not our business
ttl_days = cfg.get("sandbox_ttl_days") or DEFAULT_TTL_DAYS  # 30
mtime = max(
    statvfs(sandbox/<tid>/config.json).st_mtime,
    statvfs(sandbox/<tid>/).st_mtime,
)
age_days = (now - mtime) / 86400
if age_days > ttl_days:
    archive_sandbox(tid)          # reuse publish.py
    emit_audit(tid, age_days, ttl_days, "auto-gc")
```

**Why mtime not tracked `created_at`:** the config already carries
`created_at`, but we want **idle-based** TTL, not age-based. A tenant that
edited `souls/customer.md` yesterday is not abandoned even if the sandbox was
created 60 days ago. mtime captures "last touched". If we later need
age-from-creation, adding a check against `cfg["created_at"]` is trivial.

**Alternative rejected:** adding a `last_modified_at` column requires a
migration for every existing sandbox directory. mtime is already there, free,
and the filesystem is the source of truth we already depend on (archive_sandbox
uses mtime for `_list_archives_for` ordering — publish.py:1012-1014).

### 3.4 Per-tenant override

Tenant `config.json` may carry `sandbox_ttl_days: <int>` (nullable / absent →
use default 30). Validation: positive integer. PRD §2 E6 constraint explicitly
names this field. Zero or negative values are rejected (log warning, fall back
to default) — safer than "delete immediately on next scan".

### 3.5 Audit log

**Chosen:** append-only JSONL at `.autoservice/logs/sandbox_gc.log`.

Row shape:
```json
{"ts":"2026-04-21T14:00:00Z","action":"archived","tenant_id":"foo","age_days":31.2,"ttl_days":30,"reason":"auto-gc","from":".autoservice/sandbox/foo","to":".autoservice/archived/foo_20260421T140000Z"}
```

Also log scan summaries (every N tenants scanned, how many archived, elapsed
ms) at INFO level to stdout via the `logging` module. Scan summaries do **not**
go to the JSONL (that file is archival decisions only, for traceable audit).

Rejected SQLite table: overkill for a linear audit trail; JSONL grep'able by
ops without DB access. If future per-tenant dashboards need it, a separate
tailer can ingest the JSONL into SQLite.

### 3.6 Archived/ second-tier TTL

**Open question** — PRD does not specify. Current design: **do not auto-purge**
`.autoservice/archived/` in M3. Rationale: unfreeze (publish.py:944) must be
able to find the archive; operators may want to recover a "mistakenly
abandoned" tenant months later. If disk pressure emerges, add a separate
`archived_ttl_days` default (e.g. 180) in M3.5 / M4. Flagged in §7.

### 3.7 Failure mode — partial archive move

`archive_sandbox()` uses `shutil.move` which is **not** atomic across
filesystems and can leave state between source deleted and dest incomplete. For
M3 we accept this risk: `.autoservice/sandbox` and `.autoservice/archived` are
always on the same device (both under `.autoservice/`). If the move fails
mid-op:

- Partial dest directory: next scan sees orphaned `archived/<tid>_<ts>/`; no
  action (harmless).
- Deleted source, no dest: next scan won't find source; re-running GC is a
  no-op (tenant is gone — audit log records the original archive decision
  before the move). To detect this, emit audit **after** the move completes,
  not before. Wrap in try/except and on exception log
  `action=archive_failed` with traceback.
- `RuntimeError` during scan: one tenant's failure does not abort the pass —
  log, continue with the next tid.

### 3.8 Concurrency

Two scenarios to guard:

1. **Admin publishes during scan.** `publish.py` already acquires the sandbox
   directory exclusively (via shutil.move). If the GC's `archive_sandbox` call
   loses the race, it raises `FileNotFoundError` — catch and treat as
   "already-handled", no audit row needed (publish path emits its own).
2. **Two GC ticks overlapping.** Should not occur (single asyncio loop), but
   guard with an `asyncio.Lock` inside `SandboxGC` for safety. Per-tenant
   locking is not needed; cross-tenant scans are independent.

### 3.9 Disabled/manual mode

Global env `SANDBOX_GC_ENABLED=0` → loop starts but `_scan` is no-op. Useful
for dev-loop tests and pytest fixtures. Also: `sandbox_gc.run_once()` sync
entry point (for manual triggering + integration tests without sleeping).

---

## 4 · Design — E6.2 Playwright E2E

### 4.1 Framework choice

**Chosen: Playwright + TypeScript.** Rationale:

- Frontend stack is already TS + React + Vite (pnpm). TypeScript specs live
  alongside the apps they exercise.
- Playwright's codegen / trace viewer ship as first-class features; the Python
  binding is a wrapper.
- Keeps pytest clearly scoped to backend; Playwright clearly scoped to UI — no
  confusion about which command runs what.

**Rejected:**

- **pytest-playwright** — sounds unifying but forces UI specs into a Python
  repo structure; selectors become Python strings; codegen + trace UX worse.
- **Cypress** — weaker trace/debugger story; no cross-browser parity.
- **Selenium** — older API, weaker async; not a 2026 choice.
- **Append to existing pytest e2e** — muddles two very different test types
  in the same file, and the existing `test_m2_acceptance.py` already has
  distinct fixtures (LLM stubs) that would conflict with a real-browser run.

### 4.2 Directory layout

```
tests/e2e-playwright/                  # new, separate from tests/e2e/ (pytest)
  playwright.config.ts
  package.json                         # minimal: @playwright/test only
  fixtures/
    session.ts                         # authenticated operator/admin fixtures
    testdata.ts                        # tenant_id / operator_email generators
  specs/
    epic1-onboarding.spec.ts           # US-1.1..1.4 (4 stories)
    epic2-realtime-chat.spec.ts        # US-2.1..2.6 (6 stories)
    epic3-dashboards.spec.ts           # US-3.1..3.3 (3 stories)
    epic4-dream-learning.spec.ts       # US-4.1..4.4 (4 stories)
  README.md                            # run + debug instructions
```

The split "tests/e2e (pytest) vs tests/e2e-playwright (Playwright)" makes the
framework obvious from the path.

### 4.3 Config (`playwright.config.ts`)

```ts
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './specs',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [
    ['list'],
    ['html', { outputFolder: '../../e2e-evidence/playwright/html' }],
    ['json', { outputFile: '../../e2e-evidence/playwright/results.json' }],
  ],
  use: {
    baseURL: process.env.AUTOSERVICE_BASE_URL ?? 'http://localhost:8000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    // firefox + webkit added in M4+ once chromium is stable
  ],
});
```

**CI browser matrix decision:** chromium only for now (speed; most
AutoService users are on Chrome/Edge). Cross-browser flagged in §7 Open
Questions. Traces and screenshots captured on failure only — keeps
`e2e-evidence/playwright/` from exploding.

### 4.4 Seventeen story clusters

The 17 stories are fixed by PRD v1.1 (§0.2; verified against
`docs/prd/AutoService-UserStories-v1.1.md`). Clustered by flow to avoid
one-file-per-story:

| Spec file | Stories | Cluster description |
|---|---|---|
| **epic1-onboarding.spec.ts** | US-1.1 / 1.2 / 1.3 / 1.4 | Admin walks 4-step wizard: upload brand info → generate 4 souls → choose channel + URL → virtual rehearsal → compliance precheck. |
| **epic2-realtime-chat.spec.ts** | US-2.1 / 2.2 / 2.3 / 2.4 / 2.5 / 2.6 | Three-viewpoint live conversation: end-user greets, placeholder-then-complete reply, operator squad card, operator joins copilot, human-takeover via /hijack, role-flip (AI to copilot). |
| **epic3-dashboards.spec.ts** | US-3.1 / 3.2 / 3.3 | Admin dual ledger (conversations + billing), command-line shortcuts (/rules /status /review), SLA-alert escalation to notification center. |
| **epic4-dream-learning.spec.ts** | US-4.1 / 4.2 / 4.3 / 4.4 | Dream config via notification center, low-traffic auto-trigger, morning proposal push, canary rollout + rollback button. |

Total: **4 spec files, 17 stories.** Each spec file has one `test.describe`
block per story (so Playwright's report lists 17 labelled cases). Shared setup
(login, seed tenant) goes in fixtures — not in each spec.

### 4.5 Fixtures — authenticated session

Dependency on Epic E1 (operator login). Two authenticated fixtures, loaded by
dependency graph in playwright.config.ts:

```ts
// fixtures/session.ts
export const test = base.extend<{
  adminSession: Page;       // tenant admin (via magic-link — dev auto-login)
  operatorSession: Page;    // operator (via E1.1 operator login)
  customerSession: Page;    // unauthenticated customer-chat
}>({
  adminSession: async ({ browser }, use) => {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    await page.goto('/_dev/login?role=tenant_admin&tenant_id=e2e_tenant');
    await use(page);
    await ctx.close();
  },
  operatorSession: async ({ browser }, use) => {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    await page.goto('/_dev/login?role=operator&tenant_id=e2e_tenant');
    await use(page);
    await ctx.close();
  },
  customerSession: async ({ browser }, use) => { /* anon context */ },
});
```

The `/_dev/login` endpoint is the **dev auto-login** from
`docs/superpowers/specs/2026-04-21-dev-auto-login-design.md`. It mints session
cookies directly without magic-link copy-paste. Playwright specs rely on it
being enabled in the test stack; production builds MUST disable it. Sits on
top of E1.1 (operator session) + E1.2 (tenant operator CRUD — we seed
`e2e_tenant` with a known operator).

**E1 dependency risk:** if E1.1/1.2/1.3 slip past their B-M3-1 milestone,
E6.2 specs cannot authenticate. Mitigation: ship the fixture + skeleton specs
early using a **mock** session cookie; swap to real `/_dev/login` once E1
lands. See §4.8 CON-13 fallback.

### 4.6 CI integration

Workflow: `.github/workflows/e2e-playwright.yml` (new) runs after existing
pytest jobs.

```yaml
jobs:
  e2e-playwright:
    needs: [pytest-unit, pytest-e2e]    # only run if backend tests green
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4 (pnpm)
      - run: pnpm install
      - run: pnpm --filter autoservice-e2e-playwright exec playwright install chromium
      - run: make run-gateway & (wait-on http://localhost:8000/healthz)
      - run: pnpm e2e
      - uses: actions/upload-artifact (e2e-evidence/playwright/**)
```

**Fail-fast vs run-all:** run-all (no `--fail-fast`). Rationale: 17 stories
is small enough that running the full suite even after an early failure takes
a minute or two; the artifact upload is then a complete diagnostic snapshot,
not a truncated one.

### 4.7 Dev ergonomics

- `pnpm e2e` (in `tests/e2e-playwright/`) — runs all specs against
  `AUTOSERVICE_BASE_URL` (default localhost:8000).
- `pnpm e2e:ui` — Playwright UI mode for interactive debugging.
- `pnpm e2e:codegen` — record-a-spec helper for new tests.
- `make e2e-playwright` — top-level Makefile entry that shells to `pnpm e2e`.
  Keeps parity with existing `make run-*` vocabulary.
- Requires `make run-gateway` (or `make start`) running locally.

Developers must install browsers once: `pnpm --filter … exec playwright
install chromium`.

### 4.8 CON-13 fallback plan

If E6.2 is behind schedule at M3 smoke-test time, explicit deferral to M3.5.
**Minimum artifacts that must exist even in the deferred case**:

1. `tests/e2e-playwright/playwright.config.ts` — committed, with baseURL env
   wiring.
2. `tests/e2e-playwright/package.json` + committed lockfile.
3. `tests/e2e-playwright/fixtures/session.ts` — with at least the
   `adminSession` fixture wired to `/_dev/login` (or a documented mock).
4. Four skeleton spec files with one `test.describe` per story and
   `test.fixme('not yet impl — M3.5')` placeholders, so story-count
   discovery tests (§6.2) pass.
5. README.md explaining how to enable + run.

This means an M3.5 developer can start writing assertions directly on day 1
rather than scaffolding.

---

## 5 · Cross-cutting topics

### 5.1 E6.2 ↔ E1 dependency

E6.2 specs authenticate via cookies minted by the login endpoints that Epic E1
delivers. The dependency chain:

- E1.1 (operator SQLite session + HTTP login) → E6.2 operatorSession fixture
- E1.2 (per-tenant operator CRUD) → seeding `e2e_tenant` with a known operator
- E1.3 (invite link) → optional; only needed if a spec exercises invite flow
- `2026-04-21-dev-auto-login-design.md` → the `/_dev/login` endpoint itself

If E1 slips: fall back to the "minimum artifacts" set in §4.8 — the specs
exist but are marked `test.fixme` and auto-skipped. M3 gate does not fail
because CON-13 allows M3.5 deferral.

### 5.2 E6.1 deployment story

Runs in-process with the gateway (§3.1). No separate daemon. Implications:

- `make run-gateway` starts GC automatically.
- Devs who **don't** want GC running in their dev loop: set
  `SANDBOX_GC_ENABLED=0`.
- If we later split gateway into web vs worker tiers, GC belongs in the
  worker tier — noted in PRD non-goals but trivial to move (one call-site in
  lifespan).

### 5.3 Interaction with `unfreeze`

`unfreeze()` restores an archive → sandbox. GC will now archive sandboxes
automatically. Could a tenant unfreeze → sit idle 30 days → get auto-archived
again? Yes, and that's correct behaviour (the second archive is not a bug).
The audit log will show both events with distinct timestamps.

### 5.4 Master tenant listing

`api_routes.py:351 /master/tenants` enumerates both sandbox and archived dirs.
After GC runs, tenants will move from sandbox to archived sections of that
listing. Frontend already handles `status=archived` — no change needed.

### 5.5 Playwright + e2e-evidence layout

Existing `e2e-evidence/` has screenshots from manual runs
(`01-*.png` … `44-*.png`) and pytest e2e subdirs
(`m2-acceptance/`, `2026-04-21-scenarios/`). New Playwright artifacts land in
`e2e-evidence/playwright/` — separate subtree. `.gitignore` continues to
include `e2e-evidence/` except for curated deliverables.

---

## 6 · Test Strategy

### 6.1 E6.1 Sandbox GC

**Unit tests** (`tests/ops/test_sandbox_gc_unit.py`):

- `test_ttl_default_30d` — sandbox mtime 29d old → skip; 31d → archive.
- `test_per_tenant_override` — cfg.sandbox_ttl_days=7 wins over default 30.
- `test_override_invalid_fallback` — negative/zero/non-int → default + log
  warning.
- `test_skip_non_sandbox_status` — `published_pending_fork` and `archived`
  never archived regardless of age.
- `test_missing_config_skip` — malformed config.json logs warning, no
  archive.

**Integration tests** (`tests/ops/test_sandbox_gc_integration.py`):

- Create three sandboxes: fresh (today), stale (40d), published-pending
  (40d). Run `sandbox_gc.run_once()`. Assert: fresh untouched, stale
  archived, published-pending untouched. Assert audit log has one `archived`
  row for stale.
- Synthetic time control: patch `time.time()` or use `freezegun` to set
  clock 40 days forward, avoiding `os.utime` fiddling.

**TTL boundary test:** mtime at threshold ± 1 second. `age_days > ttl_days`
(strict), not `>=`, so exactly-30d does not trigger.

**Integration with live gateway:** extend `tests/e2e/test_m2_acceptance.py`
(or a new `tests/e2e/test_m3_gc.py`) with an e2e-marked test that starts the
gateway and verifies the GC loop logs a scan within 90s.

### 6.2 E6.2 Playwright

The Playwright suite IS the product test strategy for UI. For the
engineering of the suite itself, we add **meta-tests** in pytest:

- `tests/ops/test_playwright_config.py::test_config_loads` — import Node and
  run `node -e "require('./tests/e2e-playwright/playwright.config.ts')"` to
  confirm the config is syntactically valid. (If TS, use `tsc --noEmit`.)
- `tests/ops/test_playwright_config.py::test_seventeen_stories_present` —
  walk specs/ and count `test.describe` blocks. Assert exactly 17. Guards
  against accidentally dropping a story on refactor.
- `tests/ops/test_playwright_config.py::test_evidence_dir_configured` — grep
  playwright.config.ts for `e2e-evidence/playwright` string.

These meta-tests run in pytest (no browsers needed) and catch the most common
"I refactored the config and broke the story inventory" regressions.

---

## 7 · Open Questions

1. **Archived/ second-tier TTL — should auto-purge exist?** Current answer:
   no, keep archives forever. If disk pressure emerges in internal beta,
   add `archived_ttl_days` default 180 in M3.5.
2. **Playwright CI browser matrix — chromium-only or cross-browser?** Current
   answer: chromium only for speed. Revisit after first 2 weeks of internal
   beta — if we see browser-specific bug reports, add firefox/webkit.
3. **Can the 17-story list be enumerated cleanly?** Verified: yes. PRD v1.1
   UserStories has exactly Epic 1 (4) + Epic 2 (6) + Epic 3 (3) + Epic 4 (4)
   = 17 stories (`docs/prd/AutoService-UserStories-v1.1.md`). Matches
   kickoff §5 batch 14 (lines 284-288).
4. **GC trigger — time-based or event-based?** Current answer: time-based
   (6h). Event-based on gateway startup is useful as *supplemental* trigger
   (run_once fires 60s after startup) — we already do this. No need for
   further event hooks.
5. **Does `sandbox_ttl_days: 0` mean "never archive" or "archive
   immediately"?** Current answer: reject 0 as invalid (see §3.4), but PRD
   §2 E6 constraint ("可 tenant config 调") is ambiguous. Propose treating
   `null`/absent as default, any positive integer as the TTL, any other
   value as invalid.
6. **Should GC emit SLA/alert-engine events when archiving?** Probably not
   for M3 (noise). But `autoservice/alert_engine.py` integration is a
   one-liner if ops request it.

---

## 8 · Non-goals

- Chaos engineering (PRD §1.3 — pushed to M4+).
- Load / performance testing (PRD §1.3 — pushed to M4+).
- Distributed / multi-host GC coordination (single-process gateway only;
  see §5.2).
- Visual regression testing (pixel-diff screenshots). Playwright supports
  it but we don't turn it on — three SPAs × 17 stories × baselines is too
  much maintenance for M3. Revisit M4+.
- Auto-purge of `.autoservice/archived/` (see §3.6, §7.1).
- Playwright cross-browser coverage (see §4.3, §7.2).
- Packaging Playwright as part of `make setup` — it's opt-in via
  `make e2e-playwright` + its own `pnpm install` step.

---

## 9 · Acceptance Criteria (M3 gate rows)

PRD §6.1 rows this spec satisfies:

- [ ] "沙盒 30 天未发布自动归档 (E6.1)" — demonstrated by
      `tests/ops/test_sandbox_gc_integration.py` passing + log line present
      in `.autoservice/logs/sandbox_gc.log` for a seeded stale tenant.
- [ ] "Playwright 17 story 全绿或明确退 M3.5 (E6.2)" — either the four spec
      files all pass in CI, OR the M3.5-deferral minimum artifacts (§4.8)
      are committed and the gate signs off on the deferral.

NFR rows:

- E6.1 runs without blocking gateway shutdown (integration test asserts
  `stop()` returns within 5s).
- Playwright run wall-clock < 8 min on CI chromium-only (target).

---

## 10 · Implementation Milestones

| Order | Work | Blocker |
|---|---|---|
| 1 | E6.1 unit tests (TDD) | none — independent |
| 2 | E6.1 `sandbox_gc.py` impl | after (1) |
| 3 | E6.1 gateway lifespan wiring | after (2) |
| 4 | E6.1 integration test passes | after (3) |
| 5 | E6.2 skeleton (config + fixtures + 4 empty spec files + meta-tests) | none — can parallelize with E6.1 |
| 6 | E6.2 fill in epic1-onboarding.spec.ts | after E1.1/E1.2 done + (5) |
| 7 | E6.2 fill in epic2 / epic3 / epic4 spec files | after (6) — can parallelize |
| 8 | E6.2 CI workflow | after (5) |

E6.1 is 1-2 days. E6.2 is 2-3 days of skeleton + per-story fill-in (can be
distributed across the M3 tail). If the M3 clock hits smoke-test before step
(7) completes, invoke CON-13 → M3.5 with artifacts from steps (5)(6)(8)
committed.

---

*End of spec. ~540 lines.*
