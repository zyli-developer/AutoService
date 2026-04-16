用户想知道下一步该做什么。身份信息（可选）：$ARGUMENTS

按以下步骤推荐：

1. 从 git 分支名推断身份（dev-a → DevA，dev-b → DevB）；若用户提供了身份则以用户为准
2. 读 docs/plans/task-status.md：
   - 若有 🟦 in_progress 的任务 → 提示"你有未完成任务 {ID}，建议先用 /continue-task {ID} 继续"
   - 若无 → 进入推荐流程
3. 读 docs/plans/batches-M1-to-M5-kickoff.md 确定当前所在 Milestone 和 Batch：
   - 找到最近一个未全部 🟩 的 Phase → 当前 Milestone
   - 在该 Milestone 内找到最早一个有 ⬜ 任务的 Batch → 当前 Batch
4. 从当前 Batch 中筛选该 Owner 的 ⬜ 任务（依赖已全部 🟩）
5. 按优先级排序：🟢 Green > 🟡 Yellow > 🔴 Red
6. 输出推荐表（最多 5 个）：

| 推荐 | 任务 ID | 名称 | 类型 | 依赖状态 | 所属 Batch |
|---|---|---|---|---|---|

7. 同时检查是否有需要并行启动的 Red 前置任务（kickoff 中标注的"Red 并行"项）
8. 让用户选一个，或直接说 `/start-task {推荐的第一个}`
