# Tenant Sandbox M2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make M1's `publish` tarball→fork runbook actually produce a running fork deployment, upgrade Dream Engine to a per-tenant 5th agent, and give Master a `_master` self-iteration loop with symmetric `_local_admin` on the fork side. Add magic-link auth gating admin-portal on both deployments.

**Architecture:** Deployment mode (`master` vs `tenant`) switches via `.autoservice/config.local.yaml.deployment_mode`. Master holds multi-tenant sandboxes + `_master` bootstrap tenant; Fork holds 1 tenant + `_local_admin` helper. Dream agent runs via `cc_pool` role="dream" in a size-1 pool, triggered by `DreamScheduler` asyncio loop reading each tenant's `config.json.dream.trigger`. `tier=0` is reserved for bootstrap/internal tenants; `tier=1` for regular tenants; `tier=2` field exists but unused (M3 subtenant placeholder).

**Tech Stack:** Python 3.11 + FastAPI + pytest + Anthropic SDK | React 18 + TypeScript + Zustand + Vitest + @testing-library/react + TanStack Query | pure CSS (`cs-*` naming) | SQLite (stdlib sqlite3) | Makefile + bash `scripts/setup.sh` for symlink setup | `gh` CLI for optional fork automation.

**Spec:** [docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md](../specs/2026-04-20-tenant-sandbox-m2-design.md) — keep it open while executing.

**Dependency:** M1 spec [docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md](../specs/2026-04-20-tenant-sandbox-design.md) must be implemented first (provides `ForkCreator` Protocol, `publish.py`, sandbox schema, `/api/onboard/publish`).

---

## Conventions Used in This Plan

- **Working directory** for `pytest` commands: repo root (`d:/Work/h2os.cloud/AutoService-dev-a/`)
- **Python test command**: `pytest tests/path/to/test_file.py::test_name -xvs` (-x stop at first fail, -v verbose, -s show prints)
- **Frontend tests** working dir: `frontend/apps/admin-portal` — run `pnpm test <testfile>` or `pnpm test` for full suite
- **Commit style**: conventional (`feat(<scope>)` / `fix(<scope>)` / `test(<scope>)` / `refactor(<scope>)` / `chore(<scope>)`). Scopes: `m2-bootstrap`, `m2-dream`, `m2-auth`, `m2-tenant-layout`, `m2-fork`, `m2-e2e`.
- **After each task**: run the subset tests shown in the task; before moving to the next task, run full `pytest tests/ -x --ignore=tests/e2e` to catch regressions (E2E is slow, excluded from dev loop).
- **No wildcard imports.** Match existing import style.
- **Do not reformat unrelated code.** Keep diffs scoped.
- **PROJECT_ROOT**: the code uses `Path(__file__).resolve().parent.parent` for project root detection — preserve this pattern when adding new modules under `autoservice/`.
- **M1 preconditions**: assumes the following M1 artifacts exist. If missing, stop and flag to user:
  - `autoservice/onboarding.py` with `/upload`, `/activate`, `/rehearsal/generate`
  - `autoservice/publish.py` with `ForkCreator` Protocol + `LocalTarballForkCreator` + `_build_publish_archive` + `_archive_sandbox`
  - `autoservice/api_routes.py` with `/api/onboard/publish` + `/api/rehearsal/review` + `/api/session/mode` (master-only stub)
  - `autoservice/cc_pool.py` with `create_cc_client(role, tenant_id)` + `_load_soul(tenant_id, role)`
  - `.autoservice/sandbox/<tid>/` directory schema
  - Frontend `useTenantId.ts` + `useSessionMode.ts` (master-only stub) in `frontend/packages/shared/`

---

## File Structure After This Plan

### New files

```
autoservice/
  bootstrap.py                             # deployment_mode + get_tenant_id + lifespan helpers
  master_tenant.py                         # _master + _local_admin bootstrap
  dream_agent.py                           # run_dream() agent loop + tools
  dream_scheduler.py                       # asyncio background scheduler
  auth.py                                  # magic-link tokens + sessions + SMTP
scripts/
  setup.sh                                 # mode-aware symlink setup
tests/
  bootstrap/
    __init__.py
    test_get_deployment_mode.py
    test_ensure_master_tenant.py
    test_ensure_local_admin.py
  soul_generator/
    test_dream_role.py                     # new file under existing tests/ dir
  dream_agent/
    __init__.py
    test_emit_proposal_tool.py
    test_kb_search_tool.py
    test_list_souls_tool.py
    test_run_dream.py
  dream_scheduler/
    __init__.py
    test_should_trigger.py
    test_scheduler_loop.py
  auth/
    __init__.py
    test_request_login.py
    test_verify.py
    test_logout.py
    test_require_tenant_access.py
    test_session_mode.py
  migrations/
    __init__.py
    test_proposals_tenant_id_migration.py
    test_memory_pool_tenant_id_migration.py
  fork_runtime/
    __init__.py
    test_tenant_context_middleware.py
    test_tenant_root_helper.py
    test_fork_mode_boot.py
  publish/
    test_github_api_fork_creator.py
    test_local_runbook_includes_config_step.py
  e2e/
    test_m2_acceptance.py                  # full 8-step acceptance (manual-runnable)
frontend/apps/admin-portal/src/
  layouts/
    TenantLayout.tsx
  components/
    auth/
      LoginPage.tsx
      AuthGate.tsx
    tenant/
      ChatTab.tsx
  __tests__/
    TenantLayout.test.tsx
    LoginPage.test.tsx
    AuthGate.test.tsx
    ChatTab.test.tsx
```

### Modified files

```
autoservice/
  soul_generator.py                        # +dream role
  proposal_pipeline.py                     # run_once → run_once_legacy; schema migration
  cc_pool.py                               # role="dream" + dream_pool
  memory_pool.py                           # tenant_id column + recent(tid)/last_message_at(tid)
  api_routes.py                            # /api/auth/*, /api/dream/*, /api/admin/*, /api/session/mode ext
  web_gateway.py                           # lifespan bootstrap + scheduler + tenant middleware
  onboarding.py                            # soul_generator 5-role call
  dream_config_dialog.py                   # +refresh scheduler on confirm
  publish.py                               # GitHubApiForkCreator + LocalTarball runbook step
Makefile                                   # setup target → scripts/setup.sh
frontend/
  packages/shared/
    useSessionMode.ts                      # real fetch + auth state
    useTenantId.ts                         # full implementation
  apps/admin-portal/src/
    App.tsx                                # AuthGate wrapping + mode branch
    components/shell/
      AdminRail.tsx                        # variant prop
      AdminTopbar.tsx                      # brandName + authenticatedAs props
      AvatarMenu.tsx                       # +Logout entry
  apps/customer-chat/src/main.tsx          # mode-based route
  apps/operator-console/src/main.tsx       # mode-based route
```

### Deleted files

```
autoservice/dream_soul_template.md          # M1 artifact; content moves to soul_generator._FALLBACK_DREAM_SOUL constant
```

---

## Task 0: Baseline — verify M1 green

**Files:** none

- [ ] **Step 1: Run full Python test suite excluding E2E**

```bash
pytest tests/ -x --ignore=tests/e2e -q
```

Expected: all green. Record passing test count. If red: STOP, surface to user — baseline must be green.

- [ ] **Step 2: Run admin-portal frontend tests**

From `frontend/apps/admin-portal`:
```bash
pnpm test
```

Expected: all green. Record count.

- [ ] **Step 3: Verify M1 artifacts exist**

```bash
ls autoservice/publish.py autoservice/onboarding.py
grep -q "class ForkCreator" autoservice/publish.py && echo "OK ForkCreator protocol"
grep -q "class LocalTarballForkCreator" autoservice/publish.py && echo "OK LocalTarballForkCreator"
grep -q "def _load_soul" autoservice/cc_pool.py && echo "OK _load_soul"
```

All 3 must echo OK. If any missing: STOP, M1 incomplete.

---

# Phase 1 — Bootstrap + `_master` seed (spec §2.7, §3.1)

## Task 1.1: Extend `config.local.yaml` schema expectations

**Files:**
- Modify: `autoservice/bootstrap.py` (new file)
- Test: `tests/bootstrap/test_get_deployment_mode.py`

- [ ] **Step 1: Write the failing test**

Create `tests/bootstrap/__init__.py` (empty) and `tests/bootstrap/test_get_deployment_mode.py`:

```python
"""Tests for bootstrap.get_deployment_mode / get_tenant_id."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from autoservice import bootstrap


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """Create a fake project root with .autoservice/ and plugins/ dirs."""
    (tmp_path / ".autoservice").mkdir()
    (tmp_path / "plugins").mkdir()
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)
    bootstrap.get_deployment_mode.cache_clear()
    bootstrap.get_tenant_id.cache_clear()
    yield tmp_path
    bootstrap.get_deployment_mode.cache_clear()
    bootstrap.get_tenant_id.cache_clear()


def _write_local(tmp_path: Path, data: dict) -> None:
    (tmp_path / ".autoservice" / "config.local.yaml").write_text(yaml.safe_dump(data))


def test_default_mode_is_master(fake_repo):
    _write_local(fake_repo, {})
    assert bootstrap.get_deployment_mode() == "master"
    assert bootstrap.get_tenant_id() is None


def test_explicit_master(fake_repo):
    _write_local(fake_repo, {"deployment_mode": "master"})
    assert bootstrap.get_deployment_mode() == "master"


def test_tenant_mode_requires_matching_plugin_config(fake_repo):
    _write_local(fake_repo, {"deployment_mode": "tenant", "tenant_id": "acme"})
    (fake_repo / "plugins" / "acme").mkdir()
    (fake_repo / "plugins" / "acme" / "config.json").write_text(
        json.dumps({"tenant_id": "acme", "tier": 1})
    )
    assert bootstrap.get_deployment_mode() == "tenant"
    assert bootstrap.get_tenant_id() == "acme"


def test_tenant_mode_mismatch_raises(fake_repo):
    _write_local(fake_repo, {"deployment_mode": "tenant", "tenant_id": "acme"})
    (fake_repo / "plugins" / "acme").mkdir()
    (fake_repo / "plugins" / "acme" / "config.json").write_text(
        json.dumps({"tenant_id": "different", "tier": 1})
    )
    bootstrap.get_deployment_mode.cache_clear()
    with pytest.raises(AssertionError, match="tenant_id mismatch"):
        bootstrap.get_deployment_mode()


def test_invalid_mode_raises(fake_repo):
    _write_local(fake_repo, {"deployment_mode": "subtenant"})
    with pytest.raises(AssertionError):
        bootstrap.get_deployment_mode()
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pytest tests/bootstrap/test_get_deployment_mode.py -xvs
```

Expected: FAIL — `ModuleNotFoundError: No module named 'autoservice.bootstrap'`

- [ ] **Step 3: Implement `bootstrap.py`**

Create `autoservice/bootstrap.py`:

```python
"""Bootstrap — deployment-mode detection and startup lifecycle helpers.

M2 spec §3.1 / §2.7
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DeploymentMode = Literal["master", "tenant"]


def _local_config_path() -> Path:
    return PROJECT_ROOT / ".autoservice" / "config.local.yaml"


def _load_local_config() -> dict:
    path = _local_config_path()
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


@lru_cache(maxsize=1)
def get_deployment_mode() -> DeploymentMode:
    cfg = _load_local_config()
    mode = cfg.get("deployment_mode", "master")
    assert mode in ("master", "tenant"), f"invalid deployment_mode: {mode}"
    if mode == "tenant":
        tid = cfg.get("tenant_id")
        assert tid, "tenant_id required when deployment_mode=tenant"
        plugin_cfg_path = PROJECT_ROOT / "plugins" / tid / "config.json"
        assert plugin_cfg_path.exists(), (
            f"deployment_mode=tenant but plugins/{tid}/config.json missing"
        )
        plugin_cfg = json.loads(plugin_cfg_path.read_text())
        assert plugin_cfg.get("tenant_id") == tid, (
            f"tenant_id mismatch: config.local.yaml says {tid!r}, "
            f"plugins/{tid}/config.json says {plugin_cfg.get('tenant_id')!r}"
        )
    return mode


@lru_cache(maxsize=1)
def get_tenant_id() -> str | None:
    return _load_local_config().get("tenant_id")
```

- [ ] **Step 4: Run test, expect PASS**

```bash
pytest tests/bootstrap/test_get_deployment_mode.py -xvs
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add autoservice/bootstrap.py tests/bootstrap/
git commit -m "feat(m2-bootstrap): deployment_mode + tenant_id detection

- bootstrap.get_deployment_mode() reads .autoservice/config.local.yaml
- asserts plugins/<tid>/config.json matches when tenant
- lru_cache for hot-path performance"
```

---

## Task 1.2: Extend `soul_generator` to 5 roles (add `dream`)

**Files:**
- Modify: `autoservice/soul_generator.py`
- Test: `tests/soul_generator/test_dream_role.py`

- [ ] **Step 1: Read existing `soul_generator.py` to understand `generate_and_save` signature**

```bash
grep -n "def generate_and_save\|AGENT_ROLES\|_KB_QUERIES\|_SOUL_TEMPLATE" autoservice/soul_generator.py
```

Note the exact function signature and template dict keys — the test must import what exists.

- [ ] **Step 2: Write failing test**

Create `tests/soul_generator/` (if not exists) and `tests/soul_generator/__init__.py` (empty), then `tests/soul_generator/test_dream_role.py`:

```python
"""Tests for dream role extension in soul_generator."""
from __future__ import annotations

from pathlib import Path

import pytest

from autoservice import soul_generator


def test_agent_roles_includes_dream():
    assert "dream" in soul_generator.AGENT_ROLES
    assert len(soul_generator.AGENT_ROLES) == 5


def test_dream_role_has_kb_queries():
    assert "dream" in soul_generator._KB_QUERIES
    queries = soul_generator._KB_QUERIES["dream"]
    assert isinstance(queries, list)
    assert len(queries) >= 2


def test_dream_role_has_soul_template():
    assert "dream" in soul_generator._SOUL_TEMPLATE


def test_fallback_dream_soul_is_non_empty_string():
    assert isinstance(soul_generator._FALLBACK_DREAM_SOUL, str)
    assert len(soul_generator._FALLBACK_DREAM_SOUL) > 200
    # Must mention the 3 dream tools and 4 config params
    body = soul_generator._FALLBACK_DREAM_SOUL
    assert "kb_search" in body
    assert "emit_proposal" in body
    assert "list_souls" in body
    assert "risk_threshold" in body


def test_generate_and_save_writes_5_souls(tmp_path, monkeypatch):
    """When LLM is patched to return stub content, 5 files are written."""
    target = tmp_path / "souls"
    target.mkdir()

    # Patch the internal Anthropic call to deterministic output
    def fake_llm(prompt: str, system: str) -> str:
        return f"# stub soul for prompt-hash={hash(prompt) % 1000}"

    monkeypatch.setattr(soul_generator, "_call_claude", fake_llm, raising=False)

    soul_generator.generate_and_save(
        tenant_id="_master",
        industry="platform-ops",
        brand_name="AutoService",
        languages=["en"],
        kb_db=None,
        target_dir=target,
    )
    # 5 *_soul.md files
    for role in soul_generator.AGENT_ROLES:
        assert (target / f"{role}_soul.md").exists(), f"missing {role}_soul.md"
    # _generation_meta.yaml written
    assert (target / "_generation_meta.yaml").exists()


def test_generate_dream_falls_back_when_llm_fails(tmp_path, monkeypatch):
    """If Claude call raises, dream_soul.md is the fallback template."""
    target = tmp_path / "souls"
    target.mkdir()

    def boom(prompt: str, system: str) -> str:
        raise RuntimeError("anthropic unavailable")

    # Only the dream role should fall back; non-dream roles must use existing
    # logic (which may have its own fallback). For this test we patch both:
    monkeypatch.setattr(soul_generator, "_call_claude", boom, raising=False)

    soul_generator.generate_and_save(
        tenant_id="_master",
        industry="platform-ops",
        brand_name="AutoService",
        languages=["en"],
        kb_db=None,
        target_dir=target,
    )
    dream_text = (target / "dream_soul.md").read_text()
    assert "emit_proposal" in dream_text  # fallback content marker

    meta_text = (target / "_generation_meta.yaml").read_text()
    assert "dream" in meta_text
    assert "fallback" in meta_text
```

- [ ] **Step 3: Run test, expect FAIL**

```bash
pytest tests/soul_generator/test_dream_role.py -xvs
```

Expected: FAIL — `AssertionError: "dream" in soul_generator.AGENT_ROLES` or `AttributeError: module has no attribute _FALLBACK_DREAM_SOUL`.

- [ ] **Step 4: Extend `soul_generator.py`**

Open `autoservice/soul_generator.py`. Make these changes:

1. Change `AGENT_ROLES = ("customer", "translate", "lead", "triage")` to:
```python
AGENT_ROLES = ("customer", "translate", "lead", "triage", "dream")
```

2. Add `"dream"` entry to `_KB_QUERIES` dict:
```python
_KB_QUERIES: dict[str, list[str]] = {
    # ... existing 4 entries ...
    "dream": [
        "company mission and values",
        "known service gaps and pain points",
        "compliance and regulatory boundaries",
    ],
}
```

3. Add `"dream"` entry to `_SOUL_TEMPLATE` (structure should match existing template format — inspect one existing entry for the exact prompt template shape, then add dream with tenant self-improvement focus).

4. Add module-level constant `_FALLBACK_DREAM_SOUL` near the top of the file, after the imports:

```python
_FALLBACK_DREAM_SOUL = """\
# Dream Agent Soul (fallback template)

You are this tenant's self-evolution engine. You are the 5th agent alongside
customer, translate, lead, and triage — but your job is not to handle end-user
conversations. You are woken up periodically (see config.json.dream.trigger)
to analyze recent activity and propose concrete improvements.

## Your workflow when awakened

1. Read the recent customer conversations surfaced in your context.
2. Read the history of accepted/rejected proposals to learn from past outcomes.
3. Identify concrete improvement opportunities in four categories:
   - response_quality — places where an agent's phrasing or flow is weak
   - workflow — missing or broken handoffs between agents
   - knowledge_gap — questions the agent couldn't answer from the KB
   - tone — brand voice misses

## Tools available to you

- `kb_search(query)` — search this tenant's knowledge base. Use this to VERIFY
  a suspected knowledge gap (don't propose a "missing KB article" without first
  confirming it's genuinely missing).
- `list_souls()` — read summaries of the other 4 agent souls so your proposals
  align with current agent personalities.
- `emit_proposal(category, title, description, suggestion, evidence,
  risk_level, target_role)` — write a proposal to the tenant's proposal table.
  This is your output; nothing else you "say" is persisted.

## Config parameters you respect

- `trigger` (idle | scheduled | manual) — you don't control this; the scheduler
  decides when to wake you. But you know: `idle` means the system expects you
  to be thorough; `scheduled` means you're on a clock; `manual` means a human
  is waiting.
- `coverage` (all | sampled | category-specific) — scope of conversations to
  consider. You receive a pre-filtered window; don't second-guess it.
- `risk_threshold` (low | medium | high) — if your suggestion would change
  user-facing behavior above this risk level, either split it into smaller
  lower-risk steps or skip it. Default: err on conservative.
- `canary.stages` — rollout plan; don't propose changes that skip canary.

## Red lines

- You do NOT modify soul files, KB, or config directly. You only `emit_proposal`.
- Proposals default to `status=draft` — a human reviews before anything lands.
- You stop calling tools after ~10 turns even if you "want more data" — let
  the human trigger another run.
"""
```

5. In `generate_and_save()`, add handling that when the dream role's LLM call fails, writes `_FALLBACK_DREAM_SOUL` content and records `llm=fallback` in the meta yaml. Sketch (find the actual loop that iterates `AGENT_ROLES`; adapt this):

```python
# Inside generate_and_save, the per-role loop:
for role in AGENT_ROLES:
    try:
        content = _call_claude(prompt=_build_prompt(role, ...), system=_SOUL_TEMPLATE[role])
        meta[role] = {"source": "llm"}
    except Exception as e:
        if role == "dream":
            content = _FALLBACK_DREAM_SOUL
            meta[role] = {"source": "fallback", "error": str(e)}
        else:
            raise  # non-dream roles have their own handling
    (target_dir / f"{role}_soul.md").write_text(content)
```

- [ ] **Step 5: Run test, expect PASS**

```bash
pytest tests/soul_generator/test_dream_role.py -xvs
```

Expected: 6 passed.

- [ ] **Step 6: Run full soul_generator tests to catch regression**

```bash
pytest tests/ -k soul_generator -xvs
```

Expected: all green including existing 4-role tests.

- [ ] **Step 7: Commit**

```bash
git add autoservice/soul_generator.py tests/soul_generator/
git commit -m "feat(m2-bootstrap): soul_generator adds dream role (5th)

- AGENT_ROLES extended to 5 entries
- _FALLBACK_DREAM_SOUL constant with tool descriptions & red lines
- generate_and_save falls back gracefully when dream LLM call fails
- _generation_meta.yaml records source=llm|fallback per role"
```

---

## Task 1.3: `ensure_master_tenant()` bootstrap function

**Files:**
- Create: `autoservice/master_tenant.py`
- Test: `tests/bootstrap/test_ensure_master_tenant.py`

- [ ] **Step 1: Write failing test**

Create `tests/bootstrap/test_ensure_master_tenant.py`:

```python
"""Tests for master_tenant.ensure_master_tenant()."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from autoservice import master_tenant, soul_generator


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    (tmp_path / ".autoservice" / "sandbox").mkdir(parents=True)
    monkeypatch.setattr(master_tenant, "PROJECT_ROOT", tmp_path)
    # Patch LLM call to stub — bootstrap must work offline
    monkeypatch.setattr(
        soul_generator, "_call_claude",
        lambda prompt, system: "# stub", raising=False,
    )
    yield tmp_path


def test_creates_master_tenant_directory(fake_repo):
    master_tenant.ensure_master_tenant()
    master_dir = fake_repo / ".autoservice" / "sandbox" / "_master"
    assert master_dir.exists()
    assert (master_dir / "config.json").exists()
    assert (master_dir / "souls").is_dir()
    assert (master_dir / "kb" / "kb.db").exists()


def test_config_has_tier_0(fake_repo):
    master_tenant.ensure_master_tenant()
    cfg = json.loads(
        (fake_repo / ".autoservice" / "sandbox" / "_master" / "config.json").read_text()
    )
    assert cfg["tenant_id"] == "_master"
    assert cfg["tier"] == 0
    assert cfg["status"] == "active"
    assert cfg["parent_tenant_id"] is None
    assert "dream" in cfg
    assert cfg["dream"]["trigger"] == "idle"


def test_idempotent(fake_repo):
    master_tenant.ensure_master_tenant()
    first_mtime = (
        fake_repo / ".autoservice" / "sandbox" / "_master" / "config.json"
    ).stat().st_mtime
    master_tenant.ensure_master_tenant()
    second_mtime = (
        fake_repo / ".autoservice" / "sandbox" / "_master" / "config.json"
    ).stat().st_mtime
    assert first_mtime == second_mtime


def test_all_5_souls_written(fake_repo):
    master_tenant.ensure_master_tenant()
    souls = fake_repo / ".autoservice" / "sandbox" / "_master" / "souls"
    for role in ("customer", "translate", "lead", "triage", "dream"):
        assert (souls / f"{role}_soul.md").exists(), f"missing {role}_soul.md"
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pytest tests/bootstrap/test_ensure_master_tenant.py -xvs
```

Expected: FAIL — `ModuleNotFoundError: autoservice.master_tenant`.

- [ ] **Step 3: Implement `master_tenant.py`**

Create `autoservice/master_tenant.py`:

```python
"""Master-side `_master` tenant and fork-side `_local_admin` bootstrap.

M2 spec §2.7 / §2.8. `_master` runs on master deployment to give A a real
5-agent stack to self-iterate against. `_local_admin` is the fork-side mirror
that gives B an admin conversation partner.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Literal

from autoservice import soul_generator

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Minimal compliance defaults (M1 DEFAULT_COMPLIANCE assumed to exist in
# autoservice.onboarding; here we inline a safe subset to avoid circular import)
_DEFAULT_COMPLIANCE = {
    "pii_handling": "minimize",
    "retention_days": 90,
    "disclosure_required": True,
}

_DEFAULT_SOUL_CFG = {
    "customer_enabled": True,
    "translate_enabled": True,
    "lead_enabled": True,
    "triage_enabled": True,
}

_DEFAULT_DREAM_CFG = {
    "trigger": "idle",
    "coverage": "all",
    "risk_threshold": "medium",
    "canary": {"stages": [100], "observe_hours": 0},
}

_KB_SCHEMA = """\
CREATE TABLE IF NOT EXISTS kb_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    source_name TEXT,
    section TEXT,
    domain TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(
    content, source_name, section, domain,
    content='kb_chunks', content_rowid='id'
);
"""


def _init_empty_kb(kb_path: Path) -> None:
    kb_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(kb_path)
    try:
        conn.executescript(_KB_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _write_tenant_config(
    target_dir: Path,
    *,
    tenant_id: str,
    brand_name: str,
    industry: str,
    tier: int,
    status: str,
) -> None:
    config = {
        "tenant_id": tenant_id,
        "parent_tenant_id": None,
        "tier": tier,
        "brand_name": brand_name,
        "industry": industry,
        "status": status,
        "channels": ["web"],
        "compliance": _DEFAULT_COMPLIANCE,
        "soul": _DEFAULT_SOUL_CFG,
        "dream": _DEFAULT_DREAM_CFG,
    }
    (target_dir / "config.json").write_text(json.dumps(config, indent=2))


def ensure_master_tenant() -> None:
    """Create `.autoservice/sandbox/_master/` if missing.

    Idempotent: if config.json exists, does nothing.
    """
    master_dir = PROJECT_ROOT / ".autoservice" / "sandbox" / "_master"
    if (master_dir / "config.json").exists():
        logger.debug("_master tenant already exists, skipping bootstrap")
        return

    logger.info("Bootstrapping _master tenant at %s", master_dir)
    master_dir.mkdir(parents=True, exist_ok=True)

    _write_tenant_config(
        master_dir,
        tenant_id="_master",
        brand_name="AutoService Platform",
        industry="platform-ops",
        tier=0,
        status="active",
    )

    souls_dir = master_dir / "souls"
    souls_dir.mkdir(exist_ok=True)
    soul_generator.generate_and_save(
        tenant_id="_master",
        industry="platform-ops",
        brand_name="AutoService",
        languages=["zh", "en"],
        kb_db=None,
        target_dir=souls_dir,
    )

    _init_empty_kb(master_dir / "kb" / "kb.db")
    logger.info("_master tenant bootstrapped")


def ensure_local_admin() -> None:
    """Fork-side mirror of ensure_master_tenant. Creates plugins/_local_admin/."""
    admin_dir = PROJECT_ROOT / "plugins" / "_local_admin"
    if (admin_dir / "config.json").exists():
        logger.debug("_local_admin tenant already exists, skipping")
        return

    logger.info("Bootstrapping _local_admin tenant at %s", admin_dir)
    admin_dir.mkdir(parents=True, exist_ok=True)

    _write_tenant_config(
        admin_dir,
        tenant_id="_local_admin",
        brand_name="Local Admin Helper",
        industry="fork-ops",
        tier=0,
        status="active",
    )

    souls_dir = admin_dir / "souls"
    souls_dir.mkdir(exist_ok=True)
    soul_generator.generate_and_save(
        tenant_id="_local_admin",
        industry="fork-ops",
        brand_name="AutoService Fork",
        languages=["zh", "en"],
        kb_db=None,
        target_dir=souls_dir,
    )

    _init_empty_kb(admin_dir / "kb" / "kb.db")
    logger.info("_local_admin tenant bootstrapped")
```

- [ ] **Step 4: Run test, expect PASS**

```bash
pytest tests/bootstrap/test_ensure_master_tenant.py -xvs
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add autoservice/master_tenant.py tests/bootstrap/test_ensure_master_tenant.py
git commit -m "feat(m2-bootstrap): master_tenant.ensure_master_tenant

- creates .autoservice/sandbox/_master/ on first boot
- tier=0, status=active, dream config defaulted
- generates 5 souls via soul_generator
- idempotent: no-ops if config.json already present"
```

---

## Task 1.4: `ensure_local_admin()` fork-side bootstrap

**Files:**
- Modify: (already added in 1.3) `autoservice/master_tenant.py`
- Test: `tests/bootstrap/test_ensure_local_admin.py`

- [ ] **Step 1: Write failing test**

Create `tests/bootstrap/test_ensure_local_admin.py`:

```python
"""Tests for master_tenant.ensure_local_admin (fork-side)."""
from __future__ import annotations

import json

import pytest

from autoservice import master_tenant, soul_generator


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    (tmp_path / "plugins").mkdir()
    monkeypatch.setattr(master_tenant, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        soul_generator, "_call_claude",
        lambda prompt, system: "# stub", raising=False,
    )
    yield tmp_path


def test_creates_local_admin_under_plugins(fake_repo):
    master_tenant.ensure_local_admin()
    admin_dir = fake_repo / "plugins" / "_local_admin"
    assert admin_dir.exists()
    assert (admin_dir / "config.json").exists()
    assert (admin_dir / "souls" / "customer_soul.md").exists()
    assert (admin_dir / "kb" / "kb.db").exists()


def test_local_admin_is_tier_0(fake_repo):
    master_tenant.ensure_local_admin()
    cfg = json.loads(
        (fake_repo / "plugins" / "_local_admin" / "config.json").read_text()
    )
    assert cfg["tier"] == 0
    assert cfg["tenant_id"] == "_local_admin"


def test_idempotent(fake_repo):
    master_tenant.ensure_local_admin()
    (fake_repo / "plugins" / "_local_admin" / "config.json").write_text(
        json.dumps({"marker": "preserved"})
    )
    master_tenant.ensure_local_admin()
    cfg = json.loads(
        (fake_repo / "plugins" / "_local_admin" / "config.json").read_text()
    )
    assert cfg == {"marker": "preserved"}
```

- [ ] **Step 2: Run test, expect PASS** (already implemented in 1.3)

```bash
pytest tests/bootstrap/test_ensure_local_admin.py -xvs
```

Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/bootstrap/test_ensure_local_admin.py
git commit -m "test(m2-bootstrap): cover ensure_local_admin fork-side bootstrap"
```

---

## Task 1.5: Wire bootstrap into `web_gateway` lifespan

**Files:**
- Modify: `autoservice/web_gateway.py`
- Test: `tests/bootstrap/test_lifespan_bootstrap.py`

- [ ] **Step 1: Inspect current lifespan in web_gateway.py**

```bash
grep -n "on_event\|lifespan\|startup\|shutdown" autoservice/web_gateway.py
```

Record where `startup` handler lives — the patch point.

- [ ] **Step 2: Write failing integration-style test**

Create `tests/bootstrap/test_lifespan_bootstrap.py`:

```python
"""Test that web_gateway lifespan triggers mode-appropriate bootstrap."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autoservice import bootstrap, master_tenant


@pytest.fixture
def clear_caches():
    bootstrap.get_deployment_mode.cache_clear()
    bootstrap.get_tenant_id.cache_clear()
    yield
    bootstrap.get_deployment_mode.cache_clear()
    bootstrap.get_tenant_id.cache_clear()


def test_master_mode_calls_ensure_master_tenant(clear_caches, monkeypatch):
    monkeypatch.setattr(bootstrap, "get_deployment_mode", lambda: "master")
    ensure_master = MagicMock()
    ensure_local = MagicMock()
    monkeypatch.setattr(master_tenant, "ensure_master_tenant", ensure_master)
    monkeypatch.setattr(master_tenant, "ensure_local_admin", ensure_local)

    from autoservice import web_gateway
    # Force re-eval startup
    web_gateway._run_startup_bootstrap()

    ensure_master.assert_called_once()
    ensure_local.assert_not_called()


def test_tenant_mode_calls_ensure_local_admin(clear_caches, monkeypatch):
    monkeypatch.setattr(bootstrap, "get_deployment_mode", lambda: "tenant")
    ensure_master = MagicMock()
    ensure_local = MagicMock()
    monkeypatch.setattr(master_tenant, "ensure_master_tenant", ensure_master)
    monkeypatch.setattr(master_tenant, "ensure_local_admin", ensure_local)

    from autoservice import web_gateway
    web_gateway._run_startup_bootstrap()

    ensure_local.assert_called_once()
    ensure_master.assert_not_called()
```

- [ ] **Step 3: Run test, expect FAIL**

```bash
pytest tests/bootstrap/test_lifespan_bootstrap.py -xvs
```

Expected: FAIL — `_run_startup_bootstrap` doesn't exist.

- [ ] **Step 4: Patch `web_gateway.py`**

Add to `autoservice/web_gateway.py` (near the top-level imports, after existing imports):

```python
from autoservice import bootstrap, master_tenant


def _run_startup_bootstrap() -> None:
    """Idempotent mode-aware bootstrap — invoked from FastAPI startup event."""
    mode = bootstrap.get_deployment_mode()
    if mode == "master":
        master_tenant.ensure_master_tenant()
    else:  # tenant
        master_tenant.ensure_local_admin()
```

Then find the existing `@app.on_event("startup")` (or `lifespan` context manager) and add a call to `_run_startup_bootstrap()` as the FIRST action inside it. If no startup handler exists, add:

```python
@app.on_event("startup")
async def _startup():
    _run_startup_bootstrap()
```

- [ ] **Step 5: Run test, expect PASS**

```bash
pytest tests/bootstrap/test_lifespan_bootstrap.py -xvs
```

Expected: 2 passed.

- [ ] **Step 6: Full regression sweep**

```bash
pytest tests/ -x --ignore=tests/e2e -q
```

Expected: all green; baseline count preserved + new tests added.

- [ ] **Step 7: Commit**

```bash
git add autoservice/web_gateway.py tests/bootstrap/test_lifespan_bootstrap.py
git commit -m "feat(m2-bootstrap): wire ensure_master/_local_admin into lifespan

Startup now dispatches to the right bootstrap based on deployment_mode."
```

---

# Phase 2 — Schema migrations (spec §2.4, §3.7)

## Task 2.1: Add `tenant_id` column to `proposals` table

**Files:**
- Modify: `autoservice/proposal_pipeline.py`
- Test: `tests/migrations/test_proposals_tenant_id_migration.py`

- [ ] **Step 1: Write failing test**

Create `tests/migrations/__init__.py` (empty) and `tests/migrations/test_proposals_tenant_id_migration.py`:

```python
"""Test that the proposals table migration adds tenant_id non-destructively."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from autoservice import proposal_pipeline


def _legacy_schema() -> str:
    """M1's schema — the pre-migration shape."""
    return """
    CREATE TABLE proposals (
        id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        data TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft',
        category TEXT
    );
    """


def _connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path)


def test_migration_on_fresh_db(tmp_path):
    db = tmp_path / "proposals.db"
    proposal_pipeline.apply_schema(_connect(db))
    # Fresh DB includes tenant_id
    conn = _connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(proposals)").fetchall()}
    assert "tenant_id" in cols
    assert "id" in cols


def test_migration_backfills_existing_rows(tmp_path):
    db = tmp_path / "proposals.db"
    conn = _connect(db)
    conn.executescript(_legacy_schema())
    conn.execute(
        "INSERT INTO proposals (id, created_at, data, status, category) "
        "VALUES ('p1', '2026-04-19T00:00Z', '{}', 'draft', 'response_quality')"
    )
    conn.commit()
    conn.close()

    proposal_pipeline.apply_schema(_connect(db))

    conn = _connect(db)
    rows = conn.execute("SELECT id, tenant_id FROM proposals").fetchall()
    assert rows == [("p1", "_master")]


def test_migration_is_idempotent(tmp_path):
    db = tmp_path / "proposals.db"
    proposal_pipeline.apply_schema(_connect(db))
    proposal_pipeline.apply_schema(_connect(db))  # must not raise
    conn = _connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(proposals)").fetchall()}
    assert "tenant_id" in cols


def test_tenant_id_index_created(tmp_path):
    db = tmp_path / "proposals.db"
    proposal_pipeline.apply_schema(_connect(db))
    conn = _connect(db)
    indexes = {r[1] for r in conn.execute(
        "SELECT * FROM sqlite_master WHERE type='index' AND tbl_name='proposals'"
    ).fetchall()}
    assert "idx_proposals_tenant" in indexes


def test_run_once_legacy_alias_exists():
    """M1's run_once must still be callable as run_once_legacy (deprecated)."""
    assert hasattr(proposal_pipeline, "run_once_legacy")
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pytest tests/migrations/test_proposals_tenant_id_migration.py -xvs
```

Expected: FAIL — `AttributeError: apply_schema` or `run_once_legacy` missing.

- [ ] **Step 3: Modify `proposal_pipeline.py`**

Open `autoservice/proposal_pipeline.py`. Make these changes:

1. Rename the existing `PROPOSALS_SCHEMA` constant to reflect the new shape (add `tenant_id` column + index):

```python
PROPOSALS_SCHEMA = """\
CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    data TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    category TEXT,
    tenant_id TEXT NOT NULL DEFAULT '_master'
);

CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);
CREATE INDEX IF NOT EXISTS idx_proposals_category ON proposals(category);
CREATE INDEX IF NOT EXISTS idx_proposals_tenant ON proposals(tenant_id);
"""
```

2. Add `apply_schema()` function (handles migration from legacy):

```python
def apply_schema(conn: sqlite3.Connection) -> None:
    """Create or migrate the proposals schema. Safe to call on fresh or legacy DB."""
    # Check if proposals table exists and whether it has tenant_id
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='proposals'"
    ).fetchone()
    if tables is None:
        # Fresh DB — executescript creates everything
        conn.executescript(PROPOSALS_SCHEMA)
        conn.commit()
        return

    cols = {r[1] for r in conn.execute("PRAGMA table_info(proposals)").fetchall()}
    if "tenant_id" not in cols:
        conn.execute(
            "ALTER TABLE proposals ADD COLUMN tenant_id TEXT NOT NULL DEFAULT '_master'"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_proposals_category ON proposals(category)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_proposals_tenant ON proposals(tenant_id)"
    )
    conn.commit()
```

3. Rename the existing top-level `run_once` function to `run_once_legacy` and add a deprecation warning:

```python
def run_once_legacy(mempool: MemoryPool, db: sqlite3.Connection) -> list[dict]:
    """DEPRECATED (M2): kept for regression. New callers use dream_agent.run_dream().

    Pre-M2 one-shot pipeline: replay → analyzer prompt → parse → store.
    """
    import warnings
    warnings.warn(
        "proposal_pipeline.run_once_legacy is deprecated; use dream_agent.run_dream",
        DeprecationWarning,
        stacklevel=2,
    )
    # ... existing body unchanged ...
```

4. Find any existing code in the file that still references `run_once` and either rename those call sites to `run_once_legacy` or add `run_once = run_once_legacy` compatibility alias near the bottom:

```python
# Back-compat alias
run_once = run_once_legacy
```

- [ ] **Step 4: Run test, expect PASS**

```bash
pytest tests/migrations/test_proposals_tenant_id_migration.py -xvs
```

Expected: 5 passed.

- [ ] **Step 5: Full sweep for regressions**

```bash
pytest tests/ -x --ignore=tests/e2e -q
```

Expected: all green. If legacy tests break because they call `run_once`, either they still pass via the alias or they need updating (inspect the failure).

- [ ] **Step 6: Commit**

```bash
git add autoservice/proposal_pipeline.py tests/migrations/
git commit -m "feat(m2-dream): proposals schema adds tenant_id + migration

- apply_schema() handles fresh DB and legacy migration non-destructively
- backfills existing rows with tenant_id='_master'
- idx_proposals_tenant index added
- run_once → run_once_legacy (deprecation warning), alias preserved"
```

---

## Task 2.2: Add `tenant_id` to `memory_pool`

**Files:**
- Modify: `autoservice/memory_pool.py`
- Test: `tests/migrations/test_memory_pool_tenant_id_migration.py`

- [ ] **Step 1: Inspect memory_pool storage shape**

```bash
grep -n "CREATE TABLE\|INSERT INTO\|def recent\|def last_message" autoservice/memory_pool.py
```

Record the table name (likely `messages` or `conversations`), column set, and where INSERT happens.

- [ ] **Step 2: Write failing test**

Create `tests/migrations/test_memory_pool_tenant_id_migration.py`:

```python
"""Test memory_pool tenant_id column + new tenant-scoped helpers."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from autoservice import memory_pool


@pytest.fixture
def fresh_pool(tmp_path):
    db = tmp_path / "mem.db"
    pool = memory_pool.MemoryPool(db_path=db)
    yield pool


def test_recent_filters_by_tenant(fresh_pool):
    fresh_pool.append("s1", role="customer", text="hi A", tenant_id="A")
    fresh_pool.append("s2", role="customer", text="hi B", tenant_id="B")
    fresh_pool.append("s1", role="agent", text="hello A", tenant_id="A")

    rows_a = fresh_pool.recent("A", limit=10)
    rows_b = fresh_pool.recent("B", limit=10)

    assert len(rows_a) == 2
    assert len(rows_b) == 1
    assert all(r["tenant_id"] == "A" for r in rows_a)


def test_last_message_at(fresh_pool):
    fresh_pool.append("s1", role="customer", text="first", tenant_id="A")
    first_ts = fresh_pool.last_message_at("A")
    assert first_ts is not None

    fresh_pool.append("s1", role="customer", text="second", tenant_id="A")
    second_ts = fresh_pool.last_message_at("A")
    assert second_ts >= first_ts

    # Unknown tenant
    assert fresh_pool.last_message_at("C") is None


def test_legacy_rows_backfill_to_master(tmp_path):
    """Pre-M2 DBs without tenant_id column must migrate + backfill."""
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    # Simulate pre-M2 schema (the actual column names may differ — inspect memory_pool.py)
    conn.executescript("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            text TEXT NOT NULL,
            ts TEXT NOT NULL
        );
        INSERT INTO messages (session_id, role, text, ts)
        VALUES ('s1', 'customer', 'legacy row', '2026-04-19T00:00:00Z');
    """)
    conn.commit()
    conn.close()

    pool = memory_pool.MemoryPool(db_path=db)
    rows = pool.recent("_master", limit=10)
    assert len(rows) == 1
    assert rows[0]["text"] == "legacy row"
```

> Note: the test assumes the memory_pool table is named `messages` with columns
> `session_id / role / text / ts`. Adjust the legacy schema block after inspecting
> the real M1 schema (Step 1 grep).

- [ ] **Step 3: Run test, expect FAIL**

```bash
pytest tests/migrations/test_memory_pool_tenant_id_migration.py -xvs
```

Expected: FAIL — `TypeError: append() got unexpected keyword 'tenant_id'` or similar.

- [ ] **Step 4: Modify `memory_pool.py`**

Open `autoservice/memory_pool.py`. Make these changes:

1. Update the CREATE TABLE / schema constant to include `tenant_id TEXT NOT NULL DEFAULT '_master'`.

2. Add migration logic in the `MemoryPool.__init__` (or wherever `CREATE TABLE IF NOT EXISTS` is invoked). After the CREATE statements:

```python
# M2 migration: add tenant_id column if missing
cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()}
if "tenant_id" not in cols:
    conn.execute(
        "ALTER TABLE messages ADD COLUMN tenant_id TEXT NOT NULL DEFAULT '_master'"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_tenant ON messages(tenant_id)")
    conn.commit()
```

3. Update `append()` signature to accept `tenant_id: str = "_master"` and include it in the INSERT.

4. Add two new methods:

```python
def recent(self, tenant_id: str, limit: int = 20) -> list[dict]:
    """Return most recent messages for a tenant, newest first."""
    rows = self._conn.execute(
        """
        SELECT id, session_id, role, text, ts, tenant_id
        FROM messages
        WHERE tenant_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (tenant_id, limit),
    ).fetchall()
    return [
        {
            "id": r[0], "session_id": r[1], "role": r[2],
            "text": r[3], "ts": r[4], "tenant_id": r[5],
        }
        for r in rows
    ]


def last_message_at(self, tenant_id: str):
    """Return ISO timestamp of most recent message or None."""
    row = self._conn.execute(
        "SELECT ts FROM messages WHERE tenant_id = ? ORDER BY id DESC LIMIT 1",
        (tenant_id,),
    ).fetchone()
    return row[0] if row else None
```

- [ ] **Step 5: Run test, expect PASS**

```bash
pytest tests/migrations/test_memory_pool_tenant_id_migration.py -xvs
```

Expected: 3 passed.

- [ ] **Step 6: Sweep for regressions in callers**

```bash
grep -rn "memory_pool\|MemoryPool\|\.append(" autoservice/ | grep -v __pycache__
```

Callers that don't pass `tenant_id` now implicitly get `"_master"` — OK for master deployment. For per-tenant correctness, update known call sites in order:

- `autoservice/conversation_engine/local_engine.py` — inspect & add `tenant_id=<tid>` where session has tenant context.
- Any call site in `autoservice/gateway/message_router.py`.

(This may be deferred — the default ensures tests stay green; per-tenant propagation happens in later tasks.)

- [ ] **Step 7: Full test suite**

```bash
pytest tests/ -x --ignore=tests/e2e -q
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add autoservice/memory_pool.py tests/migrations/test_memory_pool_tenant_id_migration.py
git commit -m "feat(m2-dream): memory_pool tenant_id column + recent/last_message_at

- ALTER TABLE adds tenant_id non-destructively; legacy rows backfill to _master
- MemoryPool.recent(tenant_id, limit) and last_message_at(tenant_id) helpers
- append() gains tenant_id kwarg (default _master preserves callers)"
```

---

## Task 2.3: Create `dream_runs.db` schema + repository

**Files:**
- Create: `autoservice/dream_runs_db.py`
- Test: `tests/migrations/test_dream_runs_schema.py`

- [ ] **Step 1: Write failing test**

Create `tests/migrations/test_dream_runs_schema.py`:

```python
"""Test dream_runs.db schema + repository API."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoservice import dream_runs_db


def test_open_creates_schema(tmp_path):
    path = tmp_path / "runs.db"
    conn = dream_runs_db.open(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(dream_runs)").fetchall()}
    assert cols == {
        "id", "tenant_id", "started_at", "ended_at", "duration_ms",
        "proposals_count", "tool_calls", "tokens_in", "tokens_out",
        "status", "error_message",
    }


def test_insert_and_list_runs(tmp_path):
    conn = dream_runs_db.open(tmp_path / "runs.db")
    run_id = dream_runs_db.insert(
        conn,
        tenant_id="_master",
        started_at="2026-04-20T10:00:00Z",
        ended_at="2026-04-20T10:00:05Z",
        duration_ms=5000,
        proposals_count=2,
        tool_calls=4,
        tokens_in=1500,
        tokens_out=300,
        status="completed",
        error_message=None,
    )
    assert isinstance(run_id, str) and len(run_id) > 0

    runs = dream_runs_db.list_runs(conn, tenant_id="_master", limit=10)
    assert len(runs) == 1
    assert runs[0]["proposals_count"] == 2


def test_list_filters_by_tenant(tmp_path):
    conn = dream_runs_db.open(tmp_path / "runs.db")
    for tid in ("A", "B", "A"):
        dream_runs_db.insert(
            conn,
            tenant_id=tid,
            started_at="2026-04-20T10:00:00Z",
            ended_at="2026-04-20T10:00:01Z",
            duration_ms=1000,
            proposals_count=0,
            tool_calls=0,
            tokens_in=0,
            tokens_out=0,
            status="completed",
            error_message=None,
        )
    assert len(dream_runs_db.list_runs(conn, "A", 10)) == 2
    assert len(dream_runs_db.list_runs(conn, "B", 10)) == 1
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pytest tests/migrations/test_dream_runs_schema.py -xvs
```

Expected: FAIL — module missing.

- [ ] **Step 3: Implement `dream_runs_db.py`**

Create `autoservice/dream_runs_db.py`:

```python
"""Repository for dream_runs.db — tracks each DreamAgent invocation."""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any

SCHEMA = """\
CREATE TABLE IF NOT EXISTS dream_runs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    proposals_count INTEGER NOT NULL,
    tool_calls INTEGER NOT NULL,
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_tenant ON dream_runs(tenant_id);
"""


def open(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def insert(
    conn: sqlite3.Connection,
    *,
    tenant_id: str,
    started_at: str,
    ended_at: str,
    duration_ms: int,
    proposals_count: int,
    tool_calls: int,
    tokens_in: int,
    tokens_out: int,
    status: str,
    error_message: str | None,
) -> str:
    run_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO dream_runs (
            id, tenant_id, started_at, ended_at, duration_ms,
            proposals_count, tool_calls, tokens_in, tokens_out,
            status, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (run_id, tenant_id, started_at, ended_at, duration_ms,
         proposals_count, tool_calls, tokens_in, tokens_out,
         status, error_message),
    )
    conn.commit()
    return run_id


def list_runs(conn: sqlite3.Connection, tenant_id: str, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, tenant_id, started_at, ended_at, duration_ms,
               proposals_count, tool_calls, tokens_in, tokens_out,
               status, error_message
        FROM dream_runs WHERE tenant_id = ?
        ORDER BY started_at DESC LIMIT ?
        """,
        (tenant_id, limit),
    ).fetchall()
    cols = ["id", "tenant_id", "started_at", "ended_at", "duration_ms",
            "proposals_count", "tool_calls", "tokens_in", "tokens_out",
            "status", "error_message"]
    return [dict(zip(cols, r)) for r in rows]
```

- [ ] **Step 4: Run test, expect PASS**

```bash
pytest tests/migrations/test_dream_runs_schema.py -xvs
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add autoservice/dream_runs_db.py tests/migrations/test_dream_runs_schema.py
git commit -m "feat(m2-dream): dream_runs.db schema + repository helpers

open() / insert() / list_runs() — tracks per-run metrics (tokens, duration,
proposals produced, status: completed/tool_limit/error)."
```

---

# Phase 3 — Dream Agent (spec §2.2 - §2.5)

## Task 3.1: `emit_proposal` tool

**Files:**
- Create: `autoservice/dream_agent.py`
- Test: `tests/dream_agent/test_emit_proposal_tool.py`

- [ ] **Step 1: Write failing test**

Create `tests/dream_agent/__init__.py` (empty) and `tests/dream_agent/test_emit_proposal_tool.py`:

```python
"""Test emit_proposal tool — writes a proposal row scoped to tenant."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from autoservice import dream_agent, proposal_pipeline


@pytest.fixture
def proposals_db(tmp_path):
    db = tmp_path / "proposals.db"
    conn = sqlite3.connect(db)
    proposal_pipeline.apply_schema(conn)
    yield conn
    conn.close()


def test_emit_proposal_writes_draft_row(proposals_db):
    dream_agent.emit_proposal(
        proposals_db,
        tenant_id="_master",
        category="response_quality",
        title="Tighten greeting for B2B tone",
        description="Customer agent currently opens with 'hey'; should be 'Hello'.",
        suggestion="Update greeting template in customer_soul.md.",
        evidence=["'hey' in 3/5 sampled openings"],
        risk_level="low",
        target_role="customer",
    )
    rows = proposals_db.execute(
        "SELECT id, status, tenant_id, category, data FROM proposals"
    ).fetchall()
    assert len(rows) == 1
    row_id, status, tid, cat, data = rows[0]
    assert status == "draft"
    assert tid == "_master"
    assert cat == "response_quality"
    payload = json.loads(data)
    assert payload["title"].startswith("Tighten")
    assert payload["risk_level"] == "low"
    assert payload["target_role"] == "customer"
    assert payload["evidence"] == ["'hey' in 3/5 sampled openings"]


def test_emit_proposal_rejects_invalid_category(proposals_db):
    with pytest.raises(ValueError, match="category"):
        dream_agent.emit_proposal(
            proposals_db,
            tenant_id="_master",
            category="not-a-category",
            title="x",
            description="x",
            suggestion="x",
            evidence=[],
            risk_level="low",
            target_role="customer",
        )


def test_emit_proposal_rejects_invalid_risk_level(proposals_db):
    with pytest.raises(ValueError, match="risk_level"):
        dream_agent.emit_proposal(
            proposals_db,
            tenant_id="_master",
            category="workflow",
            title="x", description="x", suggestion="x",
            evidence=[], risk_level="extreme", target_role="triage",
        )


def test_emit_proposal_generates_unique_ids(proposals_db):
    for i in range(3):
        dream_agent.emit_proposal(
            proposals_db,
            tenant_id="_master",
            category="workflow",
            title=f"t{i}", description="x", suggestion="x",
            evidence=[], risk_level="low", target_role="customer",
        )
    ids = {r[0] for r in proposals_db.execute("SELECT id FROM proposals")}
    assert len(ids) == 3
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pytest tests/dream_agent/test_emit_proposal_tool.py -xvs
```

Expected: FAIL — `autoservice.dream_agent` missing.

- [ ] **Step 3: Implement `dream_agent.py` — tool 1**

Create `autoservice/dream_agent.py`:

```python
"""Dream Agent — 5th role, self-evolution engine per tenant.

M2 spec §2.2 - §2.5.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {"response_quality", "workflow", "knowledge_gap", "tone"}
VALID_RISK_LEVELS = {"low", "medium", "high"}
VALID_TARGET_ROLES = {"customer", "translate", "lead", "triage"}


def emit_proposal(
    conn: sqlite3.Connection,
    *,
    tenant_id: str,
    category: str,
    title: str,
    description: str,
    suggestion: str,
    evidence: list[str],
    risk_level: str,
    target_role: str,
) -> str:
    """Write a proposal row. Returns the new row id.

    Called by the dream agent via tool-use. Validates inputs and stores a draft.
    """
    if category not in VALID_CATEGORIES:
        raise ValueError(
            f"invalid category {category!r}, must be one of {sorted(VALID_CATEGORIES)}"
        )
    if risk_level not in VALID_RISK_LEVELS:
        raise ValueError(
            f"invalid risk_level {risk_level!r}, must be one of {sorted(VALID_RISK_LEVELS)}"
        )
    if target_role not in VALID_TARGET_ROLES:
        raise ValueError(
            f"invalid target_role {target_role!r}, must be one of {sorted(VALID_TARGET_ROLES)}"
        )

    row_id = str(uuid.uuid4())
    payload = {
        "title": title,
        "description": description,
        "suggestion": suggestion,
        "evidence": evidence,
        "risk_level": risk_level,
        "target_role": target_role,
    }
    conn.execute(
        """
        INSERT INTO proposals (id, created_at, data, status, category, tenant_id)
        VALUES (?, ?, ?, 'draft', ?, ?)
        """,
        (
            row_id,
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            json.dumps(payload),
            category,
            tenant_id,
        ),
    )
    conn.commit()
    return row_id
```

- [ ] **Step 4: Run test, expect PASS**

```bash
pytest tests/dream_agent/test_emit_proposal_tool.py -xvs
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add autoservice/dream_agent.py tests/dream_agent/
git commit -m "feat(m2-dream): emit_proposal tool with validation

Writes a draft proposal row scoped to tenant_id. Validates category,
risk_level, and target_role against enums."
```

---

## Task 3.2: `kb_search` tool

**Files:**
- Modify: `autoservice/dream_agent.py`
- Test: `tests/dream_agent/test_kb_search_tool.py`

- [ ] **Step 1: Write failing test**

Create `tests/dream_agent/test_kb_search_tool.py`:

```python
"""Test kb_search dream tool — FTS5 query into tenant's kb.db."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from autoservice import dream_agent


@pytest.fixture
def tenant_kb(tmp_path, monkeypatch):
    """Create a KB with 3 chunks and register PROJECT_ROOT override."""
    monkeypatch.setattr(dream_agent, "PROJECT_ROOT", tmp_path)
    kb_dir = tmp_path / ".autoservice" / "sandbox" / "T" / "kb"
    kb_dir.mkdir(parents=True)
    conn = sqlite3.connect(kb_dir / "kb.db")
    conn.executescript("""
        CREATE TABLE kb_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT, source_name TEXT, section TEXT, domain TEXT
        );
        CREATE VIRTUAL TABLE kb_fts USING fts5(
            content, source_name, section, domain,
            content='kb_chunks', content_rowid='id'
        );
        CREATE TRIGGER kb_ai AFTER INSERT ON kb_chunks BEGIN
            INSERT INTO kb_fts(rowid, content, source_name, section, domain)
            VALUES (new.id, new.content, new.source_name, new.section, new.domain);
        END;
    """)
    rows = [
        ("Our shipping policy is 5 business days.", "faq.md", "shipping", "logistics"),
        ("Refunds processed within 14 days after return received.", "faq.md", "refund", "finance"),
        ("Premium plan includes priority support.", "pricing.md", "plans", "sales"),
    ]
    for r in rows:
        conn.execute(
            "INSERT INTO kb_chunks (content, source_name, section, domain) VALUES (?, ?, ?, ?)",
            r,
        )
    conn.commit()
    conn.close()
    return tmp_path


def test_kb_search_returns_matches(tenant_kb):
    hits = dream_agent.kb_search(tenant_id="T", query="shipping policy", limit=5)
    assert len(hits) >= 1
    assert any("shipping" in h["content"].lower() for h in hits)


def test_kb_search_empty_query_returns_empty(tenant_kb):
    assert dream_agent.kb_search(tenant_id="T", query="", limit=5) == []


def test_kb_search_respects_limit(tenant_kb):
    hits = dream_agent.kb_search(tenant_id="T", query="plan OR refund OR shipping", limit=2)
    assert len(hits) <= 2


def test_kb_search_unknown_tenant_returns_empty(tenant_kb):
    assert dream_agent.kb_search(tenant_id="UNKNOWN", query="anything", limit=5) == []
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pytest tests/dream_agent/test_kb_search_tool.py -xvs
```

Expected: FAIL — `AttributeError: dream_agent.kb_search` or `PROJECT_ROOT` missing.

- [ ] **Step 3: Extend `dream_agent.py`**

Add to `autoservice/dream_agent.py`:

```python
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _tenant_kb_path(tenant_id: str) -> Path | None:
    """Resolve kb.db path; None if tenant has no KB."""
    # Try sandbox first (master), then plugins (fork / published)
    candidates = [
        PROJECT_ROOT / ".autoservice" / "sandbox" / tenant_id / "kb" / "kb.db",
        PROJECT_ROOT / "plugins" / tenant_id / "kb" / "kb.db",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def kb_search(tenant_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
    """FTS5 search into this tenant's KB. Returns top `limit` hits."""
    if not query.strip():
        return []
    kb_path = _tenant_kb_path(tenant_id)
    if kb_path is None:
        logger.info("kb_search: no kb.db for tenant=%s", tenant_id)
        return []
    conn = sqlite3.connect(kb_path)
    try:
        rows = conn.execute(
            """
            SELECT c.id, c.content, c.source_name, c.section, c.domain
            FROM kb_fts f JOIN kb_chunks c ON f.rowid = c.id
            WHERE kb_fts MATCH ? LIMIT ?
            """,
            (query, limit),
        ).fetchall()
    except sqlite3.OperationalError as e:
        logger.warning("kb_search FTS error for tenant=%s query=%r: %s", tenant_id, query, e)
        return []
    finally:
        conn.close()
    return [
        {"id": r[0], "content": r[1], "source_name": r[2], "section": r[3], "domain": r[4]}
        for r in rows
    ]
```

- [ ] **Step 4: Run test, expect PASS**

```bash
pytest tests/dream_agent/test_kb_search_tool.py -xvs
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add autoservice/dream_agent.py tests/dream_agent/test_kb_search_tool.py
git commit -m "feat(m2-dream): kb_search tool — FTS5 into tenant kb.db

Resolves kb.db under .autoservice/sandbox/<tid>/ (master) or
plugins/<tid>/ (fork). Empty query / missing KB / bad FTS query all
return []."
```

---

## Task 3.3: `list_souls` tool

**Files:**
- Modify: `autoservice/dream_agent.py`
- Test: `tests/dream_agent/test_list_souls_tool.py`

- [ ] **Step 1: Write failing test**

Create `tests/dream_agent/test_list_souls_tool.py`:

```python
"""Test list_souls — returns summaries of 4 non-dream agent souls."""
from __future__ import annotations

import pytest

from autoservice import dream_agent


@pytest.fixture
def tenant_with_souls(tmp_path, monkeypatch):
    monkeypatch.setattr(dream_agent, "PROJECT_ROOT", tmp_path)
    souls = tmp_path / ".autoservice" / "sandbox" / "T" / "souls"
    souls.mkdir(parents=True)
    for role in ("customer", "translate", "lead", "triage", "dream"):
        (souls / f"{role}_soul.md").write_text(
            f"# {role.title()} Agent\n\nYou are a helpful {role} agent. "
            f"This is the full body of {role}'s soul file with extra context."
        )
    return tmp_path


def test_list_souls_returns_4_non_dream(tenant_with_souls):
    out = dream_agent.list_souls(tenant_id="T")
    roles = {s["role"] for s in out}
    assert roles == {"customer", "translate", "lead", "triage"}
    assert "dream" not in roles


def test_list_souls_summaries_truncate(tenant_with_souls):
    out = dream_agent.list_souls(tenant_id="T", summary_chars=40)
    for s in out:
        assert len(s["summary"]) <= 40


def test_list_souls_missing_tenant_empty(tenant_with_souls):
    assert dream_agent.list_souls(tenant_id="NOPE") == []
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pytest tests/dream_agent/test_list_souls_tool.py -xvs
```

Expected: FAIL.

- [ ] **Step 3: Extend `dream_agent.py`**

Add:

```python
def _tenant_souls_dir(tenant_id: str) -> Path | None:
    candidates = [
        PROJECT_ROOT / ".autoservice" / "sandbox" / tenant_id / "souls",
        PROJECT_ROOT / "plugins" / tenant_id / "souls",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def list_souls(tenant_id: str, summary_chars: int = 200) -> list[dict[str, str]]:
    """Return {role, summary} for each of the 4 non-dream agents."""
    souls_dir = _tenant_souls_dir(tenant_id)
    if souls_dir is None:
        return []
    out: list[dict[str, str]] = []
    for role in ("customer", "translate", "lead", "triage"):
        p = souls_dir / f"{role}_soul.md"
        if not p.exists():
            continue
        text = p.read_text()
        summary = text[:summary_chars]
        out.append({"role": role, "summary": summary})
    return out
```

- [ ] **Step 4: Run test, expect PASS**

```bash
pytest tests/dream_agent/test_list_souls_tool.py -xvs
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add autoservice/dream_agent.py tests/dream_agent/test_list_souls_tool.py
git commit -m "feat(m2-dream): list_souls tool — 4 non-dream soul summaries"
```

---

## Task 3.4: `run_dream()` agent loop (core)

**Files:**
- Modify: `autoservice/dream_agent.py`
- Test: `tests/dream_agent/test_run_dream.py`

- [ ] **Step 1: Write failing test**

Create `tests/dream_agent/test_run_dream.py`:

```python
"""Test run_dream() orchestrates the agent loop end-to-end."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from autoservice import dream_agent, proposal_pipeline, dream_runs_db


@dataclass
class FakeCCClient:
    """Mimics a Claude Code client that the dream agent drives via tool-use."""
    scripted_actions: list[dict]  # each dict describes what this send() should do

    def send(self, context: list[dict], tools: list[dict]) -> dict:
        action = self.scripted_actions.pop(0)
        return action


class FakeCCPool:
    def __init__(self, client: FakeCCClient):
        self._client = client
        self.released = False

    async def acquire(self, *, role: str, tenant_id: str):
        return self._client

    async def release(self, client):
        self.released = True


class FakeMempool:
    def __init__(self, recent_msgs: list[dict]):
        self._recent = recent_msgs

    def recent(self, tenant_id: str, limit: int = 20) -> list[dict]:
        return self._recent


@pytest.fixture
def stack(tmp_path):
    proposals = sqlite3.connect(tmp_path / "proposals.db")
    proposal_pipeline.apply_schema(proposals)
    runs = dream_runs_db.open(tmp_path / "runs.db")
    yield proposals, runs
    proposals.close()
    runs.close()


@pytest.mark.asyncio
async def test_run_dream_emits_proposal_and_records_run(stack, tmp_path, monkeypatch):
    proposals, runs = stack
    monkeypatch.setattr(dream_agent, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".autoservice" / "sandbox" / "_master" / "souls").mkdir(parents=True)

    client = FakeCCClient(scripted_actions=[
        {
            "tool_calls": [
                {
                    "name": "emit_proposal",
                    "input": {
                        "category": "tone",
                        "title": "Warmer greeting",
                        "description": "Current opening too terse",
                        "suggestion": "Add 'Thanks for reaching out'",
                        "evidence": ["msg 1", "msg 3"],
                        "risk_level": "low",
                        "target_role": "customer",
                    },
                },
            ],
            "finished": True,
            "tokens_in": 1200,
            "tokens_out": 200,
        },
    ])
    pool = FakeCCPool(client)
    mempool = FakeMempool([
        {"role": "customer", "text": "hi", "tenant_id": "_master"},
        {"role": "agent", "text": "hello.", "tenant_id": "_master"},
    ])

    result = await dream_agent.run_dream(
        tenant_id="_master",
        cc_pool=pool,
        mempool=mempool,
        proposals_db=proposals,
        runs_db=runs,
    )

    assert result.proposals_count == 1
    assert result.tool_calls == 1
    assert result.status == "completed"
    assert pool.released is True

    rows = proposals.execute("SELECT tenant_id, category FROM proposals").fetchall()
    assert rows == [("_master", "tone")]

    run_rows = runs.execute("SELECT tenant_id, status FROM dream_runs").fetchall()
    assert run_rows == [("_master", "completed")]


@pytest.mark.asyncio
async def test_run_dream_enforces_tool_turn_limit(stack, tmp_path, monkeypatch):
    proposals, runs = stack
    monkeypatch.setattr(dream_agent, "PROJECT_ROOT", tmp_path)

    # Scripted: 15 consecutive kb_search calls never finishing
    actions = [
        {"tool_calls": [{"name": "kb_search", "input": {"query": "q"}}],
         "finished": False, "tokens_in": 100, "tokens_out": 20}
        for _ in range(15)
    ]
    client = FakeCCClient(scripted_actions=actions)
    pool = FakeCCPool(client)
    mempool = FakeMempool([])

    result = await dream_agent.run_dream(
        tenant_id="_master",
        cc_pool=pool,
        mempool=mempool,
        proposals_db=proposals,
        runs_db=runs,
        max_tool_turns=10,
    )
    assert result.status == "tool_limit"
    assert result.tool_calls == 10
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pytest tests/dream_agent/test_run_dream.py -xvs
```

Expected: FAIL — `run_dream` missing.

- [ ] **Step 3: Implement `run_dream()`**

Add to `autoservice/dream_agent.py`:

```python
import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from autoservice import dream_runs_db


@dataclass
class DreamRunResult:
    run_id: str
    tenant_id: str
    proposals_count: int
    tool_calls: int
    tokens_in: int
    tokens_out: int
    duration_ms: int
    status: str              # completed | tool_limit | error
    error_message: str | None = None


# Tool schema exposed to the dream CC client. Actual invocation is
# resolved in run_dream's dispatch loop below.
DREAM_TOOLS = [
    {
        "name": "kb_search",
        "description": "FTS5 search the tenant's KB. Returns list of {id, content, source_name}.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_souls",
        "description": "Summaries of the 4 non-dream agent souls (customer/translate/lead/triage).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "emit_proposal",
        "description": "Write a draft improvement proposal for this tenant.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": sorted(VALID_CATEGORIES)},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "suggestion": {"type": "string"},
                "evidence": {"type": "array", "items": {"type": "string"}},
                "risk_level": {"type": "string", "enum": sorted(VALID_RISK_LEVELS)},
                "target_role": {"type": "string", "enum": sorted(VALID_TARGET_ROLES)},
            },
            "required": ["category", "title", "description", "suggestion",
                         "evidence", "risk_level", "target_role"],
        },
    },
]


def _build_initial_context(
    tenant_id: str,
    mempool: Any,
    proposals_db: sqlite3.Connection,
    dream_cfg: dict,
) -> list[dict]:
    """Pack recent conversations + history proposals into the first message."""
    recent = mempool.recent(tenant_id, limit=20)
    history = proposals_db.execute(
        """
        SELECT category, data, status FROM proposals
        WHERE tenant_id = ? AND status IN ('accepted', 'rejected')
        ORDER BY created_at DESC LIMIT 5
        """,
        (tenant_id,),
    ).fetchall()
    payload = {
        "recent_messages": recent,
        "recent_proposals": [
            {"category": c, "data": json.loads(d), "status": s}
            for c, d, s in history
        ],
        "dream_config": dream_cfg,
    }
    return [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def _load_dream_config(tenant_id: str) -> dict:
    path = PROJECT_ROOT / ".autoservice" / "sandbox" / tenant_id / "config.json"
    if not path.exists():
        path = PROJECT_ROOT / "plugins" / tenant_id / "config.json"
    if not path.exists():
        return {"trigger": "manual", "coverage": "all",
                "risk_threshold": "medium", "canary": {"stages": [100]}}
    return json.loads(path.read_text()).get("dream", {})


async def run_dream(
    tenant_id: str,
    cc_pool: Any,
    mempool: Any,
    proposals_db: sqlite3.Connection,
    runs_db: sqlite3.Connection,
    *,
    max_tool_turns: int = 10,
) -> DreamRunResult:
    """Run one dream agent invocation for a tenant."""
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    t0 = time.monotonic()
    dream_cfg = _load_dream_config(tenant_id)
    context = _build_initial_context(tenant_id, mempool, proposals_db, dream_cfg)

    client = await cc_pool.acquire(role="dream", tenant_id=tenant_id)

    tool_calls = 0
    proposals_count = 0
    tokens_in = 0
    tokens_out = 0
    status = "completed"
    error_message = None

    try:
        while tool_calls < max_tool_turns:
            result = client.send(context, DREAM_TOOLS)
            tokens_in += result.get("tokens_in", 0)
            tokens_out += result.get("tokens_out", 0)

            calls = result.get("tool_calls", [])
            for call in calls:
                tool_calls += 1
                name = call["name"]
                args = call["input"]
                if name == "kb_search":
                    hits = kb_search(
                        tenant_id=tenant_id,
                        query=args["query"],
                        limit=args.get("limit", 5),
                    )
                    context.append({"role": "tool", "name": name,
                                     "content": json.dumps(hits, ensure_ascii=False)})
                elif name == "list_souls":
                    souls = list_souls(tenant_id=tenant_id)
                    context.append({"role": "tool", "name": name,
                                     "content": json.dumps(souls, ensure_ascii=False)})
                elif name == "emit_proposal":
                    try:
                        emit_proposal(proposals_db, tenant_id=tenant_id, **args)
                        proposals_count += 1
                        context.append({"role": "tool", "name": name,
                                         "content": "ok"})
                    except ValueError as e:
                        context.append({"role": "tool", "name": name,
                                         "content": f"error: {e}"})
                else:
                    logger.warning("dream agent called unknown tool %s", name)

            if result.get("finished") and not calls:
                break
            if result.get("finished"):
                break
            if tool_calls >= max_tool_turns:
                status = "tool_limit"
                break
    except Exception as e:
        logger.exception("dream run failed for tenant=%s", tenant_id)
        status = "error"
        error_message = str(e)
    finally:
        await cc_pool.release(client)

    ended_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    duration_ms = int((time.monotonic() - t0) * 1000)

    run_id = dream_runs_db.insert(
        runs_db,
        tenant_id=tenant_id,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
        proposals_count=proposals_count,
        tool_calls=tool_calls,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        status=status,
        error_message=error_message,
    )

    return DreamRunResult(
        run_id=run_id,
        tenant_id=tenant_id,
        proposals_count=proposals_count,
        tool_calls=tool_calls,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        duration_ms=duration_ms,
        status=status,
        error_message=error_message,
    )
```

Also ensure `pytest-asyncio` is available — it should already be in dev deps; if not, add it to `requirements-dev.txt` or the test marker will skip.

- [ ] **Step 4: Run test, expect PASS**

```bash
pytest tests/dream_agent/test_run_dream.py -xvs
```

Expected: 2 passed. If a collection error reports "@pytest.mark.asyncio requires pytest-asyncio", add it:

```bash
pip install pytest-asyncio
```

and add to `pytest.ini` or `pyproject.toml`:
```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 5: Commit**

```bash
git add autoservice/dream_agent.py tests/dream_agent/test_run_dream.py
git commit -m "feat(m2-dream): run_dream() agent loop with tool-use dispatch

- packs recent messages + history proposals + dream_cfg into initial context
- loops through client.send() dispatching kb_search/list_souls/emit_proposal
- enforces max_tool_turns=10; records run metadata into dream_runs.db
- returns DreamRunResult with status=completed|tool_limit|error"
```

---

## Task 3.5: `cc_pool` role="dream" support

**Files:**
- Modify: `autoservice/cc_pool.py`
- Test: extend existing `tests/cc_pool/` directory

- [ ] **Step 1: Inspect cc_pool to find role enum / pool config structure**

```bash
grep -n "role\|ROLES\|pool_size\|acquire\|create_cc_client" autoservice/cc_pool.py | head -30
```

Record how roles are enumerated and how pool size is configured.

- [ ] **Step 2: Write failing test**

Create `tests/cc_pool/test_dream_role.py` (if `tests/cc_pool/__init__.py` missing, create it empty first):

```python
"""Test cc_pool accepts role='dream' with its own size=1 pool."""
from __future__ import annotations

import pytest

from autoservice import cc_pool


def test_dream_is_valid_role():
    """Attempting to create a dream client must not raise on unknown role."""
    # Depending on impl: may be an enum check or dict lookup. Adjust name if needed.
    pool = cc_pool.CCPool()  # or however it's constructed
    assert "dream" in pool.VALID_ROLES  # replace with actual attribute


def test_dream_pool_default_size_is_1():
    pool = cc_pool.CCPool()
    assert pool.pool_sizes.get("dream", None) == 1


@pytest.mark.asyncio
async def test_dream_client_has_dream_tools(monkeypatch):
    """Acquired dream client is bound to the 3 dream tools."""
    # This test stubs the underlying CC spawn; verifies tool list on the
    # returned client. Adjust the assertion to the actual client shape.
    pool = cc_pool.CCPool()
    client = await pool.acquire(role="dream", tenant_id="_master")
    tool_names = {t["name"] for t in getattr(client, "tools", [])}
    assert {"kb_search", "list_souls", "emit_proposal"} <= tool_names
    await pool.release(client)
```

> Adjust class/attribute names after grep Step 1 reveals actual structure.

- [ ] **Step 3: Run test, expect FAIL**

```bash
pytest tests/cc_pool/test_dream_role.py -xvs
```

Expected: FAIL.

- [ ] **Step 4: Extend `cc_pool.py`**

In `autoservice/cc_pool.py`:

1. Add `"dream"` to the role enum/set (whatever the existing pattern is — likely `VALID_ROLES = {"customer", "translate", "lead", "triage"}` becomes `{"customer", "translate", "lead", "triage", "dream"}`).

2. Configure per-role pool sizes. If the existing code uses a single pool, refactor to per-role dict:

```python
# Near class init or module constants
DEFAULT_POOL_SIZES = {
    "customer": 3,
    "translate": 3,
    "lead": 2,
    "triage": 2,
    "dream": 1,           # M2: deployment-level singleton, dream runs are queued
}
```

3. In `create_cc_client()` or `acquire()`, when `role == "dream"`:
   - Attach the 3 dream tools from `dream_agent.DREAM_TOOLS` to the client's tool list.
   - Use the long-context model identifier `claude-opus-4-7[1m]` if the existing code lets us select model per role; otherwise note as a follow-up (don't over-engineer in this task).

Example patch shape:

```python
from autoservice import dream_agent

# in acquire() or create_cc_client():
if role == "dream":
    tools = getattr(client, "tools", []) + list(dream_agent.DREAM_TOOLS)
    client.tools = tools
```

- [ ] **Step 5: Run test, expect PASS**

```bash
pytest tests/cc_pool/test_dream_role.py -xvs
```

Expected: 3 passed. If the tool-binding assertion fails because the existing `CCClient` doesn't expose a `tools` attribute, adapt the test to match the actual attribute name or wire tools through the SDK call signature.

- [ ] **Step 6: Full regression sweep**

```bash
pytest tests/cc_pool/ tests/dream_agent/ -x
```

- [ ] **Step 7: Commit**

```bash
git add autoservice/cc_pool.py tests/cc_pool/test_dream_role.py
git commit -m "feat(m2-dream): cc_pool role=dream with independent size-1 pool

Dream clients get kb_search/list_souls/emit_proposal tools bound at
acquire. Pool is deployment-level singleton (concurrent runs queued)."
```

---

## Task 3.6: `POST /api/dream/trigger` + `GET /api/dream/runs`

**Files:**
- Modify: `autoservice/api_routes.py`
- Test: extend `tests/api/` or create `tests/dream_agent/test_dream_endpoints.py`

- [ ] **Step 1: Write failing test**

Create `tests/dream_agent/test_dream_endpoints.py`:

```python
"""Test /api/dream/trigger and /api/dream/runs endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from autoservice import api_routes  # or wherever the FastAPI app is


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    # Inject stub auth + stub cc_pool so dream "runs" without real LLM
    from autoservice import web_gateway
    client = TestClient(web_gateway.app)
    # For this test, assume a bypass auth helper exists or tests use a master-auth cookie.
    # If auth is strict: monkeypatch require_tenant_access to a no-op dep.
    yield client


def test_trigger_returns_run_id(app_client, monkeypatch):
    # Monkeypatch dream_agent.run_dream to a stub async returning a fake result
    from autoservice import dream_agent, api_routes
    from autoservice.dream_agent import DreamRunResult

    async def fake_run(*args, **kwargs):
        return DreamRunResult(
            run_id="run-123", tenant_id=kwargs.get("tenant_id", "_master"),
            proposals_count=1, tool_calls=1, tokens_in=100, tokens_out=20,
            duration_ms=500, status="completed", error_message=None,
        )
    monkeypatch.setattr(dream_agent, "run_dream", fake_run)

    resp = app_client.post("/api/dream/trigger", json={"tenant_id": "_master"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "run-123"
    assert body["status"] == "completed"


def test_runs_endpoint_lists_recent(app_client):
    resp = app_client.get("/api/dream/runs?tenant_id=_master&limit=5")
    assert resp.status_code == 200
    body = resp.json()
    assert "runs" in body
    assert isinstance(body["runs"], list)
```

> Auth bypass: if `require_tenant_access` is already wired strictly, insert a test-only dep override via `app.dependency_overrides[...] = lambda: FakeSession(...)` inside the fixture.

- [ ] **Step 2: Run test, expect FAIL**

```bash
pytest tests/dream_agent/test_dream_endpoints.py -xvs
```

Expected: FAIL — 404 Not Found.

- [ ] **Step 3: Add endpoints to `api_routes.py`**

In `autoservice/api_routes.py` (or the router module the app uses):

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from autoservice import dream_agent, dream_runs_db
# Assumes require_tenant_access exists (task 5.5). If not yet, use a placeholder
# dep that reads session cookie; this task does not add auth — just endpoints.

router = APIRouter(prefix="/api/dream", tags=["dream"])


class TriggerRequest(BaseModel):
    tenant_id: str


@router.post("/trigger")
async def trigger_dream(req: TriggerRequest):
    # Acquire cc_pool, mempool, proposals_db, runs_db from app state / DI.
    # Use helpers matching how api_routes.py currently accesses these.
    from autoservice import cc_pool as _cc, memory_pool as _mp, proposal_pipeline
    pool = _cc.get_default_pool()
    mempool = _mp.get_default()
    proposals = _open_proposals_db()
    runs = _open_runs_db()
    try:
        result = await dream_agent.run_dream(
            tenant_id=req.tenant_id,
            cc_pool=pool,
            mempool=mempool,
            proposals_db=proposals,
            runs_db=runs,
        )
        return {
            "run_id": result.run_id,
            "status": result.status,
            "proposals_count": result.proposals_count,
        }
    finally:
        proposals.close()
        runs.close()


@router.get("/runs")
def list_dream_runs(tenant_id: str, limit: int = 20):
    runs = _open_runs_db()
    try:
        return {"runs": dream_runs_db.list_runs(runs, tenant_id, limit)}
    finally:
        runs.close()
```

Add helper functions if not already present:

```python
def _open_proposals_db():
    import sqlite3
    from autoservice import proposal_pipeline
    path = PROJECT_ROOT / ".autoservice" / "database" / "proposals" / "proposals.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    proposal_pipeline.apply_schema(conn)
    return conn


def _open_runs_db():
    from autoservice import dream_runs_db
    return dream_runs_db.open(
        PROJECT_ROOT / ".autoservice" / "dream" / "runs.db"
    )
```

Then register the router in `web_gateway.py`:

```python
from autoservice.api_routes import router as dream_router  # or the specific router name
app.include_router(dream_router)
```

- [ ] **Step 4: Run test, expect PASS**

```bash
pytest tests/dream_agent/test_dream_endpoints.py -xvs
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add autoservice/api_routes.py autoservice/web_gateway.py tests/dream_agent/test_dream_endpoints.py
git commit -m "feat(m2-dream): POST /api/dream/trigger + GET /api/dream/runs"
```

---

# Phase 4 — DreamScheduler (spec §2.6)

## Task 4.1: `should_trigger()` logic

**Files:**
- Create: `autoservice/dream_scheduler.py`
- Test: `tests/dream_scheduler/test_should_trigger.py`

- [ ] **Step 1: Write failing test**

Create `tests/dream_scheduler/__init__.py` and `tests/dream_scheduler/test_should_trigger.py`:

```python
"""Test DreamScheduler.should_trigger — decides per-tenant whether to fire now."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from autoservice import dream_scheduler


def _now():
    return datetime.now(timezone.utc)


def test_manual_never_triggers():
    assert dream_scheduler.should_trigger(
        cfg={"trigger": "manual"},
        last_message_at=_now() - timedelta(hours=5),
        last_run_at=None,
        now=_now(),
    ) is False


def test_idle_triggers_when_quiet_long_enough():
    assert dream_scheduler.should_trigger(
        cfg={"trigger": "idle", "idle_threshold_min": 30},
        last_message_at=_now() - timedelta(minutes=45),
        last_run_at=None,
        now=_now(),
    ) is True


def test_idle_does_not_trigger_when_recent_activity():
    assert dream_scheduler.should_trigger(
        cfg={"trigger": "idle", "idle_threshold_min": 30},
        last_message_at=_now() - timedelta(minutes=5),
        last_run_at=None,
        now=_now(),
    ) is False


def test_idle_respects_1h_cooldown():
    now = _now()
    assert dream_scheduler.should_trigger(
        cfg={"trigger": "idle", "idle_threshold_min": 30},
        last_message_at=now - timedelta(minutes=45),
        last_run_at=now - timedelta(minutes=30),  # within 1h
        now=now,
    ) is False


def test_scheduled_fires_at_configured_time():
    target = _now().replace(hour=3, minute=0, second=0, microsecond=0)
    assert dream_scheduler.should_trigger(
        cfg={"trigger": "scheduled", "cron_hhmm": "03:00"},
        last_message_at=None,
        last_run_at=target - timedelta(days=1),
        now=target + timedelta(seconds=30),  # within scheduler tick window
    ) is True


def test_scheduled_does_not_refire_within_same_hour():
    target = _now().replace(hour=3, minute=0, second=0, microsecond=0)
    assert dream_scheduler.should_trigger(
        cfg={"trigger": "scheduled", "cron_hhmm": "03:00"},
        last_message_at=None,
        last_run_at=target + timedelta(minutes=1),
        now=target + timedelta(minutes=2),
    ) is False
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pytest tests/dream_scheduler/test_should_trigger.py -xvs
```

Expected: FAIL — module missing.

- [ ] **Step 3: Implement `dream_scheduler.py`**

Create `autoservice/dream_scheduler.py`:

```python
"""DreamScheduler — asyncio loop that fires run_dream per tenant policy.

M2 spec §2.6.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


def should_trigger(
    *,
    cfg: dict,
    last_message_at: datetime | str | None,
    last_run_at: datetime | str | None,
    now: datetime,
) -> bool:
    """Evaluate per-tenant dream config + liveness to decide if we should fire."""
    trigger = cfg.get("trigger", "manual")
    if trigger == "manual":
        return False

    last_run = _coerce_dt(last_run_at)
    last_msg = _coerce_dt(last_message_at)

    if trigger == "idle":
        threshold = timedelta(minutes=cfg.get("idle_threshold_min", 30))
        cooldown = timedelta(hours=1)
        if last_msg is None:
            return False  # no activity ever → nothing to dream about
        if (now - last_msg) < threshold:
            return False
        if last_run is not None and (now - last_run) < cooldown:
            return False
        return True

    if trigger == "scheduled":
        hhmm = cfg.get("cron_hhmm", "03:00")
        hour, minute = (int(x) for x in hhmm.split(":"))
        today_target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        # Fire if we're within 120s past the target and haven't already fired today
        if abs((now - today_target).total_seconds()) > 120:
            return False
        if last_run is not None:
            # If last run was within the past hour, skip
            if (now - last_run) < timedelta(hours=1):
                return False
        return True

    logger.warning("Unknown trigger mode: %s", trigger)
    return False


def _coerce_dt(v) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    # ISO string
    s = v.rstrip("Z")
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
```

- [ ] **Step 4: Run test, expect PASS**

```bash
pytest tests/dream_scheduler/test_should_trigger.py -xvs
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add autoservice/dream_scheduler.py tests/dream_scheduler/
git commit -m "feat(m2-dream): DreamScheduler.should_trigger policy eval

- manual: never
- idle: after idle_threshold_min + 1h cooldown
- scheduled: within 120s of cron_hhmm, not re-firing within same hour"
```

---

## Task 4.2: Scheduler loop + active-tenant discovery

**Files:**
- Modify: `autoservice/dream_scheduler.py`
- Test: `tests/dream_scheduler/test_scheduler_loop.py`

- [ ] **Step 1: Write failing test**

Create `tests/dream_scheduler/test_scheduler_loop.py`:

```python
"""Test the DreamScheduler asyncio loop discovers tenants and triggers runs."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoservice import dream_scheduler


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    (tmp_path / ".autoservice" / "sandbox").mkdir(parents=True)
    (tmp_path / "plugins").mkdir()
    monkeypatch.setattr(dream_scheduler, "PROJECT_ROOT", tmp_path)
    return tmp_path


def _write_tenant(root: Path, tid: str, dream_trigger: str = "manual"):
    tdir = root / ".autoservice" / "sandbox" / tid
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "config.json").write_text(json.dumps({
        "tenant_id": tid, "tier": 0 if tid == "_master" else 1,
        "status": "active" if tid == "_master" else "sandbox",
        "dream": {"trigger": dream_trigger},
    }))


def test_list_active_tenants_includes_master_and_sandbox(fake_repo):
    _write_tenant(fake_repo, "_master")
    _write_tenant(fake_repo, "acme")
    _write_tenant(fake_repo, "beta")
    tenants = dream_scheduler.list_active_tenants()
    assert set(tenants) == {"_master", "acme", "beta"}


@pytest.mark.asyncio
async def test_tick_dispatches_run_for_eligible_tenant(fake_repo, monkeypatch):
    _write_tenant(fake_repo, "_master", dream_trigger="idle")
    # Force should_trigger to True for _master only
    monkeypatch.setattr(
        dream_scheduler, "should_trigger",
        lambda **kw: kw.get("cfg", {}).get("trigger") == "idle",
    )
    mock_run = AsyncMock(return_value=MagicMock(run_id="r1"))
    monkeypatch.setattr(dream_scheduler, "_run_dream_for", mock_run)

    await dream_scheduler.tick_once()

    mock_run.assert_awaited_once()
    assert mock_run.call_args.kwargs["tenant_id"] == "_master"


@pytest.mark.asyncio
async def test_tick_skips_non_eligible(fake_repo, monkeypatch):
    _write_tenant(fake_repo, "_master", dream_trigger="manual")
    monkeypatch.setattr(dream_scheduler, "should_trigger", lambda **kw: False)
    mock_run = AsyncMock()
    monkeypatch.setattr(dream_scheduler, "_run_dream_for", mock_run)

    await dream_scheduler.tick_once()
    mock_run.assert_not_awaited()
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pytest tests/dream_scheduler/test_scheduler_loop.py -xvs
```

Expected: FAIL.

- [ ] **Step 3: Extend `dream_scheduler.py`**

Add to `autoservice/dream_scheduler.py`:

```python
import json
from pathlib import Path

from autoservice import bootstrap

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def list_active_tenants() -> list[str]:
    """Return tenant_ids active in this deployment."""
    mode = bootstrap.get_deployment_mode()
    if mode == "tenant":
        # fork: self + _local_admin
        self_tid = bootstrap.get_tenant_id()
        candidates = []
        for tid in (self_tid, "_local_admin"):
            if tid and (PROJECT_ROOT / "plugins" / tid / "config.json").exists():
                candidates.append(tid)
        return candidates

    # master: _master + all .autoservice/sandbox/*
    sandbox_root = PROJECT_ROOT / ".autoservice" / "sandbox"
    if not sandbox_root.exists():
        return []
    out = []
    for p in sorted(sandbox_root.iterdir()):
        if p.is_dir() and (p / "config.json").exists():
            out.append(p.name)
    return out


def _load_config(tenant_id: str) -> dict:
    mode = bootstrap.get_deployment_mode()
    if mode == "tenant":
        path = PROJECT_ROOT / "plugins" / tenant_id / "config.json"
    else:
        path = PROJECT_ROOT / ".autoservice" / "sandbox" / tenant_id / "config.json"
    return json.loads(path.read_text())


async def _run_dream_for(tenant_id: str) -> Any:
    """Dispatch a run — the default implementation. Tests monkeypatch this."""
    from autoservice import dream_agent, cc_pool as _cc, memory_pool as _mp, dream_runs_db
    from autoservice import proposal_pipeline
    import sqlite3

    proposals_path = PROJECT_ROOT / ".autoservice" / "database" / "proposals" / "proposals.db"
    proposals_path.parent.mkdir(parents=True, exist_ok=True)
    proposals = sqlite3.connect(proposals_path)
    proposal_pipeline.apply_schema(proposals)
    runs = dream_runs_db.open(PROJECT_ROOT / ".autoservice" / "dream" / "runs.db")
    try:
        return await dream_agent.run_dream(
            tenant_id=tenant_id,
            cc_pool=_cc.get_default_pool(),
            mempool=_mp.get_default(),
            proposals_db=proposals,
            runs_db=runs,
        )
    finally:
        proposals.close()
        runs.close()


_last_run_at: dict[str, datetime] = {}


async def tick_once() -> None:
    """One iteration of the scheduler loop — called every 60s in production."""
    from autoservice import memory_pool as _mp
    now = datetime.now(timezone.utc)
    mempool = _mp.get_default()

    for tid in list_active_tenants():
        try:
            cfg = _load_config(tid).get("dream", {})
        except Exception as e:
            logger.warning("tick_once: bad config for %s: %s", tid, e)
            continue
        last_run = _last_run_at.get(tid)
        last_msg_raw = mempool.last_message_at(tid)
        if should_trigger(
            cfg=cfg, last_message_at=last_msg_raw,
            last_run_at=last_run, now=now,
        ):
            logger.info("DreamScheduler firing for tenant=%s", tid)
            asyncio.create_task(_fire_and_record(tid, now))


async def _fire_and_record(tenant_id: str, fired_at: datetime) -> None:
    try:
        await _run_dream_for(tenant_id=tenant_id)
    except Exception as e:
        logger.exception("dream dispatch failed for %s", tenant_id)
    finally:
        _last_run_at[tenant_id] = fired_at


async def loop(interval_seconds: float = 60.0) -> None:
    """Main scheduler loop; runs indefinitely until cancelled."""
    while True:
        try:
            await tick_once()
        except Exception:
            logger.exception("tick_once crashed; continuing")
        await asyncio.sleep(interval_seconds)


def refresh(tenant_id: str) -> None:
    """Reset the in-memory last-run cache so a freshly-updated config takes effect."""
    _last_run_at.pop(tenant_id, None)
```

- [ ] **Step 4: Run test, expect PASS**

```bash
pytest tests/dream_scheduler/test_scheduler_loop.py -xvs
```

Expected: 3 passed.

- [ ] **Step 5: Wire into web_gateway lifespan**

In `autoservice/web_gateway.py`, extend the startup handler:

```python
@app.on_event("startup")
async def _startup():
    _run_startup_bootstrap()
    # Start dream scheduler as a background task
    from autoservice import dream_scheduler
    app.state.dream_scheduler_task = asyncio.create_task(dream_scheduler.loop())


@app.on_event("shutdown")
async def _shutdown():
    task = getattr(app.state, "dream_scheduler_task", None)
    if task:
        task.cancel()
```

- [ ] **Step 6: Commit**

```bash
git add autoservice/dream_scheduler.py autoservice/web_gateway.py tests/dream_scheduler/test_scheduler_loop.py
git commit -m "feat(m2-dream): DreamScheduler async loop + lifespan wiring

list_active_tenants discovers _master + sandbox/* (master) or self
+ _local_admin (fork). tick_once evaluates should_trigger per tenant
and dispatches run_dream. Lifespan starts/cancels the loop."
```

---

## Task 4.3: `/dream-config` confirm → scheduler refresh

**Files:**
- Modify: `autoservice/dream_config_dialog.py`
- Test: extend existing `tests/dream/test_dream_config_sync.py`

- [ ] **Step 1: Inspect existing dream_config_dialog**

```bash
grep -n "confirm\|sync\|save\|_dream_config" autoservice/dream_config_dialog.py | head
```

Find the point where `/dream-config` is considered "committed" — that's where we hook the refresh call.

- [ ] **Step 2: Write failing test**

Append to `tests/dream/test_dream_config_sync.py` (or create a new test file if hook is cleaner there):

```python
def test_dream_config_confirm_calls_scheduler_refresh(monkeypatch):
    from autoservice import dream_config_dialog, dream_scheduler
    refresh_called_with = []
    monkeypatch.setattr(
        dream_scheduler, "refresh",
        lambda tid: refresh_called_with.append(tid),
    )

    session = dream_config_dialog.DreamConfigSession(tenant_id="acme")
    # Drive session through confirmation — use whatever public API exists:
    session.trigger = "idle"  # or .set_trigger("idle")
    session.coverage = "all"
    session.risk_threshold = "medium"
    session.canary = {"stages": [5, 25, 100]}
    session.confirm()

    assert refresh_called_with == ["acme"]
```

Adjust attribute names to match the actual `DreamConfigSession` API.

- [ ] **Step 3: Run, expect FAIL**

```bash
pytest tests/dream/test_dream_config_sync.py -xvs -k refresh
```

Expected: FAIL.

- [ ] **Step 4: Patch `dream_config_dialog.py`**

Inside `DreamConfigSession.confirm()` (or wherever the finalization happens), add at the end:

```python
# Notify scheduler so the new trigger takes effect immediately
from autoservice import dream_scheduler
dream_scheduler.refresh(self.tenant_id)
```

- [ ] **Step 5: Run, expect PASS**

```bash
pytest tests/dream/test_dream_config_sync.py -xvs
```

Expected: all tests pass including new refresh test.

- [ ] **Step 6: Commit**

```bash
git add autoservice/dream_config_dialog.py tests/dream/test_dream_config_sync.py
git commit -m "feat(m2-dream): /dream-config confirm refreshes scheduler cache"
```

---

*(continues in Phase 5)*
