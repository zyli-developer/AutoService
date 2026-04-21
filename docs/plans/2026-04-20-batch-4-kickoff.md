# Batch 4 Kickoff · E2E Smoke + M1 Gate

> 1 task · est. ~4h · M1 收官

## Pre-checks

- [ ] Batch 3 gate 通过：master tabs 可用 + wizard 可 publish
- [ ] Batch 3 提交已落盘
- [ ] Backend + frontend 都能启起来

## Tasks

| ID | Task | Slot | Owner | Mode | Est. |
|---|---|---|---|---|---|
| T1S.1 | 端到端沙盒 provisioning smoke test | A | Dev1 | solo | 4h |

## Execution

覆盖 spec §10 验收 9 条：

```python
# tests/e2e/test_sandbox_provisioning.py
import pytest
from pathlib import Path

def test_step1_master_tenants_empty():
    """A 打开 Master：/master/tenants 初始空"""
    ...

def test_step2_wizard_full_flow():
    """A 走向导 Step 0~4"""
    ...

def test_step3_sandbox_artifacts_complete(tenant_id):
    """沙盒产物齐全：souls/ × 5 + kb.db + rehearsal.json + config.json"""
    sandbox = Path(f".autoservice/sandbox/{tenant_id}")
    assert (sandbox / "souls").glob("*.md").__len__() == 5
    assert (sandbox / "kb/kb.db").exists()
    rehearsal = json.loads((sandbox / "rehearsal.json").read_text())
    assert all(d["review_status"] != "pending" for d in rehearsal["dialogs"])
    cfg = json.loads((sandbox / "config.json").read_text())
    assert cfg["status"] == "sandbox"
    assert cfg["channels"]
    assert "dream" in cfg

def test_step4_preview_conversation(tenant_id):
    """/t/<tid>/chat 能对话 + WS 日志含 tenant_id"""
    ...

def test_step5_multi_tenant_isolation(tenant_x, tenant_y):
    """两个租户 agent soul 不串"""
    ...

def test_step6_master_preview_iframe(tenant_id):
    """/master/tenants/<tid>/preview 嵌入 iframe 可用"""
    ...

def test_step7_dream_config_persisted(tenant_id):
    """ManagementChat 走完 /dream-config 后 config.json.dream 含 4 参数"""
    cfg = json.loads((sandbox / "config.json").read_text())
    for key in ["trigger", "coverage", "risk_threshold", "canary"]:
        assert key in cfg["dream"]

def test_step8_publish_full_pipeline(tenant_id):
    """点 publish → tarball + runbook + record + 沙盒归档 + 410"""
    # POST /api/onboard/publish
    # 验证 tarball 存在
    # 验证 archive dir 存在
    # 再访 /t/<tid>/chat 应 410

def test_step9_tarball_fork_manual():
    """tarball 解压到 fork 仓模拟 → make check 通过（手工标注）"""
    ...
```

## Key files touched

- `tests/e2e/test_sandbox_provisioning.py` — **new**
- Possibly `conftest.py` / `tests/fixtures/` — 如需 fixtures 为 tenant 准备测试数据

## M1 Gate（所有项必过）

1. [ ] 15 tasks 全 `completed` on [m1-task-status](2026-04-20-m1-task-status.md)
2. [ ] `pytest tests/` 全绿
3. [ ] `make check` 通过
4. [ ] T6C.3 历史回归通过（`pytest tests/dream/` 或相关路径）
5. [ ] `pytest tests/e2e/test_sandbox_provisioning.py -v` 9/9 通过
6. [ ] spec §10 九条人工逐条过
7. [ ] Tarball 解压得到 `plugins/<tid>/` 手工 `git mv` 到一个 fork 仓克隆后 `make check` 通过

## 交付

- **commit**：`feat(m1): sandbox provisioning end-to-end — §10 verified`
- **更新 task-status**：[m1-task-status.md](2026-04-20-m1-task-status.md) 全部标 ✅
- **可选**：创建 PR 到 `dev` 分支
- **M2 规划**：开新 brainstorming session 处理延期的 P0 (GAP-002 管理群 IM / GAP-006 晨起推送) + TenantLayout 实装 + Dream Engine agent 化
