"""
CC Pool — Claude Code SDK instance pool.

Built on socialware.pool.AsyncPool with CC-specific client and configuration.

Usage:
    from autoservice.cc_pool import get_pool, shutdown_pool

    pool = await get_pool()
    async with pool.acquire() as instance:
        await instance.client.query("hello")
        async for msg in instance.client.receive_response():
            print(msg)

    # Or use the convenience method:
    async for msg in pool.query("hello"):
        print(msg)
"""

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any, AsyncIterator

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
from claude_agent_sdk.types import Message

# SDK content-block types — imported at module level so tests can
# ``monkeypatch.setattr(cc_pool, "AssistantMessage", ...)`` and the
# T5S.14 call_with_tools wrapper picks up the patched class via
# isinstance checks. Fallbacks keep module import working if a future
# SDK release removes any of these; real code paths will log and raise.
try:
    from claude_agent_sdk.types import (
        AssistantMessage,
        ResultMessage,
        TextBlock,
        ToolUseBlock,
    )
except ImportError:  # pragma: no cover — defensive
    AssistantMessage = object  # type: ignore[assignment,misc]
    ResultMessage = object  # type: ignore[assignment,misc]
    TextBlock = object  # type: ignore[assignment,misc]
    ToolUseBlock = object  # type: ignore[assignment,misc]

from socialware.pool import (
    PoolConfig as _BasePoolConfig,
    PooledInstance,
    AsyncPool,
)

log = logging.getLogger("cc-pool")


def _setup_file_logging() -> None:
    """Configure cc-pool logger to write to .autoservice/logs/cc_pool.log."""
    log_dir = Path.cwd() / ".autoservice" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "cc_pool.log"

    if any(isinstance(h, logging.FileHandler) and h.baseFilename == str(log_file.resolve())
           for h in log.handlers):
        return

    file_handler = logging.FileHandler(str(log_file), mode="a", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "[cc-pool] %(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    log.addHandler(file_handler)

    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
               for h in log.handlers):
        stderr_handler = logging.StreamHandler()
        stderr_handler.setLevel(logging.INFO)
        stderr_handler.setFormatter(logging.Formatter("[cc-pool] %(levelname)s %(message)s"))
        log.addHandler(stderr_handler)

    log.setLevel(logging.DEBUG)


_setup_file_logging()


def _coerce_usage(u: Any) -> dict:
    """Normalise a ``Usage`` object or dict to a plain ``{input_tokens,
    output_tokens}`` dict for the Dream tool-use wrapper. T5S.14."""
    if isinstance(u, dict):
        return {
            "input_tokens": int(u.get("input_tokens") or 0),
            "output_tokens": int(u.get("output_tokens") or 0),
        }
    return {
        "input_tokens": int(getattr(u, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(u, "output_tokens", 0) or 0),
    }


# ---------------------------------------------------------------------------
# CC-specific client wrapper (implements PoolableClient protocol)
# ---------------------------------------------------------------------------

class CCClient:
    """Wraps ClaudeSDKClient to satisfy the PoolableClient protocol."""

    def __init__(self, sdk_client: ClaudeSDKClient):
        self._sdk = sdk_client

    async def connect(self) -> None:
        await self._sdk.connect()

    async def disconnect(self) -> None:
        await self._sdk.disconnect()

    def is_healthy(self) -> bool:
        try:
            transport = self._sdk._transport
            if transport is None:
                return False
            process = getattr(transport, "_process", None)
            if process is None:
                return False
            return process.returncode is None
        except Exception:
            return False

    async def query(self, prompt: str, **kwargs: Any) -> None:
        await self._sdk.query(prompt, **kwargs)

    async def receive_response(self) -> AsyncIterator[Message]:
        async for msg in self._sdk.receive_response():
            yield msg

    async def set_model(self, model: str | None) -> None:
        """Swap the active model mid-conversation.

        Delegates to ``ClaudeSDKClient.set_model``, which is a control
        message to the CLI — **no subprocess restart**, full conversation
        state preserved. Used by :meth:`CCPool.session_query` to upgrade
        a fast-tier sticky instance to slow_model when the router flags
        the turn as slow.
        """
        await self._sdk.set_model(model)

    async def call_with_tools(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict],
    ) -> dict:
        """Dream-role tool-use wrapper over the local claude_agent_sdk.

        T5S.14 (T3B.5 core) — adds a JSON-in / JSON-out tool-use surface
        to Dream role clients. The CLI-backed SDK does not accept
        Anthropic-shape tool JSON natively, so tool schemas are
        serialised into the prompt preamble; the model's ``tool_use``
        emissions are translated back into Anthropic-shape dicts so
        :func:`dream_agent._extract_tool_uses` consumes them unchanged.

        **Scope gate**: only Dream-role clients expose this surface.
        Customer / operator / triage / lead / translate clients raise
        ``RuntimeError`` — prevents accidental blast-radius into the
        conversation-path pools.  The ``_dream_role`` flag is set by
        :func:`create_cc_client` when ``role="dream"`` and by the
        legacy dream-pool factory (:func:`_make_tenant_instance`).

        Args:
            system: System prompt for this turn (caller-owned; not
                cached across calls — the closure style means each
                turn re-sends).
            messages: Anthropic-shape message history. Tool results
                on the user side are ``{"type": "tool_result",
                "tool_use_id", "content"}`` blocks.
            tools: Caller's tool schemas (e.g. ``emit_proposal``,
                ``kb_search``, ``list_souls``). Passed through
                verbatim — never mutated.

        Returns:
            Anthropic-shape response dict:
            ``{"content": [...blocks...], "stop_reason": str,
            "usage": {"input_tokens": int, "output_tokens": int}}``.
            Each block is a dict with a ``type`` discriminator:
            ``tool_use`` (has ``id`` / ``name`` / ``input``) or
            ``text`` (has ``text``).

        Raises:
            RuntimeError: the client is not a Dream-role client
                (``_dream_role`` flag unset / False).
        """
        if not getattr(self, "_dream_role", False):
            raise RuntimeError(
                "call_with_tools is reserved for dream-role clients. "
                "Customer / operator / triage / lead / translate clients "
                "must not invoke it — use query()/receive_response() "
                "instead."
            )

        # Serialise tools + messages into the prompt so the CLI model
        # sees them. The message shape mirrors Anthropic's so the model
        # can emit tool_use blocks that downstream code already parses.
        prompt_parts: list[str] = []
        if system:
            prompt_parts.append("[SYSTEM]")
            prompt_parts.append(system)
            prompt_parts.append("")
        prompt_parts.append("[TOOLS]")
        prompt_parts.append(json.dumps(list(tools), ensure_ascii=False))
        prompt_parts.append("")
        prompt_parts.append("[MESSAGES]")
        prompt_parts.append(json.dumps(list(messages), ensure_ascii=False))
        prompt = "\n".join(prompt_parts)

        await self._sdk.query(prompt)

        content_blocks: list[dict] = []
        stop_reason: str | None = None
        usage: dict | None = None

        # Re-read module-level SDK type handles each call — tests
        # monkeypatch them on cc_pool, and isinstance against the
        # re-imported handles would bypass the patch.
        import autoservice.cc_pool as _mod  # self-reference for patch visibility

        async for msg in self._sdk.receive_response():
            if isinstance(msg, _mod.AssistantMessage):
                for block in (msg.content or []):
                    if isinstance(block, _mod.ToolUseBlock):
                        content_blocks.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })
                    elif isinstance(block, _mod.TextBlock):
                        content_blocks.append({
                            "type": "text",
                            "text": block.text,
                        })
                # AssistantMessage-level stop_reason/usage (if present)
                sr = getattr(msg, "stop_reason", None)
                if sr is not None:
                    stop_reason = sr
                u = getattr(msg, "usage", None)
                if u is not None:
                    usage = _coerce_usage(u)
            elif isinstance(msg, _mod.ResultMessage):
                sr = getattr(msg, "stop_reason", None)
                if sr is not None and stop_reason is None:
                    stop_reason = sr
                u = getattr(msg, "usage", None)
                if u is not None and usage is None:
                    usage = _coerce_usage(u)

        return {
            "content": content_blocks,
            "stop_reason": stop_reason,
            "usage": usage or {},
        }


# ---------------------------------------------------------------------------
# CC-specific configuration (extends generic PoolConfig)
# ---------------------------------------------------------------------------

@dataclass
class PoolConfig(_BasePoolConfig):
    """CC pool configuration with Claude-specific fields.

    Loadable from config.local.yaml or env vars.
    The pool uses the locally installed Claude CLI by default (found via PATH).
    Set cli_path to override with a specific binary location.

    Tier model knobs (``fast_model`` / ``slow_model`` / ``dream_model``)
    let each role group pick its own Anthropic model — see
    :func:`_resolve_model_for_role` for the role → tier mapping.
    All three default to ``None``, in which case the legacy single
    ``model`` field is used for every role (back-compat).
    """
    cwd: str | None = None
    permission_mode: str = "bypassPermissions"
    model: str | None = None
    fast_model: str | None = None
    slow_model: str | None = None
    dream_model: str | None = None
    cli_path: str | None = None
    # Enable partial/delta streaming events for progressive UI updates.
    include_partial_messages: bool = False
    #: When set, the customer pool's warmup factory pre-creates tenant-pinned
    #: instances (with that tenant's soul + KB tool) and stamps them so the
    #: first customer message doesn't trigger destroy+rebuild in
    #: ``_recycle_instance_for_tenant``. Also triggers eager creation of the
    #: sub-pools listed in ``warmup_roles`` for this tenant at ``start()``,
    #: so the first dispatch to those roles doesn't pay the cold-spawn tax.
    #: Leave ``None`` for multi-tenant deploys where no single tenant
    #: dominates.
    warmup_tenant_id: str | None = None
    #: Role sub-pools to eager-open at ``start()`` time when
    #: ``warmup_tenant_id`` is set. Default ``["triage"]`` preserves the
    #: prior behavior (only triage warmed). Add ``"lead"`` in
    #: ``config.local.yaml`` to eliminate the ~3 s cold-start on the
    #: first lead-routed customer message (observable in gateway.log
    #: as ``Starting pool (min=0, max=2) ... Warmed instance
    #: cc-lead-001`` showing up on first purchase-intent-routed turn).
    warmup_roles: list[str] = field(default_factory=lambda: ["triage"])


def load_pool_config(cwd: str | None = None) -> PoolConfig:
    """Load pool config. Layered: config.yaml → config.local.yaml → env vars.

    Loading order (later overrides earlier):
      1. .autoservice/config.yaml        — shared defaults (committed to git)
      2. .autoservice/config.local.yaml   — local overrides (gitignored, secrets)
      3. CC_POOL_* environment variables  — deploy-time injection
    """
    config = PoolConfig(cwd=cwd)
    cwd_path = Path(cwd or Path.cwd())

    yaml_files = [
        cwd_path / ".autoservice" / "config.yaml",
        cwd_path / ".autoservice" / "config.local.yaml",
    ]
    for yaml_path in yaml_files:
        if not yaml_path.exists():
            continue
        try:
            import yaml
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            pool_data = data.get("cc_pool", {})
            if isinstance(pool_data, dict):
                for key, val in pool_data.items():
                    if hasattr(config, key):
                        setattr(config, key, val)
        except Exception as e:
            log.warning("Failed to load pool config from %s: %s", yaml_path.name, e)

    _INT_FIELDS = {"min_size", "max_size", "warmup_count", "max_queries_per_instance",
                    "max_sticky_bindings"}
    _FLOAT_FIELDS = {"max_lifetime_seconds", "health_check_interval", "checkout_timeout",
                      "sticky_idle_timeout"}
    _STR_FIELDS = {"cwd", "permission_mode", "model", "cli_path",
                    "fast_model", "slow_model", "dream_model",
                    "warmup_tenant_id"}

    for field_name in _INT_FIELDS | _FLOAT_FIELDS | _STR_FIELDS:
        env_key = f"CC_POOL_{field_name.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            if field_name in _INT_FIELDS:
                setattr(config, field_name, int(env_val))
            elif field_name in _FLOAT_FIELDS:
                setattr(config, field_name, float(env_val))
            else:
                setattr(config, field_name, env_val)

    return config


# ---------------------------------------------------------------------------
# Role → model tier resolution (Plan B — fast/slow/dream split)
# ---------------------------------------------------------------------------

#: Which model tier a role belongs to. Drives model selection in the main
#: customer pool, in ``_create_role_pool`` for (lead/translate/triage)
#: sub-pools, and in ``_dream_pool_config`` for the dream pool.
#:
#: * fast — haiku-class, target latency ~1 s (triage intent parsing,
#:   translation pass-through)
#: * slow — sonnet-class, target latency 5–15 s (customer conversation,
#:   lead qualification)
#: * dream — own knob; long-horizon agent loop, falls back to slow
#:
#: Kept in sync with ``classify_intent.yaml::model_tiers`` — if you add a
#: role, pick its tier here too.
#:
#: ``customer`` defaults to ``fast`` — the customer sticky pool warms on
#: haiku. Turns that need sonnet (complaint, product inquiry with KB,
#: purchase intent) are escalated in-place via
#: :meth:`CCPool._maybe_upgrade_tier` → ``ClaudeSDKClient.set_model``, so
#: the subprocess and its conversation context survive the model swap.
#: The upgrade is one-way per sticky session (see ``_upgraded_sticky``).
_ROLE_TIER: dict[str, str] = {
    "customer": "fast",
    "lead": "slow",
    "translate": "fast",
    "triage": "fast",
    "dream": "dream",
}


def _resolve_model_for_role(config: "PoolConfig", role: str) -> str | None:
    """Return the concrete model name to use for *role*.

    Resolution order per tier:

    * ``fast``  → ``config.fast_model``  → ``config.model``
    * ``slow``  → ``config.slow_model``  → ``config.model``
    * ``dream`` → ``config.dream_model`` → ``config.slow_model`` → ``config.model``

    Unknown roles fall back to ``config.model`` so adding a role without
    wiring the tier here degrades gracefully (same behavior as before the
    tier split). Returns ``None`` only when every relevant field is unset
    — callers pass that straight through to ``ClaudeAgentOptions`` which
    treats ``None`` as "SDK default".
    """
    tier = _ROLE_TIER.get(role)
    if tier == "fast":
        return config.fast_model or config.model
    if tier == "slow":
        return config.slow_model or config.model
    if tier == "dream":
        return config.dream_model or config.slow_model or config.model
    return config.model


# ---------------------------------------------------------------------------
# Per-tenant soul injection (T1B.4)
# ---------------------------------------------------------------------------

# Absolute path to the repo root — used to locate default role souls at
# ``agents/<role>/soul.md``. Resolved here so tests that chdir() into a tmp
# cwd still find the default soul.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_soul(tenant_id: str | None, role: str) -> str | None:
    """Load the soul markdown for ``role``, preferring the tenant sandbox.

    Lookup order:
      1. ``<cwd>/.autoservice/sandbox/<tenant_id>/souls/<role>_soul.md``
         — tenant-specific soul generated by the admin wizard (see
         ``autoservice/soul_generator.save_drafts``).
      2. ``<repo_root>/agents/<role>/soul.md`` — the default role soul
         shipped with the framework.
      3. ``None`` — no soul available for this role.

    Design reference: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §4.2.

    Args:
        tenant_id: Tenant identifier, or None for the default role soul.
        role: Agent role name (e.g. "customer", "translate", "lead", "triage").

    Returns:
        Soul markdown content, or None if neither tenant nor default exists.
    """
    # Defensive: reject role names that could escape the souls directory.
    # Role is backend-supplied today, but keep this tight in case it ever
    # reaches user input.
    if not role or "/" in role or "\\" in role or ".." in role:
        log.warning("Rejecting suspicious role name: %r", role)
        return None

    if tenant_id:
        # Same guard for tenant_id (today comes from URL path / WS query).
        if "/" in tenant_id or "\\" in tenant_id or ".." in tenant_id:
            log.warning("Rejecting suspicious tenant_id: %r", tenant_id)
            tenant_id = None

    if tenant_id:
        sandbox_soul = (
            Path.cwd()
            / ".autoservice"
            / "sandbox"
            / tenant_id
            / "souls"
            / f"{role}_soul.md"
        )
        try:
            if sandbox_soul.is_file():
                return sandbox_soul.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning(
                "Failed to read tenant soul %s: %s — falling back to default",
                sandbox_soul, exc,
            )

    default_soul = _PROJECT_ROOT / "agents" / role / "soul.md"
    try:
        if default_soul.is_file():
            return default_soul.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("Failed to read default role soul %s: %s", default_soul, exc)
    return None


# ---------------------------------------------------------------------------
# CC client factory
# ---------------------------------------------------------------------------

async def create_cc_client(
    config: PoolConfig,
    mcp_servers: dict | None = None,
    system_prompt: str | None = None,
    role: str | None = None,
    tenant_id: str | None = None,
    enable_kb_tool: bool = False,
) -> CCClient:
    """Factory: creates and connects a CCClient from pool config.

    Args:
        config: Pool configuration.
        mcp_servers: Optional MCP server configs to inject (e.g. channel tools).
                     Dict of name -> McpServerConfig (stdio, SSE, HTTP, or SDK type).
        system_prompt: Optional system prompt for the Claude Code session. If
                       provided, it takes precedence over role/tenant lookup.
        role: Optional agent role name (e.g. "customer"). When given without
              an explicit ``system_prompt``, the corresponding soul markdown
              is resolved via :func:`_load_soul` and injected as the SDK
              system prompt. See T1B.4 / tenant-sandbox-design §4.2.
        tenant_id: Optional tenant identifier. Combined with ``role`` to load
                   a per-tenant soul from
                   ``.autoservice/sandbox/<tenant_id>/souls/<role>_soul.md``;
                   falls back to the default role soul when absent.
        enable_kb_tool: When True AND tenant_id is non-None, injects the
            ``autoservice_kb`` MCP server that exposes ``kb_search`` scoped
            to the given tenant. No-op when False or tenant_id is None.
    """
    cwd = config.cwd or str(Path.cwd())
    cwd_path = Path(cwd).absolute()
    plugin_path = cwd_path / ".autoservice" / ".claude"

    env = {}
    for var in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
        val = os.environ.get(var)
        if val:
            env[var] = val

    # Resolve soul from role/tenant when no explicit prompt is provided.
    if system_prompt is None and role is not None:
        system_prompt = _load_soul(tenant_id, role)
        if system_prompt is None:
            log.warning(
                "No soul found for role=%s tenant_id=%s — starting without system prompt",
                role, tenant_id,
            )

    if enable_kb_tool and tenant_id:
        # Lazy import: avoids pulling SQLite/kb deps when tool isn't needed.
        from autoservice.kb_mcp_server import build_kb_mcp_server
        kb_server = build_kb_mcp_server(tenant_id)
        mcp_servers = {**(mcp_servers or {}), "autoservice_kb": kb_server}

    options = ClaudeAgentOptions(
        cwd=cwd,
        setting_sources=None,
        plugins=[{"type": "local", "path": str(plugin_path)}]
        if plugin_path.exists() else None,
        env=env,
        permission_mode=config.permission_mode,
        model=config.model,
        cli_path=config.cli_path,
        include_partial_messages=config.include_partial_messages,
    )

    if mcp_servers:
        options.mcp_servers = mcp_servers
    if system_prompt:
        options.system_prompt = system_prompt

    sdk_client = ClaudeSDKClient(options)
    client = CCClient(sdk_client)
    # T5S.14: flag dream-role clients so ``CCClient.call_with_tools``
    # recognises them. Customer/operator/triage/lead/translate clients
    # stay unflagged and reject call_with_tools.
    if role == "dream":
        client._dream_role = True  # type: ignore[attr-defined]
    await client.connect()
    return client


# ---------------------------------------------------------------------------
# CCPool — thin subclass with query() convenience
# ---------------------------------------------------------------------------

class StickyTenantMismatch(RuntimeError):
    """Raised when acquire_sticky is called with a tenant_id that differs
    from the one already sticky-bound to the same chat_id.

    Signals a logic bug upstream (conversation's tenant ownership mutated
    mid-flight). Callers should log + degrade, not retry.
    """


#: Set of roles :meth:`CCPool.acquire` accepts. "customer" is the default
#: M1 path (preserved for back-compat); "dream" routes through the
#: module-level :data:`_dream_pool` (spec §2.5 + CON-06). Extending this set
#: is the intended extension path — add the role here, wire up pool
#: selection in ``acquire``/``_pool_for_role``, and keep the single-source
#: NotImplementedError message in sync.
_KNOWN_ROLES: frozenset[str] = frozenset({"customer", "dream", "lead", "translate", "triage"})

#: Per-role default sub-pool sizes for the lazy (role, tenant) sub-pools
#: used by the triage-dispatch path (spec §2.3). Stateful roles (lead,
#: translate) get a small warm pool; stateless triage uses size=1 since
#: each request is independent.
_ROLE_POOL_SIZES: dict[str, int] = {
    "lead": 2,
    "translate": 2,
    "triage": 1,
}

#: Idle-timeout (seconds) after which a per-(role, tenant) sub-pool is
#: reaped by the background reaper loop. Must be referenced as a module
#: attribute so tests can ``monkeypatch.setattr`` it.
_REAP_IDLE_SEC: float = 600.0


class CCPool(AsyncPool[CCClient]):
    """Pool of pre-created Claude Code SDK instances.

    Args:
        config: Pool configuration.
        mcp_servers: Optional MCP server configs injected into every instance.
        system_prompt: Optional system prompt for all instances.
    """

    def __init__(
        self,
        config: PoolConfig | None = None,
        mcp_servers: dict | None = None,
        system_prompt: str | None = None,
        on_sticky_release: Callable[[str], Awaitable[None]] | None = None,
    ):
        cfg = config or PoolConfig()
        # Customer-tier model is resolved at factory-call time so
        # ``self._config`` keeps the original tier knobs intact for the
        # sub-pool factories (lead/translate/triage/dream) to consult.
        # Mutating ``cfg.model`` here would clobber slow_model/fast_model/
        # dream_model resolution for those roles.
        #
        # ``warmup_tenant_id`` (when set) pre-pins warmup instances to one
        # tenant's soul + KB tool so the first real customer message skips
        # the destroy+rebuild path in ``_recycle_instance_for_tenant``. Left
        # ``None`` → legacy behavior (neutral warmup, recycle on first use).
        warmup_tid = cfg.warmup_tenant_id
        super().__init__(
            config=cfg,
            factory=lambda: create_cc_client(
                replace(cfg, model=_resolve_model_for_role(cfg, "customer")),
                mcp_servers=mcp_servers,
                system_prompt=system_prompt,
                role="customer",
                tenant_id=warmup_tid,
                enable_kb_tool=(warmup_tid is not None),
            ),
            instance_prefix="cc",
            logger=log,
            on_sticky_release=on_sticky_release,
        )
        # Lazy per-(role, tenant_id) sub-pools for the lead/translate/triage
        # dispatch path (spec §2.3). Created on first acquire, reaped after
        # ``_REAP_IDLE_SEC`` seconds of idle. Kept as instance state so each
        # CCPool (including test-local pools) has its own isolated sub-pool
        # table and reaper task.
        self._role_pools: dict[tuple[str, str | None], AsyncPool[CCClient]] = {}
        self._role_pool_last_used: dict[tuple[str, str | None], float] = {}
        self._role_pool_lock = asyncio.Lock()
        self._reaper_task: asyncio.Task | None = None
        self._closed = False
        #: Sticky keys that have already been upgraded from fast_model to
        #: slow_model via ``set_model``. Upgrade is one-way per session —
        #: once a conversation escalates to sonnet it stays there until
        #: sticky release (matches the old demo's `_sdk_ensure` policy,
        #: avoids model thrashing mid-conversation). Cleared on release.
        self._upgraded_sticky: set[str] = set()

    async def _create_instance(self):  # type: ignore[override]
        """Wrap the base create, then stamp ``_pool_tenant_id`` so
        ``_recycle_instance_for_tenant`` treats warmup / on-demand
        instances as already tenant-pinned when ``warmup_tenant_id`` is
        set. Without this stamp the recycle helper sees ``_UNSET`` and
        throws away the just-created subprocess on first use.
        """
        instance = await super()._create_instance()
        warmup_tid = self._config.warmup_tenant_id  # type: ignore[attr-defined]
        if warmup_tid is not None:
            instance._pool_tenant_id = warmup_tid  # type: ignore[attr-defined]
        return instance

    async def start(self) -> None:  # type: ignore[override]
        """Start the pool, then (when ``warmup_tenant_id`` is set) pre-open
        each sub-pool listed in ``warmup_roles`` with one warm instance
        so the first dispatch to that role doesn't pay the ~3 s cold-spawn
        cost. Default ``warmup_roles=["triage"]`` preserves prior behavior;
        add ``"lead"`` in ``config.local.yaml`` when lead-routed messages
        are on the hot path.

        Pre-warm failures are logged per-role and swallowed — the main
        pool still serves traffic; individual role hops just pay the
        legacy cold-start on their first call.
        """
        await super().start()
        warmup_tid = self._config.warmup_tenant_id  # type: ignore[attr-defined]
        if warmup_tid is None:
            return
        roles = self._config.warmup_roles  # type: ignore[attr-defined]
        for role in roles:
            try:
                async with self._role_pool_lock:
                    key = (role, warmup_tid)
                    if key not in self._role_pools:
                        sub_pool = await self._create_role_pool(role, warmup_tid)
                        self._role_pools[key] = sub_pool
                        self._role_pool_last_used[key] = time.monotonic()
                        if self._reaper_task is None or self._reaper_task.done():
                            self._reaper_task = asyncio.create_task(
                                self._reaper_loop(), name="cc-pool-role-reaper",
                            )
            except Exception:
                log.exception(
                    "pre-warm %s sub-pool failed for tenant=%s — first "
                    "%s call will cold-spawn", role, warmup_tid, role,
                )

    async def acquire_sticky(
        self, key: str, *, tenant_id: str | None = None,
        timeout: float | None = None,
    ) -> PooledInstance[CCClient]:
        """Acquire a sticky-bound instance for (chat_id, tenant_id).

        Extends :meth:`AsyncPool.acquire_sticky` with tenant-aware soul
        injection:

          * Already bound + tenant matches → return as-is (parent handles
            access-counter/last-access bookkeeping).
          * Already bound + tenant differs → :class:`StickyTenantMismatch`.
          * Not bound → delegate to ``super()`` for the bind, then recycle
            the instance so it carries the tenant's customer soul + KB
            tool. If recycle swaps the instance, update the sticky binding
            to point at the new one so subsequent acquires return it.
          * ``tenant_id=None`` → delegate to ``super()`` unchanged (no
            recycle, preserves pre-existing M1 semantics).

        Recycle failures are caught and logged; the uncycled warm instance
        is still returned so the caller can degrade rather than crash. The
        instance is stamped with ``_pool_tenant_id = tenant_id`` in that
        case so subsequent same-tenant acquires match instead of raising
        :class:`StickyTenantMismatch`; the instance still works without
        the tenant soul.

        Concurrency: assumes a single in-flight acquire per key. Recycle
        runs outside ``_sticky_lock`` while the binding still points at
        the instance being destroyed; a concurrent acquire for the same
        key could observe a dead binding and double-bind. Safe for the
        typical one-conv-one-caller pattern; revisit if the gateway fans
        out parallel acquires.
        """
        existing = self._sticky_bindings.get(key)  # noqa: SLF001
        if existing is not None and existing.instance.is_healthy:
            bound = getattr(existing.instance, "_pool_tenant_id", None)
            if bound == tenant_id:
                return await super().acquire_sticky(key, timeout=timeout)
            raise StickyTenantMismatch(
                f"conv {key!r} already sticky-bound to tenant={bound!r}, "
                f"refusing rebind to tenant={tenant_id!r}"
            )

        # Fresh bind — let parent do its locking + checkout + binding.
        instance = await super().acquire_sticky(key, timeout=timeout)

        if tenant_id is None:
            return instance

        try:
            instance = await _recycle_instance_for_tenant(
                self, instance,
                role="customer", tenant_id=tenant_id,
            )
            # If recycle swapped the instance, update the sticky binding
            # so future acquires see the new one.
            async with self._sticky_lock:  # noqa: SLF001
                binding = self._sticky_bindings.get(key)  # noqa: SLF001
                if binding is not None and binding.instance is not instance:
                    binding.instance = instance
        except Exception:
            log.exception(
                "acquire_sticky: recycle failed for key=%s tenant=%s; "
                "returning uncycled instance (degraded)",
                key, tenant_id,
            )
            # Bind to the target tenant anyway so subsequent acquires see
            # a match instead of raising StickyTenantMismatch; the
            # instance still works without the tenant soul.
            instance._pool_tenant_id = tenant_id  # type: ignore[attr-defined]

        return instance

    async def query(self, prompt: str, **kwargs: Any) -> AsyncIterator[Message]:
        """Convenience: checkout, query, yield messages, checkin."""
        async with self.acquire() as instance:
            instance.query_count += 1
            session_id = kwargs.get("session_id", "default")
            await instance.client.query(prompt, session_id=session_id)
            async for msg in instance.client.receive_response():
                yield msg

    async def session_query(
        self, chat_id: str, prompt: str,
        *, tenant_id: str | None = None,
        tier: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[Message]:
        """Stateful multi-turn query: chat_id is sticky-bound to a CC instance.

        The same chat_id always gets the same Claude Code subprocess,
        preserving conversation context across multiple calls.
        Use end_session() to release the binding when the conversation ends.

        When tenant_id is provided, the sticky instance is bound to that
        tenant's soul + KB tool on first acquire. Subsequent calls for the
        same chat_id MUST pass the same tenant_id or StickyTenantMismatch
        is raised.

        *tier* controls in-session model escalation:

        * ``None`` (legacy callers) — no model change; instance runs on
          whatever model it was constructed with.
        * ``"fast"`` — leave model as-is (customer pool defaults to
          fast_model via ``_ROLE_TIER['customer']='fast'``, so this is a
          no-op on a fresh sticky binding).
        * ``"slow"`` — if ``config.slow_model`` is set and this sticky
          key hasn't been upgraded yet, call
          ``ClaudeSDKClient.set_model(slow_model)`` once. Subsequent
          turns on the same key skip the call (upgrade-once semantics).

        Downgrade is intentionally impossible here — a conversation that
        reached sonnet stays there for its lifetime. Matches the old
        demo's ``_sdk_ensure`` policy. ``end_session`` / sticky auto-
        release clear the upgrade stamp so a fresh session on the same
        key can start on fast_model again.
        """
        instance = await self.acquire_sticky(chat_id, tenant_id=tenant_id)
        await self._maybe_upgrade_tier(chat_id, instance, tier)
        instance.query_count += 1
        session_id = kwargs.pop("session_id", chat_id)
        await instance.client.query(prompt, session_id=session_id)
        async for msg in instance.client.receive_response():
            yield msg
        # Instance stays sticky-bound — NOT returned to pool

    async def _maybe_upgrade_tier(
        self,
        chat_id: str,
        instance: PooledInstance[CCClient],
        tier: str | None,
    ) -> None:
        """Escalate *instance* to slow_model iff ``tier == 'slow'`` and we
        haven't already upgraded this sticky session.

        Logs + swallows ``set_model`` failures: the customer still gets a
        reply on the pre-upgrade model, which is worse quality but not
        broken. ``slow_model=None`` deployments (single-model config) are
        no-op, preserving the back-compat contract of B-plan.
        """
        if tier != "slow":
            return
        if chat_id in self._upgraded_sticky:
            return
        slow_model = self._config.slow_model  # type: ignore[attr-defined]
        if not slow_model:
            return
        try:
            await instance.client.set_model(slow_model)
        except Exception:
            log.exception(
                "sticky tier upgrade failed for conv=%s — staying on current model",
                chat_id,
            )
            return
        self._upgraded_sticky.add(chat_id)
        log.info("sticky tier upgraded to slow: conv=%s model=%s",
                 chat_id, slow_model)

    async def end_session(self, chat_id: str) -> None:
        """End a stateful session, release the instance back to pool."""
        self._upgraded_sticky.discard(chat_id)
        await self.release_sticky(chat_id)

    async def release_sticky(self, key: str) -> None:
        """Override parent ``release_sticky`` to clear the tier upgrade
        stamp — whether released explicitly via :meth:`end_session` or
        reaped by the sticky-idle timer, a subsequent bind on the same
        key must start fresh on fast_model."""
        self._upgraded_sticky.discard(key)
        await super().release_sticky(key)

    # ------------------------------------------------------------------
    # Role-aware acquire (T3B.5 — spec §2.5 + CON-06)
    # ------------------------------------------------------------------

    def acquire(
        self,
        timeout: float | None = None,
        *,
        role: str = "customer",
        tenant_id: str | None = None,
    ) -> Any:
        """Acquire a pooled CC client for *role*.

        The ``role="customer"`` path (default, no kwargs) preserves the
        M1 ``AsyncPool.acquire()`` semantics byte-for-byte — all existing
        M1 call sites (``CCPool.query``, ``CCPool.session_query``, and the
        ``async with pool.acquire() as instance`` pattern in channels /
        operator / customer code) go through the parent implementation
        unchanged. Adding a role kwarg here **must not** reduce the
        expressivity of the base signature.

        ``role="dream"`` routes through the module-level :data:`_dream_pool`
        (spec §2.5: *"Dream 使用独立小池 dream_pool（部署级 size=1）…不抢
        普通 agent 的 pool 名额"*). The dream pool is lazily initialised on
        first acquire so tests that never touch dream do not pay the cost
        of a second warmup.

        Future roles raise :class:`NotImplementedError` with a pointer to
        this function so the extension path is obvious.

        Args:
            timeout: Acquisition timeout. Mirrors
                :meth:`AsyncPool.acquire` for the customer path. For the
                dream path the dream pool's own ``checkout_timeout`` is
                used when ``None`` (spec §2.5 size=1 — queueing is
                expected and intentional).
            role: ``"customer"`` (default) or ``"dream"``.
            tenant_id: Only consulted when ``role="dream"``; selects which
                tenant's ``souls/dream_soul.md`` to inject as the system
                prompt. When ``None`` the bootstrap fallback is used (see
                :func:`_load_dream_soul`).

        Returns:
            An async-context-manager yielding a
            :class:`socialware.pool.PooledInstance[CCClient]`. Always usable
            as ``async with pool.acquire(...) as inst``. For the dream
            role, the returned instance is tagged with
            ``_pool_role='dream'`` so :meth:`release` (and future
            leak-detection tooling) can route it back to the correct
            pool unambiguously.
        """
        if role == "customer":
            # Preserve M1 hot path — do not introduce bookkeeping overhead
            # here. The parent implementation is the single source of
            # truth for the customer acquire/release contract.
            return super().acquire(timeout=timeout)

        if role == "dream":
            return _acquire_dream(tenant_id=tenant_id, timeout=timeout)

        if role in ("lead", "translate", "triage"):
            # Lazy per-(role, tenant_id) sub-pools. Stateful roles (lead,
            # translate) size=2; stateless triage size=1. See spec §2.3.
            return self._acquire_role_pool(role, tenant_id, timeout)

        raise NotImplementedError(
            f"cc_pool.acquire: role={role!r} is not implemented. "
            f"Known roles: {sorted(_KNOWN_ROLES)}."
        )

    # ------------------------------------------------------------------
    # Per-(role, tenant_id) sub-pool machinery (T2 — spec §2.3)
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def _acquire_role_pool(
        self, role: str, tenant_id: str | None, timeout: float | None,
    ) -> AsyncIterator[PooledInstance[CCClient]]:
        """Dispatch to a lazy ``(role, tenant_id)`` sub-pool.

        Creates the sub-pool on first call, reuses it on subsequent calls,
        and kicks off the background reaper on the very first call. The
        sub-pool itself is an ordinary :class:`AsyncPool`; we only hold
        the (role, tenant) → sub-pool map + a last-used timestamp for the
        reaper.
        """
        # Fix 3 (defense-in-depth): refuse to spin up new sub-pools after shutdown.
        if self._closed:
            raise RuntimeError("CCPool is shut down")

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
            # Fix 1: update last-used INSIDE the lock so the reaper can never
            # observe a stale timestamp while this acquirer holds the lock.
            self._role_pool_last_used[key] = time.monotonic()

        async with sub_pool.acquire(timeout=timeout) as inst:
            inst._pool_role = role  # type: ignore[attr-defined]
            inst._pool_tenant_id = tenant_id  # type: ignore[attr-defined]
            try:
                yield inst
            finally:
                # Fix 2: refresh last-used on release so a long-running acquire
                # does not leave the timestamp frozen at checkout time, which
                # would allow the reaper to close an in-flight sub-pool.
                self._role_pool_last_used[key] = time.monotonic()

    async def _create_role_pool(
        self, role: str, tenant_id: str | None,
    ) -> AsyncPool[CCClient]:
        """Construct + start a fresh sub-pool for ``(role, tenant_id)``.

        Clones the base pool config with role-specific sizing so the
        sub-pool picks up the same CLI binary / model / permission_mode
        as the customer pool. The factory injects the per-(role, tenant)
        soul via :func:`create_cc_client`.
        """
        size = _ROLE_POOL_SIZES[role]
        # ``self._config`` is the authoritative PoolConfig (including any
        # tier knobs supplied programmatically). It carries the unmutated
        # ``model`` field; tier resolution picks the right one for *role*.
        base = self._config
        # warmup_count=1 so the first acquire against a freshly-opened
        # sub-pool doesn't cold-spawn the subprocess inline — critical for
        # triage, whose call site has a 2 s ``_TRIAGE_AGENT_TIMEOUT`` that
        # was silently timing out on every first-use. Lead/translate get
        # the same treatment for consistency (small pool, max_size==size
        # caps the cost at one extra subprocess per role-tenant pair). The
        # lazy-open path still exists (CCPool.start only pre-opens the
        # known ``warmup_tenant_id`` triage sub-pool); this change just
        # makes that lazy open useful instead of just reserving a slot.
        sub_cfg = replace(
            base, min_size=0, max_size=size, warmup_count=1,
            model=_resolve_model_for_role(base, role),
        )

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
        """Background loop that reaps idle role sub-pools.

        Polls at roughly 1/10th the idle window (capped at 60 s, min 10 ms
        so monkeypatch-shrunk windows in tests still tick in reasonable
        time). Cancellation during :meth:`shutdown` is expected.
        """
        try:
            while True:
                await asyncio.sleep(min(60.0, max(_REAP_IDLE_SEC / 10, 0.01)))
                await self._reap_idle_role_pools_once()
        except asyncio.CancelledError:
            pass

    async def _reap_idle_role_pools_once(self) -> None:
        """One sweep: close sub-pools idle longer than ``_REAP_IDLE_SEC``.

        Public-ish (prefixed with underscore but directly called by the
        test suite) so reaper behaviour can be exercised deterministically.
        References ``_REAP_IDLE_SEC`` via the module namespace so tests can
        ``monkeypatch.setattr`` the threshold without restarting the loop.
        """
        now = time.monotonic()
        # Fix 1 (continued): Candidate scan is outside the lock (cheap read),
        # but the actual pop + shutdown decision is retaken INSIDE the lock so
        # a concurrent _acquire_role_pool that just refreshed the timestamp
        # (also under the lock) cannot be evicted mid-checkout.
        candidate_keys: list[tuple[str, str | None]] = [
            key for key, last in list(self._role_pool_last_used.items())
            if now - last > _REAP_IDLE_SEC
        ]
        for key in candidate_keys:
            async with self._role_pool_lock:
                # Re-check the timestamp now that we hold the lock; the
                # acquirer may have refreshed it while we were waiting.
                last = self._role_pool_last_used.get(key)
                if last is None or now - last <= _REAP_IDLE_SEC:
                    continue
                sub_pool = self._role_pools.pop(key, None)
                self._role_pool_last_used.pop(key, None)
            if sub_pool is not None:
                try:
                    await sub_pool.shutdown()
                    log.info("cc_pool: reaped idle sub-pool role=%s tenant=%s",
                             key[0], key[1])
                except Exception:
                    log.exception("cc_pool: reaper shutdown failed for %s", key)

    async def shutdown(self) -> None:
        """Cancel the reaper, close all role sub-pools, then shut down self.

        Order matters: the reaper must stop BEFORE we iterate ``_role_pools``
        so we don't race its own shutdown of a sub-pool. After sub-pools are
        closed we delegate to ``AsyncPool.shutdown`` for the main pool.
        """
        # Fix 3: mark as closed before tearing down so _acquire_role_pool
        # refuses to recreate sub-pools after shutdown starts.
        self._closed = True
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


# ---------------------------------------------------------------------------
# Status snapshot (for out-of-process observability, e.g. `make pool-status`)
# ---------------------------------------------------------------------------

STATUS_FILE = Path.cwd() / ".autoservice" / "cc_pool_status.json"
STATUS_WRITE_INTERVAL = 5.0


def _write_status_snapshot(pool: "CCPool") -> None:
    status = pool.status()
    status["updated_at"] = datetime.now().isoformat(timespec="seconds")
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")


def _clear_status_snapshot() -> None:
    if STATUS_FILE.exists():
        try:
            STATUS_FILE.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Module-level singleton — customer pool
# ---------------------------------------------------------------------------

_pool: CCPool | None = None
_pool_lock = asyncio.Lock()
_status_writer_task: asyncio.Task | None = None


async def _status_writer_loop(pool: "CCPool", interval: float) -> None:
    try:
        while True:
            try:
                _write_status_snapshot(pool)
            except Exception as exc:
                log.debug("status snapshot write failed: %s", exc)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass


async def get_pool(config: PoolConfig | None = None) -> CCPool:
    """Get or create the global pool singleton."""
    global _pool, _status_writer_task
    if _pool is not None and _pool._started:
        return _pool

    async with _pool_lock:
        if _pool is not None and _pool._started:
            return _pool
        if config is None:
            config = load_pool_config()
        _pool = CCPool(config)
        await _pool.start()
        if _status_writer_task is None or _status_writer_task.done():
            _write_status_snapshot(_pool)
            _status_writer_task = asyncio.create_task(
                _status_writer_loop(_pool, STATUS_WRITE_INTERVAL),
                name="cc-pool-status-writer",
            )
        return _pool


# ---------------------------------------------------------------------------
# Dream pool (T3B.5 — spec §2.5 + CON-06)
# ---------------------------------------------------------------------------
#
# Design notes (for the reviewer):
#
# 1. *Independence* — the dream pool is a separate :class:`AsyncPool`
#    instance, **not** a partition of the customer pool. A dream run that
#    blocks on LLM network I/O can never consume a customer checkout slot.
#    Spec §2.5: "不抢普通 agent 的 pool 名额".
#
# 2. *Size = 1 hard cap* — a cloned :class:`PoolConfig` is used so overriding
#    ``min_size`` / ``max_size`` / ``warmup_count`` to 1 does not mutate the
#    customer pool's config. Multi-tenant idle/scheduled triggers serialise
#    through this single slot (spec §2.5: *"多租户触发时排队"*). The
#    customer pool's ``max_size`` is left untouched.
#
# 3. *Role tagging on checkout* — every :class:`PooledInstance` returned
#    from the dream path has ``_pool_role='dream'`` stamped on it (dynamic
#    attribute on a dataclass is fine — :class:`PooledInstance` does not
#    use ``__slots__``). The ``async with`` wrapper produced by the base
#    ``AsyncPool.acquire()`` routes release back through the same pool that
#    checked out the instance, so cross-contamination is not possible via
#    the public API. The tag is kept as defence-in-depth for logging / leak
#    detection.
#
# 4. *Shutdown symmetry* — :func:`shutdown_pool` tears both down.


def _resolve_dream_tenant_root(tenant_id: str | None) -> Path | None:
    """Resolve a tenant's on-disk root for dream-soul lookup.

    Mirrors the resolution order of
    :func:`autoservice.dream_agent._resolve_tenant_root` — sandbox first
    (master layout), plugins second (fork layout) — but anchors both
    candidates at :func:`pathlib.Path.cwd` rather than the module-level
    ``PROJECT_ROOT``. The cwd anchor matches the existing customer-role
    :func:`_load_soul` in this module (see above), keeps the two code
    paths consistent, and lets tests that ``monkeypatch.chdir`` into a
    tmp tree exercise the lookup without mutating the real repo.

    Design note (reviewer concern #3): the spec wants the dream role to
    use the same path convention as customer-role soul injection. Both
    now use cwd-based lookup under ``.autoservice/sandbox/<tid>/souls/``
    first and ``plugins/<tid>/souls/`` second. The
    :func:`dream_agent._resolve_tenant_root` helper is intended for the
    *tool layer* (``kb_search``, ``list_souls``) that runs inside a
    ``run_dream`` loop with an explicit ``sandbox_root`` override — the
    pool layer has no such override seam, so anchoring at cwd is the
    correct choice here.
    """
    if not tenant_id:
        return None
    # Same injection guard as :func:`_load_soul` — reject path-escape
    # attempts before touching the filesystem.
    if "/" in tenant_id or "\\" in tenant_id or ".." in tenant_id:
        log.warning("Rejecting suspicious tenant_id for dream soul: %r", tenant_id)
        return None

    cwd = Path.cwd()
    sandbox_candidate = cwd / ".autoservice" / "sandbox" / tenant_id
    if sandbox_candidate.exists():
        return sandbox_candidate
    plugin_candidate = cwd / "plugins" / tenant_id
    if plugin_candidate.exists():
        return plugin_candidate
    return None


def _load_dream_soul(tenant_id: str | None) -> str:
    """Return the dream soul for *tenant_id*, falling back to the constant.

    Resolution order (mirrors :func:`dream_agent._load_dream_soul` so the
    pool-injected prompt matches what the agent-loop-layer computes):

      1. ``<sandbox>/<tenant_id>/souls/dream_soul.md`` — master-side.
      2. ``plugins/<tenant_id>/souls/dream_soul.md`` — fork-side.
      3. :data:`autoservice.soul_generator._FALLBACK_DREAM_SOUL` — always
         present (inlined constant; never raises).

    The fallback is the same well-formed prompt :mod:`dream_agent` uses —
    keeping the two paths in sync means an admin wizard that regenerates
    the tenant's dream soul will see the change on the next dream checkout
    (pool warm instances reload on recycle; see below).
    """
    # Deferred import — :mod:`soul_generator` is a heavier dependency.
    from autoservice.soul_generator import _FALLBACK_DREAM_SOUL

    tenant_root = _resolve_dream_tenant_root(tenant_id)
    if tenant_root is not None:
        soul_path = tenant_root / "souls" / "dream_soul.md"
        try:
            if soul_path.is_file():
                return soul_path.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning(
                "Dream soul read failed (%s) — using fallback for tenant %s",
                exc, tenant_id,
            )
    return _FALLBACK_DREAM_SOUL


def _dream_pool_config(base: PoolConfig) -> PoolConfig:
    """Clone *base* with dream-specific caps (size=1 per spec §2.5).

    Keeps ``cli_path`` / ``cwd`` / ``permission_mode`` aligned with the
    customer pool so the dream pool picks up the same local CLI binary
    and proxy config. Sizing collapses to 1, and ``model`` is resolved
    via :func:`_resolve_model_for_role` so the dream pool can use a
    distinct model (typically opus for the agent loop) without affecting
    customer/lead/triage.
    """
    return replace(
        base,
        min_size=1,
        max_size=1,
        warmup_count=1,
        # ``max_sticky_bindings=1`` keeps the size=1 invariant under any
        # future sticky-aware dream use (currently dream does not use
        # sticky sessions; this is defence-in-depth).
        max_sticky_bindings=1,
        model=_resolve_model_for_role(base, "dream"),
    )


_dream_pool: AsyncPool[CCClient] | None = None
_dream_pool_lock = asyncio.Lock()


# Sentinel for "attribute never set". ``None`` is a legitimate tenant_id
# value (meaning "use fallback"), so we need a distinct marker.
_UNSET: Any = object()


async def _get_dream_pool() -> AsyncPool[CCClient]:
    """Lazily build the module-level dream pool.

    Uses a double-checked lock so concurrent first-callers do not race
    the warmup. Once started the pool is reused indefinitely until
    :func:`shutdown_pool` tears it down.
    """
    global _dream_pool
    if _dream_pool is not None and _dream_pool._started:
        return _dream_pool
    async with _dream_pool_lock:
        if _dream_pool is not None and _dream_pool._started:
            return _dream_pool
        dream_cfg = _dream_pool_config(load_pool_config())

        async def _factory() -> CCClient:
            # The dream pool warms up BEFORE a tenant_id is known — we
            # inject the fallback soul at warmup so the warmed instance
            # always has a valid system prompt. Per-tenant souls are
            # swapped in at acquire time by recycling the instance when
            # the tenant_id changes (see :func:`_acquire_dream`).
            return await create_cc_client(
                dream_cfg, system_prompt=_load_dream_soul(None),
            )

        pool = AsyncPool[CCClient](
            config=dream_cfg,
            factory=_factory,
            instance_prefix="cc-dream",
            logger=log,
        )
        await pool.start()
        _dream_pool = pool
        return _dream_pool


@asynccontextmanager
async def _acquire_dream(
    *, tenant_id: str | None, timeout: float | None
) -> AsyncIterator[PooledInstance[CCClient]]:
    """Async context manager yielding a dream-role pooled instance.

    Per-tenant soul injection strategy: the dream pool holds at most one
    warm instance, so for the first acquire after a fresh start or after
    a tenant switch we recycle the warmed-with-fallback instance and
    create a new one carrying the requested tenant's soul. This avoids
    the alternative — threading per-call system prompts through the base
    :class:`AsyncPool`, which would break the "prompt-is-set-at-client-
    construction" invariant that :class:`CCClient` relies on.

    The recycle only happens when the tenant actually changed, so repeat
    acquires for the same tenant are zero-cost hot-path lookups.
    """
    pool = await _get_dream_pool()

    instance = await pool.checkout(timeout=timeout)
    try:
        instance = await _recycle_instance_for_tenant(
            pool, instance,
            role="dream",
            tenant_id=tenant_id,
        )
        # Tag the instance so release / leak-detection can identify it.
        instance._pool_role = "dream"  # type: ignore[attr-defined]
        yield instance
    finally:
        await pool.checkin(instance)


async def _make_tenant_instance(
    pool: AsyncPool[CCClient],
    *,
    role: str,
    tenant_id: str | None,
) -> PooledInstance[CCClient]:
    """Build + track a fresh ``PooledInstance[CCClient]`` for (role, tenant_id).

    Mirrors :meth:`AsyncPool._create_instance` but bypasses the stored
    factory so we can inject the correct per-(role, tenant) soul. The
    resulting instance IS tracked by the pool so status/health reporting
    still works.

    - ``role == "dream"`` uses the legacy :func:`_load_dream_soul` path so
      the fallback-on-missing-file behaviour is preserved byte-for-byte.
    - Any other role (``"customer"`` today, more later) delegates soul
      resolution to :func:`create_cc_client` via the ``role`` + ``tenant_id``
      kwargs — same plumbing the per-(role, tenant) sub-pools already use.
    """
    cfg = pool._config  # noqa: SLF001
    if role == "dream":
        client = await create_cc_client(
            cfg, system_prompt=_load_dream_soul(tenant_id),
        )
        # T5S.14: the legacy dream-pool factory bypasses the ``role=``
        # kwarg on create_cc_client (it supplies the system_prompt
        # directly), so the dream-role flag must be stamped here too.
        client._dream_role = True  # type: ignore[attr-defined]
    else:
        # customer + any future role: let create_cc_client resolve soul
        # via role + tenant_id.
        #
        # KB tool eligibility: customer + lead both need ``kb_search``
        # since lead qualifies against product / price / package details
        # that live in tenant KB. triage / translate / direct remain
        # tool-free (they don't touch tenant-specific content).
        client = await create_cc_client(
            cfg,
            role=role,
            tenant_id=tenant_id,
            enable_kb_tool=(
                role in ("customer", "lead") and tenant_id is not None
            ),
        )
    pool._instance_counter += 1  # noqa: SLF001
    instance_id = (
        f"{pool._instance_prefix}-{pool._instance_counter:03d}"  # noqa: SLF001
    )
    instance = PooledInstance(client=client, id=instance_id)
    pool._track(instance)  # noqa: SLF001
    log.debug(
        "pool: created instance %s for role=%s tenant=%r",
        instance_id, role, tenant_id,
    )
    return instance


async def _recycle_instance_for_tenant(
    pool: AsyncPool[CCClient],
    instance: PooledInstance[CCClient],
    *,
    role: str,
    tenant_id: str | None,
) -> PooledInstance[CCClient]:
    """Ensure *instance* has the right soul for (role, tenant_id); rebuild if not.

    Reads the stamped ``_pool_tenant_id`` sentinel. If it matches the
    requested ``tenant_id`` (including both being ``None``), returns the
    instance unchanged. Otherwise destroys and rebuilds via
    :func:`_make_tenant_instance`, stamps the new instance, and returns
    it. Rebuild failures propagate — callers decide the degrade path.
    """
    existing = getattr(instance, "_pool_tenant_id", _UNSET)
    if existing is not _UNSET and existing == tenant_id:
        return instance

    log.info(
        "pool recycle: role=%s instance=%s tenant %r -> %r",
        role, instance.id,
        existing if existing is not _UNSET else "<unset>",
        tenant_id,
    )
    await pool._destroy_instance(instance)  # noqa: SLF001
    new_instance = await _make_tenant_instance(
        pool, role=role, tenant_id=tenant_id,
    )
    new_instance._pool_tenant_id = tenant_id  # type: ignore[attr-defined]
    return new_instance


async def shutdown_pool() -> None:
    """Shutdown both the global customer pool and the dream pool.

    Order matters only for log readability — customer pool first (it's the
    bigger one), dream pool second. A failure in either does not prevent
    the other from shutting down (see the try-finally chain).
    """
    global _pool, _dream_pool, _status_writer_task
    if _status_writer_task is not None and not _status_writer_task.done():
        _status_writer_task.cancel()
        try:
            await _status_writer_task
        except (asyncio.CancelledError, Exception):
            pass
    _status_writer_task = None
    try:
        if _pool is not None:
            await _pool.shutdown()
    finally:
        _pool = None
        try:
            if _dream_pool is not None:
                await _dream_pool.shutdown()
        finally:
            _dream_pool = None
    _clear_status_snapshot()
