用户要继续推进的任务是：$ARGUMENTS

读 docs/plans/cc-prompt-templates.md §2 推进模板和 §3 归档模板。

按 dev-loop 流程继续当前任务的下一步：

1. 读 docs/plans/task-status.md 确认该任务当前是 🟦 in_progress
2. 判断当前进度（从上下文推断），执行下一步：
   - eval-doc 刚 review 过 → skill-2-test-plan-generator 产出 test-plan，停住等确认
   - test-plan 刚确认 → skill-3-test-code-writer 写测试代码
   - 测试写完 → 进入实现阶段（业务代码）
   - 代码写完 → skill-4-test-runner 跑测试
   - 全绿 → 归档：改状态 🟩 + 填 artifact ID + commit + push + 推荐下一个可启动任务
   - 有红 → 定位失败原因，修复后重跑
3. 每步完成汇报，允许用户中断调整
