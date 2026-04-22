# KB Unification — End-to-End Verification (2026-04-22)

Verifies that the refactor on branch `feat/kb-unification` (16 commits on top of `dev-a@39e489b`) closes the demo-blocking Chinese-query bug + the 2 silent wizard bugs, without regression.

## Scope

Plan: [`docs/superpowers/plans/2026-04-22-kb-unification.md`](../plans/2026-04-22-kb-unification.md)

Was: two divergent KB code paths (`autoservice/onboarding.py::_ingest_chunks_into_sandbox_kb` writing a minimal 6-col sandbox KB with `unicode61` FTS, vs `skills/knowledge-base/scripts/kb_ingest.py` writing a 13-col global KB also with `unicode61`) — runtime `kb_search` could only see the sandbox KB, and the `unicode61` tokenizer returned 0 hits for pure-Chinese queries. Wizard upload also silently dropped website-URL content and produced duplicate chunks on re-upload.

Now: single shared library `autoservice/kb_core.py::KBStore` with `trigram` tokenizer. Both the wizard (`/api/onboard/upload`) and the CLI (`skills/knowledge-base/scripts/kb_ingest.py`) delegate to it.

## Test coverage

**Total 64 tests passing** across:
- `tests/kb/test_kb_store.py` — 23 tests (init + migration + write surface + 4 ingest methods)
- `tests/kb/test_trigram_cjk.py` — 6 tests (CJK regression)
- `tests/kb/test_cli.py` — 2 tests (CLI smoke)
- `tests/dream_agent/test_kb_search_tool.py` — 9 tests (runtime KB retrieval)
- `tests/onboarding/test_upload_persists_souls_and_kb.py` — 5 tests (including 2 new bug-fix regressions)
- `tests/bootstrap/` — 19 tests (master-tenant KB bootstrap, caught during T11)

## Demo scenario — cinnox tenant

Resolved KB path: `.autoservice/sandbox/cinnox/kb/kb.db`
Seeded via: `python scripts/seed_cinnox_tenant.py` → 360 chunks (351 CINNOX glossary + 9 demo facts)

| Query | Hits | Top chunk |
|---|---|---|
| `你好，你们提供什么服务` (the original failing demo) | **1** | `cinnox Demo Knowledge / Service Overview` |
| `CINNOX 提供` (short mixed) | 3 | `CINNOX Glossary / Domain Name` |
| `what services do you provide` | 3 | `CINNOX Glossary / ADFS` |
| `Enterprise Plus SSO` | 3 | `cinnox Demo Knowledge / Enterprise Plus · Included Entitlements` |
| `DID provisioning` | 3 | `CINNOX Glossary / Offline provisioning` |
| `PSTN outage` | 3 | `cinnox Demo Knowledge / PSTN Outage Handling · P1 Escalation` |

Before this refactor, row 1 returned **0 hits**, which triggered `customer_soul.md`'s "KB empty → escalate to human" rule — the exact behaviour observed in the original screenshot.

## Bugs fixed (beyond Plan B/D scope)

Three real correctness bugs surfaced and were fixed during implementation:

1. **`INSERT OR REPLACE` + trigram FTS5 corrupts the segment index.** Reproducible: after one REPLACE, `MATCH 'old-term'` raises `database disk image is malformed` and `INSERT INTO kb_fts(kb_fts, rank) VALUES('integrity-check', 1)` fails. Every re-ingest path (T4 PDF / T10 CLI / T11 seed scripts) would have silently corrupted production KB data. Fixed by switching `save_chunk`/`save_chunks` to explicit `DELETE WHERE id=? ; INSERT`. Guarded by `test_fts_full_integrity_check_passes_after_replace`.
2. **Wizard dropped `website_url` content.** Fixed — `store.ingest_web(url, source_id="website", max_pages=1)` now runs in the same request, and the response payload carries `url_result.chunks_written`.
3. **Wizard produced duplicate chunks on re-upload** (every chunk got `uuid4()`, no dedup). Fixed — `source_id = f"file:{sha256(file_bytes)[:16]}"` lets `clear_source()` wipe the prior chunks before re-seeding.

Plus one inherited bug not caused by this refactor but observed:
4. **`seed_mystore_tenant.py` was writing to the global KB path instead of the per-tenant sandbox** — means runtime `kb_search('mystore', ...)` always returned empty. Fixed in T11 Step 3 alongside the KBStore migration.

## Known carry-forward items

- **Hybrid `_tokenize_fts_query`** (T7 shipped as hybrid, not the plan's strict-phrase form) — has `TODO(kb-unification/T11)` breadcrumb. Could be simplified now that Task 9 migrated the remaining `_init_sandbox_kb` fixture; deferred to a follow-up task since the hybrid is correct and all tests pass.
- **mystore seed requires sibling repo** for its glossary source (`CINNOX_ROOT = PROJECT_ROOT.parent / "AutoService-Cinnox"`). Degrades gracefully with `exit 2` and clear error if sibling repo absent. Pre-existing path assumption, orthogonal to this refactor.
- **Wizard doesn't yet route PDFs to `ingest_pdf` or XLSX to `ingest_xlsx`** — all files go through `OnboardingPipeline.ingest()` → `store.ingest_text()`. This was deliberately kept narrow in T8 to stay on critical path. Follow-up work can add type-aware routing for richer chunking (semantic PDF sections, XLSX rate-table regions).
- **Pre-existing test failures** on `tests/test_proposal_pipeline.py` (8 cases, order-dependent) and `tests/e2e/test_sandbox_provisioning.py::test_step7_dream_config_persisted` — exist on `dev-a@39e489b` and are unrelated to this refactor.

## Manual browser verification still to run

The web gateway in use runs from the `dev-a` checkout (not this worktree). To fully validate the demo scenario:

1. Cherry-pick / merge `feat/kb-unification` into `dev-a`
2. Restart `make run-web`
3. Re-run the original customer chat session:
   - `你好，你们提供什么服务` → expect KB-grounded reply (mentions 联络中心 / DID / IVR / Omnichannel etc), NOT "转接人工客服"
   - `what services do you provide` → KB-grounded English reply
   - `CINNOX Enterprise Plus 套餐有什么` → lists Enterprise Plus entitlements (dedicated CSM, SSO included)

The unit + integration tests prove the retrieval layer; the browser test confirms the full pipeline (customer WS → tenant_id resolution → `_build_customer_prompt` pre-fetch → customer_soul.md → streaming reply).

## Commit history (16 commits)

```
deb3904 refactor(kb): migrate seed scripts to KBStore + drop deprecated onboarding helpers
727c943 refactor(kb-skill): delegate CLI ingestion to autoservice.kb_core.KBStore
0983d91 test(kb): migrate kb_search helper from _init_sandbox_kb to KBStore
7ee2599 fix(onboarding): wire /upload to KBStore + website URL ingest + source_id dedup
e2fc8fa docs(kb): T11 breadcrumb in tokenizer + plan annotation for T7 hybrid
33529de fix(kb): trigram-compatible query tokenizer (unblocks Chinese customer queries)
760d0c1 feat(kb): KBStore.ingest_web with domain-bounded crawl and injectable session
d1284a5 feat(kb): KBStore.ingest_xlsx with rate-table region detection
d7d65e3 feat(kb): KBStore.ingest_pdf with heading/table semantic chunking
e6eb29d feat(kb): KBStore.ingest_text (paragraph chunking via save_chunks)
80b5fcd fix(kb): DELETE+INSERT not REPLACE to avoid trigram FTS corruption
c261543 feat(kb): KBStore.save_chunks (batched) + clear_source returns rowcount + FTS-REPLACE test
95ccb6a feat(kb): KBStore.save_chunk + clear_source + count (+ ctx-mgr, narrow OperationalError)
9833938 feat(kb): introduce KBStore with trigram tokenizer + legacy migration
d0e5c0a docs(plans): fix Task 1 _init_schema ALTER loop for legacy onboarding 6-col
9ff75dc docs(plans): fix Task 1 FTS schema + trigram query bounds
```
