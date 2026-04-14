"""
Generic async object pool framework.

Pre-creates client instances so they're warm and ready.
Checkout an instance, use it, return it.

Usage:
    from socialware.pool import AsyncPool, PoolableClient, PoolConfig

    class MyClient:
        async def connect(self) -> None: ...
        async def disconnect(self) -> None: ...
        def is_healthy(self) -> bool: ...

    pool = AsyncPool(
        config=PoolConfig(min_size=2, max_size=8),
        factory=create_my_client,
        instance_prefix="my",
    )
    await pool.start()

    async with pool.acquire() as instance:
        await instance.client.do_work()

    await pool.shutdown()
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Generic,
    Protocol,
    TypeVar,
    runtime_checkable,
)

log = logging.getLogger("socialware.pool")


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class PoolableClient(Protocol):
    """Interface that pooled clients must satisfy."""

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    def is_healthy(self) -> bool: ...


T = TypeVar("T", bound=PoolableClient)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class PoolConfig:
    """Generic pool configuration.

    Subclass to add domain-specific fields (e.g. model, cwd).
    """
    min_size: int = 1
    max_size: int = 4
    warmup_count: int = 1
    max_queries_per_instance: int = 50
    max_lifetime_seconds: float = 3600.0
    health_check_interval: float = 30.0
    checkout_timeout: float = 30.0
    # Sticky session support
    sticky_idle_timeout: float = 600.0    # seconds idle before auto-unbind
    max_sticky_bindings: int = 0          # 0 = no limit (capped by max_size)


# ---------------------------------------------------------------------------
# Pooled Instance
# ---------------------------------------------------------------------------

@dataclass
class PooledInstance(Generic[T]):
    """Wraps a client with pool metadata."""
    client: T
    id: str
    created_at: float = field(default_factory=time.monotonic)
    query_count: int = 0
    last_used_at: float = field(default_factory=time.monotonic)

    def needs_recycling(self, config: PoolConfig) -> bool:
        """Check if instance should be recycled based on age or query count."""
        if self.query_count >= config.max_queries_per_instance:
            return True
        age = time.monotonic() - self.created_at
        if age >= config.max_lifetime_seconds:
            return True
        return False

    @property
    def is_healthy(self) -> bool:
        """Delegate health check to the client."""
        try:
            return self.client.is_healthy()
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Sticky Binding
# ---------------------------------------------------------------------------

@dataclass
class StickyBinding(Generic[T]):
    """Tracks a pool instance bound to a sticky key.

    Sticky bindings keep an instance reserved for a specific key (e.g. chat_id)
    across multiple requests, enabling stateful multi-turn conversations.
    """
    key: str
    instance: PooledInstance[T]
    bound_at: float = field(default_factory=time.monotonic)
    last_accessed_at: float = field(default_factory=time.monotonic)
    access_count: int = 0


# ---------------------------------------------------------------------------
# AsyncPool
# ---------------------------------------------------------------------------

class AsyncPool(Generic[T]):
    """Generic pool of pre-created client instances.

    Args:
        config: Pool configuration.
        factory: Async callable that creates and connects a new client.
        instance_prefix: Prefix for instance IDs (e.g. "cc", "api").
        logger: Optional logger override (defaults to "socialware.pool").
    """

    def __init__(
        self,
        config: PoolConfig,
        factory: Callable[[], Awaitable[T]],
        instance_prefix: str = "inst",
        logger: logging.Logger | None = None,
        on_sticky_release: Callable[[str], Awaitable[None]] | None = None,
    ):
        self._config = config
        self._factory = factory
        self._instance_prefix = instance_prefix
        self._log = logger or log
        self._on_sticky_release = on_sticky_release
        self._available: asyncio.Queue[PooledInstance[T]] = asyncio.Queue()
        self._all_instances: dict[str, PooledInstance[T]] = {}
        self._lock = asyncio.Lock()
        self._started = False
        self._shutdown_flag = False
        self._health_task: asyncio.Task | None = None
        self._instance_counter = 0
        # Sticky session support
        self._sticky_bindings: dict[str, StickyBinding[T]] = {}
        self._sticky_lock = asyncio.Lock()

    @property
    def size(self) -> int:
        """Total number of tracked instances (checked out + available)."""
        return len(self._all_instances)

    def _track(self, instance: PooledInstance[T]) -> None:
        self._all_instances[instance.id] = instance

    def _untrack(self, instance: PooledInstance[T]) -> None:
        self._all_instances.pop(instance.id, None)

    @property
    def available_count(self) -> int:
        """Number of instances available for checkout."""
        return self._available.qsize()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the pool: create warmup_count instances, start health monitor."""
        if self._started:
            return
        self._started = True
        self._shutdown_flag = False

        self._log.info(
            "Starting pool (min=%d, max=%d, warmup=%d)",
            self._config.min_size, self._config.max_size, self._config.warmup_count,
        )

        for i in range(self._config.warmup_count):
            try:
                instance = await self._create_instance()
                await self._available.put(instance)
                self._log.info(
                    "Warmed instance %s (%d/%d)",
                    instance.id, i + 1, self._config.warmup_count,
                )
            except Exception as e:
                self._log.error("Failed to create warm instance %d: %s", i + 1, e)

        self._health_task = asyncio.create_task(
            self._health_check_loop(), name=f"{self._instance_prefix}-pool-health"
        )
        self._log.info("Pool started with %d instance(s)", self.size)

    async def shutdown(self) -> None:
        """Graceful shutdown: stop health monitor, disconnect all instances."""
        if not self._started:
            return
        self._log.info("Shutting down pool (%d instances, %d sticky)...",
                       self.size, self.sticky_count)
        self._shutdown_flag = True

        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
            self._health_task = None

        # Clear sticky bindings (instances will be destroyed below via _all_instances)
        self._sticky_bindings.clear()

        while not self._available.empty():
            try:
                self._available.get_nowait()
            except asyncio.QueueEmpty:
                break

        for instance in list(self._all_instances.values()):
            await self._destroy_instance(instance)

        self._started = False
        self._log.info("Pool shut down.")

    # ------------------------------------------------------------------
    # Checkout / Checkin
    # ------------------------------------------------------------------

    async def checkout(self, timeout: float | None = None) -> PooledInstance[T]:
        """Get a warm instance from the pool.

        If pool is exhausted and under max_size, creates a new one on demand.
        If at max_size, waits up to timeout seconds for one to be returned.

        Raises:
            TimeoutError: No instance available within timeout.
            RuntimeError: Pool not started or shutting down.
        """
        if not self._started or self._shutdown_flag:
            raise RuntimeError("Pool is not running")

        timeout = timeout if timeout is not None else self._config.checkout_timeout

        # Try to get an available instance (non-blocking)
        try:
            instance = self._available.get_nowait()
            if instance.is_healthy and not instance.needs_recycling(self._config):
                self._log.debug("Checked out instance %s (from queue)", instance.id)
                return instance
            await self._destroy_instance(instance)
        except asyncio.QueueEmpty:
            pass

        # Try to create a new instance if under max
        async with self._lock:
            if self.size < self._config.max_size:
                instance = await self._create_instance()
                self._log.debug("Checked out instance %s (on-demand)", instance.id)
                return instance

        # At max_size — wait for one to be returned
        self._log.debug(
            "Pool exhausted (%d/%d), waiting...", self.size, self._config.max_size,
        )
        try:
            instance = await asyncio.wait_for(self._available.get(), timeout=timeout)
            if instance.is_healthy and not instance.needs_recycling(self._config):
                self._log.debug("Checked out instance %s (after wait)", instance.id)
                return instance
            await self._destroy_instance(instance)
            async with self._lock:
                return await self._create_instance()
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"No instance available within {timeout}s "
                f"(pool size: {self.size}/{self._config.max_size})"
            )

    async def checkin(self, instance: PooledInstance[T]) -> None:
        """Return an instance to the pool."""
        if self._shutdown_flag:
            await self._destroy_instance(instance)
            return

        instance.last_used_at = time.monotonic()

        if not instance.is_healthy or instance.needs_recycling(self._config):
            self._log.info(
                "Recycling instance %s (queries=%d, healthy=%s)",
                instance.id, instance.query_count, instance.is_healthy,
            )
            await self._destroy_instance(instance)
            asyncio.create_task(
                self._ensure_min_size(),
                name=f"{self._instance_prefix}-pool-refill",
            )
            return

        await self._available.put(instance)
        self._log.debug("Checked in instance %s", instance.id)

    @asynccontextmanager
    async def acquire(self, timeout: float | None = None) -> AsyncIterator[PooledInstance[T]]:
        """Async context manager: checkout on enter, checkin on exit."""
        instance = await self.checkout(timeout=timeout)
        try:
            yield instance
        finally:
            await self.checkin(instance)

    # ------------------------------------------------------------------
    # Sticky Sessions
    # ------------------------------------------------------------------

    async def acquire_sticky(
        self, key: str, timeout: float | None = None,
    ) -> PooledInstance[T]:
        """Acquire an instance bound to a sticky key.

        First call for a key checks out from pool and binds it.
        Subsequent calls return the same instance.
        If the bound instance is unhealthy, it is replaced transparently.

        Args:
            key: Sticky binding key (e.g. chat_id).
            timeout: Override checkout timeout.

        Returns:
            The bound PooledInstance.

        Raises:
            RuntimeError: Pool not running, or max_sticky_bindings exceeded.
            TimeoutError: No instance available within timeout.
        """
        if not self._started or self._shutdown_flag:
            raise RuntimeError("Pool is not running")

        async with self._sticky_lock:
            binding = self._sticky_bindings.get(key)
            if binding is not None:
                if binding.instance.is_healthy:
                    binding.last_accessed_at = time.monotonic()
                    binding.access_count += 1
                    self._log.debug(
                        "Sticky hit: key=%s instance=%s (access #%d)",
                        key, binding.instance.id, binding.access_count,
                    )
                    return binding.instance
                # Unhealthy — destroy and fall through to create new
                self._log.info(
                    "Sticky instance %s unhealthy for key=%s, replacing",
                    binding.instance.id, key,
                )
                await self._destroy_instance(binding.instance)
                del self._sticky_bindings[key]

            # Check max_sticky_bindings limit
            max_sticky = self._config.max_sticky_bindings
            if max_sticky > 0 and len(self._sticky_bindings) >= max_sticky:
                raise RuntimeError(
                    f"Max sticky bindings reached ({max_sticky}). "
                    f"Release existing sessions or increase max_sticky_bindings."
                )

        # Checkout a new instance from the pool (outside sticky lock)
        instance = await self.checkout(timeout=timeout)

        async with self._sticky_lock:
            self._sticky_bindings[key] = StickyBinding(
                key=key, instance=instance,
            )
            self._log.info(
                "Sticky bind: key=%s -> instance=%s (total sticky: %d)",
                key, instance.id, len(self._sticky_bindings),
            )
        return instance

    async def release_sticky(self, key: str) -> None:
        """Release a sticky binding, return instance to the pool.

        No-op if key is not bound.
        """
        async with self._sticky_lock:
            binding = self._sticky_bindings.pop(key, None)

        if binding is None:
            return

        self._log.info(
            "Sticky release: key=%s instance=%s (accesses=%d)",
            key, binding.instance.id, binding.access_count,
        )
        await self.checkin(binding.instance)

        if self._on_sticky_release:
            try:
                await self._on_sticky_release(key)
            except Exception as e:
                self._log.warning("on_sticky_release callback failed for key=%s: %s", key, e)

    @property
    def sticky_count(self) -> int:
        """Number of active sticky bindings."""
        return len(self._sticky_bindings)

    async def _cleanup_sticky(self) -> None:
        """Clean up expired or unhealthy sticky bindings.

        Called periodically from _health_check_loop.
        """
        idle_timeout = self._config.sticky_idle_timeout
        now = time.monotonic()
        expired: list[str] = []

        async with self._sticky_lock:
            for key, binding in self._sticky_bindings.items():
                idle_secs = now - binding.last_accessed_at
                if idle_secs >= idle_timeout:
                    expired.append(key)
                    self._log.info(
                        "Sticky expired: key=%s instance=%s (idle %.0fs)",
                        key, binding.instance.id, idle_secs,
                    )
                elif not binding.instance.is_healthy:
                    expired.append(key)
                    self._log.info(
                        "Sticky unhealthy: key=%s instance=%s",
                        key, binding.instance.id,
                    )

            removed_bindings = []
            for key in expired:
                binding = self._sticky_bindings.pop(key)
                removed_bindings.append(binding)

        # Destroy outside lock
        for binding in removed_bindings:
            await self._destroy_instance(binding.instance)

        # Notify listener of expired keys
        if self._on_sticky_release:
            for binding in removed_bindings:
                try:
                    await self._on_sticky_release(binding.key)
                except Exception as e:
                    self._log.warning("on_sticky_release callback failed for key=%s: %s",
                                      binding.key, e)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return pool status for monitoring."""
        now = time.monotonic()
        return {
            "started": self._started,
            "total": self.size,
            "available": self.available_count,
            "sticky": self.sticky_count,
            "checked_out": self.size - self.available_count - self.sticky_count,
            "max_size": self._config.max_size,
            "instances": [
                {
                    "id": inst.id,
                    "query_count": inst.query_count,
                    "age_seconds": round(now - inst.created_at, 1),
                    "healthy": inst.is_healthy,
                }
                for inst in self._all_instances.values()
            ],
            "sticky_bindings": [
                {
                    "key": b.key,
                    "instance_id": b.instance.id,
                    "access_count": b.access_count,
                    "idle_seconds": round(now - b.last_accessed_at, 1),
                    "bound_seconds": round(now - b.bound_at, 1),
                }
                for b in self._sticky_bindings.values()
            ],
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _create_instance(self) -> PooledInstance[T]:
        """Create a new client via factory and wrap in PooledInstance."""
        self._instance_counter += 1
        instance_id = f"{self._instance_prefix}-{self._instance_counter:03d}"

        client = await self._factory()
        instance = PooledInstance(client=client, id=instance_id)
        self._track(instance)
        self._log.debug("Created instance %s (total: %d)", instance_id, self.size)
        return instance

    async def _destroy_instance(self, instance: PooledInstance[T]) -> None:
        """Disconnect and remove an instance."""
        self._untrack(instance)
        try:
            await instance.client.disconnect()
        except Exception as e:
            self._log.warning("Error disconnecting instance %s: %s", instance.id, e)
        self._log.debug("Destroyed instance %s (total: %d)", instance.id, self.size)

    async def _ensure_min_size(self) -> None:
        """Create instances until min_size is met."""
        async with self._lock:
            while self.size < self._config.min_size and not self._shutdown_flag:
                try:
                    instance = await self._create_instance()
                    await self._available.put(instance)
                except Exception as e:
                    self._log.error("Failed to create replacement instance: %s", e)
                    break

    async def _health_check_loop(self) -> None:
        """Periodic health check: detect dead instances, maintain min_size."""
        while not self._shutdown_flag:
            try:
                await asyncio.sleep(self._config.health_check_interval)
            except asyncio.CancelledError:
                return

            if self._shutdown_flag:
                return

            checked: list[PooledInstance[T]] = []
            dead: list[PooledInstance[T]] = []

            while not self._available.empty():
                try:
                    inst = self._available.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if inst.is_healthy and not inst.needs_recycling(self._config):
                    checked.append(inst)
                else:
                    dead.append(inst)

            for inst in checked:
                await self._available.put(inst)

            for inst in dead:
                self._log.info("Health check: recycling instance %s", inst.id)
                await self._destroy_instance(inst)

            await self._ensure_min_size()

            # Clean up expired sticky bindings
            await self._cleanup_sticky()

            self._log.debug(
                "Health check: %d total, %d available, %d sticky, %d recycled",
                self.size, self.available_count, self.sticky_count, len(dead),
            )
