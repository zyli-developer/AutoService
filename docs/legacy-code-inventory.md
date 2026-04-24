# Legacy Code Inventory

> Running catalog of **code paths, endpoints, and storage locations that
> are NOT part of the M2/M3 operator-visible customer flow** but still
> exist in the repo. The point is to make them quick to grep / filter when
> debugging "why doesn't X show up for operators" or "is this feature
> still alive".

**Canonical customer path (M2/M3+)**:

```
browser → channels/web/app.py (WS /chat/ws)
       → autoservice/gateway/message_router.py::dispatch
       → autoservice/conversation_engine/local_engine.py (+ sqlite_store)
       → operator-console via subscribers
```

Anything NOT on that path is listed below. Before touching any of these,
check the "Status" column — items marked `frozen` do not get new features,
items marked `dead` can be deleted once confirmed unused.

---

## 1. Cinnox-demo `/ws/chat` channel (old web flow)

**Status:** `frozen` — still wired up, still writes JSON sessions, but
**operator-console does NOT read from it**. Used by `channels/web/static/
cinnox.html` for a standalone customer-chat demo page with access-code
auth; replaced for M2+ tenant use by the gateway flow.

**Entry point:** [channels/web/websocket.py:141](../channels/web/websocket.py#L141)
— `/ws/chat` WebSocket handler. Multiplexes browser sessions over one
persistent connection to the old `ChannelServer` (feishu-era message bus,
see §2).

**Message frames:** `resume_session`, `end_session`, `bot_text_delta`,
`done`, `heartbeat`. Independent of the M2 gateway envelope v1 schema.

**Storage:** [channels/web/session_persistence.py](../channels/web/session_persistence.py)
writes JSON files to `.autoservice/database/sessions/<access_code>/
<session_id>.json`. Each file has `conversation`, `claude_session_id`,
`turn_count`, `resolution`, etc. **This dir was not present as of
2026-04-24** — the old flow is effectively dormant in current deployment.

**Related HTTP endpoints** ([channels/web/app.py](../channels/web/app.py)):

| Route | Purpose | Status |
|-------|---------|--------|
| `GET /api/sessions` | List saved JSON sessions for an access code | `frozen` — UI only in cinnox.html |
| `GET /api/sessions/{session_id}` | Single session JSON | `frozen` |
| `GET /auth/verify` | Access-code auth for the demo | `frozen` |
| `POST /auth/logout` | Release session lock | `frozen` |

**Removal checklist** (when ready): delete `channels/web/websocket.py`,
`channels/web/session_persistence.py`, `channels/web/static/cinnox.html`,
the three `/api/sessions*` + `/auth/*` routes in `channels/web/app.py`,
and the `.autoservice/database/sessions/` directory. Nothing in the
`autoservice/gateway/` tree imports them.

---

## 2. Feishu `ChannelServer` + IM channel

**Status:** `frozen` (M1 primary channel, see CLAUDE.md "Channel feature
parity"). Not kept in sync with M2/M3 features (triage, multi-role pool,
tenant sandbox, KB pre-fetch, cross-role reseed). Still works for
single-tenant Feishu IM chat with M1 semantics.

**Entry point:** `make run-channel` → [channels/feishu/channel.py](../channels/feishu/channel.py) + [channels/feishu/channel_server.py](../channels/feishu/channel_server.py).

**CRM write-through:** the Feishu path (and only the Feishu path, plus
[autoservice/plugins/lifecycle_plugin.py:131](../autoservice/plugins/lifecycle_plugin.py#L131))
writes every message to `crm.log_message()` → SQLite `conversations` table
at `.autoservice/database/crm.db`. The M2/M3 gateway flow **does NOT**
call `log_message`, so that table never sees web-channel traffic.

**Parity gaps** (vs. web/gateway): no ModelRouter/triage dispatch, no
multi-role sub-pools, no per-tenant sticky binding, no KB pre-fetch, no
cross-role history reseed. Port path (if/when needed): mirror the call
sites at `channels/feishu/channel_server.py:432` and `:1361` against
`autoservice/gateway/message_router.py`.

---

## 3. Admin-portal "chat" endpoints — stateless / stub

**Status:** intentional design (M2/M3), NOT legacy — but listed here because
"why doesn't my admin chat message persist" is a very common question.

| Endpoint | Persisted? | Why |
|----------|-----------|-----|
| `POST /api/management/chat` | No | [autoservice/api_routes.py:1242](../autoservice/api_routes.py#L1242) routes through cc_pool `_master`, returns reply. Chat state is a frontend React `useState` only. |
| `POST /api/management/chat-legacy` | No | [autoservice/api_routes.py:1300](../autoservice/api_routes.py#L1300) — M1 slash-command / Dream Engine dispatcher. Kept one milestone for pre-M2 integrations; scheduled for deletion at M3 once `_master` admin tool set lands. |
| `POST /api/admin/chat` | No | [autoservice/api_routes.py:1409](../autoservice/api_routes.py#L1409) — M2 **stub**, returns `(stub) Received: ...`. Full `_local_admin` / `run_dream` wire-up tracked by T7B.6. |

None of these write to `conversations.db` or CRM. If you need to see admin
chat history after restart, it has to be added on top of one of these
handlers — consider routing it through LocalEngine so it lives in the same
store as customer history.

---

## 4. Misleading docstrings / stale comments

| File:line | Claim | Reality |
|-----------|-------|---------|
| [autoservice/conversation_engine/local_engine.py:5](../autoservice/conversation_engine/local_engine.py#L5) | `"EventBus — in-process pub/sub + SQLite async persistence"` | Historically false — `self._events` was a pure `dict` until 2026-04-24. Now persisted via `ConversationStore` when a store is passed in. |
| [autoservice/conversation_engine/local_engine.py:116](../autoservice/conversation_engine/local_engine.py#L116) | `"All state is held in memory (dicts)"` | Now conditional — true only when `store=None`; production path wires a store. |

These are updated as of the SQLite-persistence landing (2026-04-24). If
you see similar "SQLite-backed" claims in other engine-adjacent files
that turn out to be memory dicts, add them to this table.

---

## 5. Dev-only / CI fallbacks (NOT legacy, but low-visibility)

Listed so they can be grepped quickly when investigating "why does this
behave differently in CI vs dev vs prod":

| Env var | File | Effect |
|---------|------|--------|
| `AUTH_DEV_MODE=1` | [channels/web/auth.py](../channels/web/auth.py) | Exposes `/api/auth/dev-mode` + `/api/auth/dev-login`; MUST NOT be set in prod. |
| `DREAM_DEV_STUB=1` | [autoservice/dream_agent.py](../autoservice/dream_agent.py) | Short-circuits Dream LLM loop to 3 seed proposals after 3s. |
| `TRIAGE_AGENT_ENABLED=0` | [autoservice/model_router.py](../autoservice/model_router.py) | Disables haiku triage agent fallback; routes low-confidence messages via `_triage_fallback`. |
| `PLACEHOLDER_ENABLED=0` | [autoservice/gateway/message_router.py](../autoservice/gateway/message_router.py) | Suppresses filler "正在为您查询…"; streaming still works. |
| `CONV_PERSIST=0` | [autoservice/web_gateway.py](../autoservice/web_gateway.py) | Disables SQLite conversation store. Default is ON in production; `pytest in sys.modules` auto-defaults to OFF so tests don't write real rows. |
| `CONV_DB_PATH=...` | same | Override `.autoservice/database/conversations.db`. |

---

## Maintenance

When adding an item here:
1. State current **Status** (`frozen`, `dead`, `stub`, etc.) explicitly.
2. Link to the entry point with `file:line`.
3. Note how to confirm it's unused (what grep query comes up empty).
4. If there's a replacement path, point at it.

When removing an item from the repo, also remove its section here — this
file should only list code that currently exists.
