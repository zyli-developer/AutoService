# Test diff: T7S.4 (batch-13 parallel)

新增 **8 tests** across **1 new test file** + 1 package init.

## 新增文件

- `tests/setup/__init__.py` — test package marker
- `tests/setup/test_setup_sh.py` — subprocess-driven tests for `scripts/setup.sh` (8 cases)

## 覆盖的场景

From [eval-doc-016](../eval-docs/eval-t7s-4-setup.md) 验收标准:

1. `test_fresh_install_defaults_to_master` — no config.local.yaml → master mode + runtime dirs (验收 1)
2. `test_explicit_master_mode` — `deployment_mode: master` → no per-tenant symlinks (验收 2)
3. `test_tenant_mode_requires_tenant_id` — `deployment_mode: tenant` w/o tenant_id → non-zero exit + clear error (验收 4)
4. `test_tenant_mode_with_tenant_id` — `deployment_mode: tenant` + `tenant_id: foo` → plugins/foo/skills link created (验收 3)
5. `test_idempotent_double_run` — two consecutive runs both exit 0 (验收 5)
6. `test_preserves_existing_sandbox_data` — pre-existing `.autoservice/sandbox/` sentinel survives (验收 6, invariant "non-destructive")
7. `test_tenant_mode_skips_local_admin` — `_local_admin` skill subfolder is not exposed as `skills/_local_admin` (spec §3.5)
8. `test_master_mode_skips_example_plugin` — `_example` plugin skipped by master-mode discovery (spec §3.5)

Each test spins up an isolated AutoService-shaped project under `tmp_path`, copies `scripts/setup.sh` into it, and runs the script via bash (Git-Bash on Windows, `/bin/bash` elsewhere). No test touches the real repo tree.

## 已修 regression bug

无新回归；整批运行 `pytest tests/setup/ tests/bootstrap/` → **27 passed, 0 failed**。

## 实现细节（Windows 特有）

Git-Bash 的 `ln -sfn DIR LINK` 在无 `MSYS=winsymlinks:nativestrict` 时会 deep-copy 目录而非创建 junction。为保证幂等性，`scripts/setup.sh` 引入 `safe_link()` helper：

- 如果 link 已经指向正确 target → noop
- 如果 link 是其他 symlink → `rm -f` 后重链
- 如果 link 是真目录（Git-Bash 复制 fallback）→ `rm -rf` 后重链
- 不动 `.autoservice/*` 子目录（invariant: never destroy user data）

Plugin discovery 循环里新增检查：若 `skills/<name>` 已经是真目录（first-party skill），跳过不覆盖，避免 `skills/alpha/alpha` 这类嵌套。
