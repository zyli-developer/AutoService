# Batch M3-gate Kickoff · M3 Milestone Gate · v1.2.0-mvp

**Batches**: batch-13, batch-14 · **Milestone**: M3-gate · **Target**: 2026-05-03 EOD · **Duration**: ~6h

## Pre-checks

- [ ] All code batches (batch-0 through batch-10) complete
- [ ] batch-11/12 complete OR explicitly deferred to M3.5 (documented)
- [ ] task-status.md Overall Progress = 100% for in-scope tasks
- [ ] No ⏸️ blocked tasks
- [ ] No uncommitted changes under `docs/plans/m3/` or `autoservice/`

---

## batch-13 · M2 Regression (2h, solo)

| ID | Name | Owner |
|---|---|---|
| T6S.1 | M2 regression run | Dev1 |

**Commands** (authoritative per NFR-04 / FLAG-03 resolution):
```bash
# 1. Unit + integration (e2e excluded by default per addopts)
pytest tests/

# 2. M2 acceptance e2e (requires ANTHROPIC_API_KEY + gh CLI + live uvicorn)
pytest -m e2e tests/e2e/test_m2_acceptance.py -v
```

**Gate**: both exit 0; evidence archived to `e2e-evidence/m3-gate/m2-regression.md` with:
- Test counts (passed/failed/skipped)
- Duration
- Environment versions (python, uvicorn, frontend build)
- Full stdout/stderr for both commands

---

## batch-14 · Smoke + Tag (4h, solo)

| ID | Name | Owner | Deliverables |
|---|---|---|---|
| T6S.2 | M3 smoke test + evidence | Dev1 | `.artifacts/milestones/m3-smoke-report.md` |
| T6S.3 | Tag v1.2.0-mvp + CHANGELOG + merge | Dev1 | git tag, CHANGELOG.md update |

### T6S.2 Smoke Checklist (14 in-scope criteria from PRD §6.1)

**E1 Identity & RBAC** (6 items):
- [ ] Operator can log in, see only own-tenant conversations (E1.1-1.4)
- [ ] Tenant admin can invite operator team members (E1.3)
- [ ] 1 tenant has ≥2 admins with same permissions (E1.5)

**E3 Triage Enhancement** (4 items):
- [ ] Pool wait > threshold → operator-console alert (E3.1)
- [ ] Agent `<handoff to='lead'>` → auto re-triage (E3.2)
- [ ] admin-portal keyword editor edits take effect without restart (E3.3)
- [ ] Conversation ≥20 msgs → role switch uses summary, not full log (E3.4)

**E4 Compliance** (1 item):
- [ ] US tenant does NOT see EU-only rules (E4.1)

**E5 Dream Extension** (2 items):
- [ ] Platform dream emits platform_level proposal (E5.1)
- [ ] A clicks "Apply" → proposal status→applied + audit log (E5.2)

**E6 Operations** (2 items — may be partial if Playwright deferred):
- [ ] Sandbox 30-day-unpublished auto-archived (E6.1)
- [ ] Playwright 17 stories green OR M3.5 deferral documented (E6.2)

**NFR verification**:
- [ ] NFR-01 Operator WS handshake failure rate <1% (observed in batch-3 e2e)
- [ ] NFR-02 RBAC decision P95 <5ms (from T2S.1 benchmark)
- [ ] NFR-04 M2 regression all green (batch-13)
- [ ] NFR-05 M3 new code coverage ≥80% (pytest-cov report)
- [ ] NFR-06 5 M3 Epic design specs exist (E1/E3/E4/E5/E6)
- [ ] NFR-07 .artifacts/ per task (eval-doc / test-plan / test-diff / e2e-report)

### T6S.3 Gate + Tag

Pre-tag checks:
- [ ] T6S.2 smoke 14/14 (or 13/14 with Playwright M3.5 deferral)
- [ ] All status documents finalized
- [ ] CHANGELOG.md drafted (see template below)

Commands:
```bash
# Tag
git tag -a v1.2.0-mvp -m "M3: Identity & RBAC + Triage + Compliance + Dream + Ops

Epic coverage: E1 (6 stories) + E3 (4) + E4 (2) + E5 (2) + E6 (2) = 16
Epic E2 (Subtenant/Whitelabel): DEFERRED to M4+ per PRD §8.1 Errata
  (v1.1 §8 whitelabel OoS)

CON-04 red line: enforced via 4 layers (signature lock, hardcoded draft,
  one-way import cone, AST guardrail test)

Playwright E2E: {status — green / deferred M3.5}

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

# Merge to dev (preserve branch history)
git checkout dev
git merge --no-ff dev-a
git push origin dev
git push origin v1.2.0-mvp
```

### CHANGELOG.md Entry Template

```markdown
## v1.2.0-mvp — 2026-05-03 (M3 milestone)

### Added
- Epic E1 Identity & RBAC: operator auth/session, CRUD, invites, RBAC 3-tier matrix, multi-admin
- Epic E3 Triage Enhancement: SLA pool metrics + alerts, handoff protocol, DB-backed classify_intent, history compression
- Epic E4 Compliance: country-scoped filtering (ISO alpha-2), JP/SG/AU rulesets
- Epic E5 Dream Extension: platform-level master dream, apply_proposal (CON-04 red line hardened)
- Epic E6 Operations: sandbox GC (30-day TTL), Playwright E2E {17 stories | deferred}

### Changed
- auth.py: session schema extended for operator roles
- compliance/compliance.py: scan(countries=list); region_filter @deprecated
- proposal_pipeline.py: state machine extended with `applied` state
- dream_scheduler.py: _master routes through master_dream_agent

### Deferred to M4+
- Epic E2 (Subtenant / Whitelabel / Referral): see PRD §8.1 Errata
- Fine-grained RBAC permission matrix
- Compliance hot-reload
- OAuth / SSO / 2FA / passkey
- {Playwright, if deferred}

### Security
- CON-04 red line enforced (dream agent cannot write non-draft proposal status)
  via 4-layer defense: signature lock + hardcoded string + one-way import + AST guardrail
```

---

## Gate Decision Tree

| Outcome | Action |
|---|---|
| All 14 criteria green + M2 regression green | GO → tag v1.2.0-mvp + merge |
| Playwright deferred, other 12 green + M2 green | GO → tag with "M3 gate (Playwright M3.5)" annotation |
| Any non-Playwright criterion red | NO-GO → fix + re-run smoke |
| M2 regression red | **HARD NO-GO** → root-cause + fix before any tag |

---

## Post-gate

1. Update [project.yaml](../project.yaml) `project.plans_dir` → `docs/plans/m4` (or `m3.5` if Playwright pending)
2. Run `/prd2impl:skill-11-retro M3` to produce retrospective
3. Archive `.artifacts/milestones/m3-smoke-report.md` link in README

## Next Milestone Planning

If M3.5 mini-sprint needed (Playwright):
- `/prd2impl:skill-4-plan-schedule --plans-dir docs/plans/m3.5` with tasks T5S.1-T5S.5

If M4 planning starts fresh:
- New v1.2 PRD addendum needed to re-authorize E2 (or M4+ Epic)
- `/prd2impl:skill-1-prd-analyze docs/prd/AutoService-M4-PRD.md`
