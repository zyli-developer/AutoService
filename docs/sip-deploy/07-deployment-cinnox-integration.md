---
title: AutoService SIP 接入 — 部署与 Cinnox 对接计划
date: 2026-04-28
owner: yaosh
status: 可执行（W1 开始）
companion: 06-code-changes-plan.md
---

# 部署与 Cinnox 对接计划

> 配套代码改动文档：[06-code-changes-plan.md](06-code-changes-plan.md)
> 应用层（FastAPI `/sip-audio`）部署在 **Mac**（复用现有 CF Tunnel
> `autoservice.ezagent.chat`），SIP 终结部署在 **火山云 HK VPS**。

## 0. 拓扑

```
PSTN
 │
 ├── Cinnox SBC (HK / BJ / JP / SG, 8 IPs)
 │        │
 │        │ SIP/RTP (PCMA 8kHz, RFC2833 DTMF)
 │        ▼
 │   ┌─────────────────────────────────────────┐
 │   │ 火山云 HK 轻量服务器 (固定公网 IP)        │
 │   │                                          │
 │   │ ┌───────────────────────────────────┐   │
 │   │ │ jambonz (docker-compose)          │   │
 │   │ │  ├─ drachtio (SIP UA)              │   │
 │   │ │  ├─ rtpengine (RTP 重采样)         │   │
 │   │ │  ├─ sbc-inbound / sbc-outbound     │   │
 │   │ │  ├─ feature-server                 │   │
 │   │ │  └─ jambonz-api-server / mysql     │   │
 │   │ └───────────────────────────────────┘   │
 │   │              │                           │
 │   │              │ audio_fork (wss + 16kHz   │
 │   │              │             PCM mono)     │
 │   └──────────────┼───────────────────────────┘
 │                  │
 │                  │ wss + CF-Access-Client-Id/Secret headers
 │                  ▼
 │           Cloudflare Edge
 │                  │
 │                  ▼
 │           cloudflared (Mac launchd)
 │                  │
 │                  ▼
 │           Mac:18080 (Caddy) → Mac:8000 (uvicorn)
 │                                      │
 │                                      ├── /asr /tts (现有)
 │                                      └── /sip-audio (新增)
 │                                              │
 │                                              ▼
 │                                      SipVoiceController
 │                                              │
 │                                              ├── ASRClient → Doubao
 │                                              ├── TTSClient → Doubao (streaming)
 │                                              └── CCChatClient → /ws/chat → cc_pool
 ▼
（Doubao realtime/dialogue API in 火山云 / 公网）
```

## 1. 已确定的决策

| # | 项 | 选择 | 备注 |
|---|---|---|---|
| 1 | VPS | 火山云 HK 轻量 2c2g | ¥30/月，固定 IP，离 Cinnox HK SBC 物理近 |
| 2 | 应用层部署 | Mac + 现有 CF Tunnel | 不动现有部署，直接复用 |
| 3 | SIP 终结软件 | jambonz docker-compose | 不自研 SIP stack |
| 4 | Cinnox 申请 | 仅 inbound | outbound 后续单独走 |
| 5 | 编码 | PCMA / PCMU / OPUS（不 G729） | DTLS-SRTP + TLS 5061 |
| 6 | DTMF | RFC2833 + SIP Info | 不用 in-band |
| 7 | jambonz → Mac 鉴权 | CF Access service token | 防止 /sip-audio 公开滥用 |
| 8 | 排期 | 5 周 | W1 VPS / W2 应用 / W3 自测 / W4 联调 / W5 上线 |

## 2. 总体里程碑

| Week | 主题 | 退出条件（可验证） |
|---|---|---|
| W1 | 火山云 VPS + jambonz 基础设施 | 软电话拨打 jambonz 公网 IP，audio_fork 把 PCM 推到 Mac echo WS |
| W2 | 应用层代码（见 06 文档） | `make run-gateway` 后软电话拨打能跑完一整轮对话 |
| W3 | 性能调优 + 自测稳定性 | 单机 5 路并发 30 分钟连续通话，P50 延时 < 2.0s |
| W4 | Cinnox 联调 | Cinnox 测试号能拨入并跑完对话 |
| W5 | 生产化 + demo | 监控 + runbook + demo 视频 + 客户接入文档 |

---

## 3. Week 1 — 火山云 VPS + jambonz 部署（5 天）

### 3.1 Day 1 — 开通火山云 HK 轻量服务器

**3.1.1 注册 / 登录**

- 网址：https://console.volcengine.com/
- 实名：身份证（个人）或营业执照（企业）
- 开通"轻量应用服务器"产品

**3.1.2 创建实例**

| 选项 | 值 |
|---|---|
| 地域 | 香港 |
| 镜像 | Ubuntu 22.04 LTS x64 |
| 套餐 | 2c2g 4M 带宽（约 ¥30/月） |
| 网络 | 默认 VPC，分配 1 个公网 IP |
| 登录 | SSH 公钥（推荐）或密码 |

**3.1.3 拿到的关键信息**

```
SIP_VPS_PUBLIC_IP=<填这里>
SSH:               ssh ubuntu@<SIP_VPS_PUBLIC_IP>
```

记录到本地 `~/.ssh/config`：

```
Host sip-vps
    HostName <SIP_VPS_PUBLIC_IP>
    User ubuntu
    IdentityFile ~/.ssh/id_ed25519
```

### 3.2 Day 2 — 防火墙 + 系统准备

**3.2.1 火山云控制台防火墙规则**

进入实例 → 安全组 / 防火墙，添加：

| 协议 | 端口 | 源 | 用途 |
|---|---|---|---|
| TCP | 22 | 你的办公 IP | SSH |
| UDP | 5060 | 0.0.0.0/0 | SIP（加白名单后可改为 Cinnox 8 IP） |
| TCP | 5060,5061 | 0.0.0.0/0 | SIP TLS |
| UDP | 10000-20000 | 0.0.0.0/0 | RTP |
| TCP | 3000 | 你的办公 IP | jambonz admin UI |

**3.2.2 系统层防火墙**

```bash
ssh sip-vps
sudo ufw allow 22/tcp
sudo ufw allow 5060/udp
sudo ufw allow 5060/tcp
sudo ufw allow 5061/tcp
sudo ufw allow 10000:20000/udp
sudo ufw allow 3000/tcp
sudo ufw enable
```

**3.2.3 验证 5060 UDP 真的通**

```bash
# VPS 上：
sudo nc -ul 5060

# 你 Mac 上：
echo "ping" | nc -u -w1 <SIP_VPS_PUBLIC_IP> 5060
```

VPS 上看到 "ping" → ✅ 通过。

**3.2.4 装 Docker**

```bash
ssh sip-vps
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
exit  # 重新 ssh 让 group 生效
ssh sip-vps
docker version  # 确认装上
```

### 3.3 Day 3 — 部署 jambonz docker-compose

**3.3.1 拉取 jambonz 官方部署仓库**

```bash
ssh sip-vps
mkdir -p ~/sip && cd ~/sip
git clone https://github.com/jambonz/jambonz-docker.git
cd jambonz-docker
```

**3.3.2 配置环境变量**

```bash
cp .env.example .env
nano .env
```

关键改动：
```
HOSTNAME=<SIP_VPS_PUBLIC_IP>          # 公网 IP（必须）
PUBLIC_IP=<SIP_VPS_PUBLIC_IP>         # 同上，rtpengine SDP 会用
JAMBONES_TIMEZONE=Asia/Hong_Kong
ADMIN_PASSWORD=<生成一个强密码>        # jambonz admin UI 登录
JWT_SECRET=<openssl rand -base64 32>
```

**3.3.3 启动**

```bash
docker compose up -d
docker compose ps   # 确认所有服务 healthy
docker compose logs -f drachtio | head -30   # 看 drachtio 启动日志
```

**3.3.4 验证 SIP 5060 监听**

```bash
sudo ss -tunlp | grep 5060
# 应看到 drachtio 进程监听 0.0.0.0:5060 (UDP/TCP)
```

### 3.4 Day 4 — jambonz application + carrier 配置

**3.4.1 登录 jambonz Admin UI**

- 浏览器打开 `http://<SIP_VPS_PUBLIC_IP>:3000`
- 登录 admin / `<ADMIN_PASSWORD>`
- 第一次会引导设置 system + account

**3.4.2 创建 Application**

Account → Applications → Add：

| 字段 | 值 |
|---|---|
| Application Name | `cinnox-voicebot` |
| Calling Webhook URL | `wss://autoservice.ezagent.chat/sip-audio` |
| Method | GET |
| Speech Synthesis Vendor | default |
| Speech Recognizer Vendor | default |

> 注意：jambonz 要求 webhook URL 必须可达。第一次建议先指向 echo WS（W1 D5 验证），W2 完成代码后改成 `/sip-audio`。

**3.4.3 创建 Carrier（Cinnox 8 IP 白名单）**

Account → Carriers → Add：

| 字段 | 值 |
|---|---|
| Name | `cinnox` |
| Vendor | Cinnox |
| Active | ✅ |

SIP Gateways（添加 8 行）：

| IPv4 | Port | Inbound | Outbound | Netmask |
|---|---|---|---|---|
| 101.200.218.11 | 5060 | ✅ | ❌ | 32 |
| 47.94.144.113 | 5060 | ✅ | ❌ | 32 |
| 18.163.244.252 | 5060 | ✅ | ❌ | 32 |
| 18.163.63.169 | 5060 | ✅ | ❌ | 32 |
| 3.115.111.125 | 5060 | ✅ | ❌ | 32 |
| 35.76.7.104 | 5060 | ✅ | ❌ | 32 |
| 3.1.89.69 | 5060 | ✅ | ❌ | 32 |
| 122.248.201.73 | 5060 | ✅ | ❌ | 32 |

**3.4.4 路由规则**

Account → Phone Numbers → Add：
- 暂时填一个占位号码（Cinnox 联调拿到测试号后回来更新）
- Application: `cinnox-voicebot`
- Carrier: `cinnox`

### 3.5 Day 5 — 软电话端到端验证（echo WS 模式）

**3.5.1 在 Mac 上跑临时 echo WS**

```bash
# /tmp/echo_ws.py
import asyncio, json
from websockets.server import serve

async def echo(ws):
    async for raw in ws:
        if isinstance(raw, bytes):
            await ws.send(raw)  # echo 音频
        else:
            print("text:", raw)

asyncio.run(serve(echo, "0.0.0.0", 9999).__aenter__())
```

通过 cloudflared 临时暴露 `wss://autoservice.ezagent.chat/sip-audio` 指向这个 echo（在 cloudflared config 里加一条 ingress）。

**3.5.2 软电话拨号**

```bash
# Linphone / MicroSIP / Zoiper：
# 配置一个 SIP account，用 jambonz 创建的本地用户：
#   server: <SIP_VPS_PUBLIC_IP>:5060
#   user / password: <按 jambonz UI 创建的>
# 拨打 <jambonz 配的占位号>
```

预期：你说的话从听筒里回放（echo）。验证整条链路：
PSTN → Cinnox（这一段还没接，跳过）→ jambonz → CF Tunnel → Mac echo

**3.5.3 W1 退出条件**

- [ ] VPS 5060/5061/RTP 端口对外可达
- [ ] jambonz 全部容器 healthy
- [ ] jambonz Admin UI 能登录
- [ ] application + carrier + phone number 配置完成
- [ ] 软电话拨号 → echo 听到自己声音

---

## 4. Week 2 — 应用层代码

详见 [06-code-changes-plan.md](06-code-changes-plan.md)。

W2 末退出：jambonz application 的 webhook URL 从 echo 改回 `wss://autoservice.ezagent.chat/sip-audio`，软电话拨号能听到 greeting 并完成一整轮对话。

### 4.1 CF Access service token 配置（W2 D5 必做）

**4.1.1 在 CF Dashboard 创建 service token**

1. https://one.dash.cloudflare.com → Access → Service Auth → Service Tokens
2. Create Token：
   - Name: `cinnox-voicebot-jambonz`
   - Duration: 1 year
3. 拿到两个值：
   ```
   CF_ACCESS_CLIENT_ID=xxx.access
   CF_ACCESS_CLIENT_SECRET=xxx
   ```
   **只显示一次，记下来**

**4.1.2 修改现有 CF Access Application**

进入 Access → Applications → 找到覆盖 `autoservice.ezagent.chat` 的 application：

- 加一条新 policy：
  - Action: Service Auth
  - Include: Service Token = `cinnox-voicebot-jambonz`
  - Path: `/sip-audio` only

或者更精细：拆出一个独立的 application：
- Domain: `autoservice.ezagent.chat`
- Path: `/sip-audio`
- Policy: Service Auth `cinnox-voicebot-jambonz` only

**4.1.3 配 jambonz application 的 webhook headers**

回到 jambonz Admin UI → Applications → cinnox-voicebot → Edit：
- Webhook Headers：
  ```
  CF-Access-Client-Id: xxx.access
  CF-Access-Client-Secret: xxx
  ```

**4.1.4 验证**

```bash
# 不带 token 直接连 → 应该被 CF Access 401 拦
curl -i https://autoservice.ezagent.chat/sip-audio

# 带 token 连 → 应该 101 Switching Protocols
curl -i \
  -H "CF-Access-Client-Id: xxx.access" \
  -H "CF-Access-Client-Secret: xxx" \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  -H "Sec-WebSocket-Version: 13" \
  https://autoservice.ezagent.chat/sip-audio
```

---

## 5. Week 3 — 性能调优 + 自测稳定性

| Day | 任务 | 验证 |
|---|---|---|
| 1 | ASR `end_smooth_window_ms` 1500 → 800 | turn 切换更快 |
| 2 | Prometheus metrics 接入（按 §7） | grafana 看到 5 个核心指标 |
| 3 | barge-in 端到端验证 | 用户开口 < 200ms 停 TTS |
| 4 | 30 分钟连续单路通话 | 无内存/socket 泄漏 |
| 5 | 5 路并发（sipp 脚本） | 全部跑完，P50 < 2.0s |

### 5.1 5 路并发压测脚本

`sip_vps:~/sip/sipp/uac.xml`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<scenario name="basic UAC">
  <send retrans="500">
    <![CDATA[
      INVITE sip:[service]@[remote_ip]:[remote_port] SIP/2.0
      Via: SIP/2.0/UDP [local_ip]:[local_port];branch=[branch]
      ...
    ]]>
  </send>
  <recv response="100" optional="true"/>
  <recv response="180" optional="true"/>
  <recv response="200" rtd="true"/>
  <send><![CDATA[ ACK sip:[service]@[remote_ip] SIP/2.0 ... ]]></send>
  <pause milliseconds="30000"/>  <!-- 30s 通话 -->
  <send retrans="500"><![CDATA[ BYE sip:[service]@[remote_ip] SIP/2.0 ... ]]></send>
  <recv response="200" crlf="true"/>
</scenario>
```

```bash
sipp -sf uac.xml -m 5 -r 1 <SIP_VPS_PUBLIC_IP>:5060 -t un
```

---

## 6. Week 4 — Cinnox 联调

### 6.1 Day 1 — 提交 SIP_Interconnection_Form

**回邮件给 Cinnox BD，附完整表单**：

| 字段 | 值 |
|---|---|
| Contact Email | `<工程对接邮箱>` |
| Service domain | 留默认 `Internal.cinnox.com` |
| Service ID | 留空（Cinnox 给） |
| Requested Service | ☑ **SIP In only** |
| Remark | "AI voicebot powered by AutoService voice gateway. Self-hosted jambonz on Volcengine HK Lite VPS, audio bridged to AutoService backend via Cloudflare Tunnel." |
| **Signaling IP Address** | **`<SIP_VPS_PUBLIC_IP>`** |
| Media IP Address | **`<SIP_VPS_PUBLIC_IP>`**（同上） |
| Inbound Signaling Port | 5061 (TLS) + 5060 (UDP) |
| Support OPTIONS Ping | ☑ YES |
| Codec Type | ☑ PCMU ☑ PCMA ☑ OPUS ☐ G729 |
| Encryption (DTLS) | ☑ YES |
| DTMF Type | ☑ RFC2833 ☑ SIP Info |
| Toll-Free Number | "Please assign one HK test number" |
| Genesys Domain | 留空 |

### 6.2 Day 2 — Cinnox 配 trunk + 测试号下发

Cinnox 工程师会：
1. 在他们 SBC 上加 trunk 指向你的 IP
2. 分配一个 HK 测试号给你（如 `+852-XXXXXXXX`）
3. 通知你已配完

你这边：
1. 更新 jambonz 的 phone number 为 Cinnox 给的真实号码
2. 验证 OPTIONS ping 双向通：
   ```bash
   # VPS 上看 drachtio 日志：
   docker compose logs -f drachtio | grep OPTIONS
   ```

### 6.3 Day 3 — 实拨测试

```
1. 用普通手机拨打 +852-XXXXXXXX
2. 应该听到 greeting "您好，欢迎致电 OpenClaw 客服..."
3. 说话："iPhone 15 多少钱？"
4. 听到 cc_pool 答复
```

抓包验证 codec 协商：
```bash
sudo tcpdump -i any -w /tmp/sip.pcap port 5060 or portrange 10000-20000
# 用 wireshark 打开，看 SDP 协商出 PCMA
```

### 6.4 Day 4-5 — 多区域 + 长通话稳定性

- 让人在北京 / JP / SG 各拨打一次（Cinnox 路由会从最近 SBC 出）
- 30 分钟连续通话 × 3 次

### 6.5 W4 退出条件

- [ ] Cinnox 测试号能正常拨入
- [ ] 通话 P50 延时 < 2.5s（含 SBC 路径）
- [ ] 至少 1 个北京/JP/SG 客户端实测通过
- [ ] 30 分钟连续通话无掉线 × 3 次

---

## 7. Week 5 — 生产化

### 7.1 任务清单

| Day | 任务 | 输出 |
|---|---|---|
| 1 | docker-compose restart policy + systemd（VPS） + launchd（Mac）自启 | 服务器/Mac reboot 后自动恢复 |
| 2 | Prometheus + grafana 看板 | 5 个核心指标可见 |
| 3 | 故障演练：杀 jambonz / 杀 backend / 网络抖动 | 5 分钟内恢复 |
| 4 | 写 runbook + 客户接入文档 | docs/runbooks/sip-voice.md, docs/integrations/cinnox-voice-sip.md |
| 5 | 录 demo 视频 + PR 合并 dev | mp4 给 BD |

### 7.2 监控指标

| metric | 类型 | 告警阈值 |
|---|---|---|
| `sip_active_calls` | gauge | — |
| `sip_call_duration_seconds` | histogram | — |
| `sip_e2e_response_ms` | histogram p50 | > 2.5s |
| `sip_doubao_reconnects_total` | counter rate 5m | > 1/min |
| `sip_call_failures_total` | counter rate 5m | > 5%（按 active_calls 比例） |

### 7.3 jambonz 系统监控

```bash
# 内置 Prometheus exporter
curl http://<SIP_VPS_PUBLIC_IP>:9090/metrics
```

接到你现有的 grafana（如果有），或在 VPS 上跑 `prom/prometheus` + `grafana/grafana` 容器。

---

## 8. 验收 Checklist（W5 末打勾）

### 功能
- [ ] Cinnox 测试号能拨入
- [ ] 听到 greeting
- [ ] ASR 准确率 > 90%
- [ ] cc_pool 回复能正常播放
- [ ] barge-in 工作（用户开口 < 200ms 停 TTS）
- [ ] 主动挂断 / 对方挂断都能正常清理资源

### 性能
- [ ] P50 e2e 延时 < 2.5s
- [ ] P95 e2e 延时 < 4.0s
- [ ] 5 路并发 30 分钟无故障
- [ ] 长通话 30 分钟无掉线
- [ ] 内存增长 < 50MB / 30min
- [ ] 无 socket 泄漏

### 工程
- [ ] 单元测试 + 集成测试 ≥ 90% 通过
- [ ] grafana 看板 5 个核心指标可见
- [ ] runbook 写完
- [ ] 客户接入文档写完
- [ ] VPS docker-compose restart=always
- [ ] Mac launchd 重启策略验证
- [ ] 故障演练 3 个场景全部 5 分钟内恢复

### 交付
- [ ] demo 视频 mp4 给 BD
- [ ] PoC 总结文档
- [ ] 已知问题 / follow-up 列表

---

## 9. 回滚方案

| 失败场景 | 回滚 |
|---|---|
| W1 jambonz 部署不通 | 检查 5060/RTP 端口；最差换其它 docker-compose 版本 |
| W2 应用层 bug 多 | 回滚 PR4/PR5，把 jambonz application URL 暂改回 echo |
| W3 P50 > 3s | 接受降级；改 SLA 为 P50 < 3.5s |
| W4 Cinnox trunk 配不通 | 备用：用 SIP 软电话直接 IP 联调 |
| 生产 VPS 宕机 | docker compose restart=always 自动拉起；最差迁机 |
| Mac 关电脑 → 通话全断 | 接受 PoC 阶段；生产前迁回 Linux 服务器 |

---

## 10. Cinnox 表单（最终版本，等 VPS IP 出来填）

```
Contact Email        : <你的工程邮箱>
Customer Information : OpenClaw / AutoService team
Service domain       : Internal.cinnox.com (default)
Service ID           : (Cinnox 给)
Remark               : AI voicebot powered by AutoService voice gateway
                       (Volcengine Doubao realtime dialogue API).
                       Self-hosted jambonz on Volcengine HK Lite VPS.
                       Audio bridged to AutoService backend via Cloudflare Tunnel.
Requested Service    : ☑ SIP In  ☐ SIP Out
Signaling IP Address : <SIP_VPS_PUBLIC_IP>
Media IP Address     : <SIP_VPS_PUBLIC_IP>
Inbound Port         : 5061 (TLS), 5060 (UDP)
OPTIONS Ping         : ☑ YES
Codec                : ☑ PCMU ☑ PCMA ☐ G729 ☑ OPUS
Encryption (DTLS)    : ☑ YES
DTMF                 : ☐ In-band ☑ RFC2833 ☑ SIP Info
Toll-Free Number     : (Please assign one HK test number)
Destination Number   : (same as toll-free for now)
Genesys Domain       : (n/a)

Whitelist Cinnox 8 IPs (added on our side):
- 101.200.218.11:5060 (Beijing)
- 47.94.144.113:5060  (Beijing)
- 18.163.244.252:5060 (Hong Kong)
- 18.163.63.169:5060  (Hong Kong)
- 3.115.111.125:5060  (Japan)
- 35.76.7.104:5060    (Japan)
- 3.1.89.69:5060      (Singapore)
- 122.248.201.73:5060 (Singapore)
```

---

## 11. 现在你要做的第一件事

```
1. 打开 https://console.volcengine.com/
2. 创建轻量服务器（HK / Ubuntu 22.04 / 2c2g）
3. 拿到固定公网 IP，告诉我
4. 我把 W1 D2 之后的部署脚本一次跑通给你
```

代码层（06 文档）可以**和 VPS 部署并行**——你不在 VPS 旁边时，可以
在 Mac 上写代码、跑单元测试。
