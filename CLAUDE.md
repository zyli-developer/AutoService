# AutoService — Three-Layer Fork-Based AI Application Framework

## Overview

AutoService is a three-layer fork-based framework for building AI-powered social-channel applications (customer service, sales, education, etc.). The architecture uses full-chain fork strategy (L1 → L2 → L3).

**Three layers:**
- **L1 `socialware/`** — Base framework: plugin loading, config mechanism, session framework, async pool, generic utilities
- **L2 `autoservice/`** — Application layer: customer service business logic, CRM, domain-specific configs
- **L2 `channels/`** — Channel adapters: Feishu IM, Web chat (currently L2, contains business-specific logic; generic parts may be extracted to L1 when a second application emerges)
- **L3 `plugins/<tenant>/`** — Tenant instance: customer-specific plugins and data

**Two channels:**
- **Web chat** — FastAPI app at `channels/web/app:app`. **Canonical
  customer message path** for M2/M3+ (triage, multi-role, tenant sandbox,
  KB pre-fetch all live here).
- **Feishu IM** — MCP-based, runs as `channels/feishu/channel.py`. M1
  legacy entry; **not kept in sync** with M2/M3 features. See "Channel
  feature parity" below before touching it.

## Glossary

- **Admin** — 整个 Socialware 服务的管理者（目前就是我们自己）。
- **Tenant** — 租户，开启/安装一个 Socialware 的商户（例如一个电商平台、CX）。租户不可以嵌套：租户的客户（例如 CX 服务的客户）在我们系统看起来是和上游租户平行的租户，即没有 `CX/Hotel` 的嵌套路径，只有 `CX/` 和 `Hotel/` 两个平行路径。
- **Operator** — 会和一个或多个 Agent 进行 copilot 的人类操作员。
- **EndUser** — 终端用户，例如访问电商平台的客户、酒店入住客户，是 Socialware 最终服务的用户。
- **Mode**
  - **Takeover** — Operator 完全替代 Agent 进行服务。
  - **Copilot** — Operator 给 Agent 建议，Agent 进行服务，Operator 的信息对 EndUser 不可见；Copilot 也可以调整为 Agent 给 Operator 建议的模式，此时 Agent 信息对 EndUser 不可见。
  - **Auto** — Agent 全自动服务 EndUser，Operator 只可以观察，不可以介入。

## Commands

- `make setup` — Create symlinks (.claude/ dirs, plugin skills), init runtime dirs
- `make run-channel` — Start Feishu IM channel (MCP server)
- `make run-web` — Start web chat (FastAPI, default port 8000)
- `make check` — Verify plugin discovery

## Directory Structure

```
socialware/          # L1: Base framework (CODEOWNERS protected)
  pool.py            #   Generic async object pool (AsyncPool[T], PoolableClient)
  claude.py          #   Claude Agent SDK wrapper (generic, no app-specific paths)
channels/            # L2: Channel adapters (see note below)
  feishu/            #   Feishu IM channel (MCP server)
  web/               #   Web chat channel (FastAPI)
autoservice/         # L2: Customer service application layer
  cc_pool.py         #   Claude Code instance pool (extends socialware.pool.AsyncPool)
  domain_config.py   #   Business config data (LANG_CONFIGS)
  domain_session.py  #   Session prefixes (DOMAIN_PREFIXES)
  domain_permission.py # Permission defaults
  customer_manager.py  # Customer management
  crm.py             #   CRM (contacts, conversations)
  rules.py           #   Behavior rules
skills/              # L2: Claude Code skills (symlinked into .claude/skills)
plugins/             # L3: Customer-specific plugins (declarative)
commands/            # Claude Code commands (symlinked into .claude/commands)
agents/              # Claude Code agents (symlinked into .claude/agents)
hooks/               # Claude Code hooks (symlinked into .claude/hooks)
templates/           # L2 fork scaffolding
.autoservice/        # Runtime data — logs, cache, db (gitignored)
docs/                # Design docs and plans
```

## Import Convention

```python
# L1 framework imports (preferred for new code)
from socialware import generate_id, load_config, MockDB
from socialware.plugin_loader import discover

# L2 business imports
from autoservice.domain_config import LANG_CONFIGS
from autoservice.domain_session import DOMAIN_PREFIXES
from autoservice.customer_manager import CustomerManager

# Backward-compatible (still works via shims in autoservice/)
from autoservice import generate_id, load_config  # re-exported from socialware
```

## Layer Ownership

| Directory | Layer | Owner | L3 may modify? |
|-----------|-------|-------|----------------|
| `socialware/` | L1 | Framework team | No (CODEOWNERS) |
| `channels/` | L2 | App team | No (PR to upstream) |
| `autoservice/` | L2 | App team | No (PR to upstream) |
| `plugins/_example/` | L2 | App team | No |
| `plugins/<tenant>/` | L3 | Tenant | Yes |
| `skills/<tenant>/` | L3 | Tenant | Yes |

> **Note on `channels/`:** Currently L2 because Feishu channel contains business-specific logic
> (CRM integration, business_mode, admin commands). When a second L2 application needs channel
> adapters, the generic parts (~40% of code: WebSocket routing, pub/sub bridge, message dispatch)
> should be extracted to `socialware/` as an L1 channel framework. See analysis below.

### Channel feature parity (as of M3)

The web channel is the canonical customer message path. Feishu was the M1
primary channel and has not been kept in sync with M2/M3 features. New
customer-flow work should land in `channels/web` (or `autoservice/gateway/`
which it delegates to). Touching Feishu only makes sense if it returns to
the active product roadmap.

| Feature                                          | Web (`channels/web` + `autoservice/gateway/`) | Feishu (`channels/feishu`) |
|--------------------------------------------------|-----------------------------------------------|----------------------------|
| `ModelRouter` / `triage_and_route` dispatch       | ✅ `gateway/message_router.py`                 | ❌ direct `session_query` |
| Multi-role sub-pools (lead / translate / triage) | ✅ via `cc_pool.acquire(role=…)`                | ❌ customer sticky only   |
| Per-tenant sticky binding (`tenant_id`)           | ✅ via `session_query(tenant_id=…)`            | ❌ no tenant injection     |
| KB pre-fetch (`_build_customer_prompt`)           | ✅                                             | ❌                          |
| Cross-role history reseed                         | ✅ `_build_reseeded_prompt`                    | ❌                          |
| Per-role model tier (fast/slow/dream)             | ✅ flows through cc_pool                       | ⚠️ only customer pool's `slow_model` is reachable |

The Feishu channel still works for single-tenant customer chat with M1
semantics. If/when Feishu re-enters scope, the alignment work is roughly
"port the call site at `channels/feishu/channel_server.py:432` and `:1361`
to the same triage + tenant flow as `gateway/message_router.py`".

### channels/ L1 extraction roadmap (deferred)

The following generic components are candidates for future L1 extraction:

| Component | Current location | Reusability |
|-----------|-----------------|-------------|
| WebSocket route multiplexer (exact/prefix/wildcard) | channel_server.py | High |
| ChannelClient (auto-reconnect, heartbeat, message loop) | channel.py | High |
| WebChannelBridge (pub/sub) | websocket.py | High |
| Token lifecycle management (expiry, idle cleanup) | auth.py | Medium |
| Plugin HTTP route registration | app.py | Medium |

**Extraction blocker:** channel_server.py (~1100 lines) has Feishu logic and routing logic
deeply interleaved. Requires refactoring into generic Router + pluggable ChannelAdapter before
the generic parts can move to L1. Estimated effort: medium-high.

## Plugin System

Each plugin lives in `plugins/<name>/` with `plugin.yaml` declaring MCP tools + HTTP routes.
Plugin tools are auto-loaded by `channels/feishu/channel.py` (MCP) and `channels/web/app.py` (HTTP).
Plugin skills in `plugins/<name>/skills/` are symlinked by `make setup`.

Run `make check` to verify plugin discovery.

## Fork Workflow

Three-layer fork chain: L1 (socialware) → L2 (autoservice) → L3 (tenant).
Sync direction: `git merge upstream/main` at every level.
Refinement direction: GitHub PR at every level.

| Layer | Upstream | This Repo |
|-------|----------|-----------|
| L1 | `h2oslabs/socialware` | `socialware/` |
| L2 | (this repo is L2) | `autoservice/`, `channels/`, `skills/`, `plugins/_example/` |
| L3 | This repo (upstream) | `plugins/<tenant>/`, tenant-specific data |

### For fork maintainers

**Contributing improvements back to upstream:** If you make changes that are not customer-specific (bug fixes, framework enhancements, generic skill improvements), create a PR targeting this repo. Rule of thumb: if the change benefits other customers, PR it upstream.

**Syncing with upstream:**
```bash
git fetch upstream
git merge upstream/main
```

## Dev Auth Bypass

`AUTH_DEV_MODE=1` enables two dev-only endpoints (`GET /api/auth/dev-mode`,
`POST /api/auth/dev-login`) that let developers mint an admin session without
going through the magic-link flow. **This variable MUST NOT be set in
production, staging, or any shared/networked environment** — it turns the
admin portal into a no-password console for anyone who can reach it.

- `make run-web` sets it automatically for local dev.
- Production Docker/compose/k8s configs must leave it unset.
- Spec: `docs/superpowers/specs/2026-04-21-dev-auto-login-design.md`.

## Dream Dev Stub

`DREAM_DEV_STUB=1` is an offline-dev / CI fallback for `/api/dream/trigger`.
Post-T5S.14 (M3.5) the default path always drives a real LLM tool-loop —
per-tenant via `dream_agent.run_dream` and master via `master_dream_agent.
run_platform_dream`, both backed by the CC pool's `call_with_tools`
surface (local `claude_agent_sdk`, not the Anthropic cloud SDK).

Setting `DREAM_DEV_STUB=1` short-circuits BOTH paths (master and per-tenant)
to `_run_dev_stub_dream`: three seed proposals emitted after a 3-second
sleep, no LLM traffic, no key required. Useful for:

- CI without an `ANTHROPIC_API_KEY` / without a local Claude CLI installed.
- Offline demos / video capture where deterministic output matters.
- Smoke-testing the Dream Engine UI flows without spending tokens.

Unlike `AUTH_DEV_MODE`, `DREAM_DEV_STUB` does not expose an auth-bypass
surface, so the production risk is strictly "wrong output" rather than
"unauthenticated access". Still leave it unset in production — seed
proposals would pollute real `proposals` tables.

## Triage Agent Kill-Switch

`TRIAGE_AGENT_ENABLED` controls the haiku-backed triage agent fallback
that runs when FastClassifier confidence is below the medium threshold
(`classify_intent.yaml::confidence.medium`, default 0.6).

**Default: enabled** (as of 2026-04-23 afternoon — flipped back on
after the morning's disable experiment). The agent is needed for tier
selection on keyword-miss messages: FastClassifier's
`general_question` fallback always uses `fast` tier, so ambiguous
messages that actually need sonnet never get it without the agent.
`_TRIAGE_AGENT_TIMEOUT` is **8 s** (bumped again from 4 s late the
same day after observing recurring exact-4.000s timeouts in the
gateway log — haiku's real round-trip on this network + prompt size
consistently pushed past 4 s even with a warm pool instance). Override
per-deploy with `TRIAGE_AGENT_TIMEOUT_S` env var (e.g.
`TRIAGE_AGENT_TIMEOUT_S=12` for slow links).

Off (`TRIAGE_AGENT_ENABLED=0`): low-confidence messages route via
`_triage_fallback` (intent, confidence, routing, and tier taken
directly from FastClassifier). Downstream SIDE `[分流]` messages carry
`source: "fallback"`. Use when strict latency cap matters more than
tier accuracy on the ~10% of messages that miss all keywords.

Gate: `autoservice/model_router.py::_triage_agent_enabled`.

## Placeholder Filler Kill-Switch

`PLACEHOLDER_ENABLED` controls the **filler text** ("正在为您查询..."
or soothe-picker variant) that gets emitted on a 1.5s timer if the
model hasn't produced a first token yet. Default **on**.

When set to `0`:

- The timer-based `_placeholder_worker` is never scheduled, so no
  filler bubble is ever emitted.
- **Streaming is preserved.** On the first real model token,
  `_drain_with_placeholder` inline-creates a message with that chunk
  as its content (no `is_placeholder` flag) — this becomes the edit
  target for subsequent progressive `message_edited` frames. The
  customer still gets the typewriter-style fill-in, just without the
  stiff filler bubble preceding it.
- Overrides `SOOTHE_PLACEHOLDER_ENABLED` — with this off, soothe
  templates are irrelevant because no filler is ever produced.

Net customer UX with `PLACEHOLDER_ENABLED=0`: ~0.5-1 s of empty wait
(haiku TTFT on warm pool), then the real reply streams in token-by-
token as normal. Use when the filler text feels stiff.

`make run-web` / `make run-gateway` set this to `0` for local dev;
production leaves it unset (defaults to on).

Gate: `autoservice/gateway/message_router.py::PLACEHOLDER_ENABLED`.

## Credentials

- `.feishu-credentials.json` — Feishu app credentials (gitignored)
- `.autoservice/config.local.yaml` — Local API keys and endpoints (gitignored)
- `.env` — Environment variables (gitignored)

## /autorun & batch execution conventions

When running `/autorun`, `/batch-dispatch`, or any multi-task execution:

1. **`{plans_dir}/task-status.md` is the authoritative truth** — not TodoWrite,
   not commit messages, not chat. It must be updated at every batch boundary
   (same commit as code, or a trailing `chore(m2):` commit in the same work
   session). Never skip to the next batch dispatch without updating it.

2. **Read `{plans_dir}/cc-prompt-templates.md` §3 Closing** at autorun start and
   treat it as a checklist. The template prescribes: edit task-status (phase row
   + batch row + summary + session log) → git add code + status → commit →
   declare next candidate.

3. **Subagent dispatch prompts must inline the Closing constraint**
   (see `cc-prompt-templates.md` §6). A subagent that commits without updating
   task-status is a breach — its code is correct but the record is stale and
   the next dispatch acts on wrong state.

4. **Yellow tasks** route through §5 — code-reviewer subagent review before
   Closing; reviewer verdict in commit body.

plans_dir is resolved from `docs/plans/project.yaml → project.plans_dir`.
