---
title: AutoService Voice × Cinnox SIP 接入评估
date: 2026-04-27
owner: yaosh
status: 评审中（评估完成，待对方/团队反馈）
---

# Cinnox SIP Voice Bot × AutoService 接入评估

## 背景一句话

合作方 Cinnox 的语音机器人产品线只能通过 SIP 接入第三方 voicebot；我们要把
AutoService 的 voice 能力暴露给他们的客户。下面三份文档梳理了：现有 voice
是什么样、对方提案中哪里站得住脚 / 哪里站不住，以及一份可以直接动手的 5 周
PoC 计划。

## 文档目录

| # | 文件 | 内容 |
|---|---|---|
| 01 | [current-voice-architecture.md](01-current-voice-architecture.md) | dev 分支上 voice 已经实现到哪一步、协议契约、仍是浏览器编排的事实 |
| 02 | [cinnox-sip-proposal-review.md](02-cinnox-sip-proposal-review.md) | 对原始 jambonz + audio_fork 提案的逐条评审，指出 P0/P1/P2 问题 |
| 03 | [actionable-plan.md](03-actionable-plan.md) | 修正后的 5 周可执行 PoC 计划（含里程碑、验证脚本、退出条件） |
| **04** | **[final-executable-plan.md](04-final-executable-plan.md)** | **★ 最终单文件可执行方案（合并版，开工就读这个）** |

## 一行结论

**方向正确，细节需要重写。** jambonz + audio_fork 是把 SIP 流量
桥接到 WebSocket-backed voice pipeline 的合理选择，但提案里
sip_audio_route.py 草稿里的 `tts.send_text()` / `tts.receive_audio()` /
`tts.interrupt()` 在现有代码里都不存在；提案声称"复用 Doubao E2E 一体
对话"也与现有 split-mode 实现不符。需要在 SIP adapter 之外**新写一层
服务端 voice controller**（把浏览器里的 `VoiceCallController.ts` 港到
Python），并修掉 `TTSClient` 每次合成重连 300-500ms 的旧问题，否则
P50 < 1.2s 的目标做不到。

## 已确定的决策（2026-04-27 user）

| # | 决策 | 选择 |
|---|---|---|
| 1 | 排期 | **5 周**（含 1 周 controller + 重连优化） |
| 2 | 部署 | **单点**（推荐 HK，覆盖 Cinnox HK SBC 主路径；其它区域承担额外 50-80ms） |
| 3 | Cinnox SIP 表单 | **只申请 inbound**；outbound 后续单独走流程 |
| 4 | 对话引擎 | **沿用现有 `/ws/chat` → cc_pool**；不引入多智能体 / instant-ack 复杂度 |

## 不在本评估范围

- Outbound（外呼）实现 — 需要单独 issue
- 把现有 split-mode 升级为真正的 E2E mode — 工作量大、收益不明显
- 用 Pipecat / LiveKit 等编排层重写 voice — 与现有 split 架构正交
- 接入多智能体 / instant-ack / 评分等 IM 侧编排
- WeChat Voice / 微信小程序语音 — 完全不同 channel
