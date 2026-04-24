# Test diff: T7B.6 — `/api/management/chat` → `_master` routing

**Task**: T7B.6 · Phase 7 · Green · batch-14 (parallel with T7S.5 smoke test in `tests/fork_runtime/`)
**Eval-doc**: [.artifacts/eval-docs/eval-t7b-6-management-chat.md](../eval-docs/eval-t7b-6-management-chat.md) (eval-doc-019)
**Related**: test-diff-016 (T7B.1 + T7B.2 fork-runtime foundations) · test-diff-015 (T6F.5 + T6F.6 — symmetric `/api/admin/chat` endpoint on tenant side)

## Summary

7 new tests, 1 new file. 0 new regression across `tests/api/ tests/auth/ tests/cc_pool/ tests/dream_agent/ tests/bootstrap/` (157 passed).

## 新增文件

- `tests/api/test_management_chat.py` — 7 test cases covering the M2 wire contract for `POST /api/management/chat`.

## 代码改动

- `autoservice/api_routes.py` — new `management_chat` handler replaces the M1 handler at `POST /api/management/chat`. The M1 slash-command / Dream-Engine dispatcher is preserved verbatim under the new route `POST /api/management/chat-legacy` for one milestone (rename-not-delete, per eval-doc-019).

## 覆盖的场景

### T7B.6 `/api/management/chat` M2 routing — spec §2.7 (7 tests)

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_management_chat_valid_message_returns_reply` | 200 + `{"reply": "mocked reply"}`; `pool.acquire` called once with `role="customer", tenant_id="_master"`; prompt forwarded verbatim |
| 2 | `test_management_chat_empty_message_returns_422` | Whitespace-only message → 422 `{"error": "message required"}`; pool never touched |
| 3 | `test_management_chat_missing_field_returns_422` | `{}` body → 422, pool never touched |
| 4 | `test_management_chat_routes_to_master_not_null_tenant` | Body-passed `tenant_id` override is IGNORED; handler pins `tenant_id="_master"` (never `None`, never `"default"`, never body value). Spec §2.7 contract guard |
| 5 | `test_management_chat_pool_unavailable_returns_503` | `get_pool()` → `None` → 503 `{"error": "cc_pool unavailable..."}` (not 500, not hardcoded stub reply) |
| 6 | `test_management_chat_regression_no_stub_llm` | Source-level regression guard: `inspect.getsource(management_chat)` does NOT contain `DreamConfigSession`, `/approve`, `/reject`, `/rollback`, `@Dream Engine`, `is_dream_config_trigger`, `dream_session`, or the M1 stub reply fragments. POSITIVE checks: source contains `role="customer"` AND `tenant_id="_master"` |
| 7 | `test_management_chat_legacy_still_works` | `/api/management/chat-legacy` with no body → M1 prompt-me message (confirms the M1 slash-command UX still reachable during M2→M3 deprecation window) |

### Test plumbing

- `_FakePool` / `_FakeClient` / `_FakeMessage` / `_FakeInstance` — in-file stubs that mirror the real `CCPool.acquire() + instance.client.query() + receive_response()` contract (see `autoservice/cc_pool.py:359-366`).  Uses `@asynccontextmanager` so `async with pool.acquire(...) as instance` works byte-for-byte like the real pool.
- `fake_pool` fixture patches `autoservice.cc_pool.get_pool` via `monkeypatch.setattr` — the endpoint imports `get_pool` lazily inside the handler, so module-level patch is authoritative.
- `app_client` fixture mirrors `tests/api/test_dream_api.py` — fresh FastAPI app per test with `api_router` mounted under `/api`, `monkeypatch.chdir(tmp_path)` for filesystem isolation.

## 已修 regression bug

None — new functionality. The M1 `management_chat` handler is preserved at `/api/management/chat-legacy` so no existing caller loses function.

## 不涉及的测试

- `tests/fork_runtime/` — T7S.5 territory (sibling agent). No edits under that tree.
- `tests/api/test_dream_api.py` / `test_master_tenants.py` / `test_session_mode.py` / `test_rehearsal_review_persists.py` — untouched; zero overlap with `/api/management/chat`.

## Evidence commands

```bash
# New tests — all 7 green.
python -m pytest tests/api/test_management_chat.py -v
# 7 passed in 1.16s

# Regression — all M2 backend suites green.
python -m pytest tests/api/ tests/auth/ tests/cc_pool/ tests/dream_agent/ tests/bootstrap/ -q
# 157 passed in 6.27s (0 new failures)
```

## Follow-up flagged (from eval-doc-019)

- Admin tool set (`list_tenants`, `read_proposals`, `approve_proposal`, etc.) — M3 task.
- Legacy endpoint deletion — M3, once the tool set ships.
- `cc_pool` customer-role `tenant_id` soul injection — separate refactor PR.
- `Depends(auth.require_admin)` on `/api/management/chat` — paired with the admin-tool batch.
