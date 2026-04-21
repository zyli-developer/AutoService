# Eval: M2 Phase 1 — Bootstrap + _master seed

**Backfill · 2026-04-21 · covers batch-0 + batch-1 (T1B.1 → T1B.5)**
**Spec**: [docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md](../../docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md) §1.3, §2.3, §2.7, §2.8, §3.1
**Tasks**: [docs/plans/m2/2026-04-20-tasks.yaml](../../docs/plans/m2/2026-04-20-tasks.yaml) T1B.1..T1B.5
**PRD constraints**: [docs/plans/m2/2026-04-20-m2-prd-structure.yaml](../../docs/plans/m2/2026-04-20-m2-prd-structure.yaml) CON-01, CON-04, CON-05, CON-07

## 预期行为

- **T1B.1** (spec §1.3 + §3.1) — `autoservice.bootstrap.get_deployment_mode()` reads `.autoservice/config.local.yaml`:
  - Missing `deployment_mode` → defaults to `"master"`.
  - `deployment_mode: tenant` requires `tenant_id` and consistency check against `plugins/<tid>/config.json.tenant_id`.
  - Any other value raises `AssertionError`.
  - `get_tenant_id()` returns `None` in master mode, the tenant_id string in tenant mode.
  - `dream.*` block (idle_threshold_min / cool_down_min / max_tool_turns) is loadable but not enforced here (enforcement deferred to T4B.*).
- **T1B.2** (spec §2.3 + CON-04) — `autoservice.soul_generator` extended to **5 roles**: `customer`, `translate`, `lead`, `triage`, `dream`.
  - `_KB_QUERIES["dream"]` has dream-specific retrieval prompts (mission/values, gaps, compliance boundaries).
  - `_FALLBACK_DREAM_SOUL` module constant inlined; preserves the red-line literals "NEVER auto-apply" and `status='draft'` verbatim.
  - `SoulDraft.mode` ∈ {`"llm"`, `"fallback"`} surfaced in `_generation_meta.yaml`.
  - Dream fallback short-circuits brand substitution (platform-level, owned by `_master` per §2.7).
- **T1B.3** (spec §2.7) — `autoservice.master_tenant.ensure_master_tenant()` idempotently provisions `.autoservice/sandbox/_master/` with `tier=0`, `kind=platform`, `canary.stages=[100]` (single-stage), 5-role souls (dry_run=True at startup so no LLM call), empty kb.db, deep-copied default dream cfg.
- **T1B.4** (spec §2.8) — `ensure_local_admin()` provisions **`plugins/_local_admin/`** (NOT sandbox — fork repos have no sandbox concept) with `kind=fork`, 5 souls, idempotent.
- **T1B.5** (spec §1.3 lifespan wire) — `autoservice/web_gateway.py` `@app.on_event("startup")` dispatches to `ensure_master_tenant()` or `ensure_local_admin()` based on `bootstrap.get_deployment_mode()`. Missing config.local.yaml → log + continue (non-fatal in dev).

## 验收标准

- [x] `pytest tests/bootstrap/test_get_deployment_mode.py` → 8 passed — implemented in commit `178919c`
- [x] `pytest tests/soul_generator/test_dream_role.py` → 9 passed + 2 regression fixes in `tests/test_soul_generator.py` — commit `9def883`
- [x] `pytest tests/bootstrap/test_ensure_master_tenant.py` → 4 passed — commit `dc49ff0`
- [x] `pytest tests/bootstrap/test_ensure_local_admin.py` → 4 passed — commit `dc49ff0`
- [x] `pytest tests/bootstrap/test_lifespan_wire.py` → 3 passed — commit `dc49ff0`
- [x] Red-line lock-in tests: `test_fallback_dream_soul_preserves_red_line_literal` + brand-neutrality test guard CON-04 (commit `9def883`)
- [x] Yellow review (T1B.2): superpowers:code-reviewer subagent APPROVED, no blockers (commit `9def883` body)

Total new tests for Phase 1: **20** passing across 5 files + 2 regression fixes.

## 关键 invariant

- **CON-01** — Deployment mode toggled only via `.autoservice/config.local.yaml.deployment_mode`. The bootstrap loader is the single gate; no other module reads this field directly.
- **CON-04 (red line)** — `_FALLBACK_DREAM_SOUL` and every generated dream soul must contain "NEVER auto-apply" and `status='draft'` literals. Enforced by `test_fallback_dream_soul_preserves_red_line_literal` — deliberate loudness when an editor softens the wording.
- **CON-05** — Internal tenants (`_master`, `_local_admin`) occupy `tier=0`; regular tenants use `tier=1`. `ensure_master_tenant` and `ensure_local_admin` both set `tier=0` at config creation.
- **CON-07** — No PROJECT_ROOT violations: new modules (`bootstrap.py`, `master_tenant.py`) use `Path(__file__).resolve().parent.parent` for root detection; no wildcard imports.
- **CON-04 (propagation)** — Dream soul fallback short-circuits brand substitution because platform-level Dream guidance must not be reinterpreted through merchant branding (verified by `test_dream_fallback_not_brand_substituted`).
- **Idempotency** — All three `ensure_*` helpers are safe to call on every startup without mutating already-provisioned state (verified by per-function idempotency tests).

## Evidence

| Artifact | Location |
|----------|----------|
| Test files | `tests/bootstrap/*.py`, `tests/soul_generator/test_dream_role.py` |
| Implementation | `autoservice/bootstrap.py`, `autoservice/master_tenant.py`, `autoservice/soul_generator.py`, `autoservice/web_gateway.py` |
| Commits | `178919c`, `9def883`, `dc49ff0` |
| Task status row | [docs/plans/m2/task-status.md](../../docs/plans/m2/task-status.md) Phase 1 table |
