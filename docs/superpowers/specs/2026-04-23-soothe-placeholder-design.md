# Context-Aware Soothe Placeholder — Design

**Date**: 2026-04-23 · **Author**: brainstorm session (hjj.gemini@gmail.com + Claude) · **Status**: DRAFT (pending user review)

## 1. Goal

Replace the generic 1.5s-delayed static placeholder (`"正在为您查询，请稍候..."` / `"Just a moment while I look into this..."`) with a context-aware soothing line selected from a YAML template bank, keyed by the `intent` already produced by `triage_and_route`. Emit the placeholder **immediately** after triage (no 1.5s wait) so users see acknowledgement within ~50ms instead of 1500ms.

## 2. Current state (2026-04-22 baseline)

- Placeholder emission lives in [`autoservice/gateway/message_router.py`](../../../autoservice/gateway/message_router.py) inside `_drain_with_placeholder(...)`.
- `PLACEHOLDER_DELAY_S = 1.5` — race: if first token arrives within 1.5s, no placeholder is sent; otherwise a static bubble is written, later replaced via `message_edited` when the real reply streams in.
- Static text constants: `_PLACEHOLDER_TEXT_ZH` / `_PLACEHOLDER_TEXT_EN`.
- Eligibility gate: `PLACEHOLDER_ELIGIBLE_ROLES = frozenset({"customer", "lead"})`. Fast-tier roles (`translate`, `direct`) skip the placeholder entirely — keep this.
- Frontend ([`channels/web/static/cinnox.html`](../../../channels/web/static/cinnox.html)) already handles the placeholder-then-edit flow via the existing `message` + `message_edited` events; no frontend change required.

## 3. Approach — Approach A: deterministic template bank

Chosen from three candidates (A: template bank / B: realtime haiku / C: template + async haiku rewrite). A delivers the largest UX win (1500ms → ≤50ms) at the smallest blast radius and token cost (0). B/C can be layered on later if template rotation feels stale in production (trigger conditions in §11).

## 4. Architecture

### 4.1 Data flow

```
user message
  ↓
message_router (gateway)
  ↓
triage_and_route → TriageDecision{role, intent, confidence, detected_language, tier, ...}
  ↓
_drain_with_placeholder(..., intent=decision.intent)
  ↓                              (eligible = target_role in {customer, lead})
  ├── soothe_picker.pick(intent, lang)   ← new, <5ms, in-process
  │     ↓ returns SoothePick(template_id, text)
  │     ↓
  │   engine.send_message(placeholder=True, content=text)      ← immediate
  ├── pool.acquire(role=target_role).client.query(...)          ← in parallel
  │     ↓
  │   first token → engine.edit_message(placeholder_msg, content=reply_delta)
  │     ↓
  │   message_edited events stream to frontend (existing mechanism)
```

### 4.2 Components

**New (2)**:
- `autoservice/gateway/soothe_picker.py` — module with `SoothePicker` class, `SoothePick` dataclass, module-level singleton via `get_picker()`
- `autoservice/soothe_templates.yaml` — declarative template bank

**Modified (1)**:
- [`autoservice/gateway/message_router.py`](../../../autoservice/gateway/message_router.py):
  - `_drain_with_placeholder(...)` — new `intent: str | None = None` kwarg; swap static text lookup for `soothe_picker.pick()`
  - Call site (~L1430) — pass `intent=decision.intent`
  - Default `PLACEHOLDER_DELAY_S: 1.5 → 0.0`

**Unchanged (explicit)**:
- [`channels/web/static/cinnox.html`](../../../channels/web/static/cinnox.html) — frontend sees no new event types
- `channels/web/websocket.py` — bridge unchanged
- `autoservice/model_router.py` — `TriageDecision` gets no new fields (no `sentiment`; see §8)
- `autoservice/memory_pool.py` — not read during soothe selection
- `PLACEHOLDER_ELIGIBLE_ROLES` — unchanged (`{customer, lead}`)
- `channels/feishu/` — not touched (per CLAUDE.md "channel feature parity")

## 5. Picker contract

### 5.1 API

```python
# autoservice/gateway/soothe_picker.py

from dataclasses import dataclass
from pathlib import Path
import random

@dataclass(frozen=True)
class SoothePick:
    template_id: str   # for observability
    text: str          # the line to show

class SoothePicker:
    """(intent × lang) → soothe line, YAML-backed, no hot reload."""

    def __init__(
        self,
        templates_path: Path | None = None,
        rng: random.Random | None = None,
    ) -> None: ...

    def pick(self, *, intent: str | None, lang: str | None) -> SoothePick:
        """Fallback order:
        1. (intent, lang)  exact
        2. ("*", lang)     same-language generic
        3. defaults.fallback[lang]   language-level fallback (must exist)
        """

def get_picker() -> SoothePicker: ...   # module-level singleton
```

### 5.2 Load-time validation

Raise `ValueError` during `SoothePicker.__init__` when:
- `defaults.fallback.zh` missing or empty
- `defaults.fallback.en` missing or empty
- Any template's `lines` list is empty

Log `WARNING` (do not raise) when:
- A template's `intent` value is not in [`autoservice/classify_intent.yaml`](../../../autoservice/classify_intent.yaml) — allows staging new intents ahead of the triage classifier.

### 5.3 Runtime safety

Any exception during `pick()` (e.g., unexpected KeyError from a malformed in-memory template map) is caught at the call site in `_drain_with_placeholder`, logged via `log.exception`, and the code falls back to the existing `_PLACEHOLDER_TEXT_ZH / _PLACEHOLDER_TEXT_EN` constants. The picker does no I/O at pick time — templates are already in memory from `__init__`. **`pick()` must never break the main reply pipeline.**

## 6. Template bank schema

**File**: `autoservice/soothe_templates.yaml` (sibling of `classify_intent.yaml`)

```yaml
version: 1

defaults:
  # required per-language fallback; enforced at load time
  fallback:
    zh:
      - "好的，我帮您处理一下…"
      - "收到，正在为您看…"
    en:
      - "Got it, let me take a look…"
      - "Sure, one moment…"

templates:
  - id: complaint_zh
    intent: complaint
    lang: zh
    lines:
      - "非常抱歉给您带来困扰，我这就核实…"
      - "理解您的着急，我马上查原因…"
      - "很抱歉让您不愉快，先看一下状态…"

  - id: complaint_en
    intent: complaint
    lang: en
    lines:
      - "So sorry — let me check that right away…"
      - "That's frustrating, looking into it now…"

  - id: product_inquiry_zh
    intent: product_inquiry
    lang: zh
    lines:
      - "好的，我帮您看看具体功能…"
      - "这个我先确认一下细节…"

  - id: purchase_intent_zh
    intent: purchase_intent
    lang: zh
    lines:
      - "好的，我帮您整理一下方案…"
      - "了解您的需求，正在查…"

  # one block per (intent × lang); see plan for full roster
```

### 6.1 Dimensions

| Dimension | Source of values | Count |
|---|---|---|
| `intent` | intents defined in `classify_intent.yaml` + `"*"` wildcard | 4 intents reach eligible roles: `product_inquiry` / `complaint` (customer+slow), `purchase_intent` (lead+slow), `general_question` (customer+fast). `language_barrier` routes to translate (not eligible); `greeting/thanks/bye` route to direct (not eligible) |
| `lang` | `zh` / `en` | 2 |
| `lines` per entry | 3-5 rotated via `rng.choice` | — |

### 6.2 Initial volume target

~20 template blocks covering ≥80% of observed intent traffic in staging. Sentiment is **not** a schema dimension (see §8).

### 6.3 Authoring guidelines

Template line constraints:

| Rule | Enforcement |
|---|---|
| ≤ 30 characters per line | Contract test (§12) |
| `lang` must be `zh` or `en` | Contract test (§12) |
| No specific promises (numbers, deadlines, "definitely refund") | Code review only |
| No product/competitor names | Code review only |
| Chinese full-width punctuation; English half-width | Code review only |
| End with `…` (not period) to signal "continuing" | Code review only |

## 7. Backend integration diff

### 7.1 `_drain_with_placeholder` signature

```python
async def _drain_with_placeholder(
    ...,
    detected_language: str | None = None,
    eligible: bool = True,
    delay_s: float = PLACEHOLDER_DELAY_S,
    intent: str | None = None,              # NEW
) -> tuple[str, Any | None]:
```

### 7.2 Text-source swap (inside `_drain_with_placeholder`)

```python
# Before
text = _PLACEHOLDER_TEXT_ZH if (detected_language == "zh") else _PLACEHOLDER_TEXT_EN

# After
if SOOTHE_ENABLED:
    try:
        pick = soothe_picker.get_picker().pick(intent=intent, lang=detected_language)
        text = pick.text
        template_id = pick.template_id
    except Exception:
        log.exception("soothe picker failed — falling back to static text")
        text = _PLACEHOLDER_TEXT_ZH if (detected_language == "zh") else _PLACEHOLDER_TEXT_EN
        template_id = "static_fallback"
else:
    text = _PLACEHOLDER_TEXT_ZH if (detected_language == "zh") else _PLACEHOLDER_TEXT_EN
    template_id = "static_disabled"

log.info(
    "soothe picked conv=%s intent=%s lang=%s template_id=%s",
    conv_id, intent, detected_language, template_id,
)
```

### 7.3 Call site (~L1430)

```python
decision = await triage_and_route(...)
target_role = decision.role
detected_language = decision.detected_language
intent = decision.intent                      # NEW (local capture)
...
reply_text, placeholder_msg = await _drain_with_placeholder(
    ...,
    detected_language=detected_language,
    eligible=(target_role in PLACEHOLDER_ELIGIBLE_ROLES),
    intent=intent,                            # NEW (passthrough)
)
```

### 7.4 Delay reduction

`PLACEHOLDER_DELAY_S: 1.5 → 0.0`. Retain the parameter (don't inline `0.0`) so single tests and future tuning can set it back without editing production code.

## 8. Non-goals (explicit)

These were considered and rejected for this spec:

1. **Sentiment as a schema dimension.** `TriageDecision` does not carry `sentiment`; adding it requires modifying the triage classifier soul, `ClassificationResult`, `TriageDecision`, and tests — scope creep incompatible with M3.5 Dream-first cut window. If intent granularity is insufficient post-launch, a follow-up spec may add sentiment, likely by reading `memory_pool.memory_turns.sentiment` (a column that already exists, populated per-turn).
2. **Realtime haiku generation (Approach B).** Deferred unless template rotation is shown to feel stale — trigger conditions in §11.
3. **Template + async haiku rewrite (Approach C).** Same deferral as B; this is a 2nd-order optimization.
4. **YAML hot reload.** YAML edits require process restart. Watchdog/inotify not worth the complexity at expected edit frequency (~1/week).
5. **Feishu channel parity.** Per CLAUDE.md "channel feature parity" section, Feishu is not a canonical customer path at M3.5.
6. **A2 extension to fast roles** (translate, direct). Kept at `PLACEHOLDER_ELIGIBLE_ROLES = {customer, lead}` — translate p50 is ~300ms (soothe→delta flicker risk); direct is already a pre-canned reply.
7. **Per-tenant template overrides.** All tenants share the same soothe bank in this version. Tenant overrides can be added later by extending the YAML schema with a `tenants:` section.
8. **`memory_pool` consultation at pick time.** Picker is stateless; does not read conversation history.

## 9. Observability

No new event types. Reuse existing channels:

| Signal | Mechanism | Consumer |
|---|---|---|
| Soothe template distribution | `log.info("soothe picked …")` at pick site | log aggregation / grep |
| Fallback rate (wildcard or defaults) | `template_id` starts with `"*_"` or equals `"static_fallback"` / `"fallback_<lang>"` | same |
| Placeholder emit latency | Existing `sla_placeholder` SLA timer (1s budget) — should drop from ~1500ms to <50ms | `EventBus.query("sla_placeholder")` / SLA dashboard |
| Unknown intent | `log.warning` at picker load + pick time | log alert |
| Placeholder → final reply replacement | Existing `message_edited` metric | unchanged dashboard |

## 10. Feature flag

**Env variable**: `SOOTHE_PLACEHOLDER_ENABLED` (default `"1"`).

**Module constant** (in `message_router.py`, read once at import):
```python
SOOTHE_ENABLED: bool = os.getenv("SOOTHE_PLACEHOLDER_ENABLED", "1") != "0"
```

Behavior:
- `SOOTHE_ENABLED = True` (default): picker path; `PLACEHOLDER_DELAY_S = 0.0`
- `SOOTHE_ENABLED = False`: revert to `_PLACEHOLDER_TEXT_ZH/EN` static text; `PLACEHOLDER_DELAY_S` restored to `1.5`

Flag value is captured at startup, not per-request (consistency over flexibility).

Rationale parallels the project's existing env-flag conventions (`DREAM_DEV_STUB`, `AUTH_DEV_MODE`): zero-code kill-switch for operations, clean split between code paths, long-lived (not removed after rollout).

## 11. Rollout

| Stage | Action | Duration | Exit criteria |
|---|---|---|---|
| 0. Merge | flag default `on`; YAML committed | — | CI green; picker unit tests + template-validity tests pass |
| 1. Staging | Full E2E (customer + lead, ≥20 real turns each) | 24h | `sla_placeholder` p95 < 100ms; zero `unknown intent` log warnings; `template_id` distribution ≥3 distinct |
| 2. Prod | Default on (no tenant subset needed — kill-switch is the rollback) | 48h | fallback rate (`*_` template_id) < 60%; `message_edited` success rate unchanged vs baseline |
| 3. Steady state | Keep flag as permanent kill-switch; no code removal | — | — |

**Rollback path**: `export SOOTHE_PLACEHOLDER_ENABLED=0` + rolling restart. Restores 2026-04-22 baseline within ~3 minutes.

### 11.1 Conditions that trigger Approach B/C follow-up

- Real-user feedback mentions "canned" or "repetitive" soothe lines
- Template fallback rate (`*_` matches) consistently > 40% → intent granularity is the bug, fix triage first, not haiku second
- Support NPS dips and rotation-distribution logs correlate

## 12. Testing

| Layer | File | Coverage |
|---|---|---|
| Unit | `tests/unit/test_soothe_picker.py` (new) | exact match / fallback to wildcard / fallback to defaults / unknown intent / unknown lang / empty `lines` rejection / fixed-seed determinism |
| Contract | `tests/contract/test_soothe_templates.py` (new) | `defaults.fallback.{zh,en}` exist and non-empty; every `templates[].intent` exists in `classify_intent.yaml` (warn-not-fail at runtime, fail in test); no line exceeds 30 chars; language is `zh` or `en` |
| Integration | `tests/integration/test_message_router_placeholder.py` (new or extend) | triage returns `intent=complaint, lang=zh` → placeholder text is one of the 3 complaint_zh lines; triage returns `intent=unknown` → falls to `*_zh` or `fallback_zh`; flag off → static text path |
| Regression | existing `_drain_with_placeholder` coverage | `message_edited` still fires; `placeholder_msg` cleanup on empty reply unchanged |

### 12.1 Performance budget (guidance, not hard test)

Targets for reasonable hardware — measure once during implementation, do not assert in unit tests (machine-dependent and flaky in CI):

- `SoothePicker.pick()`: <2ms (dict lookup + `random.choice`)
- `SoothePicker.__init__()`: <10ms for ≤100 templates
- Memory footprint: <100KB

If any metric is off by >10×, treat as a design bug and investigate.

## 13. Acceptance (smoke test)

1. customer slow turn (sonnet, >1.5s): placeholder arrives on frontend within **50ms** of triage decision (currently 1500ms)
2. customer fast turn (<200ms): placeholder still arrives; then `message_edited` replaces with final reply without UI error
3. lead turn: same as (1)
4. translate / direct turn: **no** placeholder — no regression vs 2026-04-22 baseline
5. Same intent requested 3× consecutively: observed `template_id` values include ≥2 distinct
6. Delete `soothe_templates.yaml` and restart: placeholder still appears (code-level fallback); log contains an `error` line; main reply chain unaffected
7. Set `SOOTHE_PLACEHOLDER_ENABLED=0` and restart: behavior reverts exactly to 2026-04-22 baseline (1.5s wait + static text)

## 14. Risks & mitigations

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Template rotation perceived as canned after repeat use | Medium | UX polish | §11.1 trigger to revisit with Approach B/C |
| Intent classifier returns intents not in template bank | Medium | Shown fallback_lang line (degraded UX, not broken) | Load-time warning + contract test + §11.1 trigger |
| YAML parse error at startup | Low | Soothe disabled, static fallback | try/except at picker init; log.exception; reduce to static fallback permanently until restart |
| Pick latency spikes (GC pause etc.) | Very low | 1 turn sees >50ms placeholder delay | Acceptable — still ≤ previous 1.5s baseline |
| Race: `message_edited` arrives before placeholder persists | Low | Existing code path already handles out-of-order (covering-semantic content) | No change needed |

## 15. Open questions (to resolve during implementation)

1. Final roster of intents in `classify_intent.yaml` — implementer should read current state and mirror it in the initial template bank.
2. Whether `defaults.fallback` should be duplicated per-language as a map or split into two lists — proposal above uses a map, confirm at YAML design time.
3. Whether `log.info` per pick is too noisy — may gate behind a debug flag if volume is prohibitive.

## 16. Implementation plan anchor

After this spec is approved, the next step is the `writing-plans` skill, which will produce a step-by-step implementation plan covering file creation order, test-first cadence, and integration boundaries.
