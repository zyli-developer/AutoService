---
type: issue
id: issue-002
status: open
producer: skill-5
created_at: "2026-04-22"
related:
  - eval-doc-022
url: https://github.com/ezagent42/AutoService/issues/79
---

# Issue #79 · customer-chat voice call FAB (integrate cc-openclaw voice service)

- **URL**: https://github.com/ezagent42/AutoService/issues/79
- **Label**: enhancement
- **Source**: eval-doc-022 (simulate mode)
- **Reporter**: li.zhenyu
- **Assignee**: TBD
- **State**: open

## 摘要

在 customer-chat SPA 浮窗的 📞 按钮接入 cc-openclaw 的语音服务。MVP 走路线 A（iframe 嵌 `https://voice.ezagent.chat`），AutoService 负责开窗 + 透传上下文（tenant_id/customer_id/call_id 等）+ 关窗；语音全链路保留在 cc-openclaw 内部（voice-web / voice_gateway / channel_server）。

详细设计、testcase、风险、未决问题和验收标准见 eval-doc-022：
`.artifacts/eval-docs/eval-voice-call-fab.md`
