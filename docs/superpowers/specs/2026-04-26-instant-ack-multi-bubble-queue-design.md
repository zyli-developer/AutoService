# Instant Ack + Multi-Bubble + CC-Queue — Design

**Date**: 2026-04-26 · **Author**: brainstorm session (allen.woods@outlook.com + Claude) · **Status**: DRAFT (pending review)

## 1. Goal

Bring the `/site/` (currently only `cinnox` tenant) customer chat closer to a "real human assistant" feel by combining three independent mechanisms:

- **A. Pre-triage instant ack** — a soothing acknowledgement bubble (~200ms) emitted before triage runs, so the user never stares at silence after pressing Enter.
- **B. Multi-bubble paragraph splitter** — agent's reply is split on paragraph boundaries (`\n\n`) into multiple distinct bubbles, mimicking how a real CSR types one short message at a time.
- **C. CC-style queue serialization** — when a new customer message arrives while an agent reply is in flight, it is queued (not interrupted, not merged), and processed strictly serially after the current turn completes.

These three are independent on the wire but combine into a unified UX that feels asynchronous, attentive, and human-paced.

## 2. Current state (2026-04-26 baseline)

### 2.1 Existing soothe placeholder system

The repo already has a soothe placeholder system, **currently disabled in production via `PLACEHOLDER_ENABLED=0` in `~/Library/LaunchAgents/com.autoservice.gateway.plist`** (set on 2026-04-25 because the inline-edit replacement felt stiff to product). Its mechanics:

- `_drain_with_placeholder()` in [`autoservice/gateway/message_router.py`](../../../autoservice/gateway/message_router.py:905) wraps the LLM stream call.
- After **triage completes** and the LLM call begins, a 1.0–3.0s timer races the first token. If the timer wins, a placeholder bubble is written via `engine.send_message(metadata={"is_placeholder": True})`.
- When real tokens arrive, the placeholder is **edited in place** via `engine.edit_message` + `message_edited` frames — same bubble, content morphs from soothe text to final answer.
- `SoothePicker` ([`autoservice/gateway/soothe_picker.py`](../../../autoservice/gateway/soothe_picker.py)) chooses the placeholder text by `(intent, lang)`; intent comes from the triage step.
- Spec: [`docs/superpowers/specs/2026-04-23-soothe-placeholder-design.md`](2026-04-23-soothe-placeholder-design.md).

**Two structural problems with the existing system that this spec fixes:**

1. The placeholder fires *after* triage (typically 0.5–4s in), not on user submit. So the "dead window" between Enter and any feedback is still long.
2. The placeholder *is* the final reply (in-place edit). The user sees one bubble whose text morphs from "正在查询" into the real answer — felt to product as visually jarring and unlike real chat.

### 2.2 Existing message routing

- `customer_message` handler at [`message_router.py:491`](../../../autoservice/gateway/message_router.py:491) calls `engine.send_message` synchronously, then **fires-and-forgets** `_generate_agent_reply` via `asyncio.create_task` with name `agent-reply-{conv_id}`.
- **No deduplication on the customer-message path.** Two rapid `customer_message` frames spawn two parallel reply tasks; replies arrive out of order. The existing dedup at `_trigger_ai_reply_if_pending` is only used by operator `/release` and `operator-SIDE` paths.
- Frontend ([`frontend/apps/customer-chat/src/`](../../../frontend/apps/customer-chat/src/)) already renders a sequence of `message` frames as separate bubbles — multi-bubble rendering is essentially free on the FE side.

### 2.3 Stream protocol already supports bubble boundaries

`_drain_with_placeholder` already parses `claude_agent_sdk.types.StreamEvent` events of type `content_block_delta` / `text_delta` ([`message_router.py:1061-1083`](../../../autoservice/gateway/message_router.py:1061)). The existing typewriter effect uses `message_edited` frames pushed at ≤12fps. The infrastructure to detect mid-stream paragraph boundaries on the accumulated `reply_text` is already in place.

## 3. Target UX

A concrete sequence (timestamps relative to user pressing Enter on the first message):

```
[t=0]      USER       : "你好"
[t=200ms]  AGENT (ack): "好的，让我帮你看看 👋"          ← A: pre-triage ack, instant
[t=2.0s]   AGENT      : "你好！欢迎来到 Cinnox。"        ← LLM reply, segment 1 of 3
[t=2.4s]   AGENT      : "我们的定价从 $50/月起。"        ← segment 2 (split on \n\n)
[t=2.7s]   AGENT      : "需要联系销售吗？"               ← segment 3, end of stream

[t=3.5s]   USER       : "可以，我邮箱是 abc@x.com"
                       — agent reply task in flight? No, finished. Process immediately.
[t=3.7s]   AGENT (ack): "收到，正在处理..."              ← A again, fresh turn
[t=5.5s]   AGENT      : "已记录！销售会在 24 小时内联系您。"

[t=8.0s]   USER       : "另外，支持中文吗?"             ← previous turn already finished, processed immediately
[t=8.2s]   AGENT (ack): "嗯，让我想想"                  ← ack for the "支持中文" turn
[t=8.4s]   USER       : "团队规模多大？"                ← arrives mid-stream → queued (C-X)
[t=10.0s]  AGENT      : "支持中文客服，团队会..."        ← reply to "支持中文" finishes
[t=10.1s]  AGENT (ack): "好的"                         ← queued msg now starts its own turn
[t=11.5s]  AGENT      : "我们目前有 30+ 工程师..."      ← reply to "团队规模"
```

The key invariant: **between `t=8.4s` and `t=10.0s`, the user's "团队规模" message is acknowledged by `engine.send_message` (so it shows in their chat history immediately) but no agent reply task starts for it until the prior turn fully completes.**

**The three mechanisms in this story:**
- A appears at every `t+200ms` after a user message, regardless of whether triage has decided anything.
- B splits the long reply into 3 bubbles instead of one.
- C queues the second mid-stream message until the first agent turn is fully done.

## 4. Architecture (Route 3 — hybrid)

### 4.1 New files

| Path | Purpose | Approx LOC |
|------|---------|-----------|
| `autoservice/gateway/agent_ack.py` | Pre-triage ack: text bank + send | ~60 |
| `autoservice/gateway/paragraph_splitter.py` | Pure-function streaming splitter | ~120 |
| `autoservice/gateway/turn_queue.py` | Per-conv asyncio.Lock + pending FIFO | ~80 |
| `autoservice/gateway/ack_templates.yaml` | Pre-triage ack lines (zh/en) | ~30 |
| `tests/gateway/test_paragraph_splitter.py` | Unit tests for splitter | ~200 |
| `tests/gateway/test_agent_ack.py` | Unit tests for ack | ~80 |
| `tests/gateway/test_turn_queue.py` | Concurrency tests for queue | ~120 |

### 4.2 Modified files

| Path | Change | Approx LOC |
|------|--------|-----------|
| `autoservice/gateway/message_router.py` | Replace `_drain_with_placeholder` body with multi-bubble drain; integrate `agent_ack` + `turn_queue`; remove in-place-edit placeholder path | ~+80 / -120 |
| `~/Library/LaunchAgents/com.autoservice.gateway.plist` | Set `PLACEHOLDER_ENABLED=1` (kept for backward-compat env var); add `MULTI_BUBBLE_ENABLED=1` | env-only |

### 4.3 Data flow (single turn)

```
user message arrives at WS
   │
   ▼
message_router.handle_customer_message()
   │
   ├─ engine.send_message(customer)               # persist user msg
   ├─ broadcast to operator squad
   │
   ▼
TurnQueue.enqueue(conv_id, customer_text, ws)
   │  (acquires per-conv lock; if already held, just appends to FIFO and returns)
   │
   ▼  (new fire-and-forget task — only one per conv at a time)
_run_agent_turn(conv_id, customer_text, ws):
   │
   ├─ agent_ack.send_pretriage_ack(engine, conv_id, ws, lang_hint)
   │     │
   │     ▼
   │   engine.send_message(agent, content=ack_text, metadata={"is_ack": True})
   │   ws.send_json(message frame)
   │   broadcast to squad
   │
   ├─ triage_and_route(...) → TriageDecision
   │
   ├─ pool.acquire(role).query(...)
   │
   ▼
_drain_into_bubbles(stream, ws):
   │  • feed chunks into ParagraphSplitter
   │  • on segment boundary:
   │     - persist Message via engine.send_message (separate DB row)
   │     - push `message` frame to ws + squad
   │     - reset accumulator for next segment
   │  • on stream end:
   │     - flush remaining accumulator as final segment
   │
   ▼
turn finishes — TurnQueue releases lock
   │
   ▼ (in finally block)
if FIFO non-empty: pop next, kick off another _run_agent_turn task
```

## 5. Pre-triage ack (`agent_ack.py`)

### 5.1 Behavior

- Emitted **before triage_and_route runs**, with a small jitter delay of 150–350ms (uniform random) — instant feels robotic, ~250ms feels human.
- Lang detected via a 5-line regex on customer_text (`一-鿿` → zh else en) — not a full lang model.
- Text picked uniformly at random from a per-lang static bank in `ack_templates.yaml`. No intent dependency (intent isn't known yet).
- Persisted as a normal agent `Message` with `metadata={"is_ack": True}` so downstream filters / analytics can identify it. Visible in chat history; **no edit-in-place** later.

### 5.2 Templates (initial bank)

`autoservice/gateway/ack_templates.yaml`:

```yaml
zh:
  - "好的，让我帮你看看 👋"
  - "收到，请稍等"
  - "马上为你查询..."
  - "好的，正在处理"
  - "嗯，让我想想"
en:
  - "Sure, let me check that for you 👋"
  - "Got it, one moment..."
  - "On it!"
  - "Let me look into this..."
  - "Hmm, give me a second"
```

Tunable per tenant later (out of scope for this spec).

### 5.3 API

```python
# autoservice/gateway/agent_ack.py
async def send_pretriage_ack(
    engine: ConversationEngine,
    conv_id: str,
    ws: WebSocket,
    customer_text: str,
    delay_range_ms: tuple[int, int] = (150, 350),
) -> Message:
    """Emit a pre-triage acknowledgement bubble.

    Returns the persisted Message so the caller can reference it (e.g.
    for sequence_number ordering in tests). Errors are logged but do not
    raise — the main reply pipeline must not break because the ack
    failed.
    """
```

### 5.4 Failure isolation

If `engine.send_message` fails or the WS push raises, log and swallow. The main reply pipeline must not be aborted because of an ack failure.

## 6. Paragraph splitter (`paragraph_splitter.py`)

### 6.1 Behavior

A pure-function streaming state machine. Consumes text chunks (from `content_block_delta` text_delta) and emits **completed segments** when boundary conditions are met.

**Boundary**: `\n\n` (two consecutive line feeds) **outside of fenced code blocks**.

**Fenced code blocks**: a triple-backtick at the start of a line (after optional `\n`) toggles "in code block" state. While inside, `\n\n` does NOT split. The code-block fence itself terminates as soon as the matching closing triple-backtick is seen.

**Trim**: each emitted segment has its trailing `\n\n` stripped, but internal whitespace and code blocks are preserved verbatim.

**Min segment length**: configurable (`MIN_SEGMENT_CHARS = 5`). If a `\n\n` is hit and the would-be-emitted segment is shorter than 5 characters (e.g. an LLM emitting `\n\n` early by mistake), the splitter accumulates more before emitting. Prevents single-emoji-per-bubble ridiculousness.

**Max segments per turn**: configurable (`MAX_SEGMENTS_PER_TURN = 5`). After 4 emissions, all remaining chunks accumulate into the final segment. Prevents a runaway LLM from emitting 30 bubbles for one question.

**Final flush**: when the stream signals end-of-text, the remaining accumulator (whatever is left, possibly with no trailing `\n\n`) is emitted as the last segment.

### 6.2 API

```python
# autoservice/gateway/paragraph_splitter.py
class ParagraphSplitter:
    def __init__(
        self,
        min_segment_chars: int = 5,
        max_segments: int = 5,
    ) -> None: ...

    def feed(self, chunk: str) -> list[str]:
        """Feed a token chunk. Returns 0 or more completed segments
        (rare to return >1 from a single small chunk, but possible on
        LLM bursts)."""

    def flush(self) -> str | None:
        """Call at end-of-stream. Returns the final pending segment
        (None if nothing buffered or only whitespace)."""

    @property
    def segment_count(self) -> int:
        """How many segments have been emitted so far (incl. flush)."""
```

### 6.3 State machine (visual)

```
state: NORMAL
  on chunk:
    accumulate; if "\n\n" found and not in code block and len >= min:
      emit segment, reset accumulator
    if "```" found at line start:
      transition CODE
state: CODE
  on chunk:
    accumulate (never emit)
    if matching "```" found at line start:
      transition NORMAL
on flush:
  emit remaining accumulator (regardless of state, never split)
```

### 6.4 Edge cases (test-pinned)

- LLM emits whole reply as one paragraph (no `\n\n`) → 1 segment via flush.
- LLM emits `\n\n\n\n\n\n` (multiple boundaries with empty text between) → only non-empty segments emitted; consecutive empty boundaries collapse.
- LLM emits a code block with `\n\n` inside ` ``` ` → not split.
- LLM hits MAX_SEGMENTS — chunk 6, 7, 8... all accumulate into final segment.
- LLM emits `\n\n` after only 2 chars (e.g. "好。\n\nHere is..."). The "好。" segment is below `MIN_SEGMENT_CHARS=5`, so accumulate; eventually emits "好。Here is..." as one segment OR splits at the next valid boundary. **Accept this** — small fragments shouldn't bubble independently.

### 6.5 LLM prompt nudge

Append a small bilingual suffix to the system prompt at the **cc_pool acquire site** (not by editing soul `.md` files). Concretely: in `autoservice/cc_pool.py` where `system_prompt = _load_soul(...)` resolves the role soul, append a constant suffix string when `MULTI_BUBBLE_ENABLED=1` and `role in {"customer", "lead"}`:

```
当回复较长时，请用空行（两个换行）将不同要点分段，让用户更容易阅读。每段保持 1-3 句话即可。
For longer replies, use a blank line (two newlines) to separate distinct points so the customer can read easily. Keep each paragraph to 1-3 sentences.
```

Doing this at acquire time (not in the soul file) means: (a) tenant-customized souls don't need updating; (b) the nudge can be feature-gated; (c) deprecating it later is a single deletion.

This is a **soft** hint — the splitter must work even if the LLM ignores it (degrades to 1 bubble per turn, which is acceptable).

## 7. Turn queue (`turn_queue.py`)

### 7.1 Behavior

CC-X (queue) semantics:

- One in-flight reply task per conversation.
- New `customer_message` while in-flight → message persisted normally, queued for processing **after the current turn fully completes** (final segment flushed, all bubbles persisted and pushed).
- No interrupt, no merge: the in-flight reply runs to completion, untouched.
- Strict FIFO order.

### 7.2 Queue depth handling

Soft cap: `MAX_QUEUE_DEPTH = 5`. If a 6th message arrives while 5 are queued and one is in flight, the 6th is **rejected at the protocol level** with an error frame:

```
{type: "error", payload: {code: "QUEUE_FULL", message: "Too many pending messages, please wait."}}
```

Hard cap exists to prevent abusive spam DoS. 5 is a reasonable upper bound for any human-paced burst.

### 7.3 Frontend indicator (optional polish, low priority)

When user sends a message and a reply is in flight, FE could show "(N queued)" near the input box. Out of scope for the first cut — may add as a follow-up.

### 7.4 API

```python
# autoservice/gateway/turn_queue.py
class TurnQueue:
    """Per-conversation FIFO + lock for serialized agent reply turns."""

    def __init__(self) -> None: ...

    async def submit(
        self,
        conv_id: str,
        runner: Callable[[], Awaitable[None]],
    ) -> None:
        """Submit a runner coroutine. If no in-flight task for this
        conv, runs immediately. Otherwise appends to FIFO. Always
        returns immediately — does not await runner completion."""

    def queue_depth(self, conv_id: str) -> int:
        """Number of pending (not-yet-in-flight) runners. 0 if conv
        has no pending state."""
```

The `runner` is the closure that does `agent_ack → triage → pool.acquire → drain_into_bubbles`. The queue doesn't know about the inner mechanics; it just guarantees serialization.

### 7.5 Cleanup

Per-conv state (lock + FIFO) is auto-cleaned when conv has no in-flight + empty FIFO. Use `weakref` or a TTL sweep to avoid memory leak from dead conversations. **Use weakref-style sentinel**: when finally block sees lock + empty FIFO, `_state.pop(conv_id, None)`.

## 8. Replacing the existing placeholder mechanism

The existing `_drain_with_placeholder` and its in-place-edit semantics are **deleted**, not gated. Reasons:

- The pre-triage ack supersedes the post-triage placeholder (always emits earlier, regardless of how slow the LLM is).
- `is_placeholder` metadata + `message_edited` editing of placeholder content was a workaround for "we don't know if we'll be slow"; with always-on ack + always-on streaming bubbles, that uncertainty is gone.
- Keeping both code paths invites bugs and confusion.

**What's preserved**:

- The `message_edited` typewriter mechanism — re-purposed for **within-bubble** typewriter (see §9.2).
- `SoothePicker` — kept *temporarily* but no longer wired into the main path. Marked deprecated; can be deleted in a follow-up cleanup PR (and `soothe_templates.yaml` with it).
- `PLACEHOLDER_ENABLED` env var — re-interpreted as "instant ack enabled". `0` disables `agent_ack.send_pretriage_ack` entirely; `1` (default) enables. Reusing the var means one fewer plist edit.
- `SOOTHE_PLACEHOLDER_ENABLED` env var — silently ignored (deprecated, no effect).

## 9. Persistence model

### 9.1 Each bubble is a real `Message` row

Every emitted segment is `engine.send_message(agent, content=segment_text, metadata={"is_segment": True, "segment_index": i})`. This means:

- Conversation history shows the bubbles as distinct messages (with `sequence_number` ordering).
- Operator console / admin replay see them as distinct.
- Edit history and CSAT analytics work normally.

The pre-triage ack is similarly a Message with `metadata={"is_ack": True}`.

**Implication for sequence_number**: a single user turn now produces 1 ack + N segments = N+1 agent messages in history. CSAT / SLA queries that count "agent replies" need to be aware (filter on metadata if they need "primary reply count"). Existing SLA queries in `autoservice/sla_aggregator.py` count by `MetricType.ACCEPT_MS`, not by message count, so no change needed there.

### 9.2 Within-bubble typewriter

Each bubble grows token-by-token via the existing `message_edited` machinery, until the next `\n\n` boundary closes it. After close, the next bubble opens with the next chunk. So:

```
t+200ms:  message     {bubble_1: "好"}              ← first token of segment 1
t+250ms:  message_edited {bubble_1: "好的"}           ← typewriter
t+400ms:  message_edited {bubble_1: "好的，让我"}     ← typewriter
t+600ms:  message_edited {bubble_1: "好的，让我想想"} ← typewriter (final form before \n\n)
t+700ms:  ← LLM emits "\n\n", splitter closes bubble_1, opens bubble_2
t+750ms:  message     {bubble_2: "我"}              ← first token of segment 2
...
```

This preserves the ChatGPT-style fill-in for the *first* bubble (bubble_1's growth), and each subsequent bubble also fills in.

### 9.3 Bubble persistence ordering

Critical invariant: **persist first via `engine.send_message`, then push the WS frame.** Doing it in the reverse order is wrong because a frame would reference a `message_id` that doesn't exist yet — e.g. an operator console reloading history right after the frame arrives would 404.

Implementation order in `_drain_into_bubbles`:
```
1. msg = await engine.send_message(agent, content=segment_text, metadata=...)
2. await ws.send_json(_message_frame(msg))
3. await _broadcast_to_squad(_message_frame(msg), conv_id, exclude_ws=ws)
```

## 10. Frontend impact

**Minimal** — the customer-chat SPA already renders `messages: Message[]` as a flat array of bubbles. Multi-bubble support comes for free.

**Removed**:
- The frontend's "is_placeholder + edit content in place" rendering branch (if any) — no longer triggered, but harmless if dead code stays. Audit and remove in the same PR.

**Added (optional / follow-up)**:
- "(N queued)" indicator near input box when `queue_depth > 0`. Out of scope for first cut.

**Verified to work without change**:
- `useChatStore.addMessage` — unchanged
- `useChatStore.updateMessage` (used for `message_edited`) — unchanged, used for within-bubble typewriter
- `MessageList.tsx` — already iterates messages and renders each as a bubble

## 11. Configuration / kill switches

| Env var | Default | Effect |
|---------|---------|--------|
| `PLACEHOLDER_ENABLED` | `1` | **Semantically repurposed** by this spec. Previously gated the post-triage 1.5s placeholder; now gates the pre-triage instant ack (§5). When `0`, `agent_ack.send_pretriage_ack` is a no-op. The main reply pipeline still runs and emits segmented bubbles. The deprecated post-triage placeholder is removed regardless of this flag. |
| `MULTI_BUBBLE_ENABLED` | `1` | When `0`, splitter is bypassed: the entire reply is emitted as one bubble (legacy single-bubble behavior). |
| `QUEUE_ENABLED` | `1` | When `0`, falls back to current "fire-and-forget per-message" behavior (concurrent reply tasks, possible interleaving). |
| `ACK_DELAY_MIN_MS` | `150` | Pre-triage ack jitter floor. |
| `ACK_DELAY_MAX_MS` | `350` | Pre-triage ack jitter ceiling. |
| `PARAGRAPH_MIN_CHARS` | `5` | Splitter `MIN_SEGMENT_CHARS`. |
| `PARAGRAPH_MAX_SEGMENTS` | `5` | Splitter `MAX_SEGMENTS_PER_TURN`. |
| `QUEUE_MAX_DEPTH` | `5` | TurnQueue soft cap. |

All kill switches are independent — a deploy can roll back A, B, or C in isolation.

The launchd plist needs `PLACEHOLDER_ENABLED=1` set (currently `0`); the others default-on without explicit declaration.

## 12. Test plan

### 12.1 Unit tests

**`tests/gateway/test_paragraph_splitter.py`** (~10-15 cases):
- Empty input → no segments, flush returns None
- Single-paragraph reply (no `\n\n`) → 1 segment via flush
- Two-paragraph (`A\n\nB`) → 2 segments
- Three-paragraph → 3 segments
- Code block containing `\n\n` → not split
- Multiple code blocks
- Min-length suppression (small fragment accumulates)
- Max-segment cap (6 paragraphs, only 5 emit, 6th merges into 5th)
- Streaming chunk boundaries fall inside `\n\n` ("`A\n`" then "`\nB`") — correctly detected
- Whitespace-only segment (`A\n\n   \n\nB`) — middle segment dropped

**`tests/gateway/test_agent_ack.py`** (~5-8 cases):
- Sends a Message with `metadata.is_ack = True`
- Picks zh template for Chinese customer text
- Picks en template for English customer text
- Random choice covers all bank lines (statistical, multiple iterations)
- Honors `delay_range_ms`
- Engine failure → swallowed, returns None
- WS push failure → swallowed

**`tests/gateway/test_turn_queue.py`** (~6-10 cases):
- Single submit runs immediately
- Two submits while first in flight: second runs after first completes
- Strict FIFO across 5 submits
- Queue depth reported correctly
- Queue full (depth 5 + 1 in flight, 7th submit) raises `QueueFullError`
- Cleanup: empty conv state pruned after queue drains

### 12.2 Integration tests (with real engine, mocked LLM)

**`tests/gateway/test_multi_bubble_integration.py`** (~5 cases):
- End-to-end: customer_message → ack persisted + frame pushed → reply persisted as N segments → all frames received in order
- Within-bubble typewriter: `message_edited` frames arrive between `message` frames for next bubble
- Two rapid `customer_message` frames: only one in-flight at a time (verify timestamps)
- Kill switch `MULTI_BUBBLE_ENABLED=0` → falls back to single bubble (no segmenting)
- Kill switch `PLACEHOLDER_ENABLED=0` → no ack emitted, reply still segmented

### 12.3 E2E (agent-browser, on production)

After deploy, drive `https://autoservice.ezagent.chat/site/?tenant=cinnox` with agent-browser:
- Send a single short message ("你好") → verify ack appears <500ms, then reply (1 or more bubbles)
- Send a complex question that should produce multi-paragraph reply ("你们有什么服务？") → verify multiple bubbles
- Burst-send 3 messages in <1 second → verify replies are processed serially (not interleaved)
- Verify ack text varies across messages (template randomization works)

## 13. Rollout

This is a backend-mainly change with no schema migration. Rollout per environment:

1. **Local**: `make run-web` with default env (kill switches all on). Run integration tests.
2. **Staging** (no separate staging — autoservice.ezagent.chat *is* staging right now): deploy, run E2E, monitor logs for splitter exceptions / queue overflow.
3. **Per-tenant rollback**: each kill switch (PLACEHOLDER_ENABLED, MULTI_BUBBLE_ENABLED, QUEUE_ENABLED) can be flipped independently to disable a piece without redeploy.

## 14. Risks & mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Splitter mis-handles a Markdown / code-fence edge case → reply renders weirdly | Medium | Comprehensive splitter unit tests (§12.1); state machine simple enough to read; degrade-gracefully to single bubble on any internal exception |
| LLM ignores `\n\n` hint → all replies are 1 bubble | High at first | Acceptable degradation; bubble count is "1 or more", never "0"; A still gives the instant-ack win |
| Pre-triage ack fires + triage decides direct-reply (greeting/thanks) → user gets two near-identical bubbles | Medium | Direct-reply is rare on Cinnox traffic; if it happens, the ack is "好的👋", direct-reply is "你好！" — duplicate but harmless. Follow-up: skip ack when triage_dispatch detects direct-reply intent (requires moving ack after triage; out of scope for v1) |
| Queue serialization adds latency for users who want their 2nd message answered ASAP | Low | This is the explicit design choice (CC-X). User chose it knowingly. |
| Per-conv lock memory leak if cleanup fails | Low | `_state.pop(conv_id)` in finally; weak references could be added in a follow-up |
| Existing tests for `_drain_with_placeholder` break | High (intentional) | All replaced with multi-bubble tests; old tests deleted in same PR |

## 15. Implementation checklist (handoff to writing-plans)

The following is the ordered task list this spec hands off to the writing-plans skill:

- [ ] **T1** Implement `paragraph_splitter.py` + unit tests
- [ ] **T2** Implement `agent_ack.py` + `ack_templates.yaml` + unit tests
- [ ] **T3** Implement `turn_queue.py` + unit tests
- [ ] **T4** Refactor `_drain_with_placeholder` → `_drain_into_bubbles` in `message_router.py`; integrate splitter
- [ ] **T5** Wire `agent_ack` and `turn_queue` into `customer_message` handler
- [ ] **T6** Delete old in-place-edit placeholder code path; mark `SoothePicker` deprecated
- [ ] **T7** Add prompt nudge suffix at cc_pool acquire site (not in soul files; see §6.5)
- [ ] **T8** Update launchd plist: `PLACEHOLDER_ENABLED=1`, add `MULTI_BUBBLE_ENABLED=1`, `QUEUE_ENABLED=1`
- [ ] **T9** Integration tests (multi-bubble end-to-end)
- [ ] **T10** Reload gateway, smoke test locally
- [ ] **T11** E2E test on autoservice.ezagent.chat with agent-browser
- [ ] **T12** PR

## 16. Out of scope (explicit)

- Per-tenant tunable ack templates (a follow-up tenant-config PR)
- "(N queued)" frontend indicator (polish; can ship later)
- Cleanup of `SoothePicker` and `soothe_templates.yaml` (deprecate now, delete later)
- Streaming-aware operator-side rendering (operator console already handles multi-message streams)
- B-精简 alternative (collapsed answer = 1 bubble) — explicitly rejected by user

## 17. Appendix — terminology

- **Ack** — the pre-triage acknowledgement bubble (always 1 per turn).
- **Segment / Bubble** — each emitted reply chunk after `\n\n`. A turn produces 1 ack + N segments where N≥1.
- **Turn** — the full agent response to one user message: ack + reply segments.
- **Queue** — the per-conv FIFO holding messages that arrived while a turn was in flight.
