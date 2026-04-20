# Takeover Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let operator release a `/hijack`-ed conversation back to AI, either manually (button) or automatically (silence 30s → COPILOT, WS offline 30s grace → AUTO) with a 5-second warning before the silence auto-release fires.

**Architecture:** Backend stores `takeover_operator_id` on `Conversation`; `LocalEngine` arms a two-stage idle timer on `/hijack` (warning frame + release) and resets it on messages from the takeover operator. A new `OfflineWatcher` tracks operator WS connect/disconnect and flips TAKEOVER conversations to AUTO after a grace period. The frontend `HijackButton` becomes dual-state (抢单 ↔ 释放回 AI) driven by the conversation mode, and a `TakeoverWarning` banner shows on warning frames with "继续" / "释放" actions.

**Tech Stack:** Python 3.11 + FastAPI + asyncio (backend); React + TypeScript + Zustand + antd + Vite (frontend); pytest (backend tests); vitest (frontend tests).

**Spec:** `docs/superpowers/specs/2026-04-17-takeover-release-design.md`

---

## Notes for the Engineer

- **Working dir:** `d:\Work\h2os.cloud\AutoService-dev-a` (git branch `dev-a`).
- **Run backend tests:** `uv run pytest tests/gateway/test_takeover_release.py -v`
- **Run frontend tests:** `cd frontend && pnpm -r --filter @autoservice/operator-console test`
- **Restart dev stack:** `make start` (port 8000 gateway, 5173/5174/5175 frontends)
- **Conventional commits** — `feat:`, `test:`, `refactor:` etc. One commit per completed task.
- **Do NOT revert existing debug prints** in `autoservice/gateway/message_router.py` (`[SUB]` / `[BCAST]`) — a separate cleanup will remove them.
- Engine uses `asyncio.Lock` per-conversation for mode transitions. Add any new timer-management logic inside or coordinated with this lock.

---

## Task 1 — Add `takeover_operator_id` to `Conversation` dataclass

**Files:**
- Modify: `autoservice/conversation_engine/types.py:77-86`
- Test: `tests/conversation_engine/test_types.py` (new file or append existing)

- [ ] **Step 1.1: Write failing test** `tests/conversation_engine/test_types.py`

```python
from datetime import datetime, timezone
from autoservice.conversation_engine.types import (
    Conversation, ConversationMode, ConversationState,
)

def test_conversation_has_takeover_operator_id_field_defaulting_to_none():
    now = datetime.now(timezone.utc)
    conv = Conversation(
        id="web_x",
        state=ConversationState.CREATED,
        mode=ConversationMode.AUTO,
        participants=(),
        created_at=now,
        updated_at=now,
    )
    assert conv.takeover_operator_id is None


def test_conversation_takeover_operator_id_can_be_set():
    now = datetime.now(timezone.utc)
    conv = Conversation(
        id="web_x",
        state=ConversationState.CREATED,
        mode=ConversationMode.TAKEOVER,
        participants=(),
        created_at=now,
        updated_at=now,
        takeover_operator_id="op-42",
    )
    assert conv.takeover_operator_id == "op-42"
```

- [ ] **Step 1.2: Run — expect failure**

Run: `uv run pytest tests/conversation_engine/test_types.py -v`
Expected: FAIL — `TypeError: Conversation.__init__() got an unexpected keyword argument 'takeover_operator_id'`

- [ ] **Step 1.3: Add the field**

Edit `autoservice/conversation_engine/types.py:77-86`:

```python
@dataclass(frozen=True)
class Conversation:
    id: str
    state: ConversationState
    mode: ConversationMode
    participants: tuple[Participant, ...]
    created_at: datetime
    updated_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)
    resolution: Resolution | None = None
    takeover_operator_id: str | None = None
```

- [ ] **Step 1.4: Run — expect pass**

Run: `uv run pytest tests/conversation_engine/test_types.py -v`
Expected: 2 passed.

- [ ] **Step 1.5: Regression run on engine tests**

Run: `uv run pytest tests/conversation_engine/ -v --timeout=10`
Expected: all previously-passing tests still pass. (The new field is optional so existing callers are unaffected.)

- [ ] **Step 1.6: Commit**

```bash
git add autoservice/conversation_engine/types.py tests/conversation_engine/test_types.py
git commit -m "feat(engine): add Conversation.takeover_operator_id field"
```

---

## Task 2 — `switch_mode` accepts and persists `takeover_operator_id`

**Files:**
- Modify: `autoservice/conversation_engine/local_engine.py` `switch_mode` (around line 396) and `handle_command("/hijack")` (around line 572)
- Test: `tests/conversation_engine/test_takeover_operator_id.py` (new)

- [ ] **Step 2.1: Write failing test** `tests/conversation_engine/test_takeover_operator_id.py`

```python
import pytest
from datetime import datetime, timezone

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import (
    ConversationMode, Participant, ParticipantRole,
)


@pytest.fixture
async def engine_with_conv():
    eng = LocalEngine()
    conv = await eng.create_conversation(channel="web", external_id="x")
    now = datetime.now(timezone.utc)
    await eng.join(conv.id, Participant(id="cust1", role=ParticipantRole.CUSTOMER, joined_at=now))
    await eng.join(conv.id, Participant(id="op42", role=ParticipantRole.OPERATOR, joined_at=now))
    return eng, conv.id


@pytest.mark.asyncio
async def test_hijack_sets_takeover_operator_id(engine_with_conv):
    eng, cid = engine_with_conv
    await eng.handle_command(cid, actor_id="op42", command="/hijack")
    conv = await eng.get_conversation(cid)
    assert conv.mode == ConversationMode.TAKEOVER
    assert conv.takeover_operator_id == "op42"


@pytest.mark.asyncio
async def test_release_clears_takeover_operator_id(engine_with_conv):
    eng, cid = engine_with_conv
    await eng.handle_command(cid, actor_id="op42", command="/hijack")
    await eng.handle_command(cid, actor_id="op42", command="/release")
    conv = await eng.get_conversation(cid)
    assert conv.mode == ConversationMode.AUTO
    assert conv.takeover_operator_id is None


@pytest.mark.asyncio
async def test_mode_changed_event_includes_takeover_operator_id(engine_with_conv):
    eng, cid = engine_with_conv
    await eng.handle_command(cid, actor_id="op42", command="/hijack")
    events = await eng.query_events(cid, types=["mode.changed"])
    ev = events[-1]
    assert ev.data["new_mode"] == "takeover"
    assert ev.data["takeover_operator_id"] == "op42"

    await eng.handle_command(cid, actor_id="op42", command="/release")
    events = await eng.query_events(cid, types=["mode.changed"])
    ev = events[-1]
    assert ev.data["new_mode"] == "auto"
    assert ev.data["takeover_operator_id"] is None
```

- [ ] **Step 2.2: Run — expect failure**

Run: `uv run pytest tests/conversation_engine/test_takeover_operator_id.py -v`
Expected: FAIL — `takeover_operator_id` field not being populated / event data missing key.

- [ ] **Step 2.3: Modify `switch_mode` signature & body**

Replace the body of `switch_mode` in `autoservice/conversation_engine/local_engine.py` (around line 396):

```python
async def switch_mode(
    self,
    conversation_id: str,
    target: ConversationMode,
    *,
    triggered_by: str,
    trigger: str,
    takeover_operator_id: str | None = None,
) -> None:
    async with self._get_lock(conversation_id):
        conv = self._get_conv(conversation_id)
        if conv.state == ConversationState.CLOSED:
            raise IllegalModeTransition(
                f"Cannot change mode on closed conversation {conversation_id}"
            )
        if conv.mode == target:
            self._emit(EventType.MODE_NOOP, conversation_id, {
                "target": target.value, "trigger": trigger,
            })
            return
        old_mode = conv.mode

        # Atomically update mode and takeover_operator_id
        new_takeover_id: str | None
        if target == ConversationMode.TAKEOVER:
            new_takeover_id = takeover_operator_id
        else:
            new_takeover_id = None
        updated = self._update_conv(
            conversation_id,
            mode=target,
            takeover_operator_id=new_takeover_id,
        )
        await self._emit_and_dispatch_hooks(
            EventType.MODE_CHANGED, conversation_id, {
                "old_mode": old_mode.value,
                "new_mode": target.value,
                "triggered_by": triggered_by,
                "trigger": trigger,
                "takeover_operator_id": new_takeover_id,
            },
            "on_mode_changed", updated, old_mode, target, trigger,
        )
```

- [ ] **Step 2.4: Modify `handle_command("/hijack")` branch**

In `handle_command` (around line 572), replace the `/hijack` branch:

```python
if command == "/hijack":
    await self.switch_mode(
        conversation_id, ConversationMode.TAKEOVER,
        triggered_by=actor_id, trigger="/hijack",
        takeover_operator_id=actor_id,
    )
```

(Do NOT change `/release` / `/copilot` — they pass `takeover_operator_id=None` by default, which clears the field.)

- [ ] **Step 2.5: Run — expect pass**

Run: `uv run pytest tests/conversation_engine/test_takeover_operator_id.py -v`
Expected: 3 passed.

- [ ] **Step 2.6: Regression**

Run: `uv run pytest tests/conversation_engine/ tests/gateway/ -v --timeout=15`
Expected: all pass. Any test asserting exact `mode.changed` event data will need updating — if found, update the assertion to allow/expect the new `takeover_operator_id` key.

- [ ] **Step 2.7: Commit**

```bash
git add autoservice/conversation_engine/local_engine.py tests/conversation_engine/test_takeover_operator_id.py
git commit -m "feat(engine): switch_mode atomically updates takeover_operator_id"
```

---

## Task 3 — Takeover config loading + default

**Files:**
- Create: `autoservice/takeover_config.py`
- Modify: `.autoservice/config.local.yaml.example`
- Test: `tests/test_takeover_config.py` (new)

- [ ] **Step 3.1: Write failing test** `tests/test_takeover_config.py`

```python
import textwrap
from pathlib import Path

from autoservice.takeover_config import (
    TakeoverConfig, DEFAULT_TAKEOVER_CONFIG, load_takeover_config,
)


def test_default_values():
    assert DEFAULT_TAKEOVER_CONFIG.idle_timeout_ms == 30_000
    assert DEFAULT_TAKEOVER_CONFIG.warning_ms == 5_000
    assert DEFAULT_TAKEOVER_CONFIG.offline_grace_ms == 30_000


def test_load_from_dict_overrides_defaults():
    raw = {"takeover": {"idle_timeout_ms": 5000, "warning_ms": 1000}}
    cfg = load_takeover_config(raw)
    assert cfg.idle_timeout_ms == 5000
    assert cfg.warning_ms == 1000
    assert cfg.offline_grace_ms == 30_000  # default preserved


def test_load_from_missing_section_returns_default():
    cfg = load_takeover_config({})
    assert cfg == DEFAULT_TAKEOVER_CONFIG


def test_load_from_none_returns_default():
    cfg = load_takeover_config(None)
    assert cfg == DEFAULT_TAKEOVER_CONFIG


def test_load_from_file(tmp_path: Path):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent("""
        takeover:
          idle_timeout_ms: 7000
          warning_ms: 2000
          offline_grace_ms: 10000
    """))
    cfg = load_takeover_config(p)
    assert cfg.idle_timeout_ms == 7000
    assert cfg.warning_ms == 2000
    assert cfg.offline_grace_ms == 10000


def test_load_from_missing_file_returns_default(tmp_path: Path):
    cfg = load_takeover_config(tmp_path / "does-not-exist.yaml")
    assert cfg == DEFAULT_TAKEOVER_CONFIG
```

- [ ] **Step 3.2: Run — expect failure**

Run: `uv run pytest tests/test_takeover_config.py -v`
Expected: FAIL — module `autoservice.takeover_config` does not exist.

- [ ] **Step 3.3: Implement `autoservice/takeover_config.py`**

```python
"""Takeover/release configuration loading.

Resolves from .autoservice/config.local.yaml 'takeover' section, falling
back to hardcoded defaults so dev environments work without a config file.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from socialware.config import load_config


@dataclass(frozen=True)
class TakeoverConfig:
    idle_timeout_ms: int = 30_000
    warning_ms: int = 5_000
    offline_grace_ms: int = 30_000


DEFAULT_TAKEOVER_CONFIG = TakeoverConfig()


def load_takeover_config(source: Path | Mapping[str, Any] | None) -> TakeoverConfig:
    """Load takeover config from a yaml path OR a parsed dict. None / missing → defaults."""
    if source is None:
        return DEFAULT_TAKEOVER_CONFIG

    if isinstance(source, Path):
        if not source.exists():
            return DEFAULT_TAKEOVER_CONFIG
        try:
            raw = load_config(source)
        except Exception:
            return DEFAULT_TAKEOVER_CONFIG
    else:
        raw = source

    section = (raw or {}).get("takeover") or {}
    return TakeoverConfig(
        idle_timeout_ms=int(section.get("idle_timeout_ms", DEFAULT_TAKEOVER_CONFIG.idle_timeout_ms)),
        warning_ms=int(section.get("warning_ms", DEFAULT_TAKEOVER_CONFIG.warning_ms)),
        offline_grace_ms=int(section.get("offline_grace_ms", DEFAULT_TAKEOVER_CONFIG.offline_grace_ms)),
    )
```

- [ ] **Step 3.4: Run — expect pass**

Run: `uv run pytest tests/test_takeover_config.py -v`
Expected: 6 passed.

- [ ] **Step 3.5: Update `.autoservice/config.local.yaml.example`**

Append to the file:

```yaml

# ─── Takeover（接管/释放）配置 ─────────────────────────
# Operator /hijack 后如何自动释放回 AI
takeover:
  idle_timeout_ms: 30000      # /hijack 后静默多久触发自动释放（含 warning 阶段）
  warning_ms: 5000            # 预警阶段长度（warning → release 之间的缓冲）
  offline_grace_ms: 30000     # operator WS 断开多久算真正离线
```

- [ ] **Step 3.6: Commit**

```bash
git add autoservice/takeover_config.py tests/test_takeover_config.py .autoservice/config.local.yaml.example
git commit -m "feat(config): add takeover config loading with defaults"
```

---

## Task 4 — Idle release timer scheduling (engine side)

**Files:**
- Modify: `autoservice/conversation_engine/local_engine.py` (`LocalEngine.__init__`, `handle_command`, new `_arm/_reset/_cancel_takeover_timer` helpers)
- Modify: `autoservice/conversation_engine/protocol.py` (callback signature for timer notifications — see below)
- Test: `tests/conversation_engine/test_takeover_timer.py` (new)

The engine emits a **TIMER event** for the two timers (`takeover_warning_<cid>`, `takeover_release_<cid>`). We wire the actual "push WS frame" in Task 5 via a `notify_fn` callback passed to `LocalEngine` — here we just produce the timer emissions, reset API, and mode transition.

- [ ] **Step 4.1: Write failing test** `tests/conversation_engine/test_takeover_timer.py`

```python
import asyncio
import pytest
from datetime import datetime, timezone

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import (
    ConversationMode, Participant, ParticipantRole,
)
from autoservice.takeover_config import TakeoverConfig


@pytest.fixture
async def engine_with_conv():
    """LocalEngine configured with a fast takeover timer (100ms idle, 30ms warning)."""
    cfg = TakeoverConfig(idle_timeout_ms=100, warning_ms=30, offline_grace_ms=200)
    eng = LocalEngine(config={"takeover": cfg})
    conv = await eng.create_conversation(channel="web", external_id="x")
    now = datetime.now(timezone.utc)
    await eng.join(conv.id, Participant(id="cust1", role=ParticipantRole.CUSTOMER, joined_at=now))
    await eng.join(conv.id, Participant(id="op42", role=ParticipantRole.OPERATOR, joined_at=now))
    return eng, conv.id


@pytest.mark.asyncio
async def test_hijack_arms_warning_and_release_timers(engine_with_conv):
    eng, cid = engine_with_conv
    # callbacks captured
    warnings: list[dict] = []
    eng.on_takeover_warning(lambda ev: warnings.append(ev))

    await eng.handle_command(cid, actor_id="op42", command="/hijack")
    # Wait for warning (idle - warning = 70ms) + release (30ms) = ~100ms total
    await asyncio.sleep(0.2)

    conv = await eng.get_conversation(cid)
    assert conv.mode == ConversationMode.COPILOT
    assert conv.takeover_operator_id is None
    assert len(warnings) == 1
    assert warnings[0]["conversation_id"] == cid
    assert warnings[0]["operator_id"] == "op42"
    assert warnings[0]["remaining_ms"] == 30


@pytest.mark.asyncio
async def test_operator_message_resets_takeover_timer(engine_with_conv):
    eng, cid = engine_with_conv
    warnings: list[dict] = []
    cancels: list[str] = []
    eng.on_takeover_warning(lambda ev: warnings.append(ev))
    eng.on_takeover_warning_cancelled(lambda ev: cancels.append(ev["conversation_id"]))

    await eng.handle_command(cid, actor_id="op42", command="/hijack")
    # Wait 80ms (past warning trigger at 70ms) so warning fires
    await asyncio.sleep(0.08)
    assert len(warnings) == 1
    # Now operator types — must reset
    await eng.send_message(cid, source="op42", content="hi")
    # We should see a cancelled notification
    await asyncio.sleep(0.01)
    assert cancels == [cid]
    # Wait another 50ms — should NOT have auto-released yet (timer restarted)
    await asyncio.sleep(0.05)
    conv = await eng.get_conversation(cid)
    assert conv.mode == ConversationMode.TAKEOVER


@pytest.mark.asyncio
async def test_non_takeover_operator_message_does_not_reset(engine_with_conv):
    eng, cid = engine_with_conv
    now = datetime.now(timezone.utc)
    await eng.join(cid, Participant(id="op99", role=ParticipantRole.OPERATOR, joined_at=now))
    await eng.handle_command(cid, actor_id="op42", command="/hijack")

    # op99 (NOT the takeover operator) sends a message
    await asyncio.sleep(0.05)
    await eng.send_message(cid, source="op99", content="hi from another op")
    # Total elapsed once timers expire will be ~100ms+
    await asyncio.sleep(0.2)

    conv = await eng.get_conversation(cid)
    assert conv.mode == ConversationMode.COPILOT  # auto-released


@pytest.mark.asyncio
async def test_release_command_cancels_timers(engine_with_conv):
    eng, cid = engine_with_conv
    warnings: list[dict] = []
    eng.on_takeover_warning(lambda ev: warnings.append(ev))

    await eng.handle_command(cid, actor_id="op42", command="/hijack")
    await eng.handle_command(cid, actor_id="op42", command="/release")
    # Wait past the would-be timer expiry
    await asyncio.sleep(0.2)

    # No warning should have fired since we released before 70ms
    assert warnings == []
    conv = await eng.get_conversation(cid)
    assert conv.mode == ConversationMode.AUTO


@pytest.mark.asyncio
async def test_continue_ack_resets_timer(engine_with_conv):
    eng, cid = engine_with_conv
    warnings: list[dict] = []
    cancels: list[str] = []
    eng.on_takeover_warning(lambda ev: warnings.append(ev))
    eng.on_takeover_warning_cancelled(lambda ev: cancels.append(ev["conversation_id"]))

    await eng.handle_command(cid, actor_id="op42", command="/hijack")
    await asyncio.sleep(0.08)  # past warning
    assert len(warnings) == 1

    await eng.reset_takeover_timer(cid, actor_id="op42")
    await asyncio.sleep(0.01)
    assert cancels == [cid]
    # Verify timer is really fresh: wait just past previous (expired) timeline
    await asyncio.sleep(0.05)
    conv = await eng.get_conversation(cid)
    assert conv.mode == ConversationMode.TAKEOVER
```

- [ ] **Step 4.2: Run — expect failure**

Run: `uv run pytest tests/conversation_engine/test_takeover_timer.py -v`
Expected: FAIL — `on_takeover_warning` etc. don't exist.

- [ ] **Step 4.3: Edit `LocalEngine.__init__`**

Replace (around line 110):

```python
def __init__(self, config: Mapping[str, Any] | None = None) -> None:
    self._config = dict(config or {})
    # Takeover config (loaded from app or defaults)
    from autoservice.takeover_config import DEFAULT_TAKEOVER_CONFIG, TakeoverConfig
    tk_cfg = self._config.get("takeover")
    self._takeover_config: TakeoverConfig = (
        tk_cfg if isinstance(tk_cfg, TakeoverConfig) else DEFAULT_TAKEOVER_CONFIG
    )
    # Notification callbacks (set externally via on_takeover_warning / on_takeover_warning_cancelled)
    self._takeover_warning_cb = None
    self._takeover_cancel_cb = None
    # Core storage
    self._conversations: dict[str, Conversation] = {}
    self._participants: dict[str, list[Participant]] = {}
    self._messages: dict[str, list[Message]] = {}
    self._seq: dict[str, int] = {}
    self._event_seq: dict[str, int] = {}
    self._mode_locks: dict[str, asyncio.Lock] = {}
    self._subscribers: list[_Subscriber] = []
    self._events: dict[str, list[Event]] = {}
    self._timers: dict[str, dict[str, tuple[Timer, asyncio.Task]]] = {}
    # Takeover timer tasks: conv_id → (warning_task, release_task, warning_fired: bool)
    self._takeover_tasks: dict[str, dict[str, Any]] = {}
    self._hooks: list[PluginHook] = []
```

- [ ] **Step 4.4: Add callback registration + reset/cancel API**

Add these methods to `LocalEngine` (anywhere after `__init__`, before `handle_command`):

```python
# ---------- Takeover timer (auto-release) ----------

def on_takeover_warning(self, cb) -> None:
    """Register callback invoked when takeover warning phase fires.

    Callback receives dict: {conversation_id, operator_id, remaining_ms, reason}.
    """
    self._takeover_warning_cb = cb

def on_takeover_warning_cancelled(self, cb) -> None:
    """Register callback invoked when a fired warning is subsequently cancelled."""
    self._takeover_cancel_cb = cb

def _arm_takeover_timer(self, conversation_id: str, operator_id: str) -> None:
    """Schedule warning and release tasks. Cancels any existing ones first."""
    self._cancel_takeover_timer(conversation_id)
    cfg = self._takeover_config
    warning_delay = max(0, cfg.idle_timeout_ms - cfg.warning_ms) / 1000.0
    release_delay = cfg.warning_ms / 1000.0

    state: dict[str, Any] = {"warning_fired": False}

    async def _warning():
        try:
            await asyncio.sleep(warning_delay)
        except asyncio.CancelledError:
            return
        state["warning_fired"] = True
        if self._takeover_warning_cb:
            try:
                self._takeover_warning_cb({
                    "conversation_id": conversation_id,
                    "operator_id": operator_id,
                    "remaining_ms": cfg.warning_ms,
                    "reason": "idle",
                })
            except Exception:
                log.exception("takeover_warning callback failed")
        # Arm release task
        state["release_task"] = asyncio.create_task(
            _release(), name=f"takeover-release-{conversation_id}",
        )

    async def _release():
        try:
            await asyncio.sleep(release_delay)
        except asyncio.CancelledError:
            return
        try:
            await self.switch_mode(
                conversation_id, ConversationMode.COPILOT,
                triggered_by="__system__", trigger="auto:idle_timeout",
            )
        except Exception:
            log.exception("auto-release switch_mode failed")

    state["warning_task"] = asyncio.create_task(
        _warning(), name=f"takeover-warning-{conversation_id}",
    )
    self._takeover_tasks[conversation_id] = state

def _cancel_takeover_timer(self, conversation_id: str) -> bool:
    """Cancel any pending warning/release tasks. Returns True if warning had fired."""
    state = self._takeover_tasks.pop(conversation_id, None)
    if state is None:
        return False
    for key in ("warning_task", "release_task"):
        t = state.get(key)
        if t and not t.done():
            t.cancel()
    return bool(state.get("warning_fired"))

async def reset_takeover_timer(self, conversation_id: str, *, actor_id: str) -> None:
    """Re-arm the timer; notify cancellation callback if warning had already fired."""
    conv = self._get_conv(conversation_id)
    if conv.mode != ConversationMode.TAKEOVER or conv.takeover_operator_id != actor_id:
        return
    warning_had_fired = self._cancel_takeover_timer(conversation_id)
    if warning_had_fired and self._takeover_cancel_cb:
        try:
            self._takeover_cancel_cb({"conversation_id": conversation_id})
        except Exception:
            log.exception("takeover_cancel callback failed")
    self._arm_takeover_timer(conversation_id, actor_id)
```

- [ ] **Step 4.5: Hook `/hijack` to arm, `/release` + `/copilot` + `/resolve` to cancel**

Replace the `/hijack` branch in `handle_command` (around line 572):

```python
if command == "/hijack":
    await self.switch_mode(
        conversation_id, ConversationMode.TAKEOVER,
        triggered_by=actor_id, trigger="/hijack",
        takeover_operator_id=actor_id,
    )
    self._arm_takeover_timer(conversation_id, actor_id)
```

For `/release`, `/copilot` branches: add `self._cancel_takeover_timer(conversation_id)` BEFORE the `switch_mode` call. For `/resolve` and `/abandon`: add the same cancel before the `close_conversation` call.

Example `/release`:

```python
elif command == "/release":
    self._cancel_takeover_timer(conversation_id)
    await self.switch_mode(
        conversation_id, ConversationMode.AUTO,
        triggered_by=actor_id, trigger="/release",
    )
```

- [ ] **Step 4.6: Hook `send_message` to reset timer for takeover operator**

In `send_message` (around line 429-455), after message is appended and BEFORE the `_emit_and_dispatch_hooks` call (or right after, doesn't matter — just outside the critical storage mutation), add:

```python
# Auto-release reset: if takeover operator is the sender, reset timer
if (conv.mode == ConversationMode.TAKEOVER
        and conv.takeover_operator_id is not None
        and source == conv.takeover_operator_id):
    await self.reset_takeover_timer(conversation_id, actor_id=source)
```

- [ ] **Step 4.7: Run — expect pass**

Run: `uv run pytest tests/conversation_engine/test_takeover_timer.py -v`
Expected: 5 passed. (Tests use ~100-300ms total; if flaky, bump sleep values in test fixture by 50%.)

- [ ] **Step 4.8: Regression**

Run: `uv run pytest tests/conversation_engine/ tests/gateway/ -v --timeout=15`
Expected: all pass.

- [ ] **Step 4.9: Commit**

```bash
git add autoservice/conversation_engine/local_engine.py tests/conversation_engine/test_takeover_timer.py
git commit -m "feat(engine): auto-release idle takeover to COPILOT with warning"
```

---

## Task 5 — Gateway wires takeover notifications to WS + `client_ack` continue handler

**Files:**
- Modify: `autoservice/web_gateway.py` (`create_app`, `_handle_connection`)
- Modify: `autoservice/gateway/message_router.py` (_process_frame → handle `client_ack` with action=continue)
- Test: `tests/gateway/test_takeover_release.py` (new)

- [ ] **Step 5.1: Write failing test** `tests/gateway/test_takeover_release.py`

```python
"""E2E-ish gateway test for takeover auto-release flow."""
import asyncio
import json
import pytest
from starlette.testclient import TestClient

from autoservice.web_gateway import create_app
from autoservice.takeover_config import TakeoverConfig


def _hello(client_app="operator-console"):
    return {"v": 1, "type": "client_hello", "id": "h", "ts": "t",
            "payload": {"protocol_version": 1, "client_app": client_app}}


@pytest.fixture
def fast_takeover_app(monkeypatch):
    """App with a tiny takeover config so tests don't wait seconds."""
    from autoservice import web_gateway
    # Force the app's takeover config to be fast
    monkeypatch.setattr(
        web_gateway, "_TAKEOVER_CONFIG_OVERRIDE",
        TakeoverConfig(idle_timeout_ms=150, warning_ms=50, offline_grace_ms=200),
        raising=False,
    )
    return create_app()


def test_warning_frame_pushed_to_operator_after_hijack(fast_takeover_app):
    with TestClient(fast_takeover_app) as client:
        with client.websocket_connect("/ws/customer") as cws, \
             client.websocket_connect("/ws/operator") as ows:

            # handshakes
            cws.send_json(_hello("customer-chat"))
            ows.send_json(_hello("operator-console"))
            cws.receive_json()  # server_hello
            ows.receive_json()

            # operator subscribes
            ows.send_json({"v": 1, "type": "subscribe", "id": "s1", "ts": "t",
                           "payload": {"scope": {"squad_id": "web-support"}}})
            # drain frames until subscription_added
            while True:
                f = ows.receive_json()
                if f["type"] == "subscription_added":
                    break

            # customer sends a message -> creates conv
            cws.send_json({"v": 1, "type": "customer_message", "id": "m1", "ts": "t",
                           "payload": {"source": "cust1", "content": "hi"}})
            # drain customer side until message_confirm
            while True:
                f = cws.receive_json()
                if f["type"] == "message_confirm":
                    conv_id = f["payload"]["conversation_id"]
                    break

            # drain operator frames until we see the customer message broadcast
            # (gives us conv_id confirmation from operator perspective too)
            # Now operator hijacks
            ows.send_json({"v": 1, "type": "operator_command", "id": "c1", "ts": "t",
                           "payload": {"conversation_id": conv_id,
                                       "command": "/hijack", "operator_id": "op42"}})

            # Within 100-200ms we should see a takeover_warning frame on operator WS
            warning = None
            import time
            deadline = time.time() + 1.0
            while time.time() < deadline:
                try:
                    f = ows.receive_json(timeout=0.2)
                except Exception:
                    continue
                if f["type"] == "takeover_warning":
                    warning = f
                    break

            assert warning is not None
            assert warning["payload"]["conversation_id"] == conv_id
            assert warning["payload"]["reason"] == "idle"


def test_client_ack_continue_resets_timer(fast_takeover_app):
    with TestClient(fast_takeover_app) as client:
        with client.websocket_connect("/ws/customer") as cws, \
             client.websocket_connect("/ws/operator") as ows:
            # skipping repeated plumbing — verify via intermediate observation:
            # after hijack, wait for warning, send client_ack continue, verify
            # takeover_warning_cancelled arrives AND final release doesn't happen.
            # (Keep concise - use helper below.)
            _setup(cws, ows)
            conv_id = _customer_start_conv(cws, ows)
            _send_cmd(ows, conv_id, "/hijack", "op42")

            warning = _wait_frame(ows, "takeover_warning", timeout=1.0)
            assert warning is not None

            ows.send_json({"v": 1, "type": "client_ack", "id": "ack1", "ts": "t",
                           "payload": {"action": "continue",
                                       "conversation_id": conv_id}})
            cancelled = _wait_frame(ows, "takeover_warning_cancelled", timeout=0.5)
            assert cancelled is not None

            # Now verify no auto-release happened within the original release window
            import time
            deadline = time.time() + 0.3
            while time.time() < deadline:
                try:
                    f = ows.receive_json(timeout=0.1)
                except Exception:
                    continue
                assert f["type"] != "event" or f["payload"]["event"]["type"] != "mode.changed" \
                    or f["payload"]["event"]["data"]["new_mode"] != "copilot", \
                    "auto-release fired after continue ack"


# Shared helpers ---------------------------------------------------------------
def _setup(cws, ows):
    cws.send_json(_hello("customer-chat"))
    ows.send_json(_hello("operator-console"))
    cws.receive_json(); ows.receive_json()
    ows.send_json({"v": 1, "type": "subscribe", "id": "s1", "ts": "t",
                   "payload": {"scope": {"squad_id": "web-support"}}})
    while ows.receive_json()["type"] != "subscription_added":
        pass

def _customer_start_conv(cws, ows):
    cws.send_json({"v": 1, "type": "customer_message", "id": "m1", "ts": "t",
                   "payload": {"source": "cust1", "content": "hi"}})
    while True:
        f = cws.receive_json()
        if f["type"] == "message_confirm":
            return f["payload"]["conversation_id"]

def _send_cmd(ws, conv_id, cmd, op_id):
    ws.send_json({"v": 1, "type": "operator_command", "id": "c", "ts": "t",
                  "payload": {"conversation_id": conv_id, "command": cmd, "operator_id": op_id}})

def _wait_frame(ws, frame_type, timeout=1.0):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            f = ws.receive_json(timeout=0.15)
        except Exception:
            continue
        if f["type"] == frame_type:
            return f
    return None
```

- [ ] **Step 5.2: Run — expect failure**

Run: `uv run pytest tests/gateway/test_takeover_release.py -v`
Expected: FAIL — helpers missing, `_TAKEOVER_CONFIG_OVERRIDE` not implemented, `takeover_warning` frame not pushed.

- [ ] **Step 5.3: Modify `autoservice/web_gateway.py`**

At module top (near existing imports and `_CORS_ORIGINS`), add:

```python
from autoservice.takeover_config import TakeoverConfig, load_takeover_config

# Test-only override; production loads from .autoservice/config.local.yaml
_TAKEOVER_CONFIG_OVERRIDE: TakeoverConfig | None = None
```

In `create_app`, after `engine = ...` instantiation (find the line that creates `LocalEngine`, then update it), add config load and wire notifications:

```python
# Load takeover config (test hook wins, else YAML, else defaults)
if _TAKEOVER_CONFIG_OVERRIDE is not None:
    takeover_cfg = _TAKEOVER_CONFIG_OVERRIDE
else:
    takeover_cfg = load_takeover_config(Path(".autoservice/config.local.yaml"))

# Pass into engine config
engine = LocalEngine(config={"takeover": takeover_cfg})  # or merge into existing config dict

# Wire notifications to WS push
from autoservice.gateway.connection import build_frame

def _push_takeover_warning(payload: dict) -> None:
    operator_id = payload["operator_id"]
    frame = build_frame("takeover_warning", {
        "conversation_id": payload["conversation_id"],
        "remaining_ms": payload["remaining_ms"],
        "reason": payload["reason"],
    })
    asyncio.create_task(_send_to_operator(operator_id, frame))

def _push_takeover_cancelled(payload: dict) -> None:
    # Broadcast to any session subscribed to the conv/squad
    frame = build_frame("takeover_warning_cancelled", {
        "conversation_id": payload["conversation_id"],
    })
    asyncio.create_task(_broadcast_cancelled(payload["conversation_id"], frame))

async def _send_to_operator(operator_id: str, frame: dict) -> None:
    # Look up all sessions whose hello carried operator_id
    from autoservice.web_gateway import _operator_sessions
    for session_id in list(_operator_sessions.get(operator_id, [])):
        ws = _ws_connections.get(session_id)
        if ws is None:
            continue
        try:
            await ws.send_json(frame)
        except Exception:
            pass

async def _broadcast_cancelled(conv_id: str, frame: dict) -> None:
    from autoservice.gateway.message_router import _broadcast_to_squad
    await _broadcast_to_squad(frame, conv_id)

engine.on_takeover_warning(_push_takeover_warning)
engine.on_takeover_warning_cancelled(_push_takeover_cancelled)
```

Add at module-level next to `_ws_connections` / `_admin_connections`:

```python
# operator_id → set of session_ids (for targeted pushes)
_operator_sessions: dict[str, set[str]] = {}
```

In `_handle_connection`, after the existing `_ws_connections[session_id] = ws` assignment, also:

```python
# Track operator_id → sessions for targeted pushes
client_operator_id = env.payload.get("operator_id")
if viewer_role == "operator" and client_operator_id:
    _operator_sessions.setdefault(client_operator_id, set()).add(session_id)
    ws.state_operator_id = client_operator_id  # for finally cleanup
```

In the `finally` block (existing cleanup around the evict_by_session call):

```python
# Clean operator_sessions index
op_id = getattr(ws, "state_operator_id", None)
if op_id and session_id in _operator_sessions.get(op_id, set()):
    _operator_sessions[op_id].discard(session_id)
    if not _operator_sessions[op_id]:
        _operator_sessions.pop(op_id, None)
```

- [ ] **Step 5.4: Modify `message_router._process_frame` to handle `client_ack` with `action=continue`**

Find `_process_frame` in `autoservice/gateway/message_router.py`. Locate the `client_ack` handling (line ~129-130 in `dispatch`) and expand:

Replace:
```python
if frame_type == "client_ack":
    return [build_frame("ack", {}, ref=env.id)]
```

With:
```python
if frame_type == "client_ack":
    payload = env.payload or {}
    if payload.get("action") == "continue":
        conv_id = payload.get("conversation_id")
        actor_id = payload.get("operator_id") or _infer_operator_from_ws(ws)
        if conv_id and actor_id:
            try:
                await engine.reset_takeover_timer(conv_id, actor_id=actor_id)
            except Exception:
                logger.exception("client_ack continue reset failed")
    return [build_frame("ack", {}, ref=env.id)]
```

Add at module level (near existing helpers):

```python
def _infer_operator_from_ws(ws) -> str | None:
    """Best-effort operator_id lookup from WS state (set in web_gateway)."""
    if ws is None:
        return None
    return getattr(ws, "state_operator_id", None)
```

- [ ] **Step 5.5: Run — expect pass**

Run: `uv run pytest tests/gateway/test_takeover_release.py -v`
Expected: 2 passed.

- [ ] **Step 5.6: Regression**

Run: `uv run pytest tests/gateway/ -v --timeout=15`
Expected: all pass.

- [ ] **Step 5.7: Commit**

```bash
git add autoservice/web_gateway.py autoservice/gateway/message_router.py tests/gateway/test_takeover_release.py
git commit -m "feat(gateway): push takeover_warning + handle continue-ack"
```

---

## Task 6 — OfflineWatcher (operator disconnect → AUTO)

**Files:**
- Create: `autoservice/gateway/offline_watcher.py`
- Modify: `autoservice/conversation_engine/local_engine.py` (add `list_conversations_in_takeover_by`)
- Modify: `autoservice/web_gateway.py` (instantiate + call `on_connect`/`on_disconnect`)
- Test: `tests/gateway/test_offline_watcher.py` (new)

- [ ] **Step 6.1: Write failing test for watcher unit** `tests/gateway/test_offline_watcher.py`

```python
import asyncio
import pytest
from datetime import datetime, timezone

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import (
    ConversationMode, Participant, ParticipantRole,
)
from autoservice.gateway.offline_watcher import OfflineWatcher


@pytest.mark.asyncio
async def test_disconnect_then_grace_expires_switches_conv_to_auto():
    eng = LocalEngine()
    conv = await eng.create_conversation(channel="web", external_id="x")
    now = datetime.now(timezone.utc)
    await eng.join(conv.id, Participant(id="cust1", role=ParticipantRole.CUSTOMER, joined_at=now))
    await eng.join(conv.id, Participant(id="op42", role=ParticipantRole.OPERATOR, joined_at=now))
    await eng.handle_command(conv.id, actor_id="op42", command="/hijack")

    watcher = OfflineWatcher(eng, grace_ms=50)
    watcher.on_connect("op42")
    watcher.on_disconnect("op42")
    await asyncio.sleep(0.1)

    final = await eng.get_conversation(conv.id)
    assert final.mode == ConversationMode.AUTO


@pytest.mark.asyncio
async def test_reconnect_within_grace_cancels():
    eng = LocalEngine()
    conv = await eng.create_conversation(channel="web", external_id="x")
    now = datetime.now(timezone.utc)
    await eng.join(conv.id, Participant(id="cust1", role=ParticipantRole.CUSTOMER, joined_at=now))
    await eng.join(conv.id, Participant(id="op42", role=ParticipantRole.OPERATOR, joined_at=now))
    await eng.handle_command(conv.id, actor_id="op42", command="/hijack")

    watcher = OfflineWatcher(eng, grace_ms=100)
    watcher.on_connect("op42")
    watcher.on_disconnect("op42")
    await asyncio.sleep(0.03)
    watcher.on_connect("op42")  # reconnect
    await asyncio.sleep(0.1)

    final = await eng.get_conversation(conv.id)
    assert final.mode == ConversationMode.TAKEOVER


@pytest.mark.asyncio
async def test_disconnect_with_no_takeover_conversations_is_noop():
    eng = LocalEngine()
    watcher = OfflineWatcher(eng, grace_ms=30)
    watcher.on_connect("op42")
    watcher.on_disconnect("op42")
    await asyncio.sleep(0.05)
    # No exception, no state — pass.
```

- [ ] **Step 6.2: Run — expect failure**

Run: `uv run pytest tests/gateway/test_offline_watcher.py -v`
Expected: FAIL — module not found.

- [ ] **Step 6.3: Implement `autoservice/gateway/offline_watcher.py`**

```python
"""Operator offline watcher: flips TAKEOVER conversations to AUTO after grace period."""
from __future__ import annotations

import asyncio
import logging

from autoservice.conversation_engine.protocol import ConversationEngine
from autoservice.conversation_engine.types import ConversationMode

log = logging.getLogger(__name__)


class OfflineWatcher:
    """Tracks operator WS connect/disconnect. On disconnect, schedules a grace
    timer; if the operator doesn't reconnect in time, all TAKEOVER conversations
    they own are switched back to AUTO with trigger=auto:operator_offline.
    """

    def __init__(self, engine: ConversationEngine, *, grace_ms: int) -> None:
        self._engine = engine
        self._grace_ms = grace_ms
        self._online: set[str] = set()
        self._pending: dict[str, asyncio.Task] = {}

    def on_connect(self, operator_id: str) -> None:
        self._online.add(operator_id)
        task = self._pending.pop(operator_id, None)
        if task and not task.done():
            task.cancel()

    def on_disconnect(self, operator_id: str) -> None:
        self._online.discard(operator_id)
        self._pending[operator_id] = asyncio.create_task(
            self._grace(operator_id), name=f"offline-grace-{operator_id}",
        )

    async def _grace(self, operator_id: str) -> None:
        try:
            await asyncio.sleep(self._grace_ms / 1000.0)
        except asyncio.CancelledError:
            return
        self._pending.pop(operator_id, None)
        if operator_id in self._online:
            return  # reconnected before expiry
        try:
            convs = await self._engine.list_conversations_in_takeover_by(operator_id)
        except Exception:
            log.exception("list_conversations_in_takeover_by failed for %s", operator_id)
            return
        for conv in convs:
            try:
                await self._engine.switch_mode(
                    conv.id,
                    ConversationMode.AUTO,
                    triggered_by="__system__",
                    trigger="auto:operator_offline",
                )
            except Exception:
                log.exception("offline switch_mode failed for conv=%s", conv.id)
```

- [ ] **Step 6.4: Implement `list_conversations_in_takeover_by` on `LocalEngine`**

Add to `LocalEngine` (near `get_conversation`):

```python
async def list_conversations_in_takeover_by(self, operator_id: str) -> list[Conversation]:
    """Return all non-closed conversations currently in TAKEOVER by this operator."""
    return [
        conv for conv in self._conversations.values()
        if conv.state != ConversationState.CLOSED
           and conv.mode == ConversationMode.TAKEOVER
           and conv.takeover_operator_id == operator_id
    ]
```

Also add a matching method to the `protocol.ConversationEngine` Protocol / ABC (so type checks pass). Find the protocol definition (`autoservice/conversation_engine/protocol.py`) and add:

```python
async def list_conversations_in_takeover_by(self, operator_id: str) -> list[Conversation]: ...
```

- [ ] **Step 6.5: Run — expect pass**

Run: `uv run pytest tests/gateway/test_offline_watcher.py -v`
Expected: 3 passed.

- [ ] **Step 6.6: Wire into `web_gateway.create_app`**

After takeover_cfg is loaded, before returning app:

```python
from autoservice.gateway.offline_watcher import OfflineWatcher
app.state.offline_watcher = OfflineWatcher(engine, grace_ms=takeover_cfg.offline_grace_ms)
```

In `_handle_connection`, where we track operator_sessions (Step 5.3), also call:
```python
if viewer_role == "operator" and client_operator_id:
    app.state.offline_watcher.on_connect(client_operator_id)
```

In the `finally` block (after cleaning `_operator_sessions`), if the operator has no sessions left call `on_disconnect`:
```python
if op_id and not _operator_sessions.get(op_id):
    ws.app.state.offline_watcher.on_disconnect(op_id)
```

- [ ] **Step 6.7: Write gateway-level test for offline flow** — append to `tests/gateway/test_takeover_release.py`

```python
def test_operator_disconnect_after_grace_switches_to_auto(fast_takeover_app):
    with TestClient(fast_takeover_app) as client:
        with client.websocket_connect("/ws/customer") as cws:
            with client.websocket_connect("/ws/operator") as ows:
                _setup(cws, ows)
                conv_id = _customer_start_conv(cws, ows)
                _send_cmd(ows, conv_id, "/hijack", "op42")
                # Consume warning (if any)
                _wait_frame(ows, "takeover_warning", timeout=0.5)
            # exited operator context → WS closed
            # grace is 200ms in fast config; wait a bit longer
            import time; time.sleep(0.4)
            # Verify via a new operator connection subscribing to history
            with client.websocket_connect("/ws/operator") as ows2:
                ows2.send_json(_hello("operator-console"))
                ows2.receive_json()
                ows2.send_json({"v": 1, "type": "history_request", "id": "h1", "ts": "t",
                                "payload": {"conversation_id": conv_id, "limit": 50}})
                # The mode should have been switched to auto — check by command result
                # or rely on the convenient backdoor: hit engine directly
                from autoservice.web_gateway import _get_engine_for_tests
                eng = _get_engine_for_tests()
                import asyncio
                conv = asyncio.get_event_loop().run_until_complete(eng.get_conversation(conv_id))
                assert conv.mode.value == "auto"
```

If `_get_engine_for_tests` doesn't exist, add it in `web_gateway.py`:

```python
def _get_engine_for_tests():
    """Test-only accessor to the currently-running engine."""
    # This is OK for single-app test runs; not for production use.
    for fn_locals in []:
        pass
    from autoservice.web_gateway import _engine  # module-level
    return _engine
```
And ensure the engine is stashed at module level in create_app (`_engine = engine`). Alternative: access via `app.state.engine` by grabbing the app out of a test fixture.

(If this plumbing gets hairy, just assert via the operator receiving a `mode.changed` event with `new_mode=auto`.)

- [ ] **Step 6.8: Run — expect pass**

Run: `uv run pytest tests/gateway/test_takeover_release.py tests/gateway/test_offline_watcher.py -v`
Expected: all pass.

- [ ] **Step 6.9: Commit**

```bash
git add autoservice/gateway/offline_watcher.py autoservice/conversation_engine/local_engine.py autoservice/conversation_engine/protocol.py autoservice/web_gateway.py tests/gateway/test_offline_watcher.py tests/gateway/test_takeover_release.py
git commit -m "feat(gateway): OfflineWatcher flips offline operator's takeovers to AUTO"
```

---

## Task 7 — ws-client schema + types

**Files:**
- Modify: `frontend/packages/ws-client/src/types.ts`
- Test: `frontend/packages/ws-client/src/__tests__/types.test.ts` (new if missing)

- [ ] **Step 7.1: Write/extend test** `frontend/packages/ws-client/src/__tests__/types.test.ts`

```ts
import { describe, it, expect } from 'vitest';
import type { BeToFeType, FeToBeType } from '../types';

describe('takeover frame types', () => {
  it('BeToFeType includes takeover_warning and takeover_warning_cancelled', () => {
    const types: BeToFeType[] = ['takeover_warning', 'takeover_warning_cancelled'];
    expect(types).toEqual(['takeover_warning', 'takeover_warning_cancelled']);
  });
});
```

- [ ] **Step 7.2: Run — expect failure**

Run: `cd frontend/packages/ws-client && pnpm test -- --run types`
Expected: TS compile error — types not present on `BeToFeType`.

- [ ] **Step 7.3: Extend `types.ts`**

In `frontend/packages/ws-client/src/types.ts` (around the `BeToFeType` list on line ~26):

```ts
export type BeToFeType =
  | 'server_hello'
  | 'ack'
  | 'pong'
  | 'error'
  | 'command_response'
  | 'subscription_added'
  | 'subscription_removed'
  | 'message'
  | 'message_edited'
  | 'message_deleted'
  | 'message_confirm'
  | 'event'
  | 'history_snapshot'
  | 'csat_request'
  | 'replay_complete'
  | 'takeover_warning'               // <-- new
  | 'takeover_warning_cancelled';    // <-- new
```

(Preserve any existing items — this list is illustrative. Add the two new strings without removing anything.)

- [ ] **Step 7.4: Run — expect pass**

Run: `cd frontend/packages/ws-client && pnpm test -- --run types`
Expected: pass.

- [ ] **Step 7.5: Commit**

```bash
git add frontend/packages/ws-client/src/types.ts frontend/packages/ws-client/src/__tests__/types.test.ts
git commit -m "feat(ws-client): add takeover_warning frame types"
```

---

## Task 8 — operatorStore: `takeoverWarning` field + actions + mode `takeover_operator_id`

**Files:**
- Modify: `frontend/apps/operator-console/src/store/operatorStore.ts`
- Test: `frontend/apps/operator-console/src/__tests__/operatorStore.test.ts`

- [ ] **Step 8.1: Extend test file with new cases** — append to `operatorStore.test.ts`

```ts
import { useOperatorStore } from '../store/operatorStore';

describe('takeover warning state', () => {
  beforeEach(() => {
    useOperatorStore.setState(useOperatorStore.getState().logout ? {} : {});
    useOperatorStore.getState().logout?.();
  });

  it('setTakeoverWarning stores per-conversation', () => {
    useOperatorStore.getState().addConversation({
      id: 'c1', squadId: 'web-support', customerId: 'cust1',
      mode: 'takeover', state: 'active', lastMessage: '', lastActivityTs: '',
    } as any);
    useOperatorStore.getState().setTakeoverWarning('c1', {
      remainingMs: 5000,
      reason: 'idle',
      warningFrameId: 'f1',
      armedAt: '2026-04-17T00:00:00Z',
    });
    const conv = useOperatorStore.getState().conversations['c1'];
    expect(conv.takeoverWarning?.remainingMs).toBe(5000);
  });

  it('clearTakeoverWarning removes the warning', () => {
    useOperatorStore.getState().addConversation({
      id: 'c1', squadId: 'web-support', customerId: 'cust1',
      mode: 'takeover', state: 'active', lastMessage: '', lastActivityTs: '',
    } as any);
    useOperatorStore.getState().setTakeoverWarning('c1', {
      remainingMs: 5000, reason: 'idle', warningFrameId: 'f1', armedAt: '',
    });
    useOperatorStore.getState().clearTakeoverWarning('c1');
    expect(useOperatorStore.getState().conversations['c1'].takeoverWarning).toBeUndefined();
  });
});
```

- [ ] **Step 8.2: Run — expect failure**

Run: `cd frontend && pnpm --filter @autoservice/operator-console test -- --run operatorStore`
Expected: FAIL — methods not defined.

- [ ] **Step 8.3: Edit `operatorStore.ts`**

Add to the `Conversation` interface:

```ts
export interface TakeoverWarning {
  remainingMs: number;
  reason: 'idle';
  warningFrameId: string;
  armedAt: string;
}

export interface Conversation {
  // ... existing fields ...
  mode: 'auto' | 'copilot' | 'takeover';
  takeoverOperatorId?: string | null;
  takeoverWarning?: TakeoverWarning;
}
```

Extend `OperatorState`:
```ts
  setTakeoverWarning: (conversationId: string, w: TakeoverWarning) => void;
  clearTakeoverWarning: (conversationId: string) => void;
```

And in the store body:
```ts
  setTakeoverWarning: (id, warning) => set((state) => {
    const conv = state.conversations[id];
    if (!conv) return state;
    return {
      conversations: {
        ...state.conversations,
        [id]: { ...conv, takeoverWarning: warning },
      },
    };
  }),

  clearTakeoverWarning: (id) => set((state) => {
    const conv = state.conversations[id];
    if (!conv || !conv.takeoverWarning) return state;
    const { takeoverWarning, ...rest } = conv;
    return {
      conversations: { ...state.conversations, [id]: rest },
    };
  }),
```

- [ ] **Step 8.4: Run — expect pass**

Run: `cd frontend && pnpm --filter @autoservice/operator-console test -- --run operatorStore`
Expected: pass.

- [ ] **Step 8.5: Commit**

```bash
git add frontend/apps/operator-console/src/store/operatorStore.ts frontend/apps/operator-console/src/__tests__/operatorStore.test.ts
git commit -m "feat(operator-console): takeover warning state + actions"
```

---

## Task 9 — useOperatorWS handles takeover frames and updates store on mode.changed

**Files:**
- Modify: `frontend/apps/operator-console/src/hooks/useOperatorWS.ts`
- Test: `frontend/apps/operator-console/src/__tests__/useOperatorWS.test.tsx` (extend existing)

- [ ] **Step 9.1: Add test cases** to existing `useOperatorWS.test.tsx`:

```tsx
it('receiving takeover_warning frame calls setTakeoverWarning', async () => {
  // set up store with a conversation
  useOperatorStore.getState().login('op42', 'tok');
  useOperatorStore.getState().addConversation({
    id: 'c1', squadId: 'web-support', customerId: 'cust1',
    mode: 'takeover', state: 'active', lastMessage: '', lastActivityTs: '',
  } as any);
  // mount hook with fake client
  // ... (follow existing pattern in file)
  fakeInstance!.triggerFrame({
    v: 1, type: 'takeover_warning', id: 'f1', ts: 't',
    payload: { conversation_id: 'c1', remaining_ms: 5000, reason: 'idle' },
  });
  await waitFor(() => {
    expect(useOperatorStore.getState().conversations['c1'].takeoverWarning?.remainingMs).toBe(5000);
  });
});

it('receiving takeover_warning_cancelled clears takeoverWarning', async () => {
  // ... similar
  useOperatorStore.getState().setTakeoverWarning('c1', {
    remainingMs: 5000, reason: 'idle', warningFrameId: 'f1', armedAt: '',
  });
  fakeInstance!.triggerFrame({
    v: 1, type: 'takeover_warning_cancelled', id: 'f2', ts: 't',
    payload: { conversation_id: 'c1' },
  });
  await waitFor(() => {
    expect(useOperatorStore.getState().conversations['c1'].takeoverWarning).toBeUndefined();
  });
});

it('mode.changed event with takeover_operator_id updates takeoverOperatorId', async () => {
  // ... similar; dispatch event frame with new_mode=takeover, takeover_operator_id=op42
  fakeInstance!.triggerFrame({
    v: 1, type: 'event', id: 'e1', ts: 't',
    payload: { event: {
      id: 'ev1', type: 'mode.changed', conversation_id: 'c1',
      data: { old_mode: 'auto', new_mode: 'takeover', takeover_operator_id: 'op42' },
      timestamp: 't',
    }}
  });
  await waitFor(() => {
    expect(useOperatorStore.getState().conversations['c1'].takeoverOperatorId).toBe('op42');
  });
});
```

- [ ] **Step 9.2: Run — expect failure**

Run: `cd frontend && pnpm --filter @autoservice/operator-console test -- --run useOperatorWS`
Expected: FAIL — frame not handled.

- [ ] **Step 9.3: Edit `useOperatorWS.ts`**

In `onFrame`, add before the `event` handler:

```typescript
if (frame.type === 'takeover_warning') {
  const p = frame.payload as {
    conversation_id: string; remaining_ms: number; reason: 'idle';
  };
  useOperatorStore.getState().setTakeoverWarning(p.conversation_id, {
    remainingMs: p.remaining_ms,
    reason: p.reason,
    warningFrameId: frame.id,
    armedAt: new Date().toISOString(),
  });
  return;
}
if (frame.type === 'takeover_warning_cancelled') {
  const p = frame.payload as { conversation_id: string };
  useOperatorStore.getState().clearTakeoverWarning(p.conversation_id);
  return;
}
```

In `handleEventFrame` (the `mode.changed` case), update takeoverOperatorId:

```typescript
case 'mode.changed': {
  const to = event.data.to as Conversation['mode'] | undefined
    ?? (event.data.new_mode as Conversation['mode']);
  const takeoverId = event.data.takeover_operator_id as string | null | undefined;
  updateConversation(convId, {
    mode: to,
    takeoverOperatorId: takeoverId ?? null,
    lastActivityTs: ts,
  });
  break;
}
```

- [ ] **Step 9.4: Run — expect pass**

Run: `cd frontend && pnpm --filter @autoservice/operator-console test -- --run useOperatorWS`
Expected: pass.

- [ ] **Step 9.5: Commit**

```bash
git add frontend/apps/operator-console/src/hooks/useOperatorWS.ts frontend/apps/operator-console/src/__tests__/useOperatorWS.test.tsx
git commit -m "feat(operator-console): handle takeover_warning frames and mode.changed takeover_operator_id"
```

---

## Task 10 — HijackButton becomes dual-state

**Files:**
- Modify: `frontend/apps/operator-console/src/components/HijackButton.tsx`
- Test: `frontend/apps/operator-console/src/__tests__/HijackButton.test.tsx` (extend existing)

- [ ] **Step 10.1: Extend test**

```tsx
it('shows 释放回 AI when mode is takeover and dispatches /release', async () => {
  useOperatorStore.getState().addConversation({
    id: 'c1', squadId: 'web-support', customerId: 'cust1',
    mode: 'takeover', state: 'active', lastMessage: '', lastActivityTs: '',
  } as any);

  const send = vi.fn();
  render(<HijackButton conversationId="c1" send={send} />);

  const btn = screen.getByTestId('btn-release-c1');
  expect(btn).toHaveTextContent('释放回 AI');
  await userEvent.click(btn);
  expect(send).toHaveBeenCalledWith(
    expect.objectContaining({
      type: 'operator_command',
      payload: expect.objectContaining({ command: '/release' }),
    }),
  );
});

it('shows 抢单 when mode is auto or copilot and dispatches /hijack', async () => {
  useOperatorStore.getState().addConversation({
    id: 'c1', squadId: 'web-support', customerId: 'cust1',
    mode: 'auto', state: 'active', lastMessage: '', lastActivityTs: '',
  } as any);

  const send = vi.fn();
  render(<HijackButton conversationId="c1" send={send} />);

  const btn = screen.getByTestId('btn-hijack-c1');
  expect(btn).toHaveTextContent('抢单');
  await userEvent.click(btn);
  expect(send.mock.calls[0][0].payload.command).toBe('/hijack');
});
```

- [ ] **Step 10.2: Run — expect failure**

Run: `cd frontend && pnpm --filter @autoservice/operator-console test -- --run HijackButton`
Expected: FAIL — button always says 抢单.

- [ ] **Step 10.3: Replace `HijackButton.tsx`**

```tsx
import { Button } from 'antd';
import type { Envelope } from '@autoservice/ws-client';
import { useOperatorStore } from '../store/operatorStore';

interface HijackButtonProps {
  conversationId: string;
  send: (frame: Envelope) => void;
  disabled?: boolean;
}

export function HijackButton({ conversationId, send, disabled }: HijackButtonProps) {
  const mode = useOperatorStore(
    (s) => s.conversations[conversationId]?.mode,
  );

  const isTakeover = mode === 'takeover';
  const command = isTakeover ? '/release' : '/hijack';
  const text = isTakeover ? '释放回 AI' : '抢单';
  const testid = isTakeover ? `btn-release-${conversationId}` : `btn-hijack-${conversationId}`;

  const handleClick = () => {
    send({
      v: 1,
      type: 'operator_command',
      id: crypto.randomUUID(),
      ts: new Date().toISOString(),
      payload: { conversation_id: conversationId, command },
    } as Envelope);
  };

  return (
    <Button
      type="primary"
      danger={!isTakeover}
      disabled={disabled}
      data-testid={testid}
      onClick={handleClick}
    >
      {text}
    </Button>
  );
}
```

- [ ] **Step 10.4: Run — expect pass**

Run: `cd frontend && pnpm --filter @autoservice/operator-console test -- --run HijackButton`
Expected: pass.

- [ ] **Step 10.5: Commit**

```bash
git add frontend/apps/operator-console/src/components/HijackButton.tsx frontend/apps/operator-console/src/__tests__/HijackButton.test.tsx
git commit -m "feat(operator-console): HijackButton dual-state for release"
```

---

## Task 11 — TakeoverWarning banner component

**Files:**
- Create: `frontend/apps/operator-console/src/components/TakeoverWarning.tsx`
- Modify: `frontend/apps/operator-console/src/components/CopilotView.tsx` (render the banner at top)
- Test: `frontend/apps/operator-console/src/__tests__/TakeoverWarning.test.tsx` (new)

- [ ] **Step 11.1: Write failing test** `TakeoverWarning.test.tsx`

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TakeoverWarning } from '../components/TakeoverWarning';
import { useOperatorStore } from '../store/operatorStore';

describe('TakeoverWarning', () => {
  beforeEach(() => {
    useOperatorStore.getState().logout();
    useOperatorStore.getState().login('op42', 'tok');
  });

  function addConvWithWarning(convId = 'c1') {
    useOperatorStore.getState().addConversation({
      id: convId, squadId: 'web-support', customerId: 'cust1',
      mode: 'takeover', state: 'active', lastMessage: '', lastActivityTs: '',
      takeoverOperatorId: 'op42',
    } as any);
    useOperatorStore.getState().setTakeoverWarning(convId, {
      remainingMs: 5000, reason: 'idle', warningFrameId: 'f1', armedAt: '2026-04-17T00:00:00Z',
    });
  }

  it('renders banner when current operator has a warning for the active conv', () => {
    addConvWithWarning();
    render(<TakeoverWarning conversationId="c1" send={vi.fn()} />);
    expect(screen.getByTestId('takeover-warning-c1')).toBeInTheDocument();
  });

  it('does not render if current operator is not the takeover operator', () => {
    useOperatorStore.getState().logout();
    useOperatorStore.getState().login('opOther', 'tok');
    addConvWithWarning();
    // (addConvWithWarning set takeoverOperatorId='op42' — current is 'opOther')
    const { container } = render(<TakeoverWarning conversationId="c1" send={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('clicking 继续接管 sends client_ack with action=continue', async () => {
    addConvWithWarning();
    const send = vi.fn();
    render(<TakeoverWarning conversationId="c1" send={send} />);
    await userEvent.click(screen.getByTestId('takeover-warning-continue'));
    expect(send).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'client_ack',
        payload: expect.objectContaining({
          action: 'continue',
          conversation_id: 'c1',
        }),
      }),
    );
  });

  it('clicking 释放 sends /release', async () => {
    addConvWithWarning();
    const send = vi.fn();
    render(<TakeoverWarning conversationId="c1" send={send} />);
    await userEvent.click(screen.getByTestId('takeover-warning-release'));
    expect(send).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'operator_command',
        payload: expect.objectContaining({ command: '/release' }),
      }),
    );
  });
});
```

- [ ] **Step 11.2: Run — expect failure**

Run: `cd frontend && pnpm --filter @autoservice/operator-console test -- --run TakeoverWarning`
Expected: FAIL — component does not exist.

- [ ] **Step 11.3: Create `TakeoverWarning.tsx`**

```tsx
import { useEffect, useState } from 'react';
import type { Envelope } from '@autoservice/ws-client';
import { useOperatorStore } from '../store/operatorStore';

interface TakeoverWarningProps {
  conversationId: string;
  send: (frame: Envelope) => void;
}

export function TakeoverWarning({ conversationId, send }: TakeoverWarningProps) {
  const currentOperatorId = useOperatorStore((s) => s.operatorId);
  const conv = useOperatorStore((s) => s.conversations[conversationId]);
  const warning = conv?.takeoverWarning;

  const [remaining, setRemaining] = useState<number>(warning?.remainingMs ?? 0);

  useEffect(() => {
    if (!warning) return;
    setRemaining(warning.remainingMs);
    const start = Date.now();
    const id = setInterval(() => {
      const elapsed = Date.now() - start;
      setRemaining(Math.max(0, warning.remainingMs - elapsed));
    }, 100);
    return () => clearInterval(id);
  }, [warning?.warningFrameId]);

  if (!warning) return null;
  if (!conv || conv.takeoverOperatorId !== currentOperatorId) return null;

  const handleContinue = () => {
    send({
      v: 1,
      type: 'client_ack' as any,
      id: crypto.randomUUID(),
      ts: new Date().toISOString(),
      payload: {
        action: 'continue',
        conversation_id: conversationId,
        ref_frame_id: warning.warningFrameId,
      },
    } as Envelope);
  };

  const handleRelease = () => {
    send({
      v: 1,
      type: 'operator_command',
      id: crypto.randomUUID(),
      ts: new Date().toISOString(),
      payload: { conversation_id: conversationId, command: '/release' },
    } as Envelope);
  };

  return (
    <div
      data-testid={`takeover-warning-${conversationId}`}
      style={{
        background: '#fff4e5',
        color: '#8a5000',
        padding: '8px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        borderBottom: '1px solid #ffd591',
      }}
    >
      <span style={{ flex: 1 }}>
        {`再 ${Math.ceil(remaining / 1000)}s 无响应将自动回到 AI`}
      </span>
      <button
        data-testid="takeover-warning-continue"
        onClick={handleContinue}
        style={{ padding: '4px 12px' }}
      >
        继续接管
      </button>
      <button
        data-testid="takeover-warning-release"
        onClick={handleRelease}
        style={{ padding: '4px 12px' }}
      >
        释放
      </button>
    </div>
  );
}
```

- [ ] **Step 11.4: Wire into CopilotView**

Find `CopilotView.tsx`. Near the top (above any existing banner or below header), render:

```tsx
<TakeoverWarning conversationId={conversationId} send={send} />
```

Add import at top:
```tsx
import { TakeoverWarning } from './TakeoverWarning';
```

- [ ] **Step 11.5: Run — expect pass**

Run: `cd frontend && pnpm --filter @autoservice/operator-console test -- --run TakeoverWarning`
Expected: pass.

- [ ] **Step 11.6: Regression**

Run: `cd frontend && pnpm --filter @autoservice/operator-console test`
Expected: all pass.

- [ ] **Step 11.7: Commit**

```bash
git add frontend/apps/operator-console/src/components/TakeoverWarning.tsx frontend/apps/operator-console/src/components/CopilotView.tsx frontend/apps/operator-console/src/__tests__/TakeoverWarning.test.tsx
git commit -m "feat(operator-console): TakeoverWarning banner"
```

---

## Task 12 — Manual QA + E2E smoke

**Files:**
- None (manual)

- [ ] **Step 12.1: Restart dev stack**

Run: `make stop && make start`
Expected: all 4 services UP per `make status`.

- [ ] **Step 12.2: Use the fast config**

Edit `.autoservice/config.local.yaml` (copy from example if missing):

```yaml
takeover:
  idle_timeout_ms: 8000
  warning_ms: 3000
  offline_grace_ms: 5000
```

Run: `make stop && make start` to pick up.

- [ ] **Step 12.3: Manual test — silent auto-release**

1. Open customer-chat (5173), send "hello".
2. Open operator-console (5174), login, click into the conversation, click **抢单**.
3. Wait 5s (no typing) → banner should appear: "再 3s 无响应将自动回到 AI".
4. Wait another 3s → banner disappears, button reverts to **抢单**, conversation mode indicator = copilot.
5. Send another customer message → AI replies.

- [ ] **Step 12.4: Manual test — continue action**

1. Hijack again.
2. Wait until banner appears.
3. Click **继续接管**.
4. Banner should disappear; button stays **释放回 AI**; wait another 8s without typing → banner reappears.

- [ ] **Step 12.5: Manual test — offline grace**

1. Hijack a conversation.
2. Close the operator-console tab (not the whole browser).
3. Wait >5s.
4. Re-open operator-console → mode should be `auto` (the card may disappear from "我的"; the conversation is back in squad queue).

- [ ] **Step 12.6: Manual test — manual release**

1. Hijack a conversation.
2. Immediately click **释放回 AI**.
3. Button becomes **抢单**; mode = auto.

- [ ] **Step 12.7: Revert fast config**

Either delete `.autoservice/config.local.yaml` takeover section or set values back to defaults (30000/5000/30000).

- [ ] **Step 12.8: Commit** (if any config files changed)

```bash
# No code commit required here unless QA uncovered something.
```

---

## Self-Review Notes

- **Spec coverage:** Every numbered item in the design doc's Section 2-4 maps to at least one task above (Task 1-6 = backend §2, Task 7-11 = frontend §3, Task 12 = edge cases/manual verification for §4).
- **Debug prints:** `[SUB]` / `[BCAST]` in `message_router.py` intentionally left in. Clean-up task not included — deferred per user instruction.
- **Out-of-scope confirmed absent:** No exclusive-lock logic, no customer-notification, no dashboard metric, no timer persistence. Any of these is a separate feature.
- **Type naming:** `takeover_operator_id` (backend snake_case) / `takeoverOperatorId` (frontend camelCase) is intentional, matches existing conventions in the same files.
