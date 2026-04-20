# Batch 1 Kickoff · Backend fan-out + Frontend 双模式 hook

> 5 tasks · est. ~4h · 含 2 个 Yellow

## Pre-checks

- [ ] Batch 0 gate 通过：沙盒目录可生成产物，useTenantId / session/mode 可用
- [ ] Batch 0 提交已落盘
- [ ] **T1B.4 开启前**：先跑 `superpowers:receiving-code-review` 对 cc_pool 现状做 pre-flight，评估 worker 启动时是否固定 system prompt 的风险

## Tasks

| ID | Task | Slot | Owner | Mode | Est. | Type |
|---|---|---|---|---|---|---|
| T1B.4 | cc_pool per-tenant soul 注入 | A | Dev1 | solo | 4h | 🟡 Yellow |
| T1B.2 | /activate 幂等 merge | B | Dev1 | solo | 1h | Green |
| T1B.3 | rehearsal 落盘 + review 端点 | B | Dev1 | solo | 1h | Green |
| T1B.6 | Dream 配置 sync | B | Dev1 | solo | 1h | 🟡 Yellow |
| T1F.2 | useSessionMode hook | B | Dev1 | solo | 1h | Green |

## Execution Order

1. **并行开局**：T1B.4 占 slot A（需要 4h focus），T1B.2 占 slot B 开始
2. **Slot B 流水线**：T1B.2 → T1B.3 → T1B.6 → T1F.2
3. **T1B.6 完成后立即跑 T6C.3 回归**（/approve /reject 流）
4. 全部完成后 batch gate check

## Key files touched

- `autoservice/cc_pool.py` — `create_cc_client(role, tenant_id=None)` + `_load_soul()`
- `autoservice/onboarding.py` — `/activate` 改 merge
- `autoservice/api_routes.py` — `/rehearsal/*` 端点、`/api/management/chat` 里 dream sync
- `autoservice/dream_config_dialog.py` — 可能需要 export hook
- `frontend/packages/shared/useSessionMode.ts` + test

## Yellow task 注意

### T1B.4 · cc_pool worker 生命周期
- **风险**：若现有 cc_pool 的 worker 在 `__init__` 就烘焙 system prompt，则无法按 tenant 切。
- **检测方法**：先读 `autoservice/cc_pool.py` 确认 `create_cc_client` 返回的对象的 prompt 注入点是 init 还是 session-level。
- **fallback 方案**：如果必须固定，则 cc_pool 改为 `dict[tenant_id, AsyncPool]`，按 tenant 维护小池 + LRU 回收；`_load_soul` 仍按上面 signature 存在。

### T1B.6 · dream_config_dialog 边界
- **风险**：破坏已稳定的 /approve /reject 流（T6C.3 标绿）
- **保护**：改动后**必须**立即 `pytest tests/dream/ -v` 或相关测试（确认仓内具体路径），确保 T6C.3 回归通过。

## Smoke

```bash
# T1B.4 done 后
pytest tests/cc_pool/test_cc_pool_tenant_soul_injection.py -v

# T1B.2 done 后
pytest tests/onboarding/test_activate_is_idempotent.py

# T1B.3 done 后
pytest tests/api/test_rehearsal_review_persists.py

# T1B.6 done 后
pytest tests/dream/    # T6C.3 回归
# 手工：ManagementChat → /dream-config 完成 → 检查 sandbox/<tid>/config.json.dream

# T1F.2 done 后
cd frontend && pnpm vitest packages/shared/useSessionMode.test.ts
```

## Gate · 进 batch-2 前必过

- [ ] T1B.4 pytest 过 + 两租户对话回复风格可肉眼区分
- [ ] T1B.2 pytest 过（多次 /activate 不覆盖）
- [ ] T1B.3 pytest 过（rehearsal.json 落盘 + review 更新）
- [ ] T1B.6 T6C.3 回归 + dream 配置落盘验证
- [ ] T1F.2 vitest 过
- [ ] commit 覆盖所有改动
