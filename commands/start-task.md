读 docs/plans/cc-prompt-templates.md 获取指令模板库。

用户要启动的任务是：$ARGUMENTS

请按以下流程操作：

1. 先读 docs/plans/task-status.md，确认该任务当前是 ⬜ pending 且前置依赖全部 🟩
2. 判断任务颜色类型（从 task-status.md 的"类型"列读取）：
   - 🟢 Green → 用 cc-prompt-templates.md §1 启动模板 + §2 dev-loop 推进
   - 🟡 Yellow → 用 cc-prompt-templates.md §6 Yellow 任务模板
   - 🔴 Red → 用 cc-prompt-templates.md §5 Red 任务模板
3. 用 Edit 把该任务行状态改为 🟦 in_progress，Owner 填当前开发者（从分支名推断：dev-a → DevA，dev-b → DevB），commit "task: {ID} → in_progress ({Owner})"
4. 读 docs/plans/2026-04-15-prd-gap-tasks-v3.md 中该任务的产出和验收标准
5. 读相关契约文件（docs/contracts/*）
6. 进入 dev-loop 第一步：skill-5-feature-eval simulate 模式，产出 eval-doc
7. eval-doc 产出后**停住等用户 review**，不要自动进入下一步

按以上顺序，每步完成汇报，不要跳步。
