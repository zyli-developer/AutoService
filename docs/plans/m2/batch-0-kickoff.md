# Batch 0 Kickoff — P1 Bootstrap foundation

**Milestone**：M2 · **Phase**：P1 · **预计时长**：4h
**Owner**：Dev1 · **模式**：串行（同一开发者）

## Pre-checks

- [ ] M1 已 shipped（项目 project.yaml 标记 `status: shipped`）
- [ ] dev-a 分支无 uncommitted 改动
- [ ] `pytest tests/` M1 baseline 全绿（非 e2e）
- [ ] plans_dir 已指向 `docs/plans/m2`

## 任务

| ID | 名称 | 类型 | 工作量 | 依赖 |
|----|------|------|--------|------|
| T1B.1 | config.local.yaml schema expectations | green | small | — |
| T1B.2 | soul_generator 5 roles (add dream) | 🟡 yellow | medium | T1B.1 |

## 执行顺序

1. **T1B.1**（先行）— 扩展 config loader 支持 `deployment_mode` / `tenant_id` / `dream.*` 字段；补 `.autoservice/config.local.yaml.example`；写 `tests/bootstrap/test_get_deployment_mode.py`
2. **T1B.2**（yellow review 点）— 修改 `soul_generator.py` 增加 dream 角色；LLM prompt 生成 + `_FALLBACK_DREAM_SOUL` 常量；写 `tests/soul_generator/test_dream_role.py`

## Yellow Review 点（T1B.2）

运行完成后，**停下来**让用户审核：
- dream 角色 prompt 内容是否贴合 spec §2.1 约束（产生 proposal，不直接改 soul）
- fallback 常量文本是否符合 red-line（绝不自动应用）
- 5 roles 列表是否完整（customer/operator/owner/manager/dream）

## 决策点

- 如果现有 `config.py` 使用 `yaml.safe_load`，可直接扩展 schema；如果用 pydantic，新字段需加到 BaseModel
- dream soul fallback：考虑是否复用 `autoservice/dream_soul_template.md`（task-hints 标记 delete）；此任务内把内容迁进 `_FALLBACK_DREAM_SOUL` 常量

## Smoke 测试

- `pytest tests/bootstrap/test_get_deployment_mode.py -v` — config 读取返回三字段
- `pytest tests/soul_generator/test_dream_role.py -v` — 5 角色生成；LLM 失败时 fallback 触发
- `pytest tests/` 无回归（M1 baseline 保持）

## 完成条件

- [ ] 两个任务 `status: done`，`task-status.md` 更新
- [ ] 上面两条 smoke test 全绿
- [ ] commit 提交（conventional commits: `feat(autoservice):` / `test(soul_generator):`）
- [ ] 进入 batch-1（Tenant bootstrap + lifespan）
