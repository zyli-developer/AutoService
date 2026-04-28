# AutoService General Bot — Third-Party Integration Guide

This guide is for third-party IM/chat platforms (CINNOX-compatible vendors)
that want to call the AutoService General Bot endpoint to get streaming bot
replies for end-user messages.

The endpoint follows the CINNOX **General Chatbot Streaming Message (SSE) API**
contract with vendor-side opt-in streaming. If you are integrating from
the CINNOX admin UI, this guide tells you exactly what URL, headers, and body
to use.

---

## 1. Endpoint

```
POST https://<your-deployment-host>/chat/{tenant_id}
```

- `tenant_id` — your assigned tenant identifier (provisioned by the AutoService
  admin team; identifies which tenant's bot serves the request)
- One fixed URL per tenant. CINNOX admin UI configures this URL once on the
  chatbot definition; AutoService routes by the path component.

> **Note:** Tenants share the same host but have distinct `tenant_id` paths.
> Cross-tenant collisions are physically prevented by the namespacing —
> `tenantA`'s `inquiryID="I-1"` is a different conversation from `tenantB`'s
> `inquiryID="I-1"`.

---

## 2. Authentication

Every request must carry a Bearer token in the `Authorization` header:

```
Authorization: Bearer <api_key>
```

- Each tenant has one or more API keys, issued by the AutoService admin team.
- Keys are 32-byte URL-safe random strings (≥43 characters in printable form).
- The same key works for both streaming and non-streaming requests.
- Treat the key as a secret. We store only its hash; if you lose the raw key,
  request a new one (the old key cannot be recovered).

### How to obtain a key

Contact the AutoService admin team with your `tenant_id` and a label
describing the integration (e.g., `"cinnox-prod"`, `"cinnox-staging"`). They
will run:

```
uv run python3 scripts/issue_general_bot_key.py <tenant_id> --label "<label>"
```

and return the raw key to you over a secure channel (the raw key is shown
once and never persisted server-side).

### Security responses

| Condition | Response |
|---|---|
| Missing `Authorization` | 401, body `{"error": "unauthorized"}` |
| Wrong / revoked / non-Bearer token | 401, **same body** |
| Unknown `tenant_id` (not provisioned) | 401, **same body** |

The 401 body is intentionally identical for all auth-or-tenant failure modes
to prevent tenant enumeration.

---

## 3. Request

### Headers

| Header | Required | Value |
|---|---|---|
| `Authorization` | yes | `Bearer <api_key>` |
| `Content-Type` | yes | `application/json` |
| `Accept` | optional | `text/event-stream` to enable SSE streaming. Anything else (or absent) → JSON response. |

### Body

```json
{
  "query": "<user message text>",
  "queryParams": { "...": "..." },
  "inquiryID": "<optional CINNOX inquiry id>",
  "action": "input.unknown"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `query` | string | yes | The end-user's message text. Empty/whitespace-only rejected with 422. |
| `queryParams` | object | no | Pass-through key/value map. Currently not interpreted server-side; reserved for future extensions. |
| `inquiryID` | string | no | When present, marks the conversation. Subsequent calls with the same `inquiryID` continue the same multi-turn session (sticky agent + KB context). When absent, the request is treated as a one-shot (no session memory across calls). |
| `action` | string | no | Always `"input.unknown"` for standard messages. Currently informational. |

> **Legacy shape**: For CINNOX backward compatibility, the legacy body
> `{"queryResult": {"queryText": "<text>"}}` is also accepted. `queryText`
> is treated equivalently to `query`.

### Validation errors

| Condition | Response |
|---|---|
| Body is not valid JSON | 422, `{"error": "invalid JSON body"}` |
| `query` (or `queryResult.queryText`) missing or empty | 422, `{"error": "query required"}` |
| `inquiryID` present but not a string | 422, `{"error": "inquiryID must be string"}` |

---

## 4. Response: Streaming (SSE)

Triggered when the request includes `Accept: text/event-stream`.

### Response headers

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

### Event sequence

Per [W3C Server-Sent Events](https://www.w3.org/TR/eventsource/) framing
(events delimited by blank lines, `data:` payloads, `:` comment lines).

**1. Initial keepalive (always emitted before any data).**
A `: keepalive\n\n` comment line is flushed immediately after the response
headers. Defeats LB idle timeouts before the first model token arrives.

**2. Periodic keepalives during slow generation.**
A `: keepalive\n\n` comment is emitted every 15 seconds while waiting for
model tokens. Safe to ignore on the client side.

**3. Zero or more delta events.**
Each delta carries a chunk of new text — NOT the cumulative transcript.
Concatenate `text` fields in order to reconstruct the reply.

```
data: {"message":{"type":1,"text":"<delta>","streamType":"delta"}}
```

**4. Exactly one terminal event.**
The terminal event has the same shape as a non-streaming JSON response body
(no `streamType` field). The `text` is the full reply.

```
data: {"message":{"type":1,"text":"<full reply>"}}
```

After the terminal event, the server closes the HTTP connection.

### Full wire example

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no

: keepalive

data: {"message":{"type":1,"text":"Hi! ","streamType":"delta"}}

data: {"message":{"type":1,"text":"I rec","streamType":"delta"}}

data: {"message":{"type":1,"text":"eived.","streamType":"delta"}}

data: {"message":{"type":1,"text":"Hi! I received."}}
```

### Mid-stream errors

If generation fails after some deltas have been written, the server **cannot**
change the HTTP status (it is already `200`). Instead, the server emits one
terminal event with an error-text body and closes the connection:

```
data: {"message":{"type":1,"text":"(抱歉,本次未能生成完整回复)"}}
```

For timeouts (see Section 6) the terminal text is:

```
data: {"message":{"type":1,"text":"(超时未生成完整回复)"}}
```

### Truncation on excessive output

If the cumulative reply exceeds 4 MB, the server stops accepting more deltas
mid-stream, then emits a truncated terminal text suffixed with `\n(回复已截断)`:

```
data: {"message":{"type":1,"text":"<truncated text>\n(回复已截断)"}}
```

---

## 5. Response: Non-streaming (JSON)

Triggered when `Accept` does NOT include `text/event-stream`.

### Response

```
HTTP/1.1 200 OK
Content-Type: application/json

{"message":{"type":1,"text":"<full reply>"}}
```

The body shape is identical to the SSE terminal event. Errors during
generation surface differently in the JSON path:

| Condition | Response |
|---|---|
| Successful reply | 200, full reply body |
| Server timeout (120 s reached) | 200, body `{"message":{"type":1,"text":"(超时未生成完整回复)"}}` |
| Hard internal error mid-generation | 500, body `{"error":"internal"}` |

> The streaming path always returns 200 because headers are committed before
> generation starts. The JSON path can return 5xx since headers are deferred.

---

## 6. Concurrency, queueing, and timing

### Per-conversation FIFO

Multiple requests with the **same `inquiryID`** are serialized server-side:
the second request waits for the first to fully complete before generation
starts. This preserves the sticky agent's session state and prevents racy
context pollution.

If too many requests pile up on the same `inquiryID` (default: more than
5 pending after the in-flight one), the server rejects newer requests:

| Condition | Response |
|---|---|
| Same `inquiryID` queue full | 429, body `{"error": "queue full"}` |

Requests with **different `inquiryID`s** (or no `inquiryID`) are independent
and run concurrently.

### Total response time cap

Each turn has a 120 s budget for the full generation pipeline (triage +
KB pre-fetch + model streaming + post-processing). On timeout, the server
emits a terminal SSE event (or returns the timeout JSON body) — see
Sections 4 and 5.

### Service unavailability

| Condition | Response |
|---|---|
| `cc_pool` not initialized (server warming up) | 503, body `{"error": "cc_pool unavailable"}` |
| Endpoint disabled by ops (`GENERAL_BOT_ENABLED=0`) | 503, body `{"error": "general_bot disabled"}` |

Clients SHOULD retry 503 with exponential backoff. 429 SHOULD be retried
after a short delay (or surface "system busy" to the end user).

---

## 7. Limits (mirrors CINNOX spec §8)

| Limit | Value |
|---|---|
| Total response time | 120 seconds |
| Per `data:` event size | 1 MB (model deltas are tiny — never hit in practice) |
| Cumulative reply text | 4 MB (truncation kicks in if exceeded) |

---

## 8. Status code summary

| Status | Meaning | Body |
|---|---|---|
| 200 | Success — JSON or streaming reply on the wire | `{"message":{"type":1,"text":"..."}}` (JSON) or SSE event sequence |
| 401 | Auth or tenant rejection (no oracle between them) | `{"error":"unauthorized"}` |
| 422 | Request body malformed or missing required field | `{"error":"<reason>"}` |
| 429 | Same-`inquiryID` queue full | `{"error":"queue full"}` |
| 500 | Hard internal error mid-JSON-generation | `{"error":"internal"}` |
| 503 | Service unavailable (warming up or disabled) | `{"error":"<reason>"}` |

---

## 9. Configuration in CINNOX admin UI

Per CINNOX **General Chatbot** configuration:

| Field | Value |
|---|---|
| Source type | `General Chatbot` |
| URL | `https://<your-deployment-host>/chat/<your-tenant-id>` |
| Method | `POST` |
| httpHeaders (JSON) | `{"Accept": "text/event-stream", "Authorization": "Bearer <your-api-key>"}` |

Remove `Accept: text/event-stream` from `httpHeaders` (or set it to
`application/json`) to fall back to the JSON response path.

---

## 10. Testing

Verify the endpoint with `curl` before going live in CINNOX.

### JSON path

```bash
curl -s -X POST "https://<your-deployment-host>/chat/<tenant_id>" \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"query":"hello","inquiryID":"smoke-001"}'
```

Expected:

```json
{"message":{"type":1,"text":"<full reply>"}}
```

### Streaming path

```bash
curl -N -X POST "https://<your-deployment-host>/chat/<tenant_id>" \
  -H "Authorization: Bearer <api_key>" \
  -H "Accept: text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"query":"hello","inquiryID":"smoke-002"}'
```

Expected output (the events should appear progressively, NOT all at the end):

```
: keepalive

data: {"message":{"type":1,"text":"Hi","streamType":"delta"}}

data: {"message":{"type":1,"text":"!","streamType":"delta"}}

data: {"message":{"type":1,"text":"Hi!"}}
```

If all events arrive simultaneously at the end, your client (or an
intermediate proxy) is buffering — check the response headers
include `X-Accel-Buffering: no` and that no upstream proxy enables
`proxy_buffering`.

### Authentication failure

```bash
curl -i -X POST "https://<your-deployment-host>/chat/<tenant_id>" \
  -H "Authorization: Bearer wrong-key" \
  -H "Content-Type: application/json" \
  -d '{"query":"hello"}'
```

Expected:

```
HTTP/1.1 401 Unauthorized
Content-Type: application/json

{"error":"unauthorized"}
```

---

## 11. Multi-turn conversation example

Two consecutive requests with the same `inquiryID` continue the same session;
the bot has access to prior turns.

**Turn 1:**

```bash
curl -N -X POST "https://<your-deployment-host>/chat/<tenant_id>" \
  -H "Authorization: Bearer <api_key>" \
  -H "Accept: text/event-stream" \
  -d '{"query":"My order is #1234","inquiryID":"customer-alice"}'
```

**Turn 2** (same `inquiryID`):

```bash
curl -N -X POST "https://<your-deployment-host>/chat/<tenant_id>" \
  -H "Authorization: Bearer <api_key>" \
  -H "Accept: text/event-stream" \
  -d '{"query":"What is its status?","inquiryID":"customer-alice"}'
```

The bot's reply to Turn 2 will reference order `#1234` from Turn 1's
context — no need for the client to repeat it.

---

## 12. FAQ

**Q: Why does the SSE stream sometimes start with a `: keepalive` comment
before any `data:` event?**

A: It's a load-balancer-defeat. Some LBs close idle connections after
5–30 s; if the model takes 5 s to produce its first token, the LB would
already have closed the connection. The pre-data keepalive ensures the
TCP socket has bytes within milliseconds.

**Q: What happens if my client disconnects mid-stream?**

A: The server detects the disconnect and stops emitting further events
(though the in-flight model call may continue briefly until it naturally
terminates or hits the 120 s cap). Subsequent requests on the same
`inquiryID` will queue normally.

**Q: Can I send `type=5` advanced messages (tables, buttons, cards)?**

A: Not on the SSE path. CINNOX spec §3.2 restricts SSE to `type=1` (text).
Advanced messages would need to use the non-streaming JSON path with the
appropriate body shape — but the AutoService General Bot v1 only emits
`type=1` text replies on either path.

**Q: How do I know if the conversation has ended?**

A: AutoService does not currently emit an explicit "session closed" signal.
The bot will simply stop receiving new messages on a given `inquiryID`.
If you need to free server-side state explicitly, contact the AutoService
admin team — there is no public end-session API in v1.

**Q: Does the bot support file attachments?**

A: Not in v1. The `query` field is text only.

**Q: What happens if the same `inquiryID` is reused weeks later?**

A: The server may have garbage-collected the conversation by then. The
behavior is identical to a brand-new `inquiryID`: a fresh session starts
with no carry-over context. Plan accordingly if you rely on long-term
memory.

---

## 13. Reference

- CINNOX General Chatbot Streaming Message (SSE) API contract this implementation follows:
  [docs/General-Bot-Streaming-Message(SSE)-API_20260427.md](../General-Bot-Streaming-Message(SSE)-API_20260427.md)
- W3C SSE spec: https://www.w3.org/TR/eventsource/

For integration support, contact the AutoService admin team.
