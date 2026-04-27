# General Bot SSE HTTP API — Design

**Date:** 2026-04-27
**Status:** Draft (pending implementation plan)
**Owner:** AutoService gateway

## 1. Goal

Provide an inbound HTTP/SSE endpoint so third-party IM platforms (e.g. CINNOX
General Chatbot integration, see [docs/General-Bot-Streaming-Message(SSE)-API_20260427.md](../../General-Bot-Streaming-Message(SSE)-API_20260427.md))
can POST end-user messages to AutoService and receive a streaming bot reply.

Out of scope:
- Outbound webhook to CINNOX (we are the bot, not the platform).
- Operator real-time intervention within a single HTTP turn (HTTP is one-shot;
  intervention only affects the next turn).
- Admin UI for issuing API keys (CLI only in v1).

## 2. Decisions

| # | Decision | Choice |
|---|----------|--------|
| 1 | Tenant routing | **B1**: tenant in URL path `/chat/{tenant_id}`; API key in `Authorization` header is auth-only |
| 2 | inquiryID semantics | **C1**: inquiryID present → sticky multi-turn conversation; absent → one-shot |
| 3 | Pipeline reuse | **D3**: reuse triage + KB + multi-role pool + direct-reply, but skip multi-bubble; new SSE-only sink + drain |
| 4 | Operator visibility | **E1**: full broadcast to operator squad (with `passive_channel: True` to skip takeover scheduler) |
| 5 | Concurrency | **F1**: same conv_id requests serialized via existing `turn_queue`; per-turn keepalive comments to defeat LB idle |

## 3. Module layout

```
autoservice/integrations/general_bot/
├── __init__.py
├── routes.py          # FastAPI router with POST /chat/{tenant_id}
├── auth.py            # Per-tenant API key load + verify
├── sse.py             # SSEStream / JSONSink + ReplySink protocol
└── reply_pipeline.py  # Transport-agnostic stream_agent_reply (D3 core)

tests/integrations/general_bot/
├── test_routes_stream.py
├── test_routes_json.py
├── test_auth.py
├── test_inquiry_id.py
├── test_concurrent.py
├── test_passive_channel.py
├── test_sse_sink.py
└── test_reply_pipeline.py

scripts/
└── issue_general_bot_key.py    # CLI to mint a key for a tenant

.autoservice/sandbox/<tid>/
└── api_keys.json               # [{key_id, hash, created_at, revoked_at?, label}]
```

Mounting: `autoservice.web_gateway.create_app()` adds
`app.include_router(general_bot_router)` next to the existing
`api_router`/`onboard_router`. Route handler reaches engine + pool through
`request.app.state.engine` and `autoservice.web_gateway._get_pool()` (same
plumbing as the WS path).

## 4. Endpoint contract

### 4.1 Request

```
POST /chat/{tenant_id}
Authorization: Bearer <api_key>
Accept: text/event-stream            # or application/json
Content-Type: application/json

{
  "query": "<user message>",
  "queryParams": {...},
  "inquiryID": "<optional>",
  "action": "input.unknown"
}
```

Also accepted (CINNOX legacy shape per spec §3.1):
```json
{"queryResult": {"queryText": "<user message>"}}
```

### 4.2 Streaming response (Accept: text/event-stream)

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no

: keepalive

data: {"message":{"type":1,"text":"<delta>","streamType":"delta"}}

...

data: {"message":{"type":1,"text":"<full reply>"}}
```

Initial `: keepalive\n\n` is flushed immediately after the response headers
to defeat LB idle timeouts before the first LLM token arrives. Subsequent
keepalives every 15s until first delta. Per CINNOX spec §3.2 / §3.4.

### 4.3 Non-streaming response

```
HTTP/1.1 200 OK
Content-Type: application/json

{"message":{"type":1,"text":"<full reply>"}}
```

### 4.4 Pre-stream errors

| Status | Trigger | Body |
|--------|---------|------|
| 401 | missing/invalid/revoked Authorization | `{"error":"unauthorized"}` (same body as 404 — no tenant-enumeration oracle) |
| 404 | unknown tenant_id (not in sandbox + plugins markers) | `{"error":"unauthorized"}` (intentionally identical to 401) |
| 422 | missing `query` (or `queryResult.queryText`) | `{"error":"query required"}` |
| 429 | `turn_queue.submit` raises `QueueFullError` | `{"error":"queue full"}` |
| 503 | cc_pool unavailable | `{"error":"cc_pool unavailable"}` |

### 4.5 Mid-stream errors

Per CINNOX spec §6.5: response status is already `200`, cannot change. We
emit one terminal SSE event and close the connection:

```
data: {"message":{"type":1,"text":"(抱歉,本次未能生成完整回复)"}}
```

Also persist a `Message` row with `metadata={"is_fallback": True}` and
broadcast to the operator squad so the failure is visible in the operator
UI.

### 4.6 Limits (spec §8)

| Limit | Implementation |
|-------|----------------|
| 120s total | `asyncio.wait_for(reply_runner, timeout=120)`; on timeout → terminal error event |
| 4MB cumulative reply | `SSEStream` accumulates byte count; on overflow stops accepting deltas, emits terminal of whatever was accumulated, logs warning |
| 1MB / event | Not enforced (claude_agent_sdk deltas are tiny) |

## 5. Authentication

### 5.1 Storage

`.autoservice/sandbox/<tid>/api_keys.json`:

```json
[
  {
    "key_id": "k_2026_01",
    "hash": "<sha256(key) hex>",
    "created_at": "2026-04-27T10:00:00.000Z",
    "revoked_at": null,
    "label": "cinnox-prod"
  }
]
```

- Key format: 32-byte URL-safe random (`secrets.token_urlsafe(32)`).
- Stored as SHA-256 hex; raw key never persisted server-side.
- Verification uses `secrets.compare_digest` against each non-revoked entry.

### 5.2 Issuance (v1 = CLI)

`scripts/issue_general_bot_key.py <tid> [--label cinnox-prod]`
- Generates key; appends `{key_id, hash, created_at, label}` to keys file
  (creating sandbox dir if absent).
- Prints raw key once to stdout for the operator to share with CINNOX.

Admin UI is out of scope (track for M3.5+).

### 5.3 Tenant resolution

Reuse `autoservice.gateway.tenant_resolver.resolve_customer_tenant({"tenant": tenant_id})`
unchanged. Same registration markers (`sandbox/<tid>/config.json`,
`plugins/<tid>/plugin.yaml`, `plugins/<tid>/config.json`) gate the path.

## 6. Data flow

```
POST /chat/{tid}
  ├─ verify Authorization        → 401 (same body as 404, no oracle)
  ├─ resolve_customer_tenant     → 404
  ├─ parse body (incl. legacy queryResult.queryText)  → 422 if no query
  │
  ├─ inquiry_id handling (C1)
  │    ├─ present: engine.create_conversation(
  │    │              channel="cinnox",
  │    │              external_id=f"{tid}:{inquiry_id}",      # tenant-namespaced
  │    │              metadata={
  │    │                "tenant_id": tid,
  │    │                "inquiry_id": inquiry_id,
  │    │                "passive_channel": True,
  │    │                "squad_id": squad_plugin.choose_squad(channel="cinnox"),
  │    │              })
  │    │       LocalEngine.create_conversation is idempotent on
  │    │       (channel, external_id): returns the existing Conversation
  │    │       if conv_id == f"cinnox_{tid}:{inquiry_id}" already exists
  │    │       and is not closed. Metadata supplied above is ONLY honored
  │    │       on first create — subsequent calls do not mutate it.
  │    │       Defensive guard: if returned conv.metadata["tenant_id"]
  │    │       != tid, treat as auth failure (401) — would only happen
  │    │       on data corruption since external_id is namespaced.
  │    └─ absent: engine.create_conversation(
  │              channel="cinnox-oneshot",
  │              external_id=str(uuid.uuid4()),
  │              metadata={"tenant_id": tid, "passive_channel": True, ...})
  │
  ├─ engine.join(conv_id, Participant(id=f"cinnox:{inquiry_id or 'anon'}", role=CUSTOMER))
  ├─ engine.send_message(conv_id, source=..., content=query)
  ├─ broadcast customer_message frame → operator squad (E1)
  │
  ├─ build sink (SSEStream | JSONSink) per Accept header
  ├─ flush 200 + headers + initial `: keepalive\n\n`
  │
  └─ turn_queue.submit(conv_id, runner)            (F1)
       runner = stream_agent_reply(engine, pool, conv_id, query, tid, sink)

stream_agent_reply (D3):
  1. triage_and_route()
  2. if direct-reply → emit_terminal(template), persist agent msg, broadcast, return
  3. _build_customer_prompt() / _build_reseeded_prompt() (KB pre-fetch + role switch)
  4. iterator = pool.session_query(conv_id, prompt, tenant_id, tier)
                or _role_stream() for non-customer roles
  5. async for item in iterator: extract text_delta → sink.emit_delta()
  6. sink.emit_terminal(full_text)
  7. engine.send_message(conv_id, source="agent", content=full_text)   # one row, no segments
  8. broadcast agent message frame → squad
  9. record SLA first_reply_ms
```

### 6.1 Reused components (no changes)

- `autoservice.triage_dispatch.triage_and_route`
- `autoservice.triage_dispatch._build_customer_prompt`
- `autoservice.triage_dispatch._build_reseeded_prompt`
- `autoservice.triage_config_loader.load_tenant_config_for_conv`
- `autoservice.cc_pool.CCPool.session_query` and `acquire(role=...)` flow
- `autoservice.gateway.message_router._broadcast_to_squad`
- `autoservice.gateway.turn_queue.TurnQueue` (module-level singleton via `get_turn_queue()`)
- `autoservice.gateway.tenant_resolver.resolve_customer_tenant`
- `autoservice.plugins.squad_plugin.SquadPlugin`

### 6.2 Small refactors

- Promote `gateway.message_router._collect_operator_suggestions` to
  `gateway.message_router.collect_operator_suggestions` (drop the underscore;
  it is already pure and reused across two call sites). Old name kept as
  alias for one release to avoid breaking anything that grepped for it.
- Add `passive_channel` skip in the takeover scheduler entry point at
  [autoservice/conversation_engine/local_engine.py:766](../../../autoservice/conversation_engine/local_engine.py#L766)
  (`_arm_takeover_timer`). Three-line guard at the top:
  ```python
  conv = self._conversations.get(conversation_id)
  if conv is not None and conv.metadata.get("passive_channel"):
      return
  ```
  This is the single funnel for arming — `reset_takeover_timer` and the
  mode/leave/close paths all flow through it, so one guard covers all cases.

### 6.3 Multi-bubble explicitly NOT used

`MULTI_BUBBLE_ENABLED` flag is irrelevant to this path: SSE produces one
terminal text event per CINNOX spec §3.4. Persistence writes ONE Message
row per turn. Operator UI sees exactly one customer message and one agent
message per turn — same shape as `MULTI_BUBBLE_ENABLED=0`.

## 7. SSE sink contract

### 7.1 Protocol

```python
class ReplySink(Protocol):
    async def emit_delta(self, text: str) -> None: ...
    async def emit_terminal(self, text: str) -> None: ...
    async def close(self) -> None: ...
```

### 7.2 SSEStream behavior

- Headers: `text/event-stream`, `no-cache`, `keep-alive`, `X-Accel-Buffering: no`.
- First write after headers: `: keepalive\n\n` (LB defeat).
- Background `_keepalive_loop` emits `: keepalive\n\n` every 15s until close.
- Each delta: `data: {"message":{"type":1,"text":"<chunk>","streamType":"delta"}}\n\n`.
- Terminal: `data: {"message":{"type":1,"text":"<full>"}}\n\n` then close.
- Cumulative cap: 4MB; on breach, sets `_truncated=True` and stops accepting
  more deltas; the eventual terminal still fires with whatever was buffered.
- All writes go through one `async send(line: bytes)` callable supplied by
  the FastAPI `StreamingResponse` content generator.

### 7.3 JSONSink behavior

- `emit_delta` accumulates into a list.
- `emit_terminal` records the final text.
- Route handler reads `.body` after `stream_agent_reply` returns and packs
  it into `JSONResponse(body)`.

## 8. Concurrency model

`TurnQueue.submit` is fire-and-forget — it returns immediately and the
runner executes in a separate task. So the HTTP route handler cannot
"call" the runner and wait for output; instead, we bridge runner → HTTP
response with an `asyncio.Queue[bytes | None]`:

```
route handler                          runner task (in TurnQueue)
─────────────                          ──────────────────────────
auth + parse + persist customer msg
                       ┌────────────►  stream_agent_reply(sink)
queue: asyncio.Queue                       │
sink wraps queue.put_nowait                │
turn_queue.submit(conv_id, runner)         │
return StreamingResponse(gen)              ▼
   └─ gen awaits queue.get() ◄──── sink.emit_delta → put(b"data: ...\n\n")
                                  ◄──── sink.emit_keepalive → put(b": ...\n\n")
                                  ◄──── sink.emit_terminal → put(b"data: ...\n\n")
                                                               put(None)  # sentinel
   └─ gen sees None, returns; FastAPI closes conn
```

- Validation/auth happens synchronously in the route handler. Failures
  return `JSONResponse(status_code=4xx)` BEFORE any queue/runner setup.
- `QueueFullError` from `turn_queue.submit` is caught in the route handler
  and returned as 429 (still pre-stream, no SSE bytes written yet).
- `DEFAULT_MAX_QUEUE_DEPTH=5` (env `QUEUE_MAX_DEPTH`, see
  [autoservice/gateway/turn_queue.py:17](../../../autoservice/gateway/turn_queue.py#L17)).
- Pre-runner `: keepalive` flush in the SSE generator's first iteration
  ensures the queued request's HTTP socket doesn't appear idle while
  waiting for its turn to fire.
- Per-runner watchdog: `asyncio.wait_for(stream_agent_reply(...), timeout=120)`
  inside the runner. On timeout: cancel, sink.emit_terminal with
  `(超时未生成完整回复)`, persist fallback row, broadcast to squad, then
  put sentinel.
- All exceptions inside the runner funnel through a single `finally:
  await sink.close()` and `queue.put_nowait(None)` to guarantee the SSE
  generator always terminates.

## 9. Edge cases

| Case | Behavior |
|------|----------|
| `inquiryID` belongs to a conv created by some other channel | Cannot collide: `conv_id = f"{channel}_{external_id}"` is namespaced by channel, so `cinnox_<tid>:<inquiry_id>` and `web_<inquiry_id>` are different rows. |
| Empty `query` after trim | 422 |
| `Accept` lists both `text/event-stream` and `application/json` | Streaming wins (substring match per spec §2.2 / §4.1) |
| Tenant exists but has no `api_keys.json` file | 401 (no oracle vs. unknown tenant) |
| Same `inquiry_id` collides across tenants | `external_id` is built as `f"{tid}:{inquiry_id}"`, so conv_id is `cinnox_<tid>:<inquiry_id>` — collisions are physically impossible at the engine row level. |
| Customer message arrives during operator takeover (`mode=TAKEOVER`) | Same as web channel: AI reply runs but `_drain_into_bubbles`-equivalent re-checks mode at end and discards if takeover; we mirror the existing post-stream check, emit terminal `(客服已接管对话)`. |
| Pool unavailable mid-stream | Drain catches exception; SSE sends terminal error event; persist fallback row with `metadata={"is_fallback": True}`. |
| 4MB cumulative reached | Truncate further deltas; emit terminal of accumulated text + a notice suffix `\n(回复已截断)`. |

## 10. Testing strategy (TDD-first)

| File | Coverage |
|------|----------|
| `test_sse_sink.py` | Byte-exact framing per spec §3.4 |
| `test_auth.py` | Valid / revoked / missing / unknown tenant — 401 vs 404 same body |
| `test_routes_stream.py` | Happy path; keepalive emission; mid-stream error → terminal event; 4MB truncation |
| `test_routes_json.py` | Non-streaming JSON; legacy queryResult.queryText; missing query → 422 |
| `test_inquiry_id.py` | Multi-turn reuse; absent → one-shot; cross-tenant collision isolation |
| `test_concurrent.py` | turn_queue serialization; queue-full → 429 |
| `test_passive_channel.py` | Takeover scheduler skips conv with `metadata.passive_channel=True` |
| `test_reply_pipeline.py` | Stub pool + sink; cover customer / role-switch / direct-reply branches |

Integration tests use `httpx.AsyncClient(app=app, base_url="http://test")` and
parse SSE bodies by splitting on `\n\n`. cc_pool is mocked at the
`session_query` level (returning a configured async iterator of fake
`StreamEvent`/`AssistantMessage` objects).

## 11. Operational notes

- Logging: `autoservice.general_bot` logger at INFO; per-request log line
  with `tenant_id`, `inquiry_id`, `conv_id`, `streaming` bool, `ttft_ms`,
  `total_ms`, `reply_chars`, `error?`. Mirrors web-channel timing line.
- SLA hooks: same `first_reply_ms`/`TTFB_MS` records as the WS path
  (`get_sla_aggregator().record(...)`).
- Metrics: counters `general_bot_requests_total{tenant,outcome}`,
  histogram `general_bot_ttft_ms{tenant}`. Wire if existing metrics
  registry has a gateway equivalent; otherwise log-only in v1.
- Env flag: `GENERAL_BOT_ENABLED` (default `1`) — when `0`, route handler
  returns 503 immediately. Useful for staged rollouts.

## 12. Backward compatibility & rollout

- Pure additive: no existing route changed; no shared state shape changed.
- New env flag `GENERAL_BOT_ENABLED` defaults on; flip off for emergency.
- New module isolated under `autoservice/integrations/general_bot/`; can
  be deleted in one commit if the integration is dropped.
- The one tiny refactor (`_collect_operator_suggestions` → public name)
  keeps a deprecated alias.

## 13. References

- [docs/General-Bot-Streaming-Message(SSE)-API_20260427.md](../../General-Bot-Streaming-Message(SSE)-API_20260427.md) — the contract this design implements
- [autoservice/web_gateway.py](../../../autoservice/web_gateway.py) — app factory + WS handlers; mount point
- [autoservice/gateway/message_router.py](../../../autoservice/gateway/message_router.py) — current WS reply pipeline (`_generate_agent_reply`, `_drain_into_bubbles`, `_broadcast_to_squad`)
- [autoservice/triage_dispatch.py](../../../autoservice/triage_dispatch.py) — triage routing reused as-is
- [autoservice/cc_pool.py](../../../autoservice/cc_pool.py) — `session_query` and multi-role acquire
- [autoservice/gateway/tenant_resolver.py](../../../autoservice/gateway/tenant_resolver.py) — tenant validation reused
- [docs/superpowers/specs/2026-04-26-instant-ack-multi-bubble-queue-design.md](2026-04-26-instant-ack-multi-bubble-queue-design.md) — `turn_queue` semantics reused
- W3C SSE: https://www.w3.org/TR/eventsource/
