# AutoService — Three-Layer Fork-Based AI Application Framework

## Overview

AutoService is a three-layer fork-based framework for building AI-powered social-channel applications (customer service, sales, education, etc.). The architecture uses full-chain fork strategy (L1 → L2 → L3).

**Three layers:**
- **L1 `socialware/`** — Base framework: plugin loading, config mechanism, session framework, async pool, generic utilities
- **L2 `autoservice/`** — Application layer: customer service business logic, CRM, domain-specific configs
- **L2 `channels/`** — Channel adapters: Feishu IM, Web chat (currently L2, contains business-specific logic; generic parts may be extracted to L1 when a second application emerges)
- **L3 `plugins/<tenant>/`** — Tenant instance: customer-specific plugins and data

**Two channels:**
- **Feishu IM** (primary) — MCP-based, runs as `channels/feishu/channel.py`
- **Web chat** (secondary) — FastAPI app at `channels/web/app:app`

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
