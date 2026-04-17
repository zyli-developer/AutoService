# test-vectors/

T0.2 / T0.3 共用的契约测试向量。LocalEngine 实现 + 契约测试套件（`tests/contract/`）从这里取数据，避免示例漂移。

## 文件清单

| 文件 | 内容 | 上游契约 |
|---|---|---|
| `events.json` | ConversationEngine 22 类 Event 的 `data` 字段正例（每类 ≥1） | `../conversation-engine.md v1.0 §5` |
| `ws-frames.json` | _(待补)_ FE→BE / BE→FE 帧示例 | `../frontend-ws-schema.md §4 §5` |
| `negative/` | _(待补)_ 反例集（应抛 ValidationError / IllegalModeTransition / PermissionDenied 等） | T0.3 测试用 |

## 用途

- **T0.3 契约测试**：`pytest tests/contract/ -v` 通过 `pytest.parametrize` 加载本目录数据
- **LocalEngine mock 实现**：开发期可直接读 events.json 作为"理想输出"对照
- **前端 mock server**：FE 联调可拿示例直接回放，无需启 LocalEngine

## 约定

- **JSON only**（YAML 不可机读 schema 校验）
- **每条向量自描述**：含 `$comment` 字段说明语义；测试代码不应解析 `$comment`
- **timestamp 全部 2026-04-15 UTC**：固定时间方便快照测试
- **ULID 格式**：26 字符；测试中如需稳定可走 fixture 替换

## 变更流程

向量变更 = 契约变更：必须连带改 `../conversation-engine.md` 或 `../frontend-ws-schema.md`，并在 PR 描述说明 v0.x → v0.y bump。
