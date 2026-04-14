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
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any, AsyncIterator

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
from claude_agent_sdk.types import Message

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


# ---------------------------------------------------------------------------
# CC-specific configuration (extends generic PoolConfig)
# ---------------------------------------------------------------------------

@dataclass
class PoolConfig(_BasePoolConfig):
    """CC pool configuration with Claude-specific fields.

    Loadable from config.local.yaml or env vars.
    The pool uses the locally installed Claude CLI by default (found via PATH).
    Set cli_path to override with a specific binary location.
    """
    cwd: str | None = None
    permission_mode: str = "bypassPermissions"
    model: str | None = None
    cli_path: str | None = None


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
    _STR_FIELDS = {"cwd", "permission_mode", "model", "cli_path"}

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
# CC client factory
# ---------------------------------------------------------------------------

async def create_cc_client(
    config: PoolConfig,
    mcp_servers: dict | None = None,
    system_prompt: str | None = None,
) -> CCClient:
    """Factory: creates and connects a CCClient from pool config.

    Args:
        config: Pool configuration.
        mcp_servers: Optional MCP server configs to inject (e.g. channel tools).
                     Dict of name -> McpServerConfig (stdio, SSE, HTTP, or SDK type).
        system_prompt: Optional system prompt for the Claude Code session.
    """
    cwd = config.cwd or str(Path.cwd())
    cwd_path = Path(cwd).absolute()
    plugin_path = cwd_path / ".autoservice" / ".claude"

    env = {}
    for var in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
        val = os.environ.get(var)
        if val:
            env[var] = val

    options = ClaudeAgentOptions(
        cwd=cwd,
        setting_sources=None,
        plugins=[{"type": "local", "path": str(plugin_path)}]
        if plugin_path.exists() else None,
        env=env,
        permission_mode=config.permission_mode,
        model=config.model,
        cli_path=config.cli_path,
    )

    if mcp_servers:
        options.mcp_servers = mcp_servers
    if system_prompt:
        options.system_prompt = system_prompt

    sdk_client = ClaudeSDKClient(options)
    client = CCClient(sdk_client)
    await client.connect()
    return client


# ---------------------------------------------------------------------------
# CCPool — thin subclass with query() convenience
# ---------------------------------------------------------------------------

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
        super().__init__(
            config=cfg,
            factory=lambda: create_cc_client(cfg, mcp_servers=mcp_servers,
                                              system_prompt=system_prompt),
            instance_prefix="cc",
            logger=log,
            on_sticky_release=on_sticky_release,
        )

    async def query(self, prompt: str, **kwargs: Any) -> AsyncIterator[Message]:
        """Convenience: checkout, query, yield messages, checkin."""
        async with self.acquire() as instance:
            instance.query_count += 1
            session_id = kwargs.get("session_id", "default")
            await instance.client.query(prompt, session_id=session_id)
            async for msg in instance.client.receive_response():
                yield msg

    async def session_query(
        self, chat_id: str, prompt: str, **kwargs: Any,
    ) -> AsyncIterator[Message]:
        """Stateful multi-turn query: chat_id is sticky-bound to a CC instance.

        The same chat_id always gets the same Claude Code subprocess,
        preserving conversation context across multiple calls.
        Use end_session() to release the binding when the conversation ends.
        """
        instance = await self.acquire_sticky(chat_id)
        instance.query_count += 1
        session_id = kwargs.pop("session_id", chat_id)
        await instance.client.query(prompt, session_id=session_id)
        async for msg in instance.client.receive_response():
            yield msg
        # Instance stays sticky-bound — NOT returned to pool

    async def end_session(self, chat_id: str) -> None:
        """End a stateful session, release the instance back to pool."""
        await self.release_sticky(chat_id)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_pool: CCPool | None = None
_pool_lock = asyncio.Lock()


async def get_pool(config: PoolConfig | None = None) -> CCPool:
    """Get or create the global pool singleton."""
    global _pool
    if _pool is not None and _pool._started:
        return _pool

    async with _pool_lock:
        if _pool is not None and _pool._started:
            return _pool
        if config is None:
            config = load_pool_config()
        _pool = CCPool(config)
        await _pool.start()
        return _pool


async def shutdown_pool() -> None:
    """Shutdown the global pool."""
    global _pool
    if _pool is not None:
        await _pool.shutdown()
        _pool = None
