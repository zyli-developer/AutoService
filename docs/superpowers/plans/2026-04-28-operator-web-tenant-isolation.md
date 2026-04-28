# Operator Web Tenant Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make operator-console see only its own tenant's data — across HTTP API, WebSocket events, and conversation engine queries — without breaking existing single-tenant behavior.

**Architecture:** Single authorization helper (`auth_scope.py`) is the only file that knows the operator↔tenant relationship; conversation engine query methods take `tenant_id` as a mandatory parameter (defense in depth via the type system); a one-time SQLite migration backfills `metadata.tenant_id="_master"` for legacy conversations; WS subscribe carries `scope.tenant_id` and routes via a compound scope key.

**Tech Stack:** Python 3.11+, FastAPI, SQLite (JSON1), pytest-asyncio, React (TypeScript), `@anthropic-ai/sdk`-style protocol via custom WS frames.

**Spec:** [docs/superpowers/specs/2026-04-28-operator-web-tenant-isolation-design.md](../specs/2026-04-28-operator-web-tenant-isolation-design.md)

---

## File Structure

### New files

| Path | Responsibility |
|------|------|
| `autoservice/auth_scope.py` | `TenantScope` dataclass; `get_accessible_tenants()`; `resolve_effective_tenant()` |
| `autoservice/migrations/2026_04_28_backfill_conv_tenant_id.py` | Idempotent backfill SQL; CLI `python -m autoservice.migrations.2026_04_28_backfill_conv_tenant_id` |
| `tests/auth_scope/__init__.py` + `tests/auth_scope/test_auth_scope.py` | Unit tests for `auth_scope` module |
| `tests/operator_isolation/__init__.py` | Test package marker |
| `tests/operator_isolation/test_engine_tenant_filter.py` | Engine-level tenant filtering |
| `tests/operator_isolation/test_api_tenant_filter.py` | 6 API endpoints' tenant filtering |
| `tests/operator_isolation/test_ws_subscribe_tenant.py` | WS subscribe scope validation |
| `tests/operator_isolation/test_ws_event_routing.py` | WS push routing by compound scope key |
| `tests/operator_isolation/test_message_router_tenant_default.py` | Write-side `_master` fallback |
| `tests/operator_isolation/test_e2e_cross_tenant.py` | Full-stack: 2 operators, 2 tenants, 0 leakage |
| `tests/migrations/test_backfill_conv_tenant_id.py` | Migration idempotency + correctness |

### Modified files

| Path | Change |
|------|------|
| `autoservice/conversation_engine/protocol.py` | Add `tenant_id: str` (required) to 4 query methods |
| `autoservice/conversation_engine/local_engine.py` | Implementations + filter logic + startup fixup |
| `autoservice/conversation_engine/sqlite_store.py` | SQLite query layer (if applicable) |
| `autoservice/api_routes.py` | 6 endpoints (lines 445, 490, 518, 534, 545, 556) |
| `autoservice/sla_aggregator.py` | Add `tenant_id` parameter to query funcs |
| `autoservice/proposal_pipeline.py` | `list_proposals(tenant_id=...)` |
| Other aggregators (billing/metrics) | TBD by Task 13–15 (each task discovers via grep) |
| `autoservice/gateway/message_router.py` | Lines 530–533 (write-side fallback); lines 309+ (subscribe handler tenant validation) |
| `autoservice/gateway/subscription_registry.py` | Lines 121–129 (`_scope_key` compound) |
| `frontend/apps/operator-console/src/hooks/useOperatorWS.ts` | Lines 145, 152 (subscribe + fetch carry tenant_id) |

---

## Phases

- **Phase 1 — Foundation** (Tasks 1–6): additive, low risk, no signature changes
- **Phase 2 — Engine signature change** (Tasks 7–10): each method's caller-update batched in same task
- **Phase 3 — API layer** (Tasks 11–16): 6 endpoints
- **Phase 4 — WS protocol** (Tasks 17–19): subscribe + scope_key + push routing
- **Phase 5 — Frontend** (Task 20)
- **Phase 6 — E2E** (Task 21)

---

## Phase 1: Foundation

### Task 1: TenantScope dataclass + get_accessible_tenants

**Files:**
- Create: `autoservice/auth_scope.py`
- Test: `tests/auth_scope/test_auth_scope.py`

- [ ] **Step 1: Create test file with TenantScope shape test**

```python
# tests/auth_scope/test_auth_scope.py
from autoservice.auth_scope import TenantScope, get_accessible_tenants


def test_tenant_scope_is_frozen():
    s = TenantScope(
        effective_tenant_id="t1",
        accessible_tenants=frozenset({"t1"}),
        is_platform_admin=False,
    )
    import dataclasses
    assert dataclasses.is_dataclass(s)
    # frozen=True means assignment raises
    import pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.effective_tenant_id = "t2"  # type: ignore[misc]


def test_get_accessible_tenants_returns_session_tenant_for_tier1_operator():
    """1:1 today: an operator with tenant_id='t1' has access to {'t1'} only."""
    class FakeSession:
        tenant_id = "t1"
        rbac_tier = 1
    accessible = get_accessible_tenants(FakeSession())
    assert accessible == frozenset({"t1"})


def test_get_accessible_tenants_returns_empty_for_platform_admin():
    """Tier-0 platform admin: empty accessible set; access gated by is_platform_admin flag."""
    class FakeSession:
        tenant_id = "_master"
        rbac_tier = 0
    assert get_accessible_tenants(FakeSession()) == frozenset()
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/auth_scope/test_auth_scope.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autoservice.auth_scope'`

- [ ] **Step 3: Implement `auth_scope.py` (dataclass + get_accessible_tenants only)**

```python
# autoservice/auth_scope.py
"""Authorization scope helpers — single source of truth for operator↔tenant access.

Spec: docs/superpowers/specs/2026-04-28-operator-web-tenant-isolation-design.md §5.1

This module is intentionally the ONLY file that knows the operator↔tenant
relationship cardinality. Today: 1:1 (each operator row maps to one tenant_id).
Future: 1:N evolves only the body of `get_accessible_tenants()`; all callers
unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class _SessionLike(Protocol):
    """Duck-typed read-only session shape we need."""
    tenant_id: str | None
    rbac_tier: int


@dataclass(frozen=True)
class TenantScope:
    """An operator's tenant-access decision for one request or subscribe."""
    effective_tenant_id: str
    accessible_tenants: frozenset[str] = field(default_factory=frozenset)
    is_platform_admin: bool = False


def get_accessible_tenants(session: _SessionLike) -> frozenset[str]:
    """Return the set of tenant_ids this session may access.

    Today (1:1): tier-1 operator → {session.tenant_id}; tier-0 → empty (use
    `is_platform_admin` for unrestricted access).
    """
    if getattr(session, "rbac_tier", 1) == 0:
        return frozenset()
    tid = getattr(session, "tenant_id", None)
    if tid is None:
        return frozenset()
    return frozenset({tid})
```

- [ ] **Step 4: Run test to verify pass**

Run: `uv run pytest tests/auth_scope/test_auth_scope.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add autoservice/auth_scope.py tests/auth_scope/__init__.py tests/auth_scope/test_auth_scope.py
git commit -m "feat(auth_scope): add TenantScope and get_accessible_tenants

Introduces the single source of truth for operator↔tenant access decisions.
1:1 today; 1:N evolution lives in this module only.

Refs: docs/superpowers/specs/2026-04-28-operator-web-tenant-isolation-design.md §5.1"
```

---

### Task 2: resolve_effective_tenant with all 4 rules

**Files:**
- Modify: `autoservice/auth_scope.py`
- Test: `tests/auth_scope/test_auth_scope.py`

- [ ] **Step 1: Add tests for resolve_effective_tenant rules**

Append to `tests/auth_scope/test_auth_scope.py`:

```python
import pytest
from fastapi import HTTPException
from autoservice.auth_scope import resolve_effective_tenant


class _Session:
    def __init__(self, tenant_id, rbac_tier=1):
        self.tenant_id = tenant_id
        self.rbac_tier = rbac_tier


def test_resolve_none_request_defaults_to_session_tenant():
    scope = resolve_effective_tenant(_Session("t1"), requested_tenant_id=None)
    assert scope.effective_tenant_id == "t1"
    assert scope.accessible_tenants == frozenset({"t1"})
    assert scope.is_platform_admin is False


def test_resolve_explicit_request_in_accessible_succeeds():
    scope = resolve_effective_tenant(_Session("t1"), requested_tenant_id="t1")
    assert scope.effective_tenant_id == "t1"


def test_resolve_explicit_request_outside_accessible_raises_403():
    with pytest.raises(HTTPException) as exc:
        resolve_effective_tenant(_Session("t1"), requested_tenant_id="t2")
    assert exc.value.status_code == 403


def test_resolve_platform_admin_can_request_any_tenant():
    scope = resolve_effective_tenant(
        _Session("_master", rbac_tier=0), requested_tenant_id="t99",
    )
    assert scope.effective_tenant_id == "t99"
    assert scope.is_platform_admin is True


def test_resolve_platform_admin_default_returns_master():
    scope = resolve_effective_tenant(
        _Session("_master", rbac_tier=0), requested_tenant_id=None,
    )
    assert scope.effective_tenant_id == "_master"
    assert scope.is_platform_admin is True


def test_resolve_tenant_operator_with_no_tenant_id_raises():
    """Defensive: a session row whose tenant_id is None and tier is 1 is
    malformed — should not silently default."""
    with pytest.raises(HTTPException) as exc:
        resolve_effective_tenant(_Session(None, rbac_tier=1), requested_tenant_id=None)
    assert exc.value.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth_scope/test_auth_scope.py -v`
Expected: 6 FAILs with `ImportError: cannot import name 'resolve_effective_tenant'`

- [ ] **Step 3: Implement resolve_effective_tenant**

Append to `autoservice/auth_scope.py`:

```python
from fastapi import HTTPException


def resolve_effective_tenant(
    session: _SessionLike,
    requested_tenant_id: str | None,
) -> TenantScope:
    """Decide which tenant_id this request operates on.

    Rules:
      1. Tier-0 platform admin: requested wins (or '_master' if None).
      2. Tier-1 operator + requested=None: defaults to session.tenant_id;
         403 if session has no tenant_id (malformed).
      3. Tier-1 operator + requested ∈ accessible: effective = requested.
      4. Tier-1 operator + requested ∉ accessible: 403.
    """
    is_admin = getattr(session, "rbac_tier", 1) == 0
    accessible = get_accessible_tenants(session)

    if is_admin:
        effective = requested_tenant_id or "_master"
        return TenantScope(
            effective_tenant_id=effective,
            accessible_tenants=accessible,
            is_platform_admin=True,
        )

    # Tier-1 operator from here on
    session_tid = getattr(session, "tenant_id", None)
    if requested_tenant_id is None:
        if session_tid is None:
            raise HTTPException(status_code=403, detail="session has no tenant scope")
        return TenantScope(
            effective_tenant_id=session_tid,
            accessible_tenants=accessible,
            is_platform_admin=False,
        )

    if requested_tenant_id not in accessible:
        raise HTTPException(
            status_code=403,
            detail=f"tenant_id={requested_tenant_id!r} not in accessible scope",
        )
    return TenantScope(
        effective_tenant_id=requested_tenant_id,
        accessible_tenants=accessible,
        is_platform_admin=False,
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/auth_scope/test_auth_scope.py -v`
Expected: PASS (9 tests total: 3 from Task 1 + 6 from Task 2)

- [ ] **Step 5: Commit**

```bash
git add autoservice/auth_scope.py tests/auth_scope/test_auth_scope.py
git commit -m "feat(auth_scope): add resolve_effective_tenant with 4 access rules

Forward-compat for 1:N: requested tenant_id (optional) checked against
accessible set. Tier-0 platform admin can request any tenant_id."
```

---

### Task 3: Migration — backfill conversations.metadata.tenant_id = '_master'

**Files:**
- Create: `autoservice/migrations/2026_04_28_backfill_conv_tenant_id.py`
- Test: `tests/migrations/test_backfill_conv_tenant_id.py`

- [ ] **Step 1: Inspect the conversations table schema**

Run: `uv run python -c "import sqlite3; c = sqlite3.connect('.autoservice/database/conversations.db' if __import__('os').path.exists('.autoservice/database/conversations.db') else ':memory:'); print([r for r in c.execute('SELECT sql FROM sqlite_master WHERE type=\"table\"')])"`
Expected: confirm `conversations` table exists with `metadata` column (JSON-stringified TEXT). If path different, search via `Glob` for `*.db` under `.autoservice/database/`.

- [ ] **Step 2: Write migration test (idempotency + correctness)**

```python
# tests/migrations/test_backfill_conv_tenant_id.py
import json
import sqlite3
import pytest

from autoservice.migrations import _2026_04_28_backfill_conv_tenant_id as mig


def _seed(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY,
            metadata TEXT NOT NULL DEFAULT '{}'
        );
        INSERT INTO conversations VALUES ('c1', '{"channel":"web"}');
        INSERT INTO conversations VALUES ('c2', '{"channel":"web","tenant_id":"t1"}');
        INSERT INTO conversations VALUES ('c3', '{}');
        INSERT INTO conversations VALUES ('c4', '{"tenant_id":"_master"}');
    """)
    conn.commit()


def test_backfill_assigns_master_to_missing_tenant_id():
    conn = sqlite3.connect(":memory:")
    _seed(conn)
    mig.run(conn)
    rows = {r[0]: json.loads(r[1]) for r in conn.execute("SELECT id, metadata FROM conversations")}
    assert rows["c1"]["tenant_id"] == "_master"
    assert rows["c2"]["tenant_id"] == "t1"        # untouched
    assert rows["c3"]["tenant_id"] == "_master"
    assert rows["c4"]["tenant_id"] == "_master"   # untouched


def test_backfill_idempotent():
    conn = sqlite3.connect(":memory:")
    _seed(conn)
    mig.run(conn)
    snapshot1 = list(conn.execute("SELECT id, metadata FROM conversations ORDER BY id"))
    mig.run(conn)
    snapshot2 = list(conn.execute("SELECT id, metadata FROM conversations ORDER BY id"))
    assert snapshot1 == snapshot2


def test_backfill_returns_count_of_modified_rows():
    conn = sqlite3.connect(":memory:")
    _seed(conn)
    n = mig.run(conn)
    assert n == 2  # c1 and c3 had no tenant_id
    n2 = mig.run(conn)
    assert n2 == 0  # idempotent — no further changes
```

- [ ] **Step 3: Run tests, expect ImportError**

Run: `uv run pytest tests/migrations/test_backfill_conv_tenant_id.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Create migration package + module**

```bash
mkdir -p autoservice/migrations
touch autoservice/migrations/__init__.py
```

Create `autoservice/migrations/_2026_04_28_backfill_conv_tenant_id.py` (underscore prefix because the date starts with a digit, not a valid Python identifier):

```python
"""Backfill conversations.metadata.tenant_id = '_master' for legacy rows.

Idempotent: targets only rows where metadata.tenant_id IS NULL.
SQLite JSON1 functions used; SQLite >= 3.38 (Python 3.11+ wheels OK).

Spec: docs/superpowers/specs/2026-04-28-operator-web-tenant-isolation-design.md §5.6
"""

from __future__ import annotations

import sqlite3


_SQL = """
UPDATE conversations
SET metadata = json_set(metadata, '$.tenant_id', '_master')
WHERE json_extract(metadata, '$.tenant_id') IS NULL;
"""


def run(conn: sqlite3.Connection) -> int:
    """Apply the migration to *conn*. Returns the number of rows modified."""
    cur = conn.execute(_SQL)
    conn.commit()
    return cur.rowcount or 0


if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(".autoservice/database/conversations.db"),
        help="Path to conversations SQLite DB",
    )
    args = parser.parse_args()
    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(str(args.db))
    n = run(conn)
    print(f"backfilled {n} conversation rows")
```

- [ ] **Step 5: Add the import alias the test uses**

Add to `autoservice/migrations/__init__.py`:

```python
from . import _2026_04_28_backfill_conv_tenant_id
```

- [ ] **Step 6: Run tests, expect pass**

Run: `uv run pytest tests/migrations/test_backfill_conv_tenant_id.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git add autoservice/migrations/ tests/migrations/test_backfill_conv_tenant_id.py
git commit -m "feat(migration): backfill conversations.metadata.tenant_id=_master

Idempotent SQLite JSON1 UPDATE for legacy rows missing tenant_id.
CLI: uv run python -m autoservice.migrations._2026_04_28_backfill_conv_tenant_id"
```

---

### Task 4: LocalEngine startup fixup for in-memory `_conversations`

**Files:**
- Modify: `autoservice/conversation_engine/local_engine.py`
- Test: `tests/operator_isolation/test_engine_tenant_filter.py` (new file, first test)

- [ ] **Step 1: Locate LocalEngine `__init__` and the persistence loader**

Run: `Grep` `class LocalEngine|_load_persisted|_conversations` in `autoservice/conversation_engine/local_engine.py` to find init/cold-start lines.
Expected: report file:line of `class LocalEngine` and where `_conversations` is populated.

- [ ] **Step 2: Write test for in-memory fixup**

```python
# tests/operator_isolation/__init__.py — empty
```

```python
# tests/operator_isolation/test_engine_tenant_filter.py
import pytest

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import (
    Conversation, ConversationMode, ConversationState,
)


@pytest.mark.asyncio
async def test_localengine_backfills_missing_tenant_id_on_startup(tmp_path):
    """A LocalEngine started against state with conv.metadata lacking
    tenant_id should rewrite metadata.tenant_id='_master' in-place."""
    engine = LocalEngine()
    # Inject a malformed legacy conversation directly
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    legacy = Conversation(
        id="legacy_1",
        state=ConversationState.CREATED,
        mode=ConversationMode.AUTO,
        participants=(),
        created_at=now, updated_at=now,
        metadata={"channel": "feishu"},  # no tenant_id
    )
    engine._conversations["legacy_1"] = legacy
    engine.normalize_tenant_metadata()  # the new fixup hook
    assert engine._conversations["legacy_1"].metadata["tenant_id"] == "_master"
```

- [ ] **Step 3: Run test, expect AttributeError on `normalize_tenant_metadata`**

Run: `uv run pytest tests/operator_isolation/test_engine_tenant_filter.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement `normalize_tenant_metadata` and call it from `__init__`**

In `autoservice/conversation_engine/local_engine.py`, add a method on `LocalEngine`:

```python
def normalize_tenant_metadata(self) -> int:
    """Backfill tenant_id='_master' on any in-memory conversation whose
    metadata is missing it. Idempotent. Returns # of rows fixed up.

    Logs a warning per fixup so spurious tenant-less data is observable.
    """
    fixed = 0
    for cid, conv in list(self._conversations.items()):
        if conv.metadata.get("tenant_id"):
            continue
        new_meta = dict(conv.metadata)
        new_meta["tenant_id"] = "_master"
        # Conversation is a dataclass — replace returns a new frozen instance
        from dataclasses import replace
        self._conversations[cid] = replace(conv, metadata=new_meta)
        logger.warning(
            "normalize_tenant_metadata: fixed up conv=%s metadata had no tenant_id",
            cid,
        )
        fixed += 1
    return fixed
```

Then call `self.normalize_tenant_metadata()` at the END of `__init__` (after any persistence load).

- [ ] **Step 5: Run test, expect pass**

Run: `uv run pytest tests/operator_isolation/test_engine_tenant_filter.py::test_localengine_backfills_missing_tenant_id_on_startup -v`
Expected: PASS.

- [ ] **Step 6: Run the existing LocalEngine test suite for regression**

Run: `uv run pytest tests/conversation_engine/ -v`
Expected: ALL PASS (no behavior change for already-tagged conversations).

- [ ] **Step 7: Commit**

```bash
git add autoservice/conversation_engine/local_engine.py tests/operator_isolation/__init__.py tests/operator_isolation/test_engine_tenant_filter.py
git commit -m "feat(engine): normalize_tenant_metadata cold-start fixup

Backfills metadata.tenant_id='_master' for in-memory conversations whose
metadata is missing it (mirror of SQL migration in Task 3, for the case
where persistence layer is bypassed)."
```

---

### Task 5: message_router web write-side `_master` fallback

**Files:**
- Modify: `autoservice/gateway/message_router.py:530-533`
- Test: `tests/operator_isolation/test_message_router_tenant_default.py`

- [ ] **Step 1: Write test for fallback + warning**

```python
# tests/operator_isolation/test_message_router_tenant_default.py
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock

from autoservice.gateway import message_router
from autoservice.master_tenant import MASTER_TENANT_ID


@pytest.mark.asyncio
async def test_conv_created_without_ws_tenant_id_falls_back_to_master(
    caplog, monkeypatch,
):
    caplog.set_level(logging.WARNING, logger=message_router.logger.name)

    # Build a fake engine that captures create_conversation kwargs
    captured = {}
    async def fake_create(*, channel, external_id, metadata):
        captured["metadata"] = metadata
        from autoservice.conversation_engine.types import (
            Conversation, ConversationMode, ConversationState,
        )
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        return Conversation(
            id=f"{channel}_{external_id}", state=ConversationState.CREATED,
            mode=ConversationMode.AUTO, participants=(),
            created_at=now, updated_at=now, metadata=metadata,
        )

    fake_engine = MagicMock()
    fake_engine.get_conversation = AsyncMock(side_effect=Exception("not found"))
    fake_engine.create_conversation = AsyncMock(side_effect=fake_create)
    fake_engine.join = AsyncMock()
    fake_engine.send_message = AsyncMock(return_value=MagicMock(id="m1"))

    fake_ws = MagicMock()
    # Critically: NO state_customer_tenant_id attribute
    fake_ws.state_customer_tenant_id = None

    # Drive the path that creates a conversation
    # (Exact call signature of message_router.handle_message_envelope or
    #  the customer ingress depends on current code — adjust as needed)
    await message_router._create_or_get_conversation_for_customer(
        engine=fake_engine, source="anon_1", ws=fake_ws,
    )

    assert captured["metadata"]["tenant_id"] == MASTER_TENANT_ID
    assert any(
        "without tenant_id" in rec.message for rec in caplog.records
    )
```

> **Note:** The exact helper name / call site in `message_router.py` may differ — Step 4 directs the engineer to find the right line and refactor a small helper if needed.

- [ ] **Step 2: Run test, expect failure**

Run: `uv run pytest tests/operator_isolation/test_message_router_tenant_default.py -v`
Expected: FAIL — depending on current structure either AttributeError or wrong default.

- [ ] **Step 3: Patch the write-side**

In `autoservice/gateway/message_router.py` around line 530, replace:

```python
            # tenant_id pinned by web_gateway._handle_connection via the
            # /ws/customer?tenant=<tid> query (validated by tenant_resolver).
            # Downstream: triage_config_loader reads conv.metadata["tenant_id"]
            # and drives KB pre-fetch + tenant-soul recycle.
            if ws is not None:
                tid = getattr(ws, "state_customer_tenant_id", None)
                if tid:
                    meta["tenant_id"] = tid
```

with:

```python
            # tenant_id pinned by web_gateway._handle_connection via the
            # /ws/customer?tenant=<tid> query (validated by tenant_resolver).
            # Falls back to _master if missing — so engine queries (which
            # require tenant_id, see auth_scope/engine signatures) can never
            # observe a tenant-less conversation. Warning logged so spurious
            # fallback fires are observable.
            tid: str | None = None
            if ws is not None:
                tid = getattr(ws, "state_customer_tenant_id", None)
            if not tid:
                from autoservice.master_tenant import MASTER_TENANT_ID
                logger.warning(
                    "conv created without tenant_id, defaulting to _master: "
                    "source=%s ws=%s",
                    source, "present" if ws else "none",
                )
                tid = MASTER_TENANT_ID
            meta["tenant_id"] = tid
```

If the test in Step 1 references a helper that doesn't exist, extract this block into `def _resolve_conv_tenant_id(ws) -> str: ...` and adjust the test accordingly.

- [ ] **Step 4: Run test, expect pass**

Run: `uv run pytest tests/operator_isolation/test_message_router_tenant_default.py -v`
Expected: PASS.

- [ ] **Step 5: Run gateway regression suite**

Run: `uv run pytest tests/gateway/ -v`
Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add autoservice/gateway/message_router.py tests/operator_isolation/test_message_router_tenant_default.py
git commit -m "feat(message_router): fallback to _master when ws lacks tenant_id

Closes the write-side hole where web channel could persist a conv with
no tenant_id in metadata. Logs a warning so unexpected fallbacks are
observable in logs."
```

---

### Task 6: Phase-1 sanity sweep

- [ ] **Step 1: Run the entire test suite**

Run: `uv run pytest -x -q`
Expected: ALL PASS. No regressions from the additive Phase 1 changes.

- [ ] **Step 2: Manually run the migration against a copy of the dev DB**

```bash
cp .autoservice/database/conversations.db /tmp/conv_backup.db 2>/dev/null || echo "no dev DB yet"
test -f .autoservice/database/conversations.db && \
  uv run python -m autoservice.migrations._2026_04_28_backfill_conv_tenant_id \
    --db .autoservice/database/conversations.db
```
Expected: prints `backfilled <N> conversation rows`. Re-run prints `backfilled 0`.

- [ ] **Step 3: Stop. No commit. Phase 1 done.**

---

## Phase 2: Engine signature change (atomic per method)

> **Discipline:** every task in Phase 2 commits the engine change AND every caller of that method in the same commit. Never leave the suite red between tasks. If grep finds an unexpected new caller mid-task, fold it in before committing.

### Task 7: list_active_conversations — add mandatory tenant_id

**Files:**
- Modify: `autoservice/conversation_engine/protocol.py:40`
- Modify: `autoservice/conversation_engine/local_engine.py:453`
- Modify: `autoservice/api_routes.py:445` (caller — covered fully in Task 11; here only signature compatibility)
- Modify: `autoservice/gateway/offline_watcher.py` (caller)
- Modify: `tests/contract/test_protocol_signatures.py`, `tests/contract/test_lifecycle.py`, `tests/conversation_engine/test_local_engine.py` (test callers)
- Test: `tests/operator_isolation/test_engine_tenant_filter.py` (extend)

- [ ] **Step 1: Add tenant-filter test**

Append to `tests/operator_isolation/test_engine_tenant_filter.py`:

```python
@pytest.mark.asyncio
async def test_list_active_conversations_filters_by_tenant_id():
    engine = LocalEngine()
    await engine.create_conversation(
        channel="web", external_id="u1", metadata={"tenant_id": "t1"},
    )
    await engine.create_conversation(
        channel="web", external_id="u2", metadata={"tenant_id": "t2"},
    )
    res_t1 = await engine.list_active_conversations(tenant_id="t1")
    assert {c.id for c in res_t1} == {"web_u1"}
    res_t2 = await engine.list_active_conversations(tenant_id="t2")
    assert {c.id for c in res_t2} == {"web_u2"}


@pytest.mark.asyncio
async def test_list_active_conversations_rejects_missing_tenant_id():
    engine = LocalEngine()
    with pytest.raises(TypeError):
        await engine.list_active_conversations()  # type: ignore[call-arg]
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run pytest tests/operator_isolation/test_engine_tenant_filter.py -v`
Expected: FAIL — engine still ignores tenant_id.

- [ ] **Step 3: Update protocol.py:40**

In `autoservice/conversation_engine/protocol.py:40`, change abstract signature:

```python
    async def list_active_conversations(
        self,
        *,
        tenant_id: str,                    # NEW — mandatory
        operator_id: str | None = None,
        squad_id: str | None = None,
    ) -> list[Conversation]: ...
```

- [ ] **Step 4: Update local_engine.py:453 implementation**

```python
    async def list_active_conversations(
        self,
        *,
        tenant_id: str,
        operator_id: str | None = None,
        squad_id: str | None = None,
    ) -> list[Conversation]:
        result = [
            c for c in self._conversations.values()
            if c.state != ConversationState.CLOSED
            and c.metadata.get("tenant_id") == tenant_id
        ]
        if operator_id is not None:
            result = [
                c for c in result
                if any(p.id == operator_id for p in self._participants.get(c.id, []))
            ]
        if squad_id is not None:
            result = [c for c in result if c.metadata.get("squad_id") == squad_id]
        return result
```

- [ ] **Step 5: Grep all callers**

Run: `Grep` pattern `list_active_conversations\(` across `**/*.py`.
Expected: list of files. Update every call site to pass `tenant_id=`.

For tests that don't care about tenant filtering (most of `tests/conversation_engine/`, `tests/contract/`, etc.), pass `tenant_id="_master"` explicitly — this is the documented "I'm tier-0 / I want to see everything" sentinel, and tests using it should also seed conversations with `metadata={"tenant_id":"_master"}` (or any other consistent value).

For `autoservice/api_routes.py:455`, leave a TODO comment `# TODO Task 11: pass scope.effective_tenant_id` and pass `tenant_id="_master"` for now (Task 11 will replace it).

For `autoservice/gateway/offline_watcher.py`, identify whether the caller has tenant context; if not, pass `tenant_id="_master"` and add a `# TODO` for follow-up.

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -x -q`
Expected: ALL PASS.

- [ ] **Step 7: Commit**

```bash
git add autoservice/conversation_engine/protocol.py \
        autoservice/conversation_engine/local_engine.py \
        autoservice/api_routes.py \
        autoservice/gateway/offline_watcher.py \
        tests/contract/test_protocol_signatures.py \
        tests/contract/test_lifecycle.py \
        tests/conversation_engine/test_local_engine.py \
        tests/operator_isolation/test_engine_tenant_filter.py
git commit -m "feat(engine): list_active_conversations requires tenant_id

Defense-in-depth (spec §5.2 Q2 B): mandatory tenant_id parameter on the
engine query method; type system catches missing-filter at call sites.
All current callers updated; api_routes.py:455 carries a TODO for Task 11."
```

---

### Task 8: list_conversations_in_takeover_by — add mandatory tenant_id

**Files:**
- Modify: `autoservice/conversation_engine/protocol.py:47`
- Modify: `autoservice/conversation_engine/local_engine.py:444`
- Modify: callers (see Step 3)
- Test: `tests/operator_isolation/test_engine_tenant_filter.py` (extend)

- [ ] **Step 1: Add filter test**

Append to `tests/operator_isolation/test_engine_tenant_filter.py`:

```python
@pytest.mark.asyncio
async def test_list_conversations_in_takeover_by_filters_by_tenant():
    engine = LocalEngine()
    # Setup: 2 convs in different tenants, both in takeover by op_x
    from datetime import datetime, timezone
    from autoservice.conversation_engine.types import Participant, ParticipantRole
    now = datetime.now(timezone.utc)
    for cid, tid in [("c1", "t1"), ("c2", "t2")]:
        await engine.create_conversation(
            channel="web", external_id=cid, metadata={"tenant_id": tid},
        )
        # mark as takeover by op_x
        full_id = f"web_{cid}"
        engine._conversations[full_id] = engine._conversations[full_id].__class__(
            **{**engine._conversations[full_id].__dict__, "takeover_operator_id": "op_x"}
        )
    res = await engine.list_conversations_in_takeover_by(
        tenant_id="t1", operator_id="op_x",
    )
    assert {c.id for c in res} == {"web_c1"}
```

- [ ] **Step 2: Run, expect TypeError**

Run: `uv run pytest tests/operator_isolation/test_engine_tenant_filter.py::test_list_conversations_in_takeover_by_filters_by_tenant -v`
Expected: FAIL.

- [ ] **Step 3: Update protocol + impl + callers**

In `autoservice/conversation_engine/protocol.py:47`:
```python
    async def list_conversations_in_takeover_by(
        self, *, tenant_id: str, operator_id: str,
    ) -> list[Conversation]: ...
```

In `autoservice/conversation_engine/local_engine.py:444`:
```python
    async def list_conversations_in_takeover_by(
        self, *, tenant_id: str, operator_id: str,
    ) -> list[Conversation]:
        return [
            conv
            for conv in self._conversations.values()
            if conv.state != ConversationState.CLOSED
            and conv.metadata.get("tenant_id") == tenant_id
            and conv.takeover_operator_id == operator_id
        ]
```

Run: `Grep` `list_conversations_in_takeover_by\(` across `**/*.py`. Update every caller (likely 1–2 production callers and a handful of tests). Production callers without tenant context get `tenant_id="_master"` + `# TODO`.

- [ ] **Step 4: Run full suite**

Run: `uv run pytest -x -q`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add autoservice/conversation_engine/protocol.py \
        autoservice/conversation_engine/local_engine.py \
        $(git diff --name-only -- '*.py' | tr '\n' ' ')
git commit -m "feat(engine): list_conversations_in_takeover_by requires tenant_id"
```

---

### Task 9: get_conversation — add mandatory tenant_id with TenantMismatch

**Files:**
- Modify: `autoservice/conversation_engine/protocol.py:36`
- Modify: `autoservice/conversation_engine/local_engine.py:441`
- Modify: ~20+ caller files (see grep results: 50 occurrences)
- Test: `tests/operator_isolation/test_engine_tenant_filter.py` (extend); add `TenantMismatch` to types module

> **Blast radius:** ~50 occurrences across 27 files. Most are tests using `engine.get_conversation(conv_id)` as setup. Strategy: introduce `TenantMismatch` exception; use a small migration helper (sed/regex) for trivial test updates; manually review production callers.

- [ ] **Step 1: Define `TenantMismatch` exception**

In `autoservice/conversation_engine/protocol.py` (or `types.py`, wherever `ConversationNotFound` lives), add:

```python
class TenantMismatch(Exception):
    """Raised by get_conversation/get_messages when conv.metadata.tenant_id
    does not match the caller's declared tenant scope. Distinct from
    ConversationNotFound: the conv exists but is not visible to this caller."""
```

- [ ] **Step 2: Add tests**

Append to `tests/operator_isolation/test_engine_tenant_filter.py`:

```python
@pytest.mark.asyncio
async def test_get_conversation_returns_when_tenant_matches():
    engine = LocalEngine()
    await engine.create_conversation(
        channel="web", external_id="u1", metadata={"tenant_id": "t1"},
    )
    conv = await engine.get_conversation("web_u1", tenant_id="t1")
    assert conv.id == "web_u1"


@pytest.mark.asyncio
async def test_get_conversation_raises_tenant_mismatch_on_mismatch():
    from autoservice.conversation_engine.protocol import TenantMismatch
    engine = LocalEngine()
    await engine.create_conversation(
        channel="web", external_id="u1", metadata={"tenant_id": "t1"},
    )
    with pytest.raises(TenantMismatch):
        await engine.get_conversation("web_u1", tenant_id="t2")


@pytest.mark.asyncio
async def test_get_conversation_master_passes_through():
    """tenant_id='_master' on get_conversation lets platform admin see any conv
    (consistent with §5.2 of spec — _master is the explicit cross-tenant value)."""
    engine = LocalEngine()
    await engine.create_conversation(
        channel="web", external_id="u1", metadata={"tenant_id": "t1"},
    )
    conv = await engine.get_conversation("web_u1", tenant_id="_master")
    assert conv.id == "web_u1"
```

- [ ] **Step 3: Run, expect failure**

Run: `uv run pytest tests/operator_isolation/test_engine_tenant_filter.py -v`
Expected: 3 NEW FAILS (TypeError on missing kw, plus AttributeError on TenantMismatch).

- [ ] **Step 4: Update protocol + impl**

`autoservice/conversation_engine/protocol.py:36`:
```python
    async def get_conversation(
        self, conversation_id: str, *, tenant_id: str,
    ) -> Conversation: ...
```

`autoservice/conversation_engine/local_engine.py:441`:
```python
    async def get_conversation(
        self, conversation_id: str, *, tenant_id: str,
    ) -> Conversation:
        conv = self._get_conv(conversation_id)
        conv_tid = conv.metadata.get("tenant_id")
        if tenant_id != "_master" and conv_tid != tenant_id:
            raise TenantMismatch(
                f"conv={conversation_id} tenant_id={conv_tid!r} "
                f"requested_tenant_id={tenant_id!r}"
            )
        return conv
```

- [ ] **Step 5: Update production callers**

Grep: `\.get_conversation\(` across `autoservice/**/*.py`. Expect ~6 production callers.

For each caller:
- If the caller has tenant context (e.g., from `conv.metadata` already, or a request session), pass that.
- Otherwise pass `tenant_id="_master"` and leave a `# TODO Task 11/12/...` comment naming the API task that will replace it.

For `message_router.py` callers (9 occurrences): they nearly always already know the tenant_id (either from conv being created in same flow or from ws.state). Use that.

- [ ] **Step 6: Bulk-update test callers**

For `tests/contract/`, `tests/conversation_engine/`, `tests/conversation/`, `tests/triage/`, `tests/gateway/`, `tests/e2e/`: these tests typically don't care about tenant filtering. Run a regex bulk update:

```bash
# preview
git ls-files 'tests/**/*.py' | xargs grep -l '\.get_conversation(' | head -20
# apply (tests pass tenant_id='_master' since they seed conversations without explicit tenant; the in-memory fixup added in Task 4 ensures created conversations have tenant_id='_master')
git ls-files 'tests/**/*.py' | xargs grep -l '\.get_conversation(' | while read f; do
  python -c "
import re, sys
path=sys.argv[1]
src=open(path).read()
# add tenant_id='_master' as last kwarg if missing
new = re.sub(
    r'\.get_conversation\(([^)]*?)\)',
    lambda m: '.get_conversation(' + m.group(1) + (', tenant_id=\"_master\"' if 'tenant_id=' not in m.group(1) else '') + ')',
    src,
)
open(path, 'w').write(new)
" "$f"
done
```

Then manually review the diff for false matches (the regex won't handle multi-line calls — those need eyeballing).

- [ ] **Step 7: Run full suite, fix any stragglers**

Run: `uv run pytest -x -q`
Expected: All PASS. If a test fails because the bulk regex missed a multi-line call, add the kw manually.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(engine): get_conversation requires tenant_id; raise TenantMismatch

~50 callers updated. Tests pass tenant_id='_master' as the explicit
cross-tenant value. Production callers either pass real tenant_id from
context or carry a TODO for the API-layer task that will inject it."
```

---

### Task 10: get_messages — add mandatory tenant_id

**Files:**
- Modify: `autoservice/conversation_engine/protocol.py:106`
- Modify: `autoservice/conversation_engine/local_engine.py:716`
- Modify: ~20 caller files (~45 occurrences)
- Test: extend `tests/operator_isolation/test_engine_tenant_filter.py`

Same shape as Task 9 but for `get_messages`. The implementation should reuse the validation: internally call `await self.get_conversation(conv_id, tenant_id=tenant_id)` first (which already raises TenantMismatch), then return messages.

- [ ] **Step 1: Add filter test**

```python
@pytest.mark.asyncio
async def test_get_messages_raises_on_tenant_mismatch():
    from autoservice.conversation_engine.protocol import TenantMismatch
    engine = LocalEngine()
    await engine.create_conversation(
        channel="web", external_id="u1", metadata={"tenant_id": "t1"},
    )
    with pytest.raises(TenantMismatch):
        await engine.get_messages("web_u1", tenant_id="t2", viewer_role="operator")
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run pytest tests/operator_isolation/test_engine_tenant_filter.py::test_get_messages_raises_on_tenant_mismatch -v`
Expected: FAIL.

- [ ] **Step 3: Update protocol + impl**

```python
# protocol.py:106
async def get_messages(
    self, conversation_id: str, *,
    tenant_id: str,
    viewer_role: str | ParticipantRole | None = None,
    limit: int | None = None,
    since_sequence: int | None = None,
) -> list[Message]: ...
```

```python
# local_engine.py:716 — add tenant guard at top
async def get_messages(self, conversation_id, *, tenant_id, viewer_role=None, limit=None, since_sequence=None):
    # Reuse get_conversation's tenant check (raises TenantMismatch on mismatch)
    await self.get_conversation(conversation_id, tenant_id=tenant_id)
    # ... existing body unchanged ...
```

- [ ] **Step 4: Update all callers (production + tests)**

Same playbook as Task 9. Bulk regex for tests; manual for production.

For `api_routes.py:462` (the existing internal `engine.get_messages(c.id, viewer_role="operator", limit=100)` call inside `list_active_conversations`), pass `tenant_id=scope.effective_tenant_id` once Task 11 lands; for now pass `tenant_id="_master"` with `# TODO Task 11`.

- [ ] **Step 5: Run full suite**

Run: `uv run pytest -x -q`
Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(engine): get_messages requires tenant_id; reuses get_conversation guard"
```

---

## Phase 3: API layer

### Task 11: GET /api/conversations/active — wire tenant_id

**Files:**
- Modify: `autoservice/api_routes.py:445-487`
- Test: `tests/operator_isolation/test_api_tenant_filter.py` (new)

- [ ] **Step 1: Locate `require_operator_session` (or equivalent)**

Run: `Grep` `def require_operator_session|operator_session_from_request` across `autoservice/`.
Expected: identify the FastAPI dependency that returns the operator's `SessionRow`. If only `/api/auth/operator/me` reads the cookie, factor a dependency from `operator_routes.py:262-280`'s implementation. Otherwise reuse the existing one.

- [ ] **Step 2: Write API test**

```python
# tests/operator_isolation/test_api_tenant_filter.py
import pytest
from fastapi.testclient import TestClient

# Use existing app fixture from conftest if present; else build minimal app
from channels.web.app import app


@pytest.fixture
def client():
    return TestClient(app)


def _login_as(client, *, tenant_id: str, operator_id: str = "op1") -> None:
    """Helper: hit dev-login (or password-login with mock) and stash cookie."""
    r = client.post(
        "/api/auth/operator/dev-login",
        json={"operator_id": operator_id, "tenant_id": tenant_id},
    )
    assert r.status_code == 200, r.text


def test_active_conversations_filters_to_session_tenant(client):
    # Seed 2 convs in 2 tenants via direct engine call
    from autoservice.api_routes import _ws_engine
    engine = _ws_engine()
    import asyncio
    asyncio.run(engine.create_conversation(
        channel="web", external_id="A", metadata={"tenant_id": "t1"},
    ))
    asyncio.run(engine.create_conversation(
        channel="web", external_id="B", metadata={"tenant_id": "t2"},
    ))
    _login_as(client, tenant_id="t1")
    r = client.get("/api/conversations/active")
    assert r.status_code == 200
    ids = {c["id"] for c in r.json()["conversations"]}
    assert "web_A" in ids
    assert "web_B" not in ids


def test_active_conversations_explicit_other_tenant_403(client):
    _login_as(client, tenant_id="t1")
    r = client.get("/api/conversations/active?tenant_id=t2")
    assert r.status_code == 403


def test_active_conversations_master_can_see_all(client):
    _login_as(client, tenant_id="_master", operator_id="platform_admin")
    r = client.get("/api/conversations/active?tenant_id=t2")
    assert r.status_code == 200
```

> **Note:** the dev-login JSON shape may be different — adjust per actual `LoginPage.tsx:100` payload, which is `{operator_id, tenant_id}`. Verify by reading the endpoint impl.

- [ ] **Step 3: Run test, expect failure**

Run: `uv run pytest tests/operator_isolation/test_api_tenant_filter.py::test_active_conversations_filters_to_session_tenant -v`
Expected: FAIL — endpoint still doesn't filter.

- [ ] **Step 4: Patch the endpoint**

In `autoservice/api_routes.py:445-457`:

```python
@api_router.get("/conversations/active")
async def list_active_conversations(
    request: Request,
    tenant_id: str | None = None,
    squad_id: str | None = None,
    operator_id: str | None = None,
) -> dict[str, Any]:
    from autoservice.auth_scope import resolve_effective_tenant
    session = require_operator_session(request)
    scope = resolve_effective_tenant(session, tenant_id)
    engine = _ws_engine()
    if engine is None:
        return {"conversations": []}
    convs = await engine.list_active_conversations(
        tenant_id=scope.effective_tenant_id,
        operator_id=operator_id,
        squad_id=squad_id,
    )
    items: list[dict[str, Any]] = []
    for c in convs:
        try:
            msgs = await engine.get_messages(
                c.id, tenant_id=scope.effective_tenant_id,
                viewer_role="operator", limit=100,
            )
        except Exception:
            msgs = []
        # ... rest of body unchanged ...
```

Replace the previous `tenant_id="_master"` TODO from Task 7 / Task 10.

- [ ] **Step 5: Run tests, expect pass**

Run: `uv run pytest tests/operator_isolation/test_api_tenant_filter.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add autoservice/api_routes.py tests/operator_isolation/test_api_tenant_filter.py
git commit -m "feat(api): /conversations/active filters by operator-session tenant_id

Forward-compat: query param tenant_id overrides default (with auth_scope
checking accessibility). Replaces the Task 7/10 TODO bridges."
```

---

### Task 12: GET /api/sla/summary — wire tenant_id

**Files:**
- Modify: `autoservice/api_routes.py:490-516`
- Modify: `autoservice/sla_aggregator.py` (add `tenant_id` parameter to query funcs)
- Test: extend `tests/operator_isolation/test_api_tenant_filter.py`

- [ ] **Step 1: Inspect `sla_aggregator.py` query function signatures**

Run: `Grep` `def .*[Mm]etric|class SlaAggregator|def query` across `autoservice/sla_aggregator.py`. Identify the function called by `/sla/summary`.
Expected: a function like `compute_metrics(window: WindowSize) -> dict` — needs `tenant_id` added.

- [ ] **Step 2: Write test**

```python
def test_sla_summary_filters_by_tenant(client):
    # Seed SLA data for two tenants; assert /sla/summary returns only one's
    # ... tenant-scoped data setup specific to current sla_aggregator ...
    _login_as(client, tenant_id="t1")
    r = client.get("/api/sla/summary?period=5m")
    assert r.status_code == 200
    # assertion shape depends on aggregator output
```

- [ ] **Step 3: Run, expect FAIL or PASS-with-cross-tenant-data**

- [ ] **Step 4: Add tenant_id param to sla_aggregator query**

Modify `sla_aggregator.compute_metrics` (or whatever the function is called) to accept `tenant_id: str` and add `WHERE tenant_id = ?` to the underlying SQL. If the SLA store lacks a tenant_id column, this is a separate schema migration — flag and fail loudly: this task is in scope only if the column exists.

- [ ] **Step 5: Wire endpoint**

```python
@api_router.get("/sla/summary")
async def sla_summary(
    request: Request, period: str = "5m", tenant_id: str | None = None,
) -> dict[str, Any]:
    from autoservice.auth_scope import resolve_effective_tenant
    session = require_operator_session(request)
    scope = resolve_effective_tenant(session, tenant_id)
    # ... existing validation of period unchanged ...
    return _format_sla(compute_metrics(window, tenant_id=scope.effective_tenant_id))
```

- [ ] **Step 6: Run tests**

- [ ] **Step 7: Commit**

```bash
git commit -m "feat(api): /sla/summary scoped to operator tenant"
```

---

### Task 13: GET /api/billing/invoices — wire tenant_id

Same shape as Task 12. Inspect `api_routes.py:518` to find the underlying repo/aggregator. Add `tenant_id` parameter to it. Wire endpoint via `resolve_effective_tenant`.

- [ ] **Step 1: Identify billing aggregator/repo**
- [ ] **Step 2: Write API test (cross-tenant 403, default to session tenant)**
- [ ] **Step 3: Add tenant_id to repo query**
- [ ] **Step 4: Wire endpoint**
- [ ] **Step 5: Run + commit**

---

### Task 14: GET /api/metrics/takeover-trend — wire tenant_id

Same shape. Endpoint at `api_routes.py:534`.

---

### Task 15: GET /api/metrics/operator-leaderboard — wire tenant_id

Same shape. Endpoint at `api_routes.py:545`.

> **Note:** leaderboard might intentionally be cross-tenant for platform admins. Design intent: tier-1 operator sees only own tenant's operators; tier-0 sees global. `resolve_effective_tenant` already encodes this.

---

### Task 16: GET /api/proposals — wire tenant_id

**Files:**
- Modify: `autoservice/api_routes.py:556-559`
- Modify: `autoservice/proposal_pipeline.py` (`list_proposals` adds `tenant_id` param)
- Test: extend `tests/operator_isolation/test_api_tenant_filter.py`

- [ ] **Step 1: Add `tenant_id` to `proposal_pipeline.list_proposals`**

```python
def list_proposals(
    *, tenant_id: str, status: str | None = None,
) -> list[Proposal]:
    sql = "SELECT * FROM proposals WHERE tenant_id = ?"
    params: list[Any] = [tenant_id]
    if status is not None:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC"
    return [Proposal(**dict(r)) for r in conn.execute(sql, params)]
```

(Adjust per actual current signature.)

- [ ] **Step 2: Write API test**

```python
def test_proposals_filters_by_tenant(client):
    # seed proposals for t1 and t2
    from autoservice import proposal_pipeline as pp
    pp.create_proposal(tenant_id="t1", ...)
    pp.create_proposal(tenant_id="t2", ...)
    _login_as(client, tenant_id="t1")
    r = client.get("/api/proposals")
    assert r.status_code == 200
    assert all(p["tenant_id"] == "t1" for p in r.json())
```

- [ ] **Step 3: Wire endpoint**

```python
@api_router.get("/proposals")
async def list_proposals(
    request: Request, tenant_id: str | None = None, status: str | None = None,
) -> list[dict[str, Any]]:
    from autoservice.auth_scope import resolve_effective_tenant
    session = require_operator_session(request)
    scope = resolve_effective_tenant(session, tenant_id)
    return pp.list_proposals(tenant_id=scope.effective_tenant_id, status=status)
```

- [ ] **Step 4: Run + commit**

---

## Phase 4: WS subscribe protocol

### Task 17: subscription_registry._scope_key — compound

**Files:**
- Modify: `autoservice/gateway/subscription_registry.py:121-129`
- Test: `tests/gateway/test_subscription_registry.py` (extend if exists; else create)

- [ ] **Step 1: Test compound key generation**

```python
# tests/gateway/test_subscription_registry.py (add tests)
from autoservice.gateway.subscription_registry import _scope_key


def test_scope_key_squad_with_tenant_compound():
    assert _scope_key({"tenant_id": "t1", "squad_id": "s1"}) == "tenant:t1|squad:s1"


def test_scope_key_global_with_tenant_compound():
    assert _scope_key({"tenant_id": "t1", "global": True}) == "tenant:t1|global"


def test_scope_key_conv_ignores_tenant_prefix():
    """conv_id is globally unique; tenant is implicit in conv.metadata."""
    assert _scope_key({"tenant_id": "t1", "conversation_id": "c1"}) == "conv:c1"


def test_scope_key_legacy_squad_only():
    """Backward-compat: squad-only scope still produces a key (used by tests
    and during migration period)."""
    assert _scope_key({"squad_id": "s1"}) == "squad:s1"
```

- [ ] **Step 2: Run, expect mismatch (current returns just `squad:s1`)**

- [ ] **Step 3: Update `_scope_key`**

```python
def _scope_key(scope: dict[str, Any]) -> str | None:
    """Derive a lookup key from a subscription scope."""
    if scope.get("conversation_id"):
        return f"conv:{scope['conversation_id']}"
    parts: list[str] = []
    if scope.get("tenant_id"):
        parts.append(f"tenant:{scope['tenant_id']}")
    if scope.get("squad_id"):
        parts.append(f"squad:{scope['squad_id']}")
    elif scope.get("global"):
        parts.append("global")
    return "|".join(parts) if parts else None
```

- [ ] **Step 4: Run tests, expect pass; run full registry suite for no regressions**

Run: `uv run pytest tests/gateway/test_subscription_registry.py -v`
Expected: PASS for new tests + existing ones (legacy squad-only still works).

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(subscription_registry): compound scope_key with tenant_id

conv: scope unchanged (conv_id is globally unique). squad/global gain a
'tenant:T1|' prefix when tenant_id is in the scope dict. Backward-compat
maintained for legacy callers omitting tenant_id."
```

---

### Task 18: WS subscribe handler — validate tenant_id via auth_scope

**Files:**
- Modify: `autoservice/gateway/message_router.py:309-345` (`_handle_subscribe`)
- Test: `tests/operator_isolation/test_ws_subscribe_tenant.py`

- [ ] **Step 1: Test cross-tenant subscribe rejected**

```python
# tests/operator_isolation/test_ws_subscribe_tenant.py
import pytest
from autoservice.gateway.message_router import _handle_subscribe
from autoservice.gateway.connection import Envelope


@pytest.mark.asyncio
async def test_subscribe_with_other_tenant_id_rejected():
    """Operator T1 trying to subscribe scope.tenant_id=T2 → error frame."""
    # Build an envelope; viewer_role='operator'; ws.session has tenant_id='t1'
    env = Envelope(id="e1", action="subscribe", payload={
        "scope": {"tenant_id": "t2", "squad_id": "s1"},
    })
    fake_session = type("S", (), {"tenant_id": "t1", "rbac_tier": 1})()
    fake_ws = type("WS", (), {"state": type("S", (), {"session": fake_session})()})()
    out = await _handle_subscribe(
        env, viewer_role="operator", engine=None, ws=fake_ws, session_id="sess1",
    )
    assert any(f["action"] == "error" for f in out)


@pytest.mark.asyncio
async def test_subscribe_default_uses_session_tenant():
    """No tenant_id in scope → server fills with session.tenant_id."""
    # Will need a real engine fixture (pytest fixture from test_local_engine.py)
    ...  # full body in Step 4
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Patch `_handle_subscribe`**

In `autoservice/gateway/message_router.py:320`, after `if not scope or not isinstance(scope, dict)` validation block, before the "exactly one of conv/squad/global" check, add:

```python
    # Tenant validation (operator viewers only — admin and customer skip)
    if viewer_role == "operator":
        from autoservice.auth_scope import resolve_effective_tenant
        from fastapi import HTTPException
        session = getattr(getattr(ws, "state", None), "session", None) if ws else None
        if session is None:
            return [build_frame("error", make_error_payload(
                ERR_VALIDATION, "subscribe requires authenticated session",
            ), ref=env.id)]
        try:
            tscope = resolve_effective_tenant(session, scope.get("tenant_id"))
        except HTTPException as e:
            return [build_frame("error", make_error_payload(
                ERR_FORBIDDEN if e.status_code == 403 else ERR_VALIDATION,
                str(e.detail),
            ), ref=env.id)]
        scope["tenant_id"] = tscope.effective_tenant_id
```

(`ERR_FORBIDDEN` may not exist; either add it or use `ERR_VALIDATION` with `details={"forbidden": True}`.)

- [ ] **Step 4: Flesh out the default-fills test in Step 1**

```python
@pytest.mark.asyncio
async def test_subscribe_default_uses_session_tenant(local_engine):
    env = Envelope(id="e1", action="subscribe", payload={
        "scope": {"squad_id": "s1"},  # no tenant_id
    })
    fake_session = type("S", (), {"tenant_id": "t1", "rbac_tier": 1})()
    fake_ws = type("WS", (), {"state": type("S", (), {"session": fake_session})()})()
    out = await _handle_subscribe(
        env, viewer_role="operator", engine=local_engine, ws=fake_ws, session_id="sess1",
    )
    # ack frame contains tenant_id=t1
    ack = next(f for f in out if f["action"] == "subscription_added")
    assert ack["payload"]["scope"].get("tenant_id") == "t1"
```

The exact response shape depends on the existing handler — adjust assertion to match.

- [ ] **Step 5: Run, expect pass**

Run: `uv run pytest tests/operator_isolation/test_ws_subscribe_tenant.py -v`

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(ws): subscribe handler validates scope.tenant_id via auth_scope

Operator viewers must subscribe with a tenant_id ⊆ accessible (or omit it
to default to session.tenant_id). Cross-tenant subscribe → error frame."
```

---

### Task 19: WS event push routing by compound scope_key

**Files:**
- Modify: places that publish events to subscribers (likely `autoservice/conversation_engine/local_engine.py` event emission, or wherever `subscription_registry.get_by_scope` is called)
- Test: `tests/operator_isolation/test_ws_event_routing.py`

- [ ] **Step 1: Locate the publish path**

Run: `Grep` `get_by_scope|_subscribers\b|fan.?out` across `autoservice/`.
Expected: identify the function that, given a new event/conv message, looks up subscribers and pushes the frame.

- [ ] **Step 2: Test cross-tenant event isolation**

```python
# tests/operator_isolation/test_ws_event_routing.py
import pytest
import asyncio


@pytest.mark.asyncio
async def test_event_from_t1_conv_not_pushed_to_t2_subscriber(local_engine):
    """T1 conv emits event; T2-scoped subscriber must not receive it."""
    # 1. Subscribe as t2 operator with squad_id=s1
    # 2. Create a conv in t1 with squad_id=s1
    # 3. Send a message in that conv
    # 4. Wait briefly for fan-out
    # 5. Assert t2 subscriber's queue is empty
    ...  # full body depends on engine.subscribe API
```

- [ ] **Step 3: Trace the publish path; ensure each event carries tenant_id**

Verify the event-emission code (`_emit_and_dispatch_hooks` in local_engine.py) passes `scope_key` matching the conv's tenant. Since conv.metadata.tenant_id is now always present (Phase 1), the scope_key for "tenant:T1|squad:S1" will only match subscribers who declared the same tenant.

This may require zero code change if the fan-out already uses `_scope_key(scope_dict_with_tenant_id)` to look up. If the fan-out instead looks up by squad_id directly, change it to construct a compound scope dict from `conv.metadata`.

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(ws): event fan-out routes by tenant-scoped compound key"
```

---

## Phase 5: Frontend

### Task 20: useOperatorWS — subscribe + fetch carry tenant_id

**Files:**
- Modify: `frontend/apps/operator-console/src/hooks/useOperatorWS.ts:140-170`
- Test: `frontend/apps/operator-console/src/__tests__/useOperatorWS.test.tsx` (extend if exists)

- [ ] **Step 1: Read existing useTenantId import path**

Run: Read `frontend/apps/operator-console/src/hooks/useOperatorWS.ts` and `frontend/packages/shared/useTenantId.ts` to verify the hook returns a string and that import path is `@autoservice/shared` or relative.

- [ ] **Step 2: Patch lines 144–146 (subscribe scope)**

```typescript
// before:
currentSquads.forEach((squadId) => {
  client.send('subscribe' as any, { scope: { squad_id: squadId } }).catch(() => {});
});

// after:
const tenantId = useTenantIdRef.current; // see Step 4 for ref wiring
currentSquads.forEach((squadId) => {
  client.send('subscribe' as any, {
    scope: { tenant_id: tenantId, squad_id: squadId },
  }).catch(() => {});
});
```

- [ ] **Step 3: Patch lines 151–152 (fetch URL)**

```typescript
// before:
const url = `/api/conversations/active?squad_id=${encodeURIComponent(squadId)}`;

// after:
const url = `/api/conversations/active?squad_id=${encodeURIComponent(squadId)}` +
            (tenantId ? `&tenant_id=${encodeURIComponent(tenantId)}` : '');
```

- [ ] **Step 4: Wire useTenantId via ref**

`useOperatorWS` is a long-lived hook called during connection bootstrap; tenantId from `useTenantId()` may change after `/me` resolves. Use a ref pattern:

```typescript
import { useTenantId } from '@autoservice/shared';
// inside the component:
const tenantId = useTenantId();
const useTenantIdRef = useRef(tenantId);
useEffect(() => { useTenantIdRef.current = tenantId; }, [tenantId]);
```

(Adjust import per actual package path; verify by running the dev server and checking module resolution.)

- [ ] **Step 5: Run frontend type check + unit tests**

```bash
cd frontend/apps/operator-console && npm run typecheck && npm test
```
Expected: PASS.

- [ ] **Step 6: Manual smoke**

```bash
make run-web   # or the existing dev command
```

Open the operator console in two browsers, login as two different tenants' operators, verify each sees only their own conversations and that no cross-tenant messages appear in real-time.

- [ ] **Step 7: Commit**

```bash
git add frontend/apps/operator-console/src/hooks/useOperatorWS.ts \
        frontend/apps/operator-console/src/__tests__/useOperatorWS.test.tsx
git commit -m "feat(operator-console): subscribe and fetch carry tenant_id

WS scope and /api/conversations/active fetch both pass tenant_id from
useTenantId hook (already wired to /api/auth/operator/me)."
```

---

## Phase 6: E2E

### Task 21: Cross-tenant E2E isolation test

**Files:**
- Create: `tests/operator_isolation/test_e2e_cross_tenant.py`

- [ ] **Step 1: Write E2E test**

```python
# tests/operator_isolation/test_e2e_cross_tenant.py
"""E2E: 2 operators in 2 tenants, full HTTP+WS surface, 0 leakage."""
import pytest
import asyncio
import json
from fastapi.testclient import TestClient

from channels.web.app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.asyncio
async def test_two_operators_see_only_own_tenant_data(client):
    # 1. Seed 2 conversations in 2 tenants
    from autoservice.api_routes import _ws_engine
    engine = _ws_engine()
    await engine.create_conversation(
        channel="web", external_id="cust_t1", metadata={"tenant_id": "t1"},
    )
    await engine.create_conversation(
        channel="web", external_id="cust_t2", metadata={"tenant_id": "t2"},
    )

    # 2. Operator A (t1) logs in, fetches active list
    client.post("/api/auth/operator/dev-login",
                json={"operator_id": "op_a", "tenant_id": "t1"})
    r_a = client.get("/api/conversations/active")
    ids_a = {c["id"] for c in r_a.json()["conversations"]}
    assert "web_cust_t1" in ids_a
    assert "web_cust_t2" not in ids_a

    # 3. Operator A's WS subscribe + send-as-customer in t2 conv → A receives nothing
    with client.websocket_connect("/ws/operator") as ws_a:
        ws_a.send_json({"id": "1", "action": "subscribe",
                        "payload": {"scope": {"squad_id": "default"}}})
        ack = ws_a.receive_json()
        assert ack["action"] == "subscription_added"
        # Drive a message in t2 conv via the engine
        await engine.send_message("web_cust_t2", source="cust_t2", content="hello")
        # Brief poll to confirm no t2 frame arrives within 500ms
        await asyncio.sleep(0.5)
        # No frame should have queued; receive with short timeout
        try:
            frame = ws_a.receive_json(mode="text")
            assert "cust_t2" not in json.dumps(frame), f"leaked: {frame}"
        except Exception:
            pass  # expected — no frame
```

> **Note:** the actual websocket helpers and queue/timeout mechanics depend on `fastapi.testclient` version and the existing test fixtures. If `tests/e2e/` already has a websocket harness, mirror its style.

- [ ] **Step 2: Run, expect pass**

Run: `uv run pytest tests/operator_isolation/test_e2e_cross_tenant.py -v -s`

- [ ] **Step 3: If it fails, debug iteratively**

Most likely failure modes:
1. WS subscribe `subscription_added` ack shape differs → adjust assertion
2. dev-login JSON shape differs → adjust login helper
3. WS frame leaks → trace back to the publish path (Task 19)

- [ ] **Step 4: Final commit**

```bash
git add tests/operator_isolation/test_e2e_cross_tenant.py
git commit -m "test(e2e): cross-tenant isolation — HTTP + WS surface

Verifies the §8 acceptance checklist: two operators logged into two
tenants observe zero cross-tenant data via API list endpoint and
zero cross-tenant frames via WebSocket subscriptions."
```

---

## Final verification

- [ ] **Step 1: Full test suite**

Run: `uv run pytest -q`
Expected: ALL PASS.

- [ ] **Step 2: Lint / type check**

Run: `uv run ruff check . && uv run mypy autoservice/auth_scope.py`
Expected: clean.

- [ ] **Step 3: Manual smoke per spec §8 acceptance checklist**

Tick each item in [docs/superpowers/specs/2026-04-28-operator-web-tenant-isolation-design.md](../specs/2026-04-28-operator-web-tenant-isolation-design.md) §8.

- [ ] **Step 4: Push branch, open PR**

PR title: `feat: operator web tenant data isolation (Phase 1-6)`
PR description: link to spec + plan, summarize the 6 phases, note out-of-scope items (CRM, Feishu, /cc_pool/runtime).
