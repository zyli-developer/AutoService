# Eval: T7S.4 scripts/setup.sh mode-aware setup + Makefile delegation

Spec: [docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §3.5](../../docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md)
Batch: batch-13 (parallel with T7F.3; this task only touches scripts/, Makefile, tests/setup/, .artifacts/).

## 预期行为

- `make setup` 委托到 `bash scripts/setup.sh`；Makefile 只剩一行 `@bash scripts/setup.sh`。
- `scripts/setup.sh` 读 `.autoservice/config.local.yaml` 的 `deployment_mode`；若文件缺失则默认 `master`（fresh install / 刚 clone）。
- Master 模式（保持 M1 行为）：
  - `.claude/{skills,commands,agents,hooks}` 指向顶层目录（symlink / junction）。
  - 扫 `plugins/*/` 发现 plugin skills，为每个 plugin 子 skill 建 `skills/<name>` symlink（跳过 `_example` 与 `_local_admin`）。
  - 创建 `.autoservice/{logs,data,cache,sandbox,run,database}` 运行时目录。
- Tenant 模式（fork 仓单租户）：
  - 读 `tenant_id`（空 → 报错退出非 0，错误信息指向 runbook 第 4 步）。
  - `.claude/skills/` 指向 `plugins/<tid>/skills/`（若存在）。
  - plugin discovery 仅扫 `plugins/<tid>/`。
  - 跳过 `_local_admin`（本地管理助手不暴露 skill）。
- 所有模式：init `.autoservice/{logs,sandbox,cache}` 等 runtime 目录（幂等 `mkdir -p`）。

## 验收标准

1. **fresh install**：无 `.autoservice/config.local.yaml` → 以 `master` 运行，创建 runtime 目录；退出码 0。
2. **master 模式显式**：`deployment_mode: master` + 无 tenant_id → 与 fresh install 一致；无 per-tenant symlink。
3. **tenant 模式（有 tenant_id）**：`deployment_mode: tenant` + `tenant_id: foo` → 创建 `plugins/foo/`、`plugins/foo/skills` symlink 指向 `skills/`；`.claude/skills` 指向 `plugins/foo/skills`；跳过 `_local_admin`。
4. **tenant 模式（缺 tenant_id）**：`deployment_mode: tenant` 无 tenant_id → 非 0 退出 + stderr 明确错误信息（含 "tenant_id"）。
5. **幂等**：连续运行两次 → 第二次不报错，无重复 symlink。
6. **非破坏**：预先存在的 `.autoservice/sandbox/` 内容保留；不 rm `.autoservice/*` 子目录。
7. **.claude/skills 若是已有 symlink** → 不覆盖（非必须保持旧指向，但不能破坏原有文件或内容）。

## 关键 invariant

- 不删除 `.autoservice/` 下的已存在数据（logs、sandbox、database、cache、run）。
- POSIX / bash-compatible；Makefile 既有 target 使用 bash features 所以允许 bash。
- Windows 上 `ln -sfn` 失败时走 fallback（junction via `cmd //c mklink /J`）或至少不崩；M1 已处理方式沿用。
- Master 模式输出与 M1 Makefile 原 setup target 行为一致（skill symlinks、runtime dirs）。
- Tenant 模式只接触 `plugins/<tid>/`，不碰其他 plugin。
- 脚本 exit code：成功 0；配置错误 非 0。
