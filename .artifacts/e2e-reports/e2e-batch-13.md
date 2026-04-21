# E2E report: batch-13 (P7 routing + infra · T7F.3 + T7S.4 parallel)

## Total

### Backend regression (T7S.4 scope + batch-12 prerequisites)
- **110 pass / 0 fail** across `tests/setup/ tests/fork_runtime/ tests/bootstrap/ tests/auth/ tests/api/`
- Duration: 10.69s
- 110 pre-existing FastAPI `on_event` deprecation warnings (M3 cleanup candidate, unrelated)

### Frontend focused scope (T7F.3)
- **5 pass / 0 fail** customer-chat `mainRouting.test.tsx` (3.7s)
- **5 pass / 0 fail** operator-console `mainRouting.test.tsx` (5.7s)
- **0 new regression** — pre-existing baseline unchanged (customer-chat 21 existing fails, operator-console 11 existing fails) per sibling subagent verification via git-stash baseline

### Batch-scope new tests
- T7S.4: 8 subprocess tests (fresh-install, master-mode, tenant-mode-requires-id, tenant-mode-with-id, idempotent, sandbox-preserved, skip-_local_admin, skip-_example)
- T7F.3: 10 tests (5 customer-chat + 5 operator-console — deriveBasename branches × loading/error)
- **Total: 18 new tests, all green**

## New vs regression classification

| Scope | New pass | Regression pass | New fail | Regression fail |
|-------|---------|-----------------|----------|-----------------|
| tests/setup/ | 8 | 0 | 0 | 0 |
| tests/fork_runtime/ (batch-12) | 0 | 17 | 0 | 0 |
| tests/bootstrap/ | 0 | 20+ | 0 | 0 |
| tests/auth/ + tests/api/ | 0 | 66+ | 0 | 0 |
| customer-chat mainRouting | 5 | 0 | 0 | 0 |
| operator-console mainRouting | 5 | 0 | 0 | 0 |

## Preexisting failures (unchanged baseline)

- Frontend: 21 in customer-chat, 11 in operator-console (i18n translation-key mismatches — same cluster as admin-portal's 24)
- Backend: 10 pre-existing (`tests/contract/test_protocol_signatures.py`, `test_ws_schema_alignment.py`, `tests/test_proposal_pipeline.py` event-loop pollution) — confirmed unchanged via batch-12's e2e-report-009 baseline

Not caused by batch-13. Out of scope; M3 cleanup candidate.

## Batch-13 commit trail (race-corrected)

- `1c63db1` — register eval-doc-016 (T7S.4)
- `782382d` — register eval-doc-017 (T7F.3)
- `41d6178` — register test-diff-017 (T7S.4)
- `5ac0bce` — register test-diff-018 (T7F.3) + link eval-doc-017 (swept T7S.4 code files due to shared `git add .artifacts/` race)
- `8bbe728` — canonical `feat(m2): T7S.4` audit-trail commit (empty, documents the race)
- `90cfd69` — `feat(m2): T7F.3 customer-chat + operator-console mode routing`

## Race observation (process improvement for M3)

T7F.3's `artifact-register.sh` invocation swept T7S.4's staged `Makefile`/`scripts/setup.sh`/`tests/setup/` changes into commit `5ac0bce` because the shared `git add .artifacts/ && git commit` in `scripts/artifact-register.sh` is not file-scoped. Recommended: make `artifact-register.sh` run `git add .artifacts/<specific-path>` (or use `git commit -o <files>`) to avoid cross-task contamination during parallel dispatch.

## 关联 artifact

- eval-doc-016 (T7S.4) + test-diff-017 (T7S.4)
- eval-doc-017 (T7F.3) + test-diff-018 (T7F.3)

## Verdict

**batch-13 ✅ GO** — 18 new tests green, 0 new regression, artifacts complete with bidirectional links. Phase 7 progress: 4/6 tasks done (T7B.1, T7B.2, T7F.3, T7S.4). Remaining: T7S.5 smoke test + T7B.6 /api/management/chat (batch-14, parallel candidates).
