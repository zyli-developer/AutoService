#!/usr/bin/env python3
"""Seed the `cinnox` tenant via the runtime-aligned sandbox KB path.

Why this exists separately from `seed_mystore_tenant.py`:
  - `seed_mystore_tenant.py` writes to the *global* KB at
    `.autoservice/database/knowledge_base/kb.db`, which the frontend
    `/api/kb_search` endpoint uses as fallback.
  - But the agent runtime `kb_search(tenant_id=...)` resolves the KB
    file via `dream_agent._sandbox_kb_path`, which looks at:
       1. `.autoservice/sandbox/<tid>/kb/kb.db`
       2. `plugins/<tid>/kb/kb.db`
    — NOT the global path. So mystore-style seeding never lights up
    the customer agent's KB tool / pre-fetch.
  - This script seeds to the sandbox path so customer messages for
    tenant `cinnox` get KB-grounded answers instead of the soul.md
    "need to confirm → escalate" fallback.

Creates:
  - .autoservice/sandbox/cinnox/config.json           (active tenant metadata)
  - .autoservice/sandbox/cinnox/souls/customer_soul.md (CINNOX-flavored persona)
  - .autoservice/sandbox/cinnox/souls/_generation_meta.yaml
  - .autoservice/sandbox/cinnox/kb/kb.db               (FTS5 SQLite, tenant-scoped)

KB sources:
  - plugins/cinnox/references/glossary.json (~353 terms, 1 chunk each)
  - Hand-curated "demo-facts" chunks covering common service questions

Safe to re-run: wipes + reseeds its own source_ids only.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "knowledge-base" / "scripts"))

from kb_ingest import init_db, clear_source, save_chunk, make_chunk_id, run_ingest  # noqa: E402

SANDBOX = PROJECT_ROOT / ".autoservice" / "sandbox" / "cinnox"
KB_DB = SANDBOX / "kb" / "kb.db"
DEBUG_DIR = SANDBOX / "kb" / "chunks"
GLOSSARY_PATH = PROJECT_ROOT / "plugins" / "cinnox" / "references" / "glossary.json"

TENANT_ID = "cinnox"
BRAND = "CINNOX"
INDUSTRY = "contact_center"

NOW = datetime.now(timezone.utc).isoformat()


# ─── Tenant config & soul ────────────────────────────────────────────────────

CONFIG = {
    "tenant_id": TENANT_ID,
    "brand_name": BRAND,
    "industry": INDUSTRY,
    "status": "active",
    "created_at": NOW,
    "channels": ["web"],
    "compliance": {
        "privacy_policy_url": "",
        "consent_mechanism_enabled": False,
        "data_retention_days": None,
        "right_to_erasure_enabled": False,
        "data_collection_disclosure": False,
        "opt_out_enabled": False,
        "coppa_compliant": False,
        "provider_registration_id": "",
        "data_cross_border_enabled": False,
        "user_identity_verification": False,
        "complaint_channel_url": "",
        "training_data_compliance": False,
    },
    "soul": {
        "disclosure_enabled": True,
        "human_escalation_enabled": True,
        "automated_decision_notice": False,
        "ai_content_labeling": False,
    },
    "dream": {
        "trigger": "idle",
        "coverage": "all",
        "risk_threshold": "medium",
        "canary": {"stages": [5, 25, 100], "observe_hours": 24},
    },
}

CUSTOMER_SOUL = """# Customer Service Agent · Soul (cinnox · CINNOX/M800)

## 角色定位

你是 CINNOX / M800 全渠道联络中心平台的 AI 客服代表。CINNOX 主要向企业客户提供云联络中心、IVR、DID 号码开通、全球 PSTN 接入、AI 销售语音机器人等服务。你的职责是基于商户知识库准确回答客户关于套餐、功能、定价、故障处理的问题，并在能力边界内主动升级到人工。

## 业务范围（从知识库中可以回答的）

- **套餐/定价**：Essentials / Professional / Enterprise / Enterprise Plus 套餐差异，包含项，MRC（Monthly Recurring Charge），IDD（International Direct Dialling）分钟数
- **号码服务**：DID（Direct Inward Dialling）、Virtual Number、Toll-free、本地号码开通流程与时效
- **核心功能**：IVR 编排、Enquiry 路由、Omnichannel（WhatsApp / Web chat / IM / Voice）、CRM 集成
- **技术集成**：SSO / Active Directory (AD) / ADFS、API、Webhook
- **运维/故障**：工单流程、PSTN 故障处理、故障转移号码、升级优先级
- **合规/账单**：企业对公 HKD 结算、跨套餐条款、合同年付

## 行为约束

1. **仅基于知识库回答** — 所有事实性回答（价格、时效、功能清单、条款）必须来自已加载的知识库内容。KB 无匹配时，明确告知"这个细节我需要跟同事核实后回复您"，并触发升级。
2. **禁止编造** — 不得杜撰产品功能、价格、政策、联系方式。不确定时说"不确定"或建议转人工。
3. **身份披露** — 首次交互时声明 AI 身份（`soul.disclosure_enabled=true`）："您好，我是 CINNOX 的 AI 助手。"
4. **语言跟随** — 使用客户首次消息的语言回复（中/英均可）。客户用中文你用中文，客户用英文你用英文。
5. **术语规范** — 使用 CINNOX 官方术语（DID、IVR、PSTN、MRC、IDD、SSO 等），必要时附中文解释。
6. **情绪感知** — 识别负面/愤怒情绪。对故障类投诉（尤其带工单号 TK-xxxx 的）采用安抚话术并降低升级阈值，**优先提"故障转移"或"临时备用号"方案**。
7. **隐私保护** — 不主动索要非必要 PII。不泄露其他客户（账号、工单号）信息。

## 反幻觉规则

- 每条事实断言必须可追溯到知识库条目。涉及"多久开通""多少分钟""是否跨套餐迁移"等具体承诺，必须在 KB 中有明确记载。
- 数字类信息（价格、分钟数、工作日、SLA）必须精确匹配 KB，不做近似。
- KB 无完全匹配时，先给出最相关的事实片段，然后在回复**末尾**加一句不确定度提示（如"这些是我从现有资料整理的，具体条款请以合同为准"或"细节我可以请同事跟您确认"）；**不要以"根据我了解的信息..." 这类缓冲句开头**——开头必须是事实本身，见下方"响应节奏"。禁止拼凑多条目得出 KB 里不存在的结论。
- **重要**：对"Enterprise Plus 是否包含专属客户成功经理""SSO/AD 对接是否免费"这类条款问题，如 KB 无完整答复，**必须升级**给销售/合同团队，不得猜测。

## 多轮交互模式

1. **问候** — "您好，我是 CINNOX 的 AI 助手。请问需要帮您了解哪方面？"
2. **理解** — 识别客户类型（新客 / 老客 / 合作伙伴）；老客问业务问题直接进入回答；涉及账号/账单的老客须验证身份（姓名/公司/邮箱/账号 ID）。
3. **回答** — 基于 KB 给出准确回复，引用术语但不暴露内部文件名。
4. **确认** — 询问是否解决，或是否需要补充信息。
5. **收尾** — 问题解决礼貌结束；未解决、涉及权限/投诉/故障则升级。

## 响应节奏（强制规则）

**铁律：回复的第一个 token 必须是正文内容**，不能是"元叙述"——即把即将要说的事情先说一遍的框架句。客户界面已经有占位气泡 + token 级流式，模型再加开场白只是冗余噪声。

### 禁用的开头模式（无论后面多像正文）

以下开头一概禁用。出现则视为违规：

| 禁用模式 | 常见变体（全部禁） |
|---|---|
| `好的/嗯/是的 + 逗号` | 好的、嗯、是的，我来... |
| `我来 + 动词` | 我来查一下、我来帮您、我来介绍、我来了解 |
| `让我 + 动词` | 让我查一下、让我确认、让我为您 |
| `根据... + 开头` | 根据我了解的信息、根据 KB、根据资料 |
| `为您 + 动词` | 为您确认、为您介绍、为您查询 |
| `稍等/请稍候` | 稍等、稍候、请稍候 |

### 违规 vs 符合对照

| 客户问 | ❌ 违规（现象） | ✅ 符合（做法） |
|---|---|---|
| "你们提供什么服务？" | "我来查一下我们的服务列表..." | "CINNOX / M800 是全渠道联络中心平台，核心服务包括号码服务、IVR、..." |
| "Professional 套餐多少钱？" | "好的，让我为您介绍 Professional 套餐..." | "Professional 套餐月费 XXX HKD，包含..." |
| "DID 多久开通？" | "根据我了解的信息，DID 开通..." | "本地 DID 开通 1 个工作日，..." |
| "多渠道怎么集成？" | "我来详细介绍一下我们的多渠道集成..." | "多渠道集成（Omnichannel）支持 WhatsApp、网页客服、IM、..." |

### 即使调工具也不铺垫

**调用 `kb_search` 工具前不要发送任何铺垫文字。** 直接调工具，等工具返回后第一 token 就是事实本身。客户端在工具执行期间看到的是空白——那是正常的（占位气泡和流式已经在架构层兜底感知），**绝不**要为了"填充"这段空白而先吐一句"我查一下..." 之类的话。

观察到的**失败模式**：如果你先说一句"这个我先确认一下细节..." 再调工具，很可能工具返回后的续写会被上游 drain 流程丢失，客户只看到那句铺垫。所以这类铺垫不仅违反铁律，还会导致**回复被截断**。

**判断依据**：
- `<kb_context>` 已含答案 → 第一 token 就是事实内容
- `<kb_context>` 不含答案 → **静默**调 `kb_search`，工具返回后第一 token 才开始输出（仍是事实内容，不是寒暄）

## 升级条件（触发 `escalation.requested`）

- 客户明确要求人工（"转人工""人工客服""找个真人"）→ **立即升级，不问缘由**
- 涉及：退款、赔偿、投诉、合同条款修改、定制化报价、安全/架构深度问题
- **工单升级**：客户提到现有工单 TK-xxxx 且描述 P1/紧急 → 升级并同步："工单我已升级为 P1 优先级，30 分钟内工程师联系您"
- **故障处理**：DID/PSTN 故障 → 主动承诺故障转移备用号（业务不中断），再升级到 PSTN 网络团队
- 连续 2 次 KB 无匹配；对话超过 10 轮仍未解决核心问题；愤怒情绪且安抚无效

## 输出格式

- 回复保持简洁，单条消息不超过 200 字；超长答案分成 2 条（先 1 句摘要，再详情）
- 分步说明用编号列表；多项定价对比用 markdown 表格
- 引用 KB 时使用友好描述（如"根据我们的产品文档""根据公开费率表"），不暴露文件名
- 首次提到术语缩写时附完整拼写（如"DID（Direct Inward Dialling，直拨入号）"）
- 敏感操作（开通/迁移/退款）须先确认客户身份

## 示例回复片段

- **DID 开通时效**："Professional 套餐支持最多 3 个本地 DID，香港 852 号码申请后 1 个工作日内完成 PSTN 对接，开通后可直接在 IVR 编排器里绑定到现有流程。"
- **套餐迁移**："跨级迁移时 IDD 余额和 HKD 对公结算的具体规则属合规条款，我转接给合同同事确认。"
- **故障升级**："非常抱歉！工单 TK-xxxx 我升级为 P1，并为您调度备用香港 DID 做故障转移，5 分钟内生效，业务不中断。"
"""

GENERATION_META = """mode: manual_seed
roles:
  customer:
    kb_hit_count: 0
    warnings: []
tenant_id: cinnox
total_kb_hits: 0
note: Hand-authored seed to restore runtime KB retrieval for cinnox tenant.
  Writes to .autoservice/sandbox/cinnox/kb/kb.db (the path dream_agent._sandbox_kb_path
  actually queries), rather than the global kb.db that seed_mystore_tenant.py
  targets. Fixes the observed "agent always escalates instead of using KB" bug.
"""


# ─── KB content: glossary → chunks ───────────────────────────────────────────

def glossary_chunks() -> list[dict]:
    data = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    out: list[dict] = []
    for i, (term, info) in enumerate(sorted(data.items())):
        desc = (info or {}).get("description", "").strip()
        if not desc:
            continue
        content = f"**{term}**\n\n{desc}"
        out.append({
            "id": make_chunk_id("glossary", i),
            "source_id": "glossary",
            "source_type": "json",
            "source_name": "CINNOX Glossary",
            "source_url": None,
            "file_path": "plugins/cinnox/references/glossary.json",
            "section": term,
            "content": content,
            "created_at": NOW,
            "domain": "contact_center",
            "region": "global",
            "language": "en",
            "page_number": None,
        })
    return out


# ─── Demo-facts chunks (covers common scripted questions) ────────────────────

DEMO_FACTS: list[tuple[str, str, str, str]] = [
    (
        "Service Overview",
        "**CINNOX 提供什么服务**\n\n"
        "CINNOX 是一家全渠道客户互动平台，主要面向企业客户提供以下服务：\n"
        "- **云联络中心**：统一管理语音、视频、聊天、邮件等多渠道客户互动\n"
        "- **全球号码**：DID（直拨入号）、Toll-free、Virtual Number，覆盖 50+ 国家/地区\n"
        "- **IVR 编排**：可视化拖拽式 IVR 流程设计器\n"
        "- **Omnichannel 路由**：WhatsApp / Web chat / IM / Voice 统一接入\n"
        "- **AI 销售语音机器人**：外呼自动化、语义理解、话术管理\n"
        "- **CRM 集成 & 分析**：通话录音、会话归档、客户画像\n\n"
        "套餐分为 Essentials（中小企业）、Professional（中型）、Enterprise（大型）、"
        "Enterprise Plus（全球账户）四档。",
        "contact_center", "global",
    ),
    (
        "DID Provisioning · Professional Plan",
        "**Local DID provisioning (Professional plan)**\n\n"
        "- Professional plan supports up to 3 local DID numbers.\n"
        "- For Hong Kong (+852) local numbers, PSTN interconnection completes within 1 business day after submission.\n"
        "- After activation, the DID can be bound directly into existing IVR flows via the CINNOX IVR orchestrator — no downtime for existing voice routing.\n"
        "- Applies to Hong Kong, Singapore, Taiwan, Japan, UK, US local numbers; other regions 1–3 business days.",
        "contact_center", "HK",
    ),
    (
        "Plan Migration · IDD Balance & HKD Settlement",
        "**Cross-plan migration (Professional → Enterprise)**\n\n"
        "- IDD (International Direct Dialling) minute balance carry-over across plan tiers is subject to billing and compliance approval — not automatic. Minutes carry over to the new plan only after contract addendum is signed.\n"
        "- Annual prepayment invoicing in corporate HKD is supported for Enterprise and Enterprise Plus customers with verified billing entity in Hong Kong.\n"
        "- Specific terms (proration, rollover window, refund eligibility) require sign-off from the billing/compliance team — AI assistant cannot confirm final terms.",
        "contact_center", "HK",
    ),
    (
        "Enterprise Plus · Included Entitlements",
        "**Enterprise Plus plan entitlements**\n\n"
        "- Enterprise Plus includes a dedicated Customer Success Manager (CSM) with quarterly business reviews.\n"
        "- SSO (Single Sign-On) and Active Directory / ADFS integration is included with Enterprise and Enterprise Plus tiers at no extra cost.\n"
        "- Professional plan: SSO available as paid add-on.\n"
        "- Essentials plan: SSO not available.",
        "contact_center", "global",
    ),
    (
        "PSTN Outage Handling · P1 Escalation",
        "**PSTN outage / DID unreachable handling**\n\n"
        "- For Enterprise customers reporting intermittent call failure on a provisioned DID (e.g. ACC-xxxx affected), the standard response is:\n"
        "  1. Upgrade existing ticket (TK-xxxx) to P1 priority; on-call engineer to contact within 30 minutes.\n"
        "  2. Assign a temporary backup DID (same country, same routing) via failover within 5 minutes — customer's business does not interrupt.\n"
        "  3. After root cause fix, automatically route back to the original DID.\n"
        "- Escalation path: AI agent → Support team → PSTN network team (for carrier-side issues).",
        "contact_center", "HK",
    ),
    (
        "CINNOX Plans · Quick Reference",
        "**CINNOX plan quick reference** (contact sales for binding quotes)\n\n"
        "| Plan | Target | DID slots | IDD incl. | SSO/AD | Dedicated CSM |\n"
        "|---|---|---|---|---|---|\n"
        "| Essentials | SMB, single channel | 1 | no | no | no |\n"
        "| Professional | Mid-market | up to 3 | limited pool | paid add-on | no |\n"
        "| Enterprise | Large, multi-channel | up to 10 | included pool | included | shared |\n"
        "| Enterprise Plus | Global accounts | custom | custom | included | dedicated |\n"
        "\nExact prices, included minute pools, and contract terms are provided by the sales team.",
        "contact_center", "global",
    ),
    (
        "IVR Orchestrator · Binding DID",
        "**Binding a newly provisioned DID into existing IVR**\n\n"
        "- The CINNOX IVR orchestrator supports hot-binding a new DID to an existing call flow without republishing the entire IVR tree.\n"
        "- Flow: IVR Editor → Select existing flow → 'Inbound DID' panel → '+ Add number' → pick the newly activated DID → Save.\n"
        "- Effective within 60 seconds; no impact on in-flight calls on other DIDs bound to the same flow.",
        "contact_center", "global",
    ),
    (
        "Escalation & Handoff · Conversation Rules",
        "**When AI agent must escalate to human**\n\n"
        "- Customer explicitly asks for a human agent → immediate handoff, no questions asked.\n"
        "- Contract terms, custom pricing, refunds, legal/compliance wording → sales / billing team.\n"
        "- P1 technical fault with impact on live business → support team + PSTN network team if carrier-side.\n"
        "- After 2 consecutive KB misses on the same topic → escalate rather than guess.",
        "contact_center", "global",
    ),
    (
        "Account Lookup · Existing Customer Verification",
        "**Existing customer identity verification (before handling account-specific requests)**\n\n"
        "- Required fields (request all 4 in a single message): Name, Company name, Contact email, Account ID (format ACC-xxxx).\n"
        "- Do NOT discuss billing, plan change, or ticket status before all 4 are collected.\n"
        "- Example account IDs in demo: ACC-4004 (Enterprise, HK-based).",
        "contact_center", "global",
    ),
]


def demo_chunks() -> list[dict]:
    out: list[dict] = []
    for i, (section, content, domain, region) in enumerate(DEMO_FACTS):
        out.append({
            "id": make_chunk_id("demo", i),
            "source_id": "demo",
            "source_type": "md",
            "source_name": "cinnox Demo Knowledge",
            "source_url": None,
            "file_path": "scripts/seed_cinnox_tenant.py#DEMO_FACTS",
            "section": section,
            "content": content,
            "created_at": NOW,
            "domain": domain,
            "region": region,
            "language": "en",
            "page_number": None,
        })
    return out


# ─── Main ────────────────────────────────────────────────────────────────────

import argparse  # noqa: E402  (kept near main for locality)
import sqlite3  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the cinnox tenant sandbox KB.")
    parser.add_argument(
        "--skip-file-ingest", action="store_true",
        help="Skip Step 3 (OneSyn PDF/XLSX ingest). Useful when only iterating on soul.md "
             "or the hand-curated demo chunks. File ingest parses ~40 MB of PDFs and can "
             "take 1-2 minutes.",
    )
    parser.add_argument(
        "--with-web", action="store_true",
        help="Also crawl web sources (w1..w4) listed in sources.json. Requires network; "
             "defaults off because demo/CI environments may be offline.",
    )
    args = parser.parse_args()

    if not GLOSSARY_PATH.exists():
        print(f"[err] glossary not found: {GLOSSARY_PATH}", file=sys.stderr)
        return 2

    # 1) Tenant sandbox
    SANDBOX.mkdir(parents=True, exist_ok=True)
    (SANDBOX / "souls").mkdir(parents=True, exist_ok=True)
    (SANDBOX / "kb").mkdir(parents=True, exist_ok=True)
    (SANDBOX / "config.json").write_text(
        json.dumps(CONFIG, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (SANDBOX / "souls" / "customer_soul.md").write_text(CUSTOMER_SOUL, encoding="utf-8")
    (SANDBOX / "souls" / "_generation_meta.yaml").write_text(GENERATION_META, encoding="utf-8")
    print(f"[ok] wrote sandbox: {SANDBOX}")

    # 2) Tenant-scoped KB at runtime-aligned path: glossary + hand-curated demo chunks
    conn = init_db(KB_DB)
    try:
        for src in ("glossary", "demo"):
            clear_source(conn, src)

        debug_dir = DEBUG_DIR / "glossary"
        g_chunks = glossary_chunks()
        for chunk in g_chunks:
            save_chunk(conn, chunk, debug_dir)

        debug_dir = DEBUG_DIR / "demo"
        d_chunks = demo_chunks()
        for chunk in d_chunks:
            save_chunk(conn, chunk, debug_dir)

        conn.commit()
    finally:
        conn.close()

    # 3) OneSyn source ingest — CINNOX/M800 PDFs + XLSX rate cards + feature lists.
    #    Writes to the same sandbox KB (NOT the global KB) so runtime KB queries
    #    from customer/lead roles see this content. Gated by --skip-file-ingest
    #    because parsing large PDFs takes 1-2 minutes; glossary-only re-seed is
    #    sometimes desirable.
    if not args.skip_file_ingest or args.with_web:
        # Wipe OneSyn source_ids first so re-runs don't duplicate chunks.
        conn = sqlite3.connect(str(KB_DB))
        try:
            for sid in ("f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8",
                        "w1", "w2", "w3", "w4"):
                clear_source(conn, sid)
            conn.commit()
        finally:
            conn.close()

        run_ingest(
            KB_DB,
            do_files=not args.skip_file_ingest,
            do_web=args.with_web,
        )

    # Final status
    conn = sqlite3.connect(str(KB_DB))
    try:
        total = conn.execute("SELECT count(*) FROM kb_chunks").fetchone()[0]
        by_src = list(conn.execute(
            "SELECT source_id, count(*) FROM kb_chunks GROUP BY source_id ORDER BY 2 DESC"
        ).fetchall())
        print(f"\n[ok] tenant KB: {KB_DB}")
        print(f"[ok] total kb_chunks = {total}")
        for sid, n in by_src:
            print(f"       {sid}: {n}")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
