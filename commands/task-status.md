读 docs/plans/task-status.md 和 docs/plans/cc-prompt-templates.md §7.1，给我：

1. 当前整体进度（x/66，各 Phase 明细百分比）
2. 进行中任务（🟦 + Owner 列表）
3. 阻塞任务（⚠️ + 阻塞原因）
4. 下一批可启动的 ⬜ 任务（依赖已满足，按优先级排序，一次最多 5 个）
5. 风险提示（落后于计划时间表的任务）

用简洁表格输出。
