# Changelog

All notable changes to AutoService are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
with semantic milestone tags (M1, M2, M3, ...).

## [v1.2.0-mvp] — 2026-04-21 (M3 milestone)

M3 delivers the **Identity & RBAC + Triage + Compliance + Dream + Ops**
feature set on top of the M2 tenant-sandbox foundation. Gate report:
`.artifacts/milestones/m3/m3-smoke-report.md`.

### Added

- **Epic E1 — Identity & RBAC**: operator auth/session (magic-link +
  strict WS cookie validation T1S.3), operator CRUD, tenant-admin
  invites, 3-tier RBAC matrix (viewer/responder/admin) with
  frozenset-based P95 <5ms decision, multi-admin support per tenant,
  AUTH_DEV_MODE dev-bypass for both admin and operator surfaces.
- **Epic E3 — Triage Enhancement**: `pool_wait_ms` SLA metric (T2S.4)
  exposed via `/api/sla/summary`; `<handoff to='lead'>` auto re-triage
  (T3S.1); DB-backed `classify_intent` keyword editor with hot-reload
  (T3S.3); `history_compressor` with haiku default for conversations
  ≥20 messages (T4S.7).
- **Epic E4 — Compliance**: country-scoped filtering (ISO alpha-2)
  replacing the legacy region filter; JP (APPI ×4), SG (PDPA ×4), AU
  (Privacy Act ×3) rule packs merged into the compliance registry (T4S.6).
- **Epic E5 — Dream Extension**: platform-level master dream agent
  (T2S.8 skeleton + T4S.4 cross-tenant signal ingestion); HTTP
  `POST /api/admin/proposals/{id}/apply` endpoint (T4S.3) backed by the
  canonical `proposal_apply.apply_proposal` writer; `/api/dream/status`
  endpoint exposing `should_trigger` reason_code vocabulary (T4S.3b).
- **Epic E6 — Operations**: sandbox GC (T4S.5, 30-day TTL with
  per-tenant override); `.artifacts/` per-task registry populated.

### Changed

- `auth.py`: session schema extended with role column for operator
  sessions; magic-link flow re-used for both admin and operator.
- `compliance/compliance.py`: `scan(countries=list)` replaces
  `region_filter` (marked deprecated; removal target M5).
- `proposal_pipeline.py`: state machine extended with `applied` state;
  `VALID_STATUSES` rename `implemented → applied`;
  `_mark_applied_internal` is now the **sole writer** of `status='applied'`
  (conditional `UPDATE … WHERE id=? AND status='accepted'` for
  race-safety); `PROPOSAL_AUDIT_SCHEMA` + `apply_m3_migration()` added.
- `dream_scheduler.py`: `_master` tenant routes through
  `master_dream_agent` instead of per-tenant `dream_agent.run_dream`.
- `api_routes.py`: `/api/management/chat` reverted to cc_pool-only
  (M2 invariant); dialog handling (dream-config, /approve, /rollback)
  lives on `/api/management/chat-legacy` until M3.5 D3 unification.

### Security

- **CON-04 red line enforced** via 5-layer defense:
  1. Signature lock — `emit_proposal()` has no `status` kwarg.
  2a. String hardcode — `'draft'` literal in JSON + SQL emission sites.
  2b. Value rejection — `update_status` rejects `'applied'`.
  3. Import cone — dream agents cannot import `proposal_apply`.
  4. AST guardrail — status-write strings only in allow-listed files
     (enforced by `tests/dream_agent/test_con04_guardrail.py` with
     canary meta-test).

### Deferred to M3.5 (mini-sprint)

See `docs/plans/m3.5-mini-sprint.md`.

- T5S.1–5 Playwright E2E (17 stories) + Frontend UI work.
- U1–U6 operator-console / admin-portal surfaces.
- D1–D4 dream-ui augmentation frontend components.
- Fork-side e2e harness (steps 3–6 of M2 acceptance: separate uvicorn
  :8001 process for per-tenant fork).

### Deferred to M4+

- **Epic E2** — Subtenant / Whitelabel / Referral: out of scope per
  PRD v1.1 §8 (whitelabel OoS). Saved ~10 days of work + 2 Red-tier
  tasks eliminated.
- Fine-grained RBAC permission matrix (beyond 3-tier).
- Compliance hot-reload (editor today still requires restart).
- OAuth / SSO / 2FA / passkey auth flows.

### Test coverage

- 1670/1670 unit + integration tests pass (ex. 8 pre-existing asyncio
  event-loop pollution flakes in `tests/test_proposal_pipeline.py` from
  April 16, before M3 work — tracked as infra debt, not an M3 regression).
- M2 acceptance e2e (local Claude SDK, no `ANTHROPIC_API_KEY`): 3/7
  master-side PASS + step-8 M3 apply surface PASS; 4 fork-side SKIP
  deferred to M3.5.
- CON-04 guardrail test includes a canary meta-test that fails if the
  allow-list grows without explicit review.

### Known issues

- `tests/test_proposal_pipeline.py` 8 tests use legacy
  `asyncio.get_event_loop().run_until_complete(...)` and flake in
  full-suite mode depending on prior-module loop state. Passes cleanly
  in any isolated or reasonable sub-suite run. Migration to
  `@pytest.mark.asyncio` is scheduled for M3.5 cleanup.

[v1.2.0-mvp]: https://github.com/h2oslabs/AutoService/releases/tag/v1.2.0-mvp
