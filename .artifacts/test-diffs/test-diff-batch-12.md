# Test diff: batch-12

17 new tests across 2 new files (1 new package `tests/fork_runtime/`).

## 新增文件

- `tests/fork_runtime/__init__.py` — package marker
- `tests/fork_runtime/test_tenant_root.py` — T7B.2 helper (10 tests)
- `tests/fork_runtime/test_tenant_context.py` — T7B.1 middleware (7 tests)

## 覆盖的场景

### T7B.2 tenant_root() — spec §3.3 (10 tests)

| Class | Test | Rule |
|-------|------|------|
| `TestInternalTenantsModeAgnostic` | `test_master_in_master_mode` | Rule 1 — `_master` fixed path |
| | `test_master_in_tenant_mode` | Rule 1 — internal ID is mode-agnostic |
| | `test_local_admin_in_master_mode` | Rule 1 — `_local_admin` fixed path |
| | `test_local_admin_in_tenant_mode` | Rule 1 — mode-agnostic |
| | `test_unknown_internal_tenant_raises` | defensive: `_phantom` → ValueError |
| `TestRegularTenantsFollowMode` | `test_regular_in_master_mode_goes_to_sandbox` | Rule 2 — master → `.autoservice/sandbox/<tid>` |
| | `test_regular_in_tenant_mode_goes_to_plugins` | Rule 2 — tenant → `plugins/<tid>` |
| `TestNoneFallback` | `test_none_in_master_mode_falls_back_to_master_tenant` | Rule 3 — spec-ambiguity decision (`_master` default) |
| | `test_none_in_tenant_mode_uses_self_tenant_id` | Rule 3 — tenant mode None → `get_tenant_id()` |
| `TestEmptyStringRejected` | `test_empty_string_raises` | defensive: `""` → ValueError |

### T7B.1 TenantContext middleware — spec §3.2 (7 tests)

| Class | Test | Behaviour |
|-------|------|-----------|
| `TestMasterModePassThrough` | `test_prefixed_path_is_not_rewritten` | `/t/acme/chat` unchanged, state populated |
| | `test_flat_path_is_not_rewritten` | `/echo` unchanged |
| `TestTenantModeRewriting` | `test_self_tenant_prefix_stripped` | `/t/acme/chat` → `/chat` |
| | `test_cross_tenant_returns_403` | `/t/bob/chat` → 403 JSON |
| | `test_flat_url_passes_through` | `/chat` pass-through |
| | `test_request_state_populated_on_prefixed_path` | state.deployment_mode + tenant_id |
| | `test_bare_self_tenant_rewrites_to_root` | `/t/acme` → `/` |

## 已修 regression bug

None — new functionality. Pre-existing failures in `tests/contract/test_protocol_signatures.py::test_no_extra_protocol_methods` + `tests/test_proposal_pipeline.py` (10 failures) are independent of batch-12 (confirmed by re-running without our changes: identical failures).

## Evidence commands

```bash
python -m pytest tests/fork_runtime/ -v            # 17 passed
python -m pytest tests/fork_runtime/ tests/bootstrap/ tests/api/ tests/auth/ -q  # 102 passed, 0 failed
```
