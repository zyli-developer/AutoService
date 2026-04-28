# CINNOX Bot Integration — AutoService

This guide tells you exactly how to wire up your CINNOX General Chatbot
to the AutoService bot endpoint. End-user messages your CINNOX deployment
collects will be forwarded to AutoService, which streams the bot reply
back over SSE (or returns a single JSON response, your choice).

---

## 1. Endpoint

```
POST https://autoservice.ezagent.chat/chat/cinnox
```

This is **the** URL — one URL, fixed forever. Configure it once on the
CINNOX side and forget about it.

---

## 2. Authentication

Every request must carry a Bearer API key in the `Authorization` header:

```
Authorization: Bearer <api_key>
```

The API key is provided to you out-of-band by AutoService. Treat it as a
secret — anyone with this key can post messages to your bot. We store
only its hash; if the key is lost, request a new one (the old key cannot
be recovered).

> Failed authentication returns `401 {"error":"unauthorized"}`. The same
> body is returned for all auth-failure cases (missing key, wrong key,
> revoked key) — there is no way to probe whether a tenant exists from
> the response shape.

---

## 3. Configure CINNOX admin UI

Per CINNOX **General Chatbot** configuration:

| Field | Value |
|---|---|
| Source type | `General Chatbot` |
| URL | `https://autoservice.ezagent.chat/chat/cinnox` |
| Method | `POST` |
| httpHeaders (JSON) | `{"Accept": "text/event-stream", "Authorization": "Bearer <api_key>"}` |

To switch off SSE streaming (and receive the full reply as a single JSON
response), drop `Accept: text/event-stream` from `httpHeaders`. Everything
else stays the same.

---

## 4. Request body

CINNOX will POST this shape (matches CINNOX spec §3.1):

```json
{
  "query": "<user message text>",
  "queryParams": { "...": "..." },
  "inquiryID": "<inquiry id>",
  "action": "input.unknown"
}
```

| Field | Required | Notes |
|---|---|---|
| `query` | yes | The end-user's message text. Empty/whitespace-only → 422. |
| `queryParams` | no | Pass-through map. Reserved for future use. |
| `inquiryID` | no | When present, marks the conversation. **Two requests with the same `inquiryID` continue the same multi-turn session** — the bot remembers prior turns. When absent, each request is a one-shot (no memory). |
| `action` | no | Always `"input.unknown"` for standard messages. |

The legacy shape `{"queryResult": {"queryText": "..."}}` is also accepted
for older CINNOX deployments.

---

## 5. Response — Streaming (SSE)

Triggered by `Accept: text/event-stream`.

### Headers

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

### Event sequence

The first thing on the wire is always a `: keepalive\n\n` comment line —
this is sent immediately to defeat load-balancer idle timeouts. Ignore it
on the client side. After that, zero or more delta events with the new
text chunk:

```
data: {"message":{"type":1,"text":"<chunk>","streamType":"delta"}}
```

Concatenate the `text` fields **in order** to reconstruct the reply. The
`streamType: "delta"` field marks progressive chunks.

Finally, exactly one **terminal** event with the full reply (and **no**
`streamType` field):

```
data: {"message":{"type":1,"text":"<full reply>"}}
```

After the terminal event, the server closes the connection.

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

If generation fails after some deltas have already been sent, the HTTP
status is already `200` and cannot be changed. The server emits one
final terminal event with an error message and closes:

```
data: {"message":{"type":1,"text":"(Sorry, the reply could not be completed.)"}}
```

For timeouts (see §7):

```
data: {"message":{"type":1,"text":"(Timed out before the reply could be completed.)"}}
```

For replies exceeding the 4 MB cap, the server emits a truncated
terminal text suffixed with `\n(reply truncated)`.

---

## 6. Response — Non-streaming (JSON)

Triggered when `Accept` does NOT include `text/event-stream`.

### Headers + body

```
HTTP/1.1 200 OK
Content-Type: application/json

{"message":{"type":1,"text":"<full reply>"}}
```

| Condition | Status | Body |
|---|---|---|
| Successful reply | 200 | full reply |
| Server timeout (120 s reached) | 200 | `{"message":{"type":1,"text":"(Timed out before the reply could be completed.)"}}` |
| Hard internal error mid-generation | 500 | `{"error":"internal"}` |

(SSE always returns 200 — once the response headers go out, the status
is committed and only a terminal event can signal failure.)

---

## 7. Limits and timing

| Limit | Value |
|---|---|
| Total response time | **120 seconds** per turn |
| Cumulative reply text | **4 MB** (truncation kicks in if exceeded) |
| Per-event size | 1 MB (model deltas are tiny — never hit in practice) |
| Same-`inquiryID` queue depth | 5 pending after the in-flight one |

### Per-conversation FIFO

Multiple requests with the **same `inquiryID`** are serialized server-side:
the second request waits for the first to fully complete before the bot
starts generating its second reply. This preserves session state.

Requests with **different `inquiryID`s** (or no `inquiryID`) run
concurrently with no coordination.

If too many requests pile up on the same `inquiryID`, the server rejects
newer requests with **`429 {"error":"queue full"}`**. Retry after a short
delay or surface "system busy" to the end user.

---

## 8. Status codes

| Status | Meaning | Body |
|---|---|---|
| 200 | Success — reply on the wire (JSON or SSE) | `{"message":{"type":1,"text":"..."}}` or SSE event sequence |
| 401 | Auth failure (or unknown tenant — same body) | `{"error":"unauthorized"}` |
| 422 | Request body malformed | `{"error":"<reason>"}` |
| 429 | Same-`inquiryID` queue full | `{"error":"queue full"}` |
| 500 | Hard internal error mid-JSON-generation | `{"error":"internal"}` |
| 503 | Service unavailable (warming up or temporarily disabled) | `{"error":"<reason>"}` |

Clients **should** retry 503 with exponential backoff. 429 should be
retried after a short delay.

---

## 9. Smoke tests

### JSON path

```bash
curl -s -X POST "https://autoservice.ezagent.chat/chat/cinnox" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"hello","inquiryID":"smoke-001"}'
```

Expected:

```json
{"message":{"type":1,"text":"<full reply>"}}
```

### Streaming path

```bash
curl -N -X POST "https://autoservice.ezagent.chat/chat/cinnox" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Accept: text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"query":"hello","inquiryID":"smoke-002"}'
```

Expected (events should appear progressively, **NOT** all at the end):

```
: keepalive

data: {"message":{"type":1,"text":"Hi","streamType":"delta"}}

data: {"message":{"type":1,"text":"!","streamType":"delta"}}

data: {"message":{"type":1,"text":"Hi!"}}
```

If all events arrive simultaneously after the request finishes, your
client (or an intermediate proxy) is buffering. Verify the response
headers include `X-Accel-Buffering: no` and that no upstream proxy
enables `proxy_buffering`.

### Authentication failure

```bash
curl -i -X POST "https://autoservice.ezagent.chat/chat/cinnox" \
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

## 10. Multi-turn conversation example

Two consecutive requests with the **same `inquiryID`** continue the same
session. The bot has access to prior turns.

**Turn 1:**

```bash
curl -N -X POST "https://autoservice.ezagent.chat/chat/cinnox" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Accept: text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"query":"My order is #1234","inquiryID":"customer-alice"}'
```

**Turn 2** (same `inquiryID`):

```bash
curl -N -X POST "https://autoservice.ezagent.chat/chat/cinnox" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Accept: text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"query":"What is its status?","inquiryID":"customer-alice"}'
```

The bot's reply to Turn 2 will reference order `#1234` from Turn 1's
context — your client doesn't need to repeat it.

---

## 11. FAQ

**Q: Why does the SSE stream sometimes start with a `: keepalive` comment
before any `data:` event?**

A: Load-balancer-defeat. Some LBs close idle connections after 5–30 s; if
the model takes 5 s to produce its first token, the LB would drop the
connection. The pre-data keepalive ensures TCP bytes flow within
milliseconds of the response headers.

**Q: What happens if the client disconnects mid-stream?**

A: The server detects the disconnect and stops emitting further events.
Subsequent requests on the same `inquiryID` queue normally.

**Q: Can the bot send `type=5` rich messages (tables, buttons, cards)?**

A: Not in this version. Both SSE and JSON paths emit `type=1` text only.
Rich messages would require a future protocol upgrade.

**Q: How do I end a session explicitly?**

A: There is no end-session API. The server cleans up sessions
automatically based on inactivity. Long-idle `inquiryID`s may have their
context garbage-collected; if you reuse such an ID much later, behavior
is identical to a fresh `inquiryID` (no carry-over context).

**Q: Does the bot handle file attachments?**

A: Not in this version. The `query` field is text only.

**Q: What's the max length of a reply?**

A: 4 MB cumulative. Beyond that, the reply is truncated server-side and
the client receives `(reply truncated)` as the final suffix. In practice replies
are much shorter (a few KB at most).

**Q: How do I rotate the API key?**

A: Contact AutoService and request a new key. After we issue the new
key, swap it into the CINNOX admin UI's `httpHeaders` field. Once
verified, ask AutoService to revoke the old key.

---

## 12. Reference

This implementation follows the CINNOX **General Chatbot Streaming
Message (SSE) API** specification. All deltas, terminal events, and
keepalive comments conform to W3C Server-Sent Events framing.

For integration support, contact your AutoService account representative.
