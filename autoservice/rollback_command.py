from __future__ import annotations

from datetime import datetime, timezone

from autoservice.canary import CanaryRouter, CanaryStage


class RollbackCommand:
    """Operator-invokable command to roll back canary deployment to DISABLED."""

    def __init__(self, canary_router: CanaryRouter) -> None:
        self._canary_router = canary_router

    async def execute(self, *, actor_id: str, reason: str = "") -> dict:
        """Execute rollback.

        Returns dict with previous_stage, current_stage, reason,
        rolled_back_by, and timestamp.
        """
        previous_stage = self._canary_router.current_stage
        self._canary_router.rollback(reason=reason)
        return {
            "success": True,
            "previous_stage": previous_stage.value,
            "current_stage": CanaryStage.DISABLED.value,
            "reason": reason,
            "rolled_back_by": actor_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def status(self) -> dict:
        """Return current canary status (delegates to canary_router.status())."""
        return self._canary_router.status()

    @property
    def is_rollback_needed(self) -> bool:
        """True if canary is not already DISABLED."""
        return self._canary_router.current_stage != CanaryStage.DISABLED
