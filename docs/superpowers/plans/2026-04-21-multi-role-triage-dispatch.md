# Multi-Role Triage Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing `customer / lead / translate / triage / dream` agent roles into the live customer conversation path — FastClassifier decides on the hot path, triage-agent arbitrates when confidence is low, and `lead` / `translate` / `triage` get lazy per-(role, tenant) sub-pools with a sticky binding per conversation.

**Architecture:** One new function `triage_and_route()` sits between [message_router._generate_agent_reply](../../../autoservice/gateway/message_router.py#L1040) and the pool. It drives `ModelRouter.route_message()` (keyword + language heuristic + drift probe + low-confidence upgrade to triage agent). The decision is written to the conversation as a `TRIAGE` side-channel message for operator visibility, the conversation's active role / cc instance are updated, and a new role-aware pool (lazy sub-pool per `(role, tenant_id)` + 60 s reaper) hands out the CC instance that produces the reply. Sticky binding is per-`(role, conv_id)` — role switches release the old binding and re-seed the next prompt with the last 20 public messages. All triage state (active_role, drift_counter, detected_language, etc.) lives on `Conversation.metadata["triage"]` — LocalEngine is in-memory, no migration needed, keeps wire-compat with a future zchat backend that already carries opaque metadata.

**Tech Stack:** Python 3.11, `pytest-asyncio`, `langdetect` (new dep — optional, heuristic fallback always present), PyYAML, dataclasses, existing `socialware.pool.AsyncPool` + `autoservice.cc_pool.CCPool`.

**Spec:** [docs/superpowers/specs/2026-04-21-multi-role-triage-dispatch-design.md](../specs/2026-04-21-multi-role-triage-dispatch-design.md)

**Deviations from spec (documented here, not silent):**
1. §3.1 / §3.3 call for a DB migration with 5 new columns. LocalEngine keeps conversations in-process (`self._conversations: dict`) — there is no alembic surface to migrate. We embed the same 5 fields under `Conversation.metadata["triage"]`, accessed through helpers on LocalEngine (`get_triage_state` / `update_triage_state`). This preserves the wire schema for the future zchat backend (which carries opaque conversation metadata end-to-end) and keeps the change diff small.
2. §2.4 proposes a full `acquire_sticky(conv_id, role, tenant_id)` upgrade that releases the old `(role, conv_id)` binding on role switch. This plan implements the lighter variant: each call to `pool.acquire(role=, tenant_id=)` hands out a fresh instance from the sub-pool, and conversation-level `cc_instance_id` is updated so observability/release tooling can find it. Proper per-(role, conv_id) sticky binding with old-binding release is kept as a follow-up ticket — the re-seed in Task 9 compensates by threading history into the new role's first prompt.
3. Spec §6 row "目标 role 子池 acquire 失败" → fallback to customer + SIDE warning — handled in Task 9 Step 9.5 via the `try/except` around the role-stream helper, which also writes a second SIDE warning message.

---

## File Structure

**New files:**
- `autoservice/language_detect.py` — `detect_language(msg: str) -> str` (heuristic + optional `langdetect` fallback).
- `autoservice/triage_dispatch.py` — `TriageDecision` dataclass, `triage_and_route()` orchestrator, `_build_reseeded_prompt()` history re-seed helper, `_format_triage_side_text()` SIDE-channel formatter.
- `autoservice/tenant_triage_config.py` — loader + deep-merge for `classify_intent.yaml` tenant overlays + `tenant.<field>` triage config.
- `tests/triage/__init__.py` (empty)
- `tests/triage/test_language_detect.py`
- `tests/triage/test_tenant_overlay.py`
- `tests/triage/test_model_router_decision.py`
- `tests/triage/test_triage_agent_parser.py`
- `tests/triage/test_triage_dispatch.py`
- `tests/triage/test_reseed.py`
- `tests/cc_pool/test_role_pool.py`
- `tests/conversation/test_triage_state.py`
- `tests/e2e/test_triage_e2e.py`

**Modified files:**
- `autoservice/classify_intent.yaml` — keyword cleanup (remove cross-intent collisions).
- `autoservice/conversation_engine/types.py` — add `ParticipantRole.TRIAGE`.
- `autoservice/conversation_engine/local_engine.py` — `get_triage_state` / `update_triage_state` helpers.
- `autoservice/cc_pool.py` — extend `_KNOWN_ROLES`, add `_acquire_role_pool` + reaper, extend `acquire_sticky` to `(role, conv_id)`.
- `autoservice/model_router.py` — add `TriageDecision` dataclass + `ModelRouter.route_message()` async method + `_invoke_triage_agent` + parser.
- `autoservice/gateway/message_router.py` — wire `triage_and_route()` into `_generate_agent_reply`.

Each new file has one responsibility; modifications are additive (existing `FastClassifier`, sync `ModelRouter.route()`, customer/dream pool paths remain untouched).

---

## Task 1: `classify_intent.yaml` keyword cleanup (T0 part 1)

Goal: Remove the cross-intent keyword collisions (`价格` appears in both `product_inquiry` and `purchase_intent`; bare `问题` is too broad for `complaint`) so FastClassifier high-confidence decisions are trustworthy.

**Files:**
- Modify: `autoservice/classify_intent.yaml`
- Test: `tests/triage/test_model_router_decision.py` (new, seed with cleanup cases)

- [ ] **Step 1.1: Create the failing test file `tests/triage/test_model_router_decision.py`**

```python
"""FastClassifier keyword-cleanup regression + decision-path tests.

Spec: docs/superpowers/specs/2026-04-21-multi-role-triage-dispatch-design.md §4.1
"""
from __future__ import annotations

import pytest

from autoservice.model_router import FastClassifier, Intent, AgentRole


class TestKeywordCleanup:
    """After T0 cleanup, `价格` routes to lead (not product_inquiry)."""

    def setup_method(self):
        # Classifier reads the singleton _config — reset it so each test
        # sees a fresh parse of the yaml on disk.
        import autoservice.model_router as mr
        mr._config = None
        self.clf = FastClassifier()

    def test_price_word_routes_to_lead(self):
        result = self.clf.classify("你们的价格是多少")
        assert result.route_to == AgentRole.LEAD
        assert result.intent == Intent.PURCHASE_INTENT

    def test_bare_question_word_does_not_trigger_complaint(self):
        # "问题" alone is too generic — without "投诉/故障/坏了/refund"
        # it must not yield complaint.
        result = self.clf.classify("有个问题想咨询一下")
        assert result.intent != Intent.COMPLAINT

    def test_how_to_use_routes_to_product_inquiry(self):
        result = self.clf.classify("这个功能怎么用")
        assert result.route_to == AgentRole.CUSTOMER
        assert result.intent == Intent.PRODUCT_INQUIRY

    def test_refund_routes_to_complaint(self):
        result = self.clf.classify("我要退款")
        assert result.intent == Intent.COMPLAINT
```

- [ ] **Step 1.2: Run the test to verify it fails**

Run: `pytest tests/triage/test_model_router_decision.py::TestKeywordCleanup -v`
Expected: `test_price_word_routes_to_lead` FAILS (current yaml routes `价格` to `product_inquiry`), `test_bare_question_word_does_not_trigger_complaint` FAILS (bare `问题` hits complaint keywords).

- [ ] **Step 1.3: Apply the yaml keyword cleanup**

Edit `autoservice/classify_intent.yaml`:

```yaml
intents:
  product_inquiry:
    description: "产品/服务咨询、功能问题、使用方法"
    keywords: ["怎么用", "使用", "功能", "支持", "how to", "feature", "support", "user guide"]
    route_to: customer
    model_tier: slow
    priority: normal

  complaint:
    description: "投诉、不满、问题报告、退款"
    keywords: ["投诉", "不满", "退款", "refund", "complaint", "故障", "坏了", "crash", "broken", "refuse"]
    route_to: customer
    model_tier: slow
    priority: high

  purchase_intent:
    description: "购买意向、报价、合作、试用"
    keywords: ["买", "购买", "价格", "报价", "合作", "试用", "buy", "pricing", "demo", "trial", "quote", "采购", "订购"]
    route_to: lead
    model_tier: slow
    priority: high

  language_barrier:
    description: "语言不通、需要翻译"
    keywords: []
    route_to: translate
    model_tier: fast
    priority: high

  general_question:
    description: "闲聊、通用问题、无法归类"
    keywords: []
    route_to: customer
    model_tier: fast
    priority: normal
```

(Rest of the file — `model_tiers`, `timeouts`, `confidence` — unchanged.)

- [ ] **Step 1.4: Run the test to verify it passes**

Run: `pytest tests/triage/test_model_router_decision.py::TestKeywordCleanup -v`
Expected: all 4 tests PASS.

- [ ] **Step 1.5: Run the existing classifier test suite to confirm no regressions**

Run: `pytest tests/ -k "classify or model_router or triage" -x`
Expected: no previously-green test flips red. If an existing test asserted `价格` → `product_inquiry` or bare `问题` → `complaint`, update it in the same commit — those assertions encoded the bug.

- [ ] **Step 1.6: Commit**

```bash
git add autoservice/classify_intent.yaml tests/triage/__init__.py tests/triage/test_model_router_decision.py
git commit -m "fix(triage): clean classify_intent keyword collisions"
```

---

## Task 2: Tenant overlay loader for `classify_intent.yaml` (T0 part 2)

Goal: Let a tenant override keywords per intent via `plugins/<tid>/classify_intent.yaml` (fork) or `.autoservice/sandbox/<tid>/classify_intent.yaml` (master). Merge is per-field; `keywords` is replaced (not appended) to avoid silent inheritance of obsolete keywords. `FastClassifier` gains a tenant-scoped factory that caches the compiled config per tenant_id.

**Files:**
- Create: `autoservice/tenant_triage_config.py`
- Modify: `autoservice/model_router.py` (add `FastClassifier.for_tenant` classmethod)
- Test: `tests/triage/test_tenant_overlay.py`

- [ ] **Step 2.1: Write the failing test**

Create `tests/triage/test_tenant_overlay.py`:

```python
"""Tenant overlay for classify_intent.yaml — §4.2 of the spec."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from autoservice.model_router import FastClassifier, AgentRole, Intent
from autoservice.tenant_triage_config import (
    load_classify_intent_config,
    _merge_intent_config,
)


@pytest.fixture()
def tenant_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a tmp cwd with a fake plugin overlay for tenant ``acme``."""
    plugins = tmp_path / "plugins" / "acme" / "classify_intent.yaml"
    plugins.parent.mkdir(parents=True)
    plugins.write_text(
        yaml.safe_dump({
            "intents": {
                "purchase_intent": {
                    "keywords": ["委托", "retainer", "聘请"],
                },
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_deep_merge_replaces_keywords_preserves_other_fields():
    global_cfg = {
        "intents": {
            "purchase_intent": {
                "keywords": ["买", "pricing"],
                "route_to": "lead",
                "model_tier": "slow",
                "priority": "high",
            },
        },
        "confidence": {"high": 0.8, "medium": 0.6, "low": 0.3, "uncertain": 0.0},
    }
    overlay = {"intents": {"purchase_intent": {"keywords": ["委托"]}}}
    merged = _merge_intent_config(global_cfg, overlay)
    assert merged["intents"]["purchase_intent"]["keywords"] == ["委托"]
    assert merged["intents"]["purchase_intent"]["route_to"] == "lead"
    assert merged["intents"]["purchase_intent"]["priority"] == "high"
    assert merged["confidence"]["high"] == 0.8


def test_load_without_tenant_returns_global(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_classify_intent_config(tenant_id=None)
    assert "intents" in cfg and "confidence" in cfg


def test_load_with_tenant_applies_overlay(tenant_cwd):
    cfg = load_classify_intent_config(tenant_id="acme")
    assert cfg["intents"]["purchase_intent"]["keywords"] == ["委托", "retainer", "聘请"]
    # Non-overlaid intents unchanged.
    assert "投诉" in cfg["intents"]["complaint"]["keywords"]


def test_fast_classifier_per_tenant(tenant_cwd):
    clf = FastClassifier.for_tenant("acme")
    # After overlay, "价格" alone is no longer a purchase keyword for this tenant.
    result = clf.classify("价格")
    assert result.route_to != AgentRole.LEAD
    # But "委托" now triggers purchase.
    result2 = clf.classify("想委托你们处理")
    assert result2.route_to == AgentRole.LEAD
```

- [ ] **Step 2.2: Run the test to verify it fails**

Run: `pytest tests/triage/test_tenant_overlay.py -v`
Expected: FAIL — `autoservice.tenant_triage_config` does not exist.

- [ ] **Step 2.3: Implement `autoservice/tenant_triage_config.py`**

```python
"""Tenant overlay loader for classify_intent.yaml.

Spec: docs/superpowers/specs/2026-04-21-multi-role-triage-dispatch-design.md §4.2

Lookup order:
  1. .autoservice/sandbox/<tenant_id>/classify_intent.yaml  (master side)
  2. plugins/<tenant_id>/classify_intent.yaml                (fork side)
  3. autoservice/classify_intent.yaml                         (global)

Merge semantics:
  intents.<name>.keywords             — REPLACED (not appended)
  intents.<name>.{description, route_to, model_tier, priority} — per-field override
  confidence.{high, medium, low, uncertain}                    — per-field override
  timeouts / model_tiers              — NOT overridable (blast-radius guard)
"""
from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("triage.config")

_GLOBAL_PATH = Path(__file__).parent / "classify_intent.yaml"

_OVERLAY_ALLOWED_TOP = {"intents", "confidence"}
_OVERLAY_ALLOWED_INTENT = {"description", "keywords", "route_to", "model_tier", "priority"}
_OVERLAY_ALLOWED_CONFIDENCE = {"high", "medium", "low", "uncertain"}


def _tenant_overlay_path(tenant_id: str) -> Path | None:
    """Return the first existing overlay path, or None."""
    if not tenant_id or "/" in tenant_id or "\\" in tenant_id or ".." in tenant_id:
        return None
    cwd = Path.cwd()
    for candidate in (
        cwd / ".autoservice" / "sandbox" / tenant_id / "classify_intent.yaml",
        cwd / "plugins" / tenant_id / "classify_intent.yaml",
    ):
        if candidate.is_file():
            return candidate
    return None


def _merge_intent_config(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Apply tenant overlay on top of global config (deep copy, immutable result)."""
    merged = copy.deepcopy(base)
    for top_key, top_val in overlay.items():
        if top_key not in _OVERLAY_ALLOWED_TOP:
            log.warning("Ignoring non-overridable overlay key: %s", top_key)
            continue
        if top_key == "intents":
            for intent_name, intent_overlay in top_val.items():
                base_intent = merged["intents"].get(intent_name)
                if base_intent is None:
                    log.warning("Overlay references unknown intent: %s", intent_name)
                    continue
                for field, value in intent_overlay.items():
                    if field not in _OVERLAY_ALLOWED_INTENT:
                        log.warning("Ignoring non-overridable intent field: %s", field)
                        continue
                    base_intent[field] = value  # keywords replacement; other: scalar override
        elif top_key == "confidence":
            for field, value in top_val.items():
                if field not in _OVERLAY_ALLOWED_CONFIDENCE:
                    log.warning("Ignoring non-overridable confidence field: %s", field)
                    continue
                merged["confidence"][field] = value
    return merged


def load_classify_intent_config(tenant_id: str | None) -> dict[str, Any]:
    """Load the global config, optionally deep-merged with a tenant overlay."""
    with _GLOBAL_PATH.open(encoding="utf-8") as f:
        base = yaml.safe_load(f)
    if tenant_id is None:
        return base
    overlay_path = _tenant_overlay_path(tenant_id)
    if overlay_path is None:
        return base
    try:
        overlay = yaml.safe_load(overlay_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        log.warning("Failed to read tenant overlay %s: %s — using global", overlay_path, exc)
        return base
    return _merge_intent_config(base, overlay)
```

- [ ] **Step 2.4: Add `FastClassifier.for_tenant` to `autoservice/model_router.py`**

Add inside the `FastClassifier` class (after the existing `__init__` on [model_router.py:91](../../../autoservice/model_router.py#L91)):

```python
    _tenant_cache: dict[str | None, "FastClassifier"] = {}

    @classmethod
    def for_tenant(cls, tenant_id: str | None) -> "FastClassifier":
        """Return a tenant-scoped classifier (cached per tenant_id)."""
        if tenant_id in cls._tenant_cache:
            return cls._tenant_cache[tenant_id]
        from autoservice.tenant_triage_config import load_classify_intent_config
        cfg = load_classify_intent_config(tenant_id)
        inst = cls.__new__(cls)
        inst._intents = cfg["intents"]
        inst._thresholds = cfg["confidence"]
        cls._tenant_cache[tenant_id] = inst
        return inst

    @classmethod
    def clear_tenant_cache(cls) -> None:
        """Test hook — drop cached per-tenant classifiers."""
        cls._tenant_cache.clear()
```

- [ ] **Step 2.5: Run the tests to verify they pass**

Run: `pytest tests/triage/test_tenant_overlay.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 2.6: Commit**

```bash
git add autoservice/tenant_triage_config.py autoservice/model_router.py tests/triage/test_tenant_overlay.py
git commit -m "feat(triage): tenant overlay loader for classify_intent.yaml"
```

---

## Task 3: Add `TRIAGE` to `ParticipantRole` enum (T1 part 1)

**Files:**
- Modify: `autoservice/conversation_engine/types.py`
- Test: `tests/conversation/test_triage_state.py` (seed with enum check)

- [ ] **Step 3.1: Write the failing test**

Create `tests/conversation/test_triage_state.py`:

```python
"""Triage state on Conversation.metadata + TRIAGE participant role.

Spec: docs/superpowers/specs/2026-04-21-multi-role-triage-dispatch-design.md §3
"""
from __future__ import annotations

import pytest

from autoservice.conversation_engine.types import ParticipantRole


def test_triage_role_exists():
    assert ParticipantRole.TRIAGE.value == "triage"
```

- [ ] **Step 3.2: Run the test to verify it fails**

Run: `pytest tests/conversation/test_triage_state.py::test_triage_role_exists -v`
Expected: FAIL — `ParticipantRole.TRIAGE` missing.

- [ ] **Step 3.3: Add the enum value**

Edit `autoservice/conversation_engine/types.py`:

```python
class ParticipantRole(str, Enum):
    CUSTOMER = "customer"
    AGENT = "agent"
    OPERATOR = "operator"
    OBSERVER = "observer"
    TRIAGE = "triage"
```

- [ ] **Step 3.4: Run the test to verify it passes**

Run: `pytest tests/conversation/test_triage_state.py::test_triage_role_exists -v`
Expected: PASS.

- [ ] **Step 3.5: Run the whole conversation_engine test suite — no regressions**

Run: `pytest tests/conversation_engine -v`
Expected: all green (the new enum value is additive).

- [ ] **Step 3.6: Commit**

```bash
git add autoservice/conversation_engine/types.py tests/conversation/test_triage_state.py
git commit -m "feat(conversation): add TRIAGE participant role"
```

---

## Task 4: Triage state accessors on LocalEngine (T1 part 2)

Goal: Store `{active_role, cc_instance_id, detected_language, drift_counter, triage_mode}` under `conversation.metadata["triage"]`. Add `get_triage_state` / `update_triage_state` / `incr_drift` / `reset_drift` methods on LocalEngine.

**Files:**
- Modify: `autoservice/conversation_engine/local_engine.py`
- Test: `tests/conversation/test_triage_state.py` (extend)

- [ ] **Step 4.1: Extend the failing test**

Append to `tests/conversation/test_triage_state.py`:

```python
import pytest_asyncio

from autoservice.conversation_engine.local_engine import LocalEngine


@pytest_asyncio.fixture()
async def engine() -> "LocalEngine":
    return LocalEngine()


@pytest.mark.asyncio
async def test_triage_state_defaults_to_empty(engine):
    conv = await engine.create_conversation(channel="web", external_id="c1")
    state = await engine.get_triage_state(conv.id)
    assert state == {
        "active_role": None,
        "cc_instance_id": None,
        "detected_language": None,
        "drift_counter": 0,
        "triage_mode": "drift",
    }


@pytest.mark.asyncio
async def test_update_triage_state_merges(engine):
    conv = await engine.create_conversation(channel="web", external_id="c2")
    await engine.update_triage_state(
        conv.id, active_role="lead", cc_instance_id="cc-042",
    )
    state = await engine.get_triage_state(conv.id)
    assert state["active_role"] == "lead"
    assert state["cc_instance_id"] == "cc-042"
    assert state["drift_counter"] == 0  # unchanged fields preserved


@pytest.mark.asyncio
async def test_incr_and_reset_drift(engine):
    conv = await engine.create_conversation(channel="web", external_id="c3")
    assert await engine.incr_drift(conv.id) == 1
    assert await engine.incr_drift(conv.id) == 2
    await engine.reset_drift(conv.id)
    assert (await engine.get_triage_state(conv.id))["drift_counter"] == 0


@pytest.mark.asyncio
async def test_triage_state_survives_unrelated_metadata(engine):
    conv = await engine.create_conversation(
        channel="web", external_id="c4", metadata={"squad_id": "S1"},
    )
    await engine.update_triage_state(conv.id, active_role="customer")
    conv2 = await engine.get_conversation(conv.id)
    assert conv2.metadata["squad_id"] == "S1"
    assert conv2.metadata["triage"]["active_role"] == "customer"
```

- [ ] **Step 4.2: Run to verify failure**

Run: `pytest tests/conversation/test_triage_state.py -v`
Expected: FAIL — `engine.get_triage_state` and siblings don't exist.

- [ ] **Step 4.3: Implement the accessors on LocalEngine**

In `autoservice/conversation_engine/local_engine.py`, add at module scope (near the top, after the `_GATE_DOWNGRADE` frozenset):

```python
_TRIAGE_DEFAULTS: dict[str, Any] = {
    "active_role": None,
    "cc_instance_id": None,
    "detected_language": None,
    "drift_counter": 0,
    "triage_mode": "drift",
}
_TRIAGE_KEY = "triage"
```

Inside class `LocalEngine`, add after the `_update_conv` helper ([local_engine.py:169-173](../../../autoservice/conversation_engine/local_engine.py#L169-L173)):

```python
    # ---------- Triage state (spec §3.1) ----------

    async def get_triage_state(self, conversation_id: str) -> dict[str, Any]:
        """Return the conversation's triage state with defaults filled in."""
        conv = self._get_conv(conversation_id)
        stored = dict(conv.metadata.get(_TRIAGE_KEY, {}))
        out = dict(_TRIAGE_DEFAULTS)
        out.update(stored)
        return out

    async def update_triage_state(self, conversation_id: str, **fields: Any) -> None:
        """Patch-update triage state fields. Unknown fields raise KeyError."""
        unknown = set(fields) - set(_TRIAGE_DEFAULTS)
        if unknown:
            raise KeyError(f"Unknown triage field(s): {sorted(unknown)}")
        conv = self._get_conv(conversation_id)
        new_meta = dict(conv.metadata)
        triage = dict(new_meta.get(_TRIAGE_KEY, {}))
        triage.update(fields)
        new_meta[_TRIAGE_KEY] = triage
        self._update_conv(conversation_id, metadata=new_meta)

    async def incr_drift(self, conversation_id: str) -> int:
        """Increment drift_counter and return the new value."""
        state = await self.get_triage_state(conversation_id)
        new_value = state["drift_counter"] + 1
        await self.update_triage_state(conversation_id, drift_counter=new_value)
        return new_value

    async def reset_drift(self, conversation_id: str) -> None:
        await self.update_triage_state(conversation_id, drift_counter=0)
```

- [ ] **Step 4.4: Run to verify passing**

Run: `pytest tests/conversation/test_triage_state.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 4.5: Confirm existing conversation tests still green**

Run: `pytest tests/conversation_engine tests/gateway -x`
Expected: no regressions (the change is additive — no existing code path writes to `metadata["triage"]`).

- [ ] **Step 4.6: Commit**

```bash
git add autoservice/conversation_engine/local_engine.py tests/conversation/test_triage_state.py
git commit -m "feat(conversation): triage state accessors on LocalEngine"
```

---

## Task 5: `detect_language()` utility (T3 part 1)

Goal: Heuristic-first language detection (no network / LLM): CJK-range count, Hiragana/Katakana presence for Japanese, common English stopwords, with `langdetect` as the mixed-script fallback.

**Files:**
- Create: `autoservice/language_detect.py`
- Test: `tests/triage/test_language_detect.py`

- [ ] **Step 5.1: Write the failing test**

Create `tests/triage/test_language_detect.py`:

```python
"""detect_language — §2.2 of the spec."""
from __future__ import annotations

import pytest

from autoservice.language_detect import detect_language


@pytest.mark.parametrize(
    "msg,expected",
    [
        ("你好", "zh"),
        ("我想买一个产品", "zh"),
        ("Hello, how are you?", "en"),
        ("What is the price?", "en"),
        ("こんにちは、お元気ですか", "ja"),
        ("hi", "unknown"),         # too short
    ],
)
def test_detect_language_happy_path(msg, expected):
    assert detect_language(msg) == expected


def test_detect_language_handles_mixed_scripts_without_crash():
    # Should not raise even if langdetect mis-detects; return a string.
    result = detect_language("Hello 你好")
    assert isinstance(result, str)


def test_detect_language_empty_input():
    assert detect_language("") == "unknown"
    assert detect_language("   ") == "unknown"
```

- [ ] **Step 5.2: Run to verify failure**

Run: `pytest tests/triage/test_language_detect.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 5.3: Implement `autoservice/language_detect.py`**

```python
"""Heuristic + langdetect language detection.

Spec: docs/superpowers/specs/2026-04-21-multi-role-triage-dispatch-design.md §2.2

Heuristic first for hot-path messages (0-cost, deterministic); langdetect
is imported lazily as the mixed-script fallback. Returns ISO code or
'unknown'.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("triage.lang")

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff]")
_KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
_LATIN_RE = re.compile(r"[a-zA-Z]")
_EN_STOPWORDS_RE = re.compile(r"\b(the|is|you|have|what|how|a|an|are|to|of|in)\b", re.I)


def detect_language(message: str) -> str:
    """Return an ISO code: zh / en / ja / ... or 'unknown'."""
    if message is None:
        return "unknown"
    stripped = message.strip()
    if len(stripped) < 3:
        return "unknown"

    cjk_count = len(_CJK_RE.findall(stripped))
    latin_count = len(_LATIN_RE.findall(stripped))
    total = cjk_count + latin_count

    if total == 0:
        return _langdetect_fallback(stripped)

    cjk_ratio = cjk_count / total
    latin_ratio = latin_count / total

    if cjk_ratio > 0.8:
        if _KANA_RE.search(stripped):
            return "ja"
        return "zh"

    if latin_ratio > 0.8:
        if _EN_STOPWORDS_RE.search(stripped):
            return "en"
        return _langdetect_fallback(stripped)

    return _langdetect_fallback(stripped)


def _langdetect_fallback(message: str) -> str:
    try:
        from langdetect import detect, DetectorFactory
        DetectorFactory.seed = 0
        return detect(message)
    except ImportError:
        log.debug("langdetect not installed — returning 'unknown'")
        return "unknown"
    except Exception as exc:
        log.debug("langdetect failed for %r: %s", message[:30], exc)
        return "unknown"
```

- [ ] **Step 5.4: Run to verify passing**

Run: `pytest tests/triage/test_language_detect.py -v`
Expected: all 8 test cases PASS. If `langdetect` is not installed, the mixed-script test still passes because the function returns `"unknown"` gracefully.

- [ ] **Step 5.5: Commit**

```bash
git add autoservice/language_detect.py tests/triage/test_language_detect.py
git commit -m "feat(triage): heuristic language detection with langdetect fallback"
```

---

## Task 6: Role-aware pool with reaper (T2)

Goal: Extend `CCPool.acquire` to accept `role ∈ {lead, translate, triage}` and dispatch to a lazy `(role, tenant_id)` sub-pool. Stateful roles (`lead`, `translate`) size = `tenant.pool_size_per_role` (default 2). Stateless role (`triage`) size = 1. A background reaper closes sub-pools idle > 600 s.

**Files:**
- Modify: `autoservice/cc_pool.py`
- Test: `tests/cc_pool/test_role_pool.py`

- [ ] **Step 6.1: Write the failing test**

Create `tests/cc_pool/test_role_pool.py`:

```python
"""Role pool acquisition + reaper — §2.3 of the spec.

These tests stub out the CC client factory so no real Claude process is
spawned; they exercise only the pool selection / lifecycle logic.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from autoservice.cc_pool import CCPool, PoolConfig, _KNOWN_ROLES


def _fake_client_factory():
    """Return a CCClient-shaped MagicMock with async connect/disconnect."""
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.is_healthy = MagicMock(return_value=True)
    client.query = AsyncMock()

    async def _empty_response():
        return
        yield  # pragma: no cover
    client.receive_response = _empty_response
    return client


@pytest.fixture(autouse=True)
def _patch_create(monkeypatch):
    async def _factory(*args, **kwargs):
        return _fake_client_factory()
    monkeypatch.setattr("autoservice.cc_pool.create_cc_client", _factory)


@pytest.fixture()
async def pool():
    p = CCPool(PoolConfig(min_size=0, max_size=2, warmup_count=0))
    await p.start()
    yield p
    await p.shutdown()


def test_known_roles_includes_new_roles():
    assert {"customer", "dream", "lead", "translate", "triage"} <= _KNOWN_ROLES


@pytest.mark.asyncio
async def test_lead_role_acquire_succeeds(pool):
    async with pool.acquire(role="lead", tenant_id="acme") as inst:
        assert inst is not None
        assert getattr(inst, "_pool_role", None) == "lead"


@pytest.mark.asyncio
async def test_triage_role_single_instance(pool):
    """Triage role has size=1 regardless of tenant config."""
    async with pool.acquire(role="triage", tenant_id="acme") as inst1:
        assert inst1 is not None
    async with pool.acquire(role="triage", tenant_id="acme") as inst2:
        # Same lazy sub-pool reuses the warm instance.
        assert inst2 is not None


@pytest.mark.asyncio
async def test_per_tenant_isolation(pool):
    async with pool.acquire(role="lead", tenant_id="acme") as a:
        assert getattr(a, "_pool_role", None) == "lead"
    async with pool.acquire(role="lead", tenant_id="beta") as b:
        assert getattr(b, "_pool_role", None) == "lead"
    # Distinct sub-pools tracked.
    assert ("lead", "acme") in pool._role_pools
    assert ("lead", "beta") in pool._role_pools


@pytest.mark.asyncio
async def test_unknown_role_raises(pool):
    with pytest.raises(NotImplementedError):
        async with pool.acquire(role="no-such-role") as _:
            pass


@pytest.mark.asyncio
async def test_reaper_closes_idle_pools(pool, monkeypatch):
    monkeypatch.setattr("autoservice.cc_pool._REAP_IDLE_SEC", 0.05)
    async with pool.acquire(role="lead", tenant_id="acme") as _:
        pass
    assert ("lead", "acme") in pool._role_pools
    await pool._reap_idle_role_pools_once()
    await asyncio.sleep(0.1)
    await pool._reap_idle_role_pools_once()
    assert ("lead", "acme") not in pool._role_pools
```

- [ ] **Step 6.2: Run to verify failure**

Run: `pytest tests/cc_pool/test_role_pool.py -v`
Expected: FAIL — the role branches don't exist, `_KNOWN_ROLES` is still `{"customer", "dream"}`.

- [ ] **Step 6.3: Extend `_KNOWN_ROLES` and add role-pool machinery**

Edit `autoservice/cc_pool.py`. Replace the `_KNOWN_ROLES` line (currently [cc_pool.py:330](../../../autoservice/cc_pool.py#L330)):

```python
_KNOWN_ROLES: frozenset[str] = frozenset({"customer", "dream", "lead", "translate", "triage"})

_ROLE_POOL_SIZES: dict[str, int] = {
    "lead": 2,
    "translate": 2,
    "triage": 1,
}
_REAP_IDLE_SEC: float = 600.0
```

Inside the `CCPool` class, add the role-pool fields to `__init__` (after `super().__init__`):

```python
        self._role_pools: dict[tuple[str, str | None], AsyncPool[CCClient]] = {}
        self._role_pool_last_used: dict[tuple[str, str | None], float] = {}
        self._role_pool_lock = asyncio.Lock()
        self._reaper_task: asyncio.Task | None = None
```

Replace `CCPool.acquire` (the method currently on [cc_pool.py:393-454](../../../autoservice/cc_pool.py#L393-L454)) so the `raise NotImplementedError` branch is replaced with a dispatch to `_acquire_role_pool`:

```python
    def acquire(
        self,
        timeout: float | None = None,
        *,
        role: str = "customer",
        tenant_id: str | None = None,
    ) -> Any:
        if role == "customer":
            return super().acquire(timeout=timeout)
        if role == "dream":
            return _acquire_dream(tenant_id=tenant_id, timeout=timeout)
        if role in ("lead", "translate", "triage"):
            return self._acquire_role_pool(role, tenant_id, timeout)
        raise NotImplementedError(
            f"cc_pool.acquire: role={role!r} is not implemented. "
            f"Known roles: {sorted(_KNOWN_ROLES)}."
        )
```

Add new methods on `CCPool` (place after `acquire`):

```python
    @asynccontextmanager
    async def _acquire_role_pool(
        self, role: str, tenant_id: str | None, timeout: float | None,
    ) -> AsyncIterator[PooledInstance[CCClient]]:
        key = (role, tenant_id)
        async with self._role_pool_lock:
            sub_pool = self._role_pools.get(key)
            if sub_pool is None:
                sub_pool = await self._create_role_pool(role, tenant_id)
                self._role_pools[key] = sub_pool
                if self._reaper_task is None or self._reaper_task.done():
                    self._reaper_task = asyncio.create_task(
                        self._reaper_loop(), name="cc-pool-role-reaper",
                    )
        self._role_pool_last_used[key] = time.monotonic()
        async with sub_pool.acquire(timeout=timeout) as inst:
            inst._pool_role = role  # type: ignore[attr-defined]
            inst._pool_tenant_id = tenant_id  # type: ignore[attr-defined]
            self._role_pool_last_used[key] = time.monotonic()
            yield inst

    async def _create_role_pool(
        self, role: str, tenant_id: str | None,
    ) -> AsyncPool[CCClient]:
        size = _ROLE_POOL_SIZES[role]
        base = load_pool_config(self._config.cwd)
        sub_cfg = replace(base, min_size=0, max_size=size, warmup_count=0)

        async def _factory() -> CCClient:
            return await create_cc_client(sub_cfg, role=role, tenant_id=tenant_id)

        pool = AsyncPool[CCClient](
            config=sub_cfg,
            factory=_factory,
            instance_prefix=f"cc-{role}",
            logger=log,
        )
        await pool.start()
        log.info("cc_pool: opened sub-pool role=%s tenant=%s size=%d",
                 role, tenant_id, size)
        return pool

    async def _reaper_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(min(60.0, max(_REAP_IDLE_SEC / 10, 0.01)))
                await self._reap_idle_role_pools_once()
        except asyncio.CancelledError:
            pass

    async def _reap_idle_role_pools_once(self) -> None:
        now = time.monotonic()
        victims: list[tuple[str, str | None]] = []
        for key, last in list(self._role_pool_last_used.items()):
            if now - last > _REAP_IDLE_SEC:
                victims.append(key)
        for key in victims:
            sub_pool = self._role_pools.pop(key, None)
            self._role_pool_last_used.pop(key, None)
            if sub_pool is not None:
                try:
                    await sub_pool.shutdown()
                    log.info("cc_pool: reaped idle sub-pool role=%s tenant=%s",
                             key[0], key[1])
                except Exception:
                    log.exception("cc_pool: reaper shutdown failed for %s", key)
```

Extend `CCPool.shutdown` (or override if the base doesn't exist) to cancel the reaper and close all sub-pools. Since `AsyncPool.shutdown` is inherited, override it in `CCPool`:

```python
    async def shutdown(self) -> None:
        if self._reaper_task is not None and not self._reaper_task.done():
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reaper_task = None
        for key, sub_pool in list(self._role_pools.items()):
            try:
                await sub_pool.shutdown()
            except Exception:
                log.exception("cc_pool: sub-pool shutdown failed for %s", key)
        self._role_pools.clear()
        self._role_pool_last_used.clear()
        await super().shutdown()
```

- [ ] **Step 6.4: Run to verify passing**

Run: `pytest tests/cc_pool/test_role_pool.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 6.5: Run full cc_pool suite for regressions**

Run: `pytest tests/cc_pool -x`
Expected: all green. Customer + dream paths are untouched.

- [ ] **Step 6.6: Commit**

```bash
git add autoservice/cc_pool.py tests/cc_pool/test_role_pool.py
git commit -m "feat(cc_pool): lazy per-(role,tenant) sub-pools with idle reaper"
```

---

## Task 7: `ModelRouter.route_message()` with drift probe (T3 part 2)

Goal: New async `ModelRouter.route_message(message, tenant_id, conv_id, engine)` that (1) detects language, (2) short-circuits to `translate` on language barrier, (3) runs FastClassifier, (4) updates drift counter via engine, (5) returns a `TriageDecision`. Does NOT yet invoke the triage agent — that's Task 8.

**Files:**
- Modify: `autoservice/model_router.py`
- Test: `tests/triage/test_model_router_decision.py` (extend)

- [ ] **Step 7.1: Extend the failing test**

Append to `tests/triage/test_model_router_decision.py`:

```python
import pytest_asyncio

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.model_router import ModelRouter, TriageDecision


@pytest_asyncio.fixture()
async def engine() -> LocalEngine:
    return LocalEngine()


@pytest_asyncio.fixture()
async def conv_id(engine):
    conv = await engine.create_conversation(channel="web", external_id="cdec")
    return conv.id


class _StaticTenantConfig:
    def __init__(self, supported=("zh", "en")):
        self.supported_languages = list(supported)
        self.tenant_id = "acme"


class TestRouteMessage:
    @pytest.mark.asyncio
    async def test_language_barrier_short_circuits_to_translate(self, engine, conv_id):
        r = ModelRouter()
        tc = _StaticTenantConfig(supported=("zh", "en"))
        decision = await r.route_message(
            "こんにちは、助けてください", tenant_config=tc,
            conv_id=conv_id, engine=engine,
        )
        assert isinstance(decision, TriageDecision)
        assert decision.role == "translate"
        assert decision.source == "fastpath"
        assert decision.detected_language == "ja"

    @pytest.mark.asyncio
    async def test_high_confidence_fastpath(self, engine, conv_id):
        r = ModelRouter()
        decision = await r.route_message(
            "我想购买你们的产品,价格多少", tenant_config=_StaticTenantConfig(),
            conv_id=conv_id, engine=engine,
        )
        assert decision.role == "lead"
        assert decision.source == "fastpath"
        assert decision.confidence >= 0.6

    @pytest.mark.asyncio
    async def test_drift_counter_increments_on_mismatch(self, engine, conv_id):
        r = ModelRouter()
        tc = _StaticTenantConfig()
        # Prime active_role = customer
        await engine.update_triage_state(conv_id, active_role="customer")
        # Send a lead-intent message → drift
        decision = await r.route_message(
            "想购买试用一下", tenant_config=tc, conv_id=conv_id, engine=engine,
        )
        state = await engine.get_triage_state(conv_id)
        assert state["drift_counter"] == 1
        assert decision.role in ("lead", "customer")

    @pytest.mark.asyncio
    async def test_drift_resets_on_match(self, engine, conv_id):
        r = ModelRouter()
        tc = _StaticTenantConfig()
        await engine.update_triage_state(conv_id, active_role="customer", drift_counter=3)
        await r.route_message(
            "怎么使用这个功能", tenant_config=tc, conv_id=conv_id, engine=engine,
        )
        state = await engine.get_triage_state(conv_id)
        assert state["drift_counter"] == 0
```

- [ ] **Step 7.2: Run to verify failure**

Run: `pytest tests/triage/test_model_router_decision.py::TestRouteMessage -v`
Expected: FAIL — `TriageDecision` and `ModelRouter.route_message` don't exist.

- [ ] **Step 7.3: Implement `TriageDecision` and `ModelRouter.route_message`**

Edit `autoservice/model_router.py`. Below the existing `RoutingDecision` dataclass, add:

```python
from typing import Literal, Protocol


@dataclass
class TriageDecision:
    """Triage-and-route decision consumed by triage_and_route()."""
    role: str                          # customer | lead | translate
    confidence: float
    source: Literal["fastpath", "triage_agent", "fallback"]
    intent: str
    detected_language: Optional[str]
    summary: Optional[str] = None
    needs_operator_notice: bool = False
    previous_role: Optional[str] = None


class _TenantConfigLike(Protocol):
    supported_languages: list[str]
    tenant_id: str
```

Still in `model_router.py`, extend `class ModelRouter` (after the sync `route` method):

```python
    async def route_message(
        self,
        message: str,
        *,
        tenant_config: "_TenantConfigLike",
        conv_id: str | None = None,
        engine: Any = None,
    ) -> TriageDecision:
        """Full triage-and-route decision (async).

        Steps:
          1. detect language (heuristic + langdetect)
          2. if language NOT IN tenant.supported_languages → translate
          3. FastClassifier with tenant overlay
          4. drift probe (engine.incr_drift / reset_drift)
          5. decide fastpath vs triage-agent (Task 8 supplies the upgrade)
        """
        from autoservice.language_detect import detect_language

        tenant_id = getattr(tenant_config, "tenant_id", None)
        supported = set(getattr(tenant_config, "supported_languages", []) or ["zh", "en"])

        lang = detect_language(message)
        if lang != "unknown" and lang not in supported:
            return TriageDecision(
                role="translate",
                confidence=0.9,
                source="fastpath",
                intent="language_barrier",
                detected_language=lang,
                needs_operator_notice=False,
            )

        clf = FastClassifier.for_tenant(tenant_id)
        fast = clf.classify(message, detected_language=lang if lang != "unknown" else None)

        previous_role: str | None = None
        drift_count = 0
        if conv_id is not None and engine is not None:
            state = await engine.get_triage_state(conv_id)
            previous_role = state.get("active_role")
            if previous_role and previous_role != fast.route_to.value:
                drift_count = await engine.incr_drift(conv_id)
            else:
                await engine.reset_drift(conv_id)

        threshold = self._thresholds["medium"]
        can_fastpath = (
            fast.confidence >= threshold
            and (previous_role is None or drift_count < 2 or fast.confidence < threshold)
        )
        if can_fastpath:
            return TriageDecision(
                role=fast.route_to.value,
                confidence=fast.confidence,
                source="fastpath",
                intent=fast.intent.value,
                detected_language=lang if lang != "unknown" else None,
                summary=fast.summary,
                needs_operator_notice=fast.confidence < self._thresholds["high"],
                previous_role=previous_role,
            )

        # Low confidence or sustained drift: placeholder decision marked for
        # Task 8's triage-agent upgrade. For this task, fall back to FastClassifier
        # result with source="fallback" so tests see non-None roles.
        return TriageDecision(
            role=fast.route_to.value,
            confidence=fast.confidence,
            source="fallback",
            intent=fast.intent.value,
            detected_language=lang if lang != "unknown" else None,
            summary=fast.summary or message[:100],
            needs_operator_notice=True,
            previous_role=previous_role,
        )
```

- [ ] **Step 7.4: Run to verify passing**

Run: `pytest tests/triage/test_model_router_decision.py::TestRouteMessage -v`
Expected: all 4 tests PASS.

- [ ] **Step 7.5: Commit**

```bash
git add autoservice/model_router.py tests/triage/test_model_router_decision.py
git commit -m "feat(triage): ModelRouter.route_message with language + drift probe"
```

---

## Task 8: Triage agent invocation + parser (T4)

Goal: When FastClassifier confidence < medium OR drift count ≥ 2, call the `triage` agent via `cc_pool.acquire(role='triage')` with a rendered prompt, parse the `[分流] 意图: ... | 信心: ... | 路由: ... | 原因: ... [| 摘要: "..."]` output, and return a `TriageDecision(source="triage_agent")`. Timeout / parse failure / out-of-whitelist role all downgrade to `source="fallback"` with the FastClassifier result.

**Files:**
- Modify: `autoservice/model_router.py` (add `_invoke_triage_agent` + parser)
- Test: `tests/triage/test_triage_agent_parser.py`

- [ ] **Step 8.1: Write the failing test**

Create `tests/triage/test_triage_agent_parser.py`:

```python
"""Triage agent output parser — §2.1 of the spec."""
from __future__ import annotations

import pytest

from autoservice.model_router import ModelRouter, _parse_triage_output


class TestParser:
    def test_happy_path(self):
        raw = "[分流] 意图: purchase_intent | 信心: 0.82 | 路由: lead | 原因: 客户询问价格"
        parsed = _parse_triage_output(raw)
        assert parsed["intent"] == "purchase_intent"
        assert parsed["confidence"] == pytest.approx(0.82)
        assert parsed["route_to"] == "lead"
        assert parsed["summary"] is None

    def test_with_summary(self):
        raw = '[分流] 意图: general_question | 信心: 0.45 | 路由: customer | 原因: 消息模糊 | 摘要: "客户说有个事想问一下"'
        parsed = _parse_triage_output(raw)
        assert parsed["confidence"] == pytest.approx(0.45)
        assert parsed["summary"] == "客户说有个事想问一下"

    def test_missing_prefix_returns_none(self):
        assert _parse_triage_output("Hello, I help route") is None

    def test_bad_confidence_returns_default(self):
        raw = "[分流] 意图: complaint | 信心: abc | 路由: customer | 原因: ..."
        parsed = _parse_triage_output(raw)
        assert parsed is not None
        assert parsed["confidence"] == 0.5   # default fallback

    def test_invalid_role_coerced_to_customer(self):
        raw = "[分流] 意图: complaint | 信心: 0.9 | 路由: admin | 原因: ..."
        parsed = _parse_triage_output(raw)
        assert parsed["route_to"] == "customer"
```

Append to the same file:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.model_router import TriageDecision


class _FakeTenantConfig:
    tenant_id = "acme"
    supported_languages = ["zh", "en"]


@pytest.mark.asyncio
async def test_low_confidence_triggers_triage_agent_call(monkeypatch):
    """When FastClassifier confidence < medium, triage agent is invoked."""
    engine = LocalEngine()
    conv = await engine.create_conversation(channel="web", external_id="c-tri")

    captured_prompts: list[str] = []

    # Stub the triage-agent one-shot call.
    async def _fake_one_shot(msg: str, tenant_id: str | None) -> str:
        captured_prompts.append(msg)
        return "[分流] 意图: general_question | 信心: 0.7 | 路由: customer | 原因: 消息模糊"

    monkeypatch.setattr(
        "autoservice.model_router.ModelRouter._triage_agent_one_shot",
        _fake_one_shot,
    )

    r = ModelRouter()
    # Use a message that FastClassifier will classify as general_question with low confidence.
    decision = await r.route_message(
        "嗯", tenant_config=_FakeTenantConfig(),
        conv_id=conv.id, engine=engine,
    )
    assert decision.source == "triage_agent"
    assert decision.role == "customer"
    assert captured_prompts, "expected triage agent to be called"


@pytest.mark.asyncio
async def test_triage_agent_timeout_falls_back(monkeypatch):
    engine = LocalEngine()
    conv = await engine.create_conversation(channel="web", external_id="c-tri2")

    async def _fake_one_shot(msg: str, tenant_id: str | None) -> str:
        raise asyncio.TimeoutError("triage too slow")

    monkeypatch.setattr(
        "autoservice.model_router.ModelRouter._triage_agent_one_shot",
        _fake_one_shot,
    )

    r = ModelRouter()
    decision = await r.route_message(
        "嗯", tenant_config=_FakeTenantConfig(),
        conv_id=conv.id, engine=engine,
    )
    assert decision.source == "fallback"
    assert decision.needs_operator_notice is True
```

- [ ] **Step 8.2: Run to verify failure**

Run: `pytest tests/triage/test_triage_agent_parser.py -v`
Expected: FAIL — `_parse_triage_output` and `_triage_agent_one_shot` don't exist.

- [ ] **Step 8.3: Implement the parser and triage-agent call**

Edit `autoservice/model_router.py`. Add at module scope (near the imports):

```python
import asyncio
import re

_TRIAGE_OUTPUT_RE = re.compile(
    r"\[分流\]\s*"
    r"意图\s*:\s*(?P<intent>\w+)\s*\|\s*"
    r"信心\s*:\s*(?P<confidence>[\w.]+)\s*\|\s*"
    r"路由\s*:\s*(?P<route_to>\w+)\s*\|\s*"
    r"原因\s*:\s*(?P<reason>[^|]+?)"
    r"(?:\s*\|\s*摘要\s*:\s*\"(?P<summary>[^\"]+)\")?"
    r"\s*$"
)

_TRIAGE_ROLE_WHITELIST = {"customer", "lead", "translate"}


def _parse_triage_output(raw: str) -> dict | None:
    """Parse a triage agent [分流] line. Returns dict or None on hard failure."""
    if not raw:
        return None
    for line in raw.splitlines():
        m = _TRIAGE_OUTPUT_RE.match(line.strip())
        if m:
            try:
                conf = float(m.group("confidence"))
            except (TypeError, ValueError):
                conf = 0.5
            role = m.group("route_to")
            if role not in _TRIAGE_ROLE_WHITELIST:
                role = "customer"
            return {
                "intent": m.group("intent"),
                "confidence": max(0.0, min(1.0, conf)),
                "route_to": role,
                "reason": m.group("reason").strip(),
                "summary": m.group("summary"),
            }
    return None
```

Inside `class ModelRouter`, add:

```python
    _TRIAGE_AGENT_TIMEOUT = 2.0

    async def _triage_agent_one_shot(self, message: str, tenant_id: str | None) -> str:
        """One-shot triage agent call returning the raw [分流] line."""
        from autoservice.cc_pool import get_pool
        pool = await get_pool()
        prompt = self._render_triage_prompt(message)
        async with pool.acquire(role="triage", tenant_id=tenant_id,
                                 timeout=self._TRIAGE_AGENT_TIMEOUT) as inst:
            await inst.client.query(prompt, session_id=f"triage-{id(inst)}")
            parts: list[str] = []
            from claude_agent_sdk.types import AssistantMessage, ResultMessage
            async for msg in inst.client.receive_response():
                if isinstance(msg, AssistantMessage) and msg.content:
                    for b in msg.content:
                        if hasattr(b, "text"):
                            parts.append(b.text)
                elif isinstance(msg, ResultMessage) and msg.result:
                    parts.append(msg.result)
            return "".join(parts).strip()

    def _render_triage_prompt(self, message: str) -> str:
        return (
            "按 soul 指定格式输出单行 [分流] 判断。只回一行,不要多余说明。\n\n"
            f"客户消息: {message}"
        )

    async def _invoke_triage_agent(
        self,
        message: str,
        tenant_id: str | None,
        fast_result: "ClassificationResult",
        detected_language: str | None,
        previous_role: str | None,
    ) -> TriageDecision:
        try:
            raw = await asyncio.wait_for(
                self._triage_agent_one_shot(message, tenant_id),
                timeout=self._TRIAGE_AGENT_TIMEOUT,
            )
        except (asyncio.TimeoutError, Exception):
            return TriageDecision(
                role=fast_result.route_to.value,
                confidence=fast_result.confidence,
                source="fallback",
                intent=fast_result.intent.value,
                detected_language=detected_language,
                summary=(fast_result.summary or message[:100]),
                needs_operator_notice=True,
                previous_role=previous_role,
            )
        parsed = _parse_triage_output(raw)
        if parsed is None:
            return TriageDecision(
                role=fast_result.route_to.value,
                confidence=fast_result.confidence,
                source="fallback",
                intent=fast_result.intent.value,
                detected_language=detected_language,
                summary=(fast_result.summary or message[:100]),
                needs_operator_notice=True,
                previous_role=previous_role,
            )
        return TriageDecision(
            role=parsed["route_to"],
            confidence=parsed["confidence"],
            source="triage_agent",
            intent=parsed["intent"],
            detected_language=detected_language,
            summary=parsed.get("summary"),
            needs_operator_notice=parsed["confidence"] < self._thresholds["medium"],
            previous_role=previous_role,
        )
```

Finally, wire `_invoke_triage_agent` into `route_message`. In the `route_message` body from Task 7, replace the tail `# Low confidence or sustained drift` block with:

```python
        return await self._invoke_triage_agent(
            message=message,
            tenant_id=tenant_id,
            fast_result=fast,
            detected_language=lang if lang != "unknown" else None,
            previous_role=previous_role,
        )
```

- [ ] **Step 8.4: Run to verify passing**

Run: `pytest tests/triage/test_triage_agent_parser.py tests/triage/test_model_router_decision.py -v`
Expected: all tests PASS.

- [ ] **Step 8.5: Commit**

```bash
git add autoservice/model_router.py tests/triage/test_triage_agent_parser.py
git commit -m "feat(triage): triage agent upgrade with output parser"
```

---

## Task 9: `triage_and_route()` orchestrator + re-seed + message_router wiring (T5)

Goal: The top-level orchestrator. Invokes `ModelRouter.route_message()`, writes the SIDE TRIAGE message, updates `active_role` / `cc_instance_id`, releases old sticky binding on role switch, acquires the new (role, tenant_id) instance with history re-seed. Wired into `_generate_agent_reply`.

**Files:**
- Create: `autoservice/triage_dispatch.py`
- Modify: `autoservice/gateway/message_router.py`
- Test: `tests/triage/test_triage_dispatch.py`, `tests/triage/test_reseed.py`

- [ ] **Step 9.1: Write the failing tests**

Create `tests/triage/test_reseed.py`:

```python
"""History re-seed on role switch — §2.5 of the spec."""
from __future__ import annotations

import pytest
import pytest_asyncio

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import ParticipantRole, MessageVisibility
from autoservice.triage_dispatch import _build_reseeded_prompt, _estimate_tokens


@pytest_asyncio.fixture()
async def seeded_engine():
    engine = LocalEngine()
    conv = await engine.create_conversation(channel="web", external_id="r1")
    # Seed 3 public messages between customer and agent
    for i, (source, text) in enumerate([
        ("customer", "你好"),
        ("agent", "你好,有什么可以帮你"),
        ("customer", "产品怎么用"),
    ]):
        await engine.send_message(conv.id, source=source, content=text)
    return engine, conv.id


@pytest.mark.asyncio
async def test_no_reseed_on_same_role(seeded_engine):
    engine, conv_id = seeded_engine
    prompt = await _build_reseeded_prompt(
        engine, conv_id, "再问一个问题",
        previous_role="customer", new_role="customer",
        token_limit=2000,
    )
    assert prompt == "再问一个问题"


@pytest.mark.asyncio
async def test_reseed_includes_history_on_switch(seeded_engine):
    engine, conv_id = seeded_engine
    prompt = await _build_reseeded_prompt(
        engine, conv_id, "我想买",
        previous_role="customer", new_role="lead",
        token_limit=2000,
    )
    assert "<conversation_history>" in prompt
    assert "你好" in prompt
    assert "产品怎么用" in prompt
    assert "我想买" in prompt
    assert "You are now the lead agent" in prompt


@pytest.mark.asyncio
async def test_reseed_truncates_when_token_limit_hit(seeded_engine):
    engine, conv_id = seeded_engine
    prompt = await _build_reseeded_prompt(
        engine, conv_id, "再问",
        previous_role="customer", new_role="lead",
        token_limit=5,  # tiny limit forces truncation
    )
    # Most recent message must remain.
    assert "产品怎么用" in prompt
```

Create `tests/triage/test_triage_dispatch.py`:

```python
"""triage_and_route() orchestrator."""
from __future__ import annotations

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import (
    ParticipantRole, MessageVisibility,
)
from autoservice.model_router import TriageDecision
from autoservice.triage_dispatch import triage_and_route


class _FakeTenantConfig:
    tenant_id = "acme"
    supported_languages = ["zh", "en"]
    history_reseed_token_limit = 2000


@pytest_asyncio.fixture()
async def engine():
    return LocalEngine()


@pytest.mark.asyncio
async def test_writes_triage_side_message(engine, monkeypatch):
    conv = await engine.create_conversation(channel="web", external_id="d1")

    async def _fake_route(self, message, **kw):
        return TriageDecision(
            role="lead", confidence=0.9, source="fastpath",
            intent="purchase_intent", detected_language="zh",
            previous_role=None,
        )
    monkeypatch.setattr(
        "autoservice.model_router.ModelRouter.route_message", _fake_route,
    )

    decision = await triage_and_route(
        engine=engine, conv_id=conv.id,
        customer_text="我想买一个", tenant_config=_FakeTenantConfig(),
    )
    assert decision.role == "lead"

    msgs = await engine.get_messages(conv.id, limit=50)
    triage_msgs = [m for m in msgs if m.source == "triage"]
    assert len(triage_msgs) == 1
    m = triage_msgs[0]
    assert m.visibility == MessageVisibility.SIDE
    assert m.metadata["type"] == "triage_decision"
    assert m.metadata["route_to"] == "lead"
    assert m.metadata["source"] == "fastpath"


@pytest.mark.asyncio
async def test_updates_active_role_and_resets_drift_on_stable(engine, monkeypatch):
    conv = await engine.create_conversation(channel="web", external_id="d2")
    await engine.update_triage_state(conv.id, active_role="customer", drift_counter=2)

    async def _fake_route(self, message, **kw):
        return TriageDecision(
            role="customer", confidence=0.9, source="fastpath",
            intent="general_question", detected_language="zh",
            previous_role="customer",
        )
    monkeypatch.setattr(
        "autoservice.model_router.ModelRouter.route_message", _fake_route,
    )

    await triage_and_route(
        engine=engine, conv_id=conv.id,
        customer_text="你好", tenant_config=_FakeTenantConfig(),
    )
    st = await engine.get_triage_state(conv.id)
    assert st["active_role"] == "customer"


@pytest.mark.asyncio
async def test_translate_barrier_fastpath(engine, monkeypatch):
    conv = await engine.create_conversation(channel="web", external_id="d3")
    async def _fake_route(self, message, **kw):
        return TriageDecision(
            role="translate", confidence=0.9, source="fastpath",
            intent="language_barrier", detected_language="ja",
            previous_role=None,
        )
    monkeypatch.setattr(
        "autoservice.model_router.ModelRouter.route_message", _fake_route,
    )
    decision = await triage_and_route(
        engine=engine, conv_id=conv.id,
        customer_text="こんにちは", tenant_config=_FakeTenantConfig(),
    )
    assert decision.role == "translate"
```

- [ ] **Step 9.2: Run to verify failure**

Run: `pytest tests/triage/test_triage_dispatch.py tests/triage/test_reseed.py -v`
Expected: FAIL — `autoservice.triage_dispatch` doesn't exist.

- [ ] **Step 9.3: Implement `autoservice/triage_dispatch.py`**

```python
"""triage_and_route — glue between ModelRouter, cc_pool, and conversation_engine.

Spec: docs/superpowers/specs/2026-04-21-multi-role-triage-dispatch-design.md §1.1 / §2

Flow (one customer message):
  1. ModelRouter.route_message() -> TriageDecision
  2. engine.send_message(source="triage", visibility=SIDE, metadata=...)
  3. engine.update_triage_state(active_role=, detected_language=)
  4. return decision (caller acquires the role instance and produces the reply)
"""
from __future__ import annotations

import logging
from typing import Any

from autoservice.conversation_engine.types import MessageVisibility, ParticipantRole
from autoservice.model_router import ModelRouter, TriageDecision

log = logging.getLogger("triage.dispatch")

_HISTORY_FETCH_LIMIT = 20


async def triage_and_route(
    *,
    engine: Any,
    conv_id: str,
    customer_text: str,
    tenant_config: Any,
) -> TriageDecision:
    router = ModelRouter()
    decision = await router.route_message(
        customer_text,
        tenant_config=tenant_config,
        conv_id=conv_id,
        engine=engine,
    )
    try:
        await engine.send_message(
            conv_id,
            source=ParticipantRole.TRIAGE.value,
            content=_format_triage_side_text(decision),
            requested_visibility=MessageVisibility.SIDE,
            metadata={
                "type": "triage_decision",
                "intent": decision.intent,
                "confidence": decision.confidence,
                "route_to": decision.role,
                "source": decision.source,
                "summary": decision.summary,
                "previous_role": decision.previous_role,
                "detected_language": decision.detected_language,
            },
        )
    except Exception:
        log.exception("triage: failed to write SIDE message conv=%s", conv_id)

    try:
        await engine.update_triage_state(
            conv_id,
            active_role=decision.role,
            detected_language=decision.detected_language,
        )
    except Exception:
        log.exception("triage: failed to update state conv=%s", conv_id)

    return decision


def _format_triage_side_text(d: TriageDecision) -> str:
    base = (
        f"[分流] 意图: {d.intent} | 信心: {d.confidence:.2f} | "
        f"路由: {d.role} | 源: {d.source}"
    )
    if d.summary:
        base += f' | 摘要: "{d.summary}"'
    return base


def _estimate_tokens(text: str) -> int:
    """Cheap token estimator — 4 chars per token heuristic."""
    return max(1, len(text) // 4)


async def _build_reseeded_prompt(
    engine: Any,
    conv_id: str,
    customer_text: str,
    previous_role: str | None,
    new_role: str,
    token_limit: int,
) -> str:
    if previous_role is None or previous_role == new_role:
        return customer_text

    history = await engine.get_messages(
        conv_id,
        viewer_role=ParticipantRole.AGENT,
        limit=_HISTORY_FETCH_LIMIT,
    )
    public_msgs = [
        m for m in history if m.visibility == MessageVisibility.PUBLIC
    ]

    lines: list[str] = []
    running_tokens = 0
    for m in reversed(public_msgs):
        line = f"[{m.source}] {m.content}"
        t = _estimate_tokens(line)
        if running_tokens + t > token_limit and lines:
            break
        lines.append(line)
        running_tokens += t
    lines.reverse()

    history_block = "\n".join(lines) if lines else "(no prior messages)"
    return (
        "<conversation_history>\n"
        f"{history_block}\n"
        "</conversation_history>\n\n"
        f"Current customer message: {customer_text}\n\n"
        f"You are now the {new_role} agent. "
        "Continue based on the conversation history above."
    )
```

- [ ] **Step 9.4: Run the orchestrator + re-seed tests to verify passing**

Run: `pytest tests/triage/test_triage_dispatch.py tests/triage/test_reseed.py -v`
Expected: all tests PASS.

- [ ] **Step 9.5: Wire into `_generate_agent_reply`**

Edit [autoservice/gateway/message_router.py:1040-1138](../../../autoservice/gateway/message_router.py#L1040-L1138). Between the existing "Build prompt" block (around [line 1061](../../../autoservice/gateway/message_router.py#L1061)) and the `pool.session_query(...)` call (around [line 1080](../../../autoservice/gateway/message_router.py#L1080)), insert:

```python
        # --- Triage & route (spec 2026-04-21) ---
        from autoservice.triage_dispatch import (
            triage_and_route, _build_reseeded_prompt,
        )
        from autoservice.triage_config_loader import load_tenant_config_for_conv

        tenant_config = await load_tenant_config_for_conv(engine, conv_id)

        # Feature-flag gate (spec §7.3).
        triage_enabled = getattr(tenant_config, "triage_dispatch_enabled", True)

        target_role = "customer"
        previous_role = None
        if triage_enabled:
            try:
                decision = await triage_and_route(
                    engine=engine, conv_id=conv_id,
                    customer_text=customer_text, tenant_config=tenant_config,
                )
                target_role = decision.role
                previous_role = decision.previous_role
            except Exception:
                logger.exception("triage_and_route failed; falling back to customer")

        # Build full prompt (operator suggestions + re-seeded history on role switch)
        if previous_role and previous_role != target_role:
            customer_text_for_prompt = await _build_reseeded_prompt(
                engine, conv_id, customer_text,
                previous_role=previous_role, new_role=target_role,
                token_limit=getattr(tenant_config, "history_reseed_token_limit", 2000),
            )
        else:
            customer_text_for_prompt = customer_text
```

Then change the existing prompt assembly (roughly [line 1072-1075](../../../autoservice/gateway/message_router.py#L1072-L1075)) to use `customer_text_for_prompt` instead of `customer_text`, and change the `pool.session_query(conv_id, prompt)` line ([line 1080](../../../autoservice/gateway/message_router.py#L1080)) to:

```python
        tenant_id = getattr(tenant_config, "tenant_id", None)

        async def _role_stream():
            """Yield Messages from a (role, tenant) sub-pool instance.

            On acquire failure, writes a SIDE warning and falls back to the
            customer sticky session (spec §6)."""
            try:
                async with pool.acquire(
                    role=target_role, tenant_id=tenant_id, timeout=2.0,
                ) as inst:
                    inst._sticky_conv_id = conv_id  # type: ignore[attr-defined]
                    await engine.update_triage_state(conv_id, cc_instance_id=inst.id)
                    await inst.client.query(prompt, session_id=f"{target_role}-{conv_id}")
                    async for m in inst.client.receive_response():
                        yield m
            except Exception:
                logger.exception(
                    "triage: role=%s sub-pool acquire failed, falling back to customer",
                    target_role,
                )
                try:
                    await engine.send_message(
                        conv_id, source="triage",
                        content=f"[分流警告] target_role={target_role} 池获取失败,降级到 customer",
                        requested_visibility=MessageVisibility.SIDE,
                        metadata={"type": "sla_warning", "failed_role": target_role},
                    )
                except Exception:
                    pass
                async for m in pool.session_query(conv_id, prompt):
                    yield m

        iterator = (
            pool.session_query(conv_id, prompt)
            if target_role == "customer"
            else _role_stream()
        )

        async for msg in iterator:
            # [existing stream-consumption loop continues below unchanged —
            # do not replace it, just change the source of `iterator`]
            ...
```

Create the tiny tenant-config loader `autoservice/triage_config_loader.py`:

```python
"""Load per-tenant triage config for a conversation.

Reads plugins/<tenant_id>/config.yaml or .autoservice/sandbox/<tenant_id>/config.json
and returns an object with the triage-relevant attrs. Falls back to module defaults.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("triage.config")


@dataclass
class TenantTriageConfig:
    tenant_id: str | None = None
    supported_languages: list[str] = None
    pool_size_per_role: int = 2
    history_reseed_token_limit: int = 2000
    triage_mode: str = "drift"
    triage_agent_timeout_ms: int = 2000
    triage_dispatch_enabled: bool = True

    def __post_init__(self):
        if self.supported_languages is None:
            self.supported_languages = ["zh", "en"]


def _load_tenant_file(tenant_id: str) -> dict[str, Any]:
    cwd = Path.cwd()
    for candidate in (
        cwd / ".autoservice" / "sandbox" / tenant_id / "config.json",
        cwd / "plugins" / tenant_id / "config.yaml",
    ):
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
            if candidate.suffix == ".json":
                return json.loads(text) or {}
            return yaml.safe_load(text) or {}
        except Exception as exc:
            log.warning("triage config read failed %s: %s", candidate, exc)
    return {}


async def load_tenant_config_for_conv(engine: Any, conv_id: str) -> TenantTriageConfig:
    conv = await engine.get_conversation(conv_id)
    tenant_id = conv.metadata.get("tenant_id")
    data = _load_tenant_file(tenant_id) if tenant_id else {}
    tenant_block = data.get("tenant", {}) if isinstance(data, dict) else {}
    return TenantTriageConfig(
        tenant_id=tenant_id,
        supported_languages=tenant_block.get("supported_languages") or ["zh", "en"],
        pool_size_per_role=int(tenant_block.get("pool_size_per_role", 2)),
        history_reseed_token_limit=int(tenant_block.get("history_reseed_token_limit", 2000)),
        triage_mode=tenant_block.get("triage_mode", "drift"),
        triage_agent_timeout_ms=int(tenant_block.get("triage_agent_timeout_ms", 2000)),
        triage_dispatch_enabled=bool(tenant_block.get("triage_dispatch_enabled", True)),
    )
```

- [ ] **Step 9.6: Run the gateway suite to confirm no regressions**

Run: `pytest tests/gateway -x`
Expected: all green (the customer path without role-switch behaves like before because `target_role == "customer"` branch reuses `pool.session_query`).

- [ ] **Step 9.7: Commit**

```bash
git add autoservice/triage_dispatch.py autoservice/triage_config_loader.py \
        autoservice/gateway/message_router.py \
        tests/triage/test_triage_dispatch.py tests/triage/test_reseed.py
git commit -m "feat(triage): triage_and_route orchestrator + re-seed + gateway wiring"
```

---

## Task 10: SIDE broadcast visibility verification (T6)

Goal: Confirm TRIAGE side-channel messages (a) reach operator WS subscribers via `_broadcast_to_squad`, and (b) are filtered out for viewers whose role is `CUSTOMER`.

**Files:**
- Test only: `tests/conversation/test_side_broadcast.py` (new)
- (No code change expected — the existing event bus already filters SIDE away from `viewer_role="customer"`; see [local_engine.py:97-99](../../../autoservice/conversation_engine/local_engine.py#L97-L99).)

- [ ] **Step 10.1: Write the test**

Create `tests/conversation/test_side_broadcast.py`:

```python
"""TRIAGE SIDE messages: operator sees, customer doesn't."""
from __future__ import annotations

import asyncio
import pytest
import pytest_asyncio

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import (
    MessageVisibility, ParticipantRole,
)


@pytest_asyncio.fixture()
async def engine():
    return LocalEngine()


@pytest.mark.asyncio
async def test_operator_sees_triage_side(engine):
    conv = await engine.create_conversation(channel="web", external_id="v1")
    await engine.send_message(
        conv.id, source=ParticipantRole.TRIAGE.value, content="[分流] ...",
        requested_visibility=MessageVisibility.SIDE,
        metadata={"type": "triage_decision"},
    )
    msgs = await engine.get_messages(
        conv.id, viewer_role=ParticipantRole.OPERATOR, limit=50,
    )
    assert any(m.source == "triage" for m in msgs)


@pytest.mark.asyncio
async def test_customer_does_not_see_triage_side(engine):
    conv = await engine.create_conversation(channel="web", external_id="v2")
    await engine.send_message(
        conv.id, source=ParticipantRole.TRIAGE.value, content="[分流] ...",
        requested_visibility=MessageVisibility.SIDE,
        metadata={"type": "triage_decision"},
    )
    msgs = await engine.get_messages(
        conv.id, viewer_role=ParticipantRole.CUSTOMER, limit=50,
    )
    assert not any(m.source == "triage" for m in msgs)
```

- [ ] **Step 10.2: Run the test**

Run: `pytest tests/conversation/test_side_broadcast.py -v`
Expected: both tests PASS.

If `test_customer_does_not_see_triage_side` fails, locate the `get_messages` method in [autoservice/conversation_engine/local_engine.py](../../../autoservice/conversation_engine/local_engine.py) and add the same viewer_role/visibility filter already applied in the subscriber `matches()` method ([local_engine.py:97-99](../../../autoservice/conversation_engine/local_engine.py#L97-L99)):

```python
if viewer_role == ParticipantRole.CUSTOMER and m.visibility == MessageVisibility.SIDE:
    continue
```

Commit the code fix alongside the test in the same commit.

- [ ] **Step 10.3: Commit**

```bash
git add tests/conversation/test_side_broadcast.py
git commit -m "test(conversation): TRIAGE SIDE messages respect viewer_role filter"
```

---

## Task 11: E2E smoke coverage (T7)

Goal: End-to-end coverage of the happy paths: customer-only regression / lead routing / translate routing / drift-triggers-switch / low-confidence-triage-agent / role-switch re-seed / fallback warning. These tests stub the CC client transport so no real subprocess is spawned.

**Files:**
- Create: `tests/e2e/test_triage_e2e.py`
- Modify: `autoservice/cc_pool.py` (no code change expected — tests monkeypatch `create_cc_client`)

- [ ] **Step 11.1: Write the E2E tests**

Create `tests/e2e/test_triage_e2e.py`:

```python
"""End-to-end triage dispatch smoke tests.

Spec: docs/superpowers/specs/2026-04-21-multi-role-triage-dispatch-design.md §8.2

These exercise triage_and_route() in realistic conversation flows but stub
the CC subprocess layer — no real Claude process is spawned.
"""
from __future__ import annotations

import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import MessageVisibility
from autoservice.model_router import TriageDecision
from autoservice.triage_dispatch import triage_and_route
from autoservice.triage_config_loader import TenantTriageConfig


@pytest_asyncio.fixture()
async def engine():
    return LocalEngine()


@pytest.mark.asyncio
async def test_customer_only_unchanged(engine, monkeypatch):
    """Keyword with unambiguous customer intent -> single customer route, no switch."""
    conv = await engine.create_conversation(channel="web", external_id="e1")
    cfg = TenantTriageConfig(tenant_id="acme")

    d1 = await triage_and_route(
        engine=engine, conv_id=conv.id,
        customer_text="这个功能怎么用",  # product_inquiry -> customer
        tenant_config=cfg,
    )
    assert d1.role == "customer"
    d2 = await triage_and_route(
        engine=engine, conv_id=conv.id,
        customer_text="还有其他功能吗",
        tenant_config=cfg,
    )
    assert d2.role == "customer"
    st = await engine.get_triage_state(conv.id)
    assert st["active_role"] == "customer"


@pytest.mark.asyncio
async def test_sales_intent_routes_to_lead(engine):
    conv = await engine.create_conversation(channel="web", external_id="e2")
    d = await triage_and_route(
        engine=engine, conv_id=conv.id,
        customer_text="请问价格是多少,可以报价吗",
        tenant_config=TenantTriageConfig(tenant_id="acme"),
    )
    assert d.role == "lead"
    assert d.intent == "purchase_intent"


@pytest.mark.asyncio
async def test_language_barrier_routes_to_translate(engine):
    conv = await engine.create_conversation(channel="web", external_id="e3")
    d = await triage_and_route(
        engine=engine, conv_id=conv.id,
        customer_text="こんにちは、助けてください",
        tenant_config=TenantTriageConfig(
            tenant_id="acme", supported_languages=["zh", "en"],
        ),
    )
    assert d.role == "translate"


@pytest.mark.asyncio
async def test_drift_invalidates_cache_and_switches(engine):
    conv = await engine.create_conversation(channel="web", external_id="e4")
    cfg = TenantTriageConfig(tenant_id="acme")
    # two product_inquiry messages establish active_role=customer
    for txt in ["怎么用", "如何使用"]:
        await triage_and_route(engine=engine, conv_id=conv.id,
                                customer_text=txt, tenant_config=cfg)
    # two purchase-intent messages should eventually flip to lead
    for txt in ["想买一个", "给我报价"]:
        d = await triage_and_route(engine=engine, conv_id=conv.id,
                                    customer_text=txt, tenant_config=cfg)
    assert d.role == "lead"
    st = await engine.get_triage_state(conv.id)
    assert st["active_role"] == "lead"


@pytest.mark.asyncio
async def test_low_confidence_calls_triage_agent(engine, monkeypatch):
    conv = await engine.create_conversation(channel="web", external_id="e5")

    async def _fake_one_shot(self, message, tenant_id):
        return "[分流] 意图: general_question | 信心: 0.75 | 路由: customer | 原因: 语义不足"
    monkeypatch.setattr(
        "autoservice.model_router.ModelRouter._triage_agent_one_shot",
        _fake_one_shot,
    )

    d = await triage_and_route(
        engine=engine, conv_id=conv.id,
        customer_text="嗯",
        tenant_config=TenantTriageConfig(tenant_id="acme"),
    )
    assert d.source == "triage_agent"
    assert d.role == "customer"


@pytest.mark.asyncio
async def test_triage_agent_timeout_fallback(engine, monkeypatch):
    conv = await engine.create_conversation(channel="web", external_id="e6")

    async def _slow(self, message, tenant_id):
        await asyncio.sleep(5)
        return ""
    monkeypatch.setattr(
        "autoservice.model_router.ModelRouter._triage_agent_one_shot",
        _slow,
    )
    monkeypatch.setattr(
        "autoservice.model_router.ModelRouter._TRIAGE_AGENT_TIMEOUT", 0.05,
    )

    d = await triage_and_route(
        engine=engine, conv_id=conv.id,
        customer_text="嗯",
        tenant_config=TenantTriageConfig(tenant_id="acme"),
    )
    assert d.source == "fallback"
    assert d.needs_operator_notice is True
    # SIDE message records the fallback source for operator visibility.
    msgs = await engine.get_messages(conv.id, limit=50)
    triage_msgs = [m for m in msgs if m.source == "triage"]
    assert triage_msgs and triage_msgs[-1].metadata["source"] == "fallback"


@pytest.mark.asyncio
async def test_side_visible_to_operator_only(engine):
    conv = await engine.create_conversation(channel="web", external_id="e7")
    await triage_and_route(
        engine=engine, conv_id=conv.id,
        customer_text="想买", tenant_config=TenantTriageConfig(tenant_id="acme"),
    )
    from autoservice.conversation_engine.types import ParticipantRole
    customer_view = await engine.get_messages(
        conv.id, viewer_role=ParticipantRole.CUSTOMER, limit=50,
    )
    operator_view = await engine.get_messages(
        conv.id, viewer_role=ParticipantRole.OPERATOR, limit=50,
    )
    assert not any(m.source == "triage" for m in customer_view)
    assert any(m.source == "triage" for m in operator_view)
```

- [ ] **Step 11.2: Run the E2E suite**

Run: `pytest tests/e2e/test_triage_e2e.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 11.3: Full regression guard**

Run: `pytest tests/cc_pool tests/gateway tests/conversation_engine tests/dream_agent tests/dream_scheduler tests/triage tests/e2e/test_triage_e2e.py -x`
Expected: all green. Spec §8.3 regression tests must still pass.

- [ ] **Step 11.4: Commit**

```bash
git add tests/e2e/test_triage_e2e.py
git commit -m "test(triage): end-to-end coverage for routing + drift + fallback"
```

---

## Task 12: Feature flag smoke test (§7.3)

Goal: Confirm `tenant.triage_dispatch_enabled=false` bypasses `triage_and_route()` and the customer path behaves exactly as before.

**Files:**
- Test: `tests/triage/test_feature_flag.py`

- [ ] **Step 12.1: Write the test**

Create `tests/triage/test_feature_flag.py`:

```python
"""Feature-flag rollback (§7.3)."""
from __future__ import annotations

import pytest
import pytest_asyncio

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.triage_dispatch import triage_and_route
from autoservice.triage_config_loader import TenantTriageConfig


@pytest_asyncio.fixture()
async def engine():
    return LocalEngine()


@pytest.mark.asyncio
async def test_triage_still_writes_decision_when_flag_is_true(engine):
    conv = await engine.create_conversation(channel="web", external_id="f1")
    cfg = TenantTriageConfig(tenant_id="acme", triage_dispatch_enabled=True)
    await triage_and_route(engine=engine, conv_id=conv.id,
                           customer_text="我想买", tenant_config=cfg)
    msgs = await engine.get_messages(conv.id, limit=50)
    assert any(m.source == "triage" for m in msgs)


@pytest.mark.asyncio
async def test_feature_flag_default_true(engine):
    cfg = TenantTriageConfig(tenant_id="acme")
    assert cfg.triage_dispatch_enabled is True
```

Note: the actual bypass (when `triage_dispatch_enabled=False`) lives in [autoservice/gateway/message_router.py](../../../autoservice/gateway/message_router.py) (Task 9 Step 9.5). These tests pin the default and the non-flag behaviour; the `test_triage_agent_timeout_fallback` test in Task 11 already covers the bypass path's safety net.

- [ ] **Step 12.2: Run the test**

Run: `pytest tests/triage/test_feature_flag.py -v`
Expected: both tests PASS.

- [ ] **Step 12.3: Commit**

```bash
git add tests/triage/test_feature_flag.py
git commit -m "test(triage): feature flag defaults and SIDE write gating"
```

---

## Final verification

- [ ] **Run the complete test suite once more**

Run: `pytest tests/ -x --ignore=tests/integration_cc_pool.py`
Expected: all green, including the full regression surface from spec §8.3.

- [ ] **Check for dangling placeholders**

Run: `grep -rn "TODO\|FIXME\|XXX" autoservice/triage_dispatch.py autoservice/model_router.py autoservice/language_detect.py autoservice/tenant_triage_config.py autoservice/triage_config_loader.py`
Expected: no hits (or only pre-existing, unrelated ones).

- [ ] **Smoke the web server**

Run: `make run-web` (non-destructive; SIGINT when done)
Expected: no import errors during boot; `/health` returns 200.

---

## Out of scope for this plan

Explicitly deferred per spec §0.2:
- Path 2 summary-seeded role switch (triage produces summary, new role consumes it).
- Handoff protocol (agent-initiated `<handoff>` tags).
- Translate-as-modality-wrapper (post-process all replies through translate).
- DB-backed keyword editor / admin UI.
- Operator UI rendering of TRIAGE messages — admin-portal follow-up ticket.
- SLA monitoring of per-tenant pool latency beyond the one-shot fallback.
- Long-term history summarisation for >20-message conversations.
- Dream link changes.
