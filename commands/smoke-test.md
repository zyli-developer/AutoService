执行 Milestone smoke test。目标 Milestone：$ARGUMENTS

1. 读 docs/plans/batches-M1-to-M5-kickoff.md 找到对应 Milestone 的 smoke test 章节（标有 🤝 的段落）
2. 读 docs/plans/task-status.md 确认该 Milestone 对应 Phase 的所有任务状态
3. 输出验收检查表：

## {Mx} Smoke Test 检查表

### 前置条件
- [ ] 该 Phase 所有任务 🟩（列出未完成的）
- [ ] pytest 相关测试目录全绿

### 验收点
（从 kickoff 的 smoke test 章节逐条列出，带 checkbox）

### 需要启动的服务
（从 kickoff 列出启动命令）

### 执行
4. 若用户说"跑"，依次执行可自动化的检查：
   - 跑 pytest 对应目录
   - 检查 task-status.md 状态完整性
   - 检查 .artifacts/registry.json 产出齐全
5. 不可自动化的项（如浏览器手工验收）标注"需手动验证"
6. 输出结果汇总：通过 / 未通过 / 需手动
7. 全部通过 → 建议执行 Milestone 合并流程（cc-prompt-templates §7.3）
