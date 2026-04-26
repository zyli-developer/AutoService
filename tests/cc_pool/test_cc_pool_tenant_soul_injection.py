"""Tests for T1B.4: per-tenant soul injection in cc_pool.create_cc_client().

Verifies that create_cc_client correctly loads per-tenant soul markdown files
from .autoservice/sandbox/<tenant_id>/souls/<role>_soul.md, falls back to
default role souls at agents/<role>/soul.md, and doesn't crash when soul files
are missing.

The Claude Agent SDK subprocess is NOT actually started — we patch
ClaudeSDKClient to capture the options it was constructed with.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from autoservice import cc_pool
from autoservice.cc_pool import PoolConfig, create_cc_client, _load_soul


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def sandbox_root(tmp_path, monkeypatch):
    """Create a tmp cwd with .autoservice/sandbox/ structure and chdir to it."""
    monkeypatch.chdir(tmp_path)
    sandbox = tmp_path / ".autoservice" / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def patched_sdk():
    """Patch ClaudeSDKClient so we capture ClaudeAgentOptions without connecting."""
    captured = {}

    class _FakeSDKClient:
        def __init__(self, options):
            captured["options"] = options
            self._transport = None

        async def connect(self):
            # Simulate successful connect without starting a real CLI.
            return None

        async def disconnect(self):
            return None

    with patch.object(cc_pool, "ClaudeSDKClient", _FakeSDKClient):
        yield captured


def _write_sandbox_soul(root: Path, tenant_id: str, role: str, content: str) -> None:
    soul_dir = root / ".autoservice" / "sandbox" / tenant_id / "souls"
    soul_dir.mkdir(parents=True, exist_ok=True)
    (soul_dir / f"{role}_soul.md").write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# _load_soul unit tests
# ---------------------------------------------------------------------------


class TestLoadSoul:
    def test_tenant_none_returns_default_role_soul(self, sandbox_root):
        """tenant_id=None → falls back to default agents/<role>/soul.md."""
        # Default soul at agents/customer/soul.md exists in the repo
        # (via PROJECT_ROOT). The loader must return non-empty content.
        soul = _load_soul(tenant_id=None, role="customer")
        assert soul is not None
        assert len(soul) > 0
        assert "Customer" in soul or "客服" in soul or "customer" in soul.lower()

    def test_tenant_with_sandbox_soul(self, sandbox_root):
        """tenant_id='X' with sandbox soul → returns that soul content."""
        tenant_soul = "# Tenant X Soul\n\nYou are a custom agent for tenant X."
        _write_sandbox_soul(sandbox_root, "tenantX", "customer", tenant_soul)

        soul = _load_soul(tenant_id="tenantX", role="customer")
        assert soul == tenant_soul

    def test_tenant_missing_sandbox_falls_back(self, sandbox_root):
        """tenant_id set but no sandbox dir → falls back to default role soul."""
        soul = _load_soul(tenant_id="nonexistent_tenant", role="customer")
        # Must not crash; must return default (non-None)
        assert soul is not None
        assert len(soul) > 0

    def test_tenant_missing_role_file_falls_back(self, sandbox_root):
        """tenant_id set, sandbox dir exists but no <role>_soul.md → falls back."""
        # Create empty sandbox souls dir
        (sandbox_root / ".autoservice" / "sandbox" / "tenantY" / "souls").mkdir(
            parents=True
        )
        soul = _load_soul(tenant_id="tenantY", role="customer")
        assert soul is not None
        assert len(soul) > 0

    def test_unknown_role_with_no_tenant(self, sandbox_root):
        """Unknown role with no tenant → returns None (no default available)."""
        soul = _load_soul(tenant_id=None, role="not_a_real_role")
        assert soul is None

    def test_different_tenants_get_different_souls(self, sandbox_root):
        """Two tenants with distinct sandbox souls must return distinct content."""
        _write_sandbox_soul(sandbox_root, "tenantA", "customer", "SOUL_A_CONTENT")
        _write_sandbox_soul(sandbox_root, "tenantB", "customer", "SOUL_B_CONTENT")

        soul_a = _load_soul(tenant_id="tenantA", role="customer")
        soul_b = _load_soul(tenant_id="tenantB", role="customer")
        assert soul_a == "SOUL_A_CONTENT"
        assert soul_b == "SOUL_B_CONTENT"
        assert soul_a != soul_b


# ---------------------------------------------------------------------------
# create_cc_client integration — verifies soul is actually injected into SDK
# ---------------------------------------------------------------------------


class TestCreateCCClientTenantInjection:
    @pytest.mark.asyncio
    async def test_no_tenant_no_role_no_system_prompt(
        self, sandbox_root, patched_sdk
    ):
        """Backward compat: no role, no tenant, no explicit prompt → no prompt set."""
        cfg = PoolConfig(cwd=str(sandbox_root))
        client = await create_cc_client(cfg)

        options = patched_sdk["options"]
        # system_prompt is a dataclass field that defaults to None; we only
        # set it when explicitly provided. So it should be None (default).
        assert getattr(options, "system_prompt", None) is None
        assert client is not None

    @pytest.mark.asyncio
    async def test_explicit_system_prompt_wins(self, sandbox_root, patched_sdk):
        """Explicit system_prompt must override any role/tenant lookup."""
        _write_sandbox_soul(sandbox_root, "tenantZ", "customer", "SANDBOX_SOUL")
        cfg = PoolConfig(cwd=str(sandbox_root))
        await create_cc_client(
            cfg,
            system_prompt="EXPLICIT_PROMPT",
            role="customer",
            tenant_id="tenantZ",
        )
        assert patched_sdk["options"].system_prompt == "EXPLICIT_PROMPT"

    @pytest.mark.asyncio
    async def test_tenant_id_none_uses_default_role_soul(
        self, sandbox_root, patched_sdk
    ):
        """tenant_id=None + role='customer' → inject default role soul."""
        cfg = PoolConfig(cwd=str(sandbox_root))
        await create_cc_client(cfg, role="customer", tenant_id=None)

        injected = patched_sdk["options"].system_prompt
        assert injected is not None
        assert len(injected) > 0
        # Should start with default agents/customer/soul.md (the
        # multi-bubble paragraph nudge is appended to customer/lead souls
        # by cc_pool — see spec 2026-04-26 §6.5).
        default_path = (
            Path(__file__).resolve().parent.parent.parent
            / "agents"
            / "customer"
            / "soul.md"
        )
        assert injected.startswith(default_path.read_text(encoding="utf-8"))

    @pytest.mark.asyncio
    async def test_tenant_with_sandbox_soul_injected(
        self, sandbox_root, patched_sdk
    ):
        """tenant_id='X' with sandbox soul → inject that soul."""
        custom = "# Custom X\n\nTenant-specific instructions."
        _write_sandbox_soul(sandbox_root, "tenantX", "customer", custom)
        cfg = PoolConfig(cwd=str(sandbox_root))

        await create_cc_client(cfg, role="customer", tenant_id="tenantX")
        # Soul is prepended to the multi-bubble paragraph nudge appended
        # by cc_pool (spec 2026-04-26 §6.5).
        assert patched_sdk["options"].system_prompt.startswith(custom)

    @pytest.mark.asyncio
    async def test_two_tenants_produce_distinct_clients(
        self, sandbox_root, patched_sdk
    ):
        """Two successive create_cc_client calls with different tenants
        must produce distinctly different system prompts."""
        _write_sandbox_soul(sandbox_root, "tenantA", "customer", "SOUL_A")
        _write_sandbox_soul(sandbox_root, "tenantB", "customer", "SOUL_B")
        cfg = PoolConfig(cwd=str(sandbox_root))

        await create_cc_client(cfg, role="customer", tenant_id="tenantA")
        prompt_a = patched_sdk["options"].system_prompt

        await create_cc_client(cfg, role="customer", tenant_id="tenantB")
        prompt_b = patched_sdk["options"].system_prompt

        # Soul is prepended to the multi-bubble paragraph nudge appended
        # by cc_pool (spec 2026-04-26 §6.5). Compare prefix only.
        assert prompt_a.startswith("SOUL_A")
        assert prompt_b.startswith("SOUL_B")
        assert prompt_a != prompt_b

    @pytest.mark.asyncio
    async def test_missing_tenant_sandbox_falls_back_no_crash(
        self, sandbox_root, patched_sdk
    ):
        """Missing sandbox/<tid>/souls/<role>_soul.md → fall back to default, no crash."""
        cfg = PoolConfig(cwd=str(sandbox_root))
        # tenant "ghost" has no sandbox at all
        client = await create_cc_client(cfg, role="customer", tenant_id="ghost")

        injected = patched_sdk["options"].system_prompt
        assert injected is not None
        # Matches default agents/customer/soul.md
        default_path = (
            Path(__file__).resolve().parent.parent.parent
            / "agents"
            / "customer"
            / "soul.md"
        )
        # Soul is prepended to the multi-bubble paragraph nudge appended
        # by cc_pool (spec 2026-04-26 §6.5).
        assert injected.startswith(default_path.read_text(encoding="utf-8"))
        assert client is not None
