from __future__ import annotations

import hashlib
import time
from enum import Enum


class CanaryStage(str, Enum):
    DISABLED = "disabled"      # 0% — canary off
    STAGE_5 = "stage_5"        # 5%
    STAGE_25 = "stage_25"      # 25%
    STAGE_100 = "stage_100"    # 100% — fully rolled out


STAGE_PERCENTAGE: dict[CanaryStage, int] = {
    CanaryStage.DISABLED: 0,
    CanaryStage.STAGE_5: 5,
    CanaryStage.STAGE_25: 25,
    CanaryStage.STAGE_100: 100,
}

_STAGE_ORDER: list[CanaryStage] = [
    CanaryStage.DISABLED,
    CanaryStage.STAGE_5,
    CanaryStage.STAGE_25,
    CanaryStage.STAGE_100,
]


class CanaryRouter:
    """Gradual rollout router for Dream Engine proposals.

    Supports staged rollout: 5% -> 25% -> 100% with configurable
    observation windows between stages.
    """

    def __init__(self, observation_hours: int = 24) -> None:
        self._observation_hours = observation_hours
        self._current_stage = CanaryStage.DISABLED
        self._stage_started_at: float = time.time()
        self._history: list[dict] = []

    @property
    def current_stage(self) -> CanaryStage:
        return self._current_stage

    @property
    def percentage(self) -> int:
        return STAGE_PERCENTAGE[self._current_stage]

    def should_apply(self, conversation_id: str) -> bool:
        """Deterministic: hash(conv_id) % 100 < percentage -> apply proposal."""
        pct = self.percentage
        if pct == 0:
            return False
        if pct >= 100:
            return True
        bucket = int(hashlib.sha256(conversation_id.encode()).hexdigest(), 16) % 100
        return bucket < pct

    def can_advance(self) -> bool:
        """True if observation_hours elapsed since current stage started."""
        if self._current_stage == CanaryStage.STAGE_100:
            return False
        elapsed = time.time() - self._stage_started_at
        return elapsed >= self._observation_hours * 3600

    def advance(self, *, _now: float | None = None) -> CanaryStage:
        """Advance to next stage. Returns new stage.

        Raises ValueError if observation period not elapsed or already at max.
        """
        if self._current_stage == CanaryStage.STAGE_100:
            raise ValueError("Already at STAGE_100, cannot advance further")
        if not self.can_advance():
            raise ValueError(
                f"Observation period ({self._observation_hours}h) not elapsed"
            )
        idx = _STAGE_ORDER.index(self._current_stage)
        new_stage = _STAGE_ORDER[idx + 1]
        now = _now if _now is not None else time.time()
        self._history.append({
            "action": "advance",
            "from_stage": self._current_stage.value,
            "to_stage": new_stage.value,
            "timestamp": now,
        })
        self._current_stage = new_stage
        self._stage_started_at = now
        return new_stage

    def rollback(self, reason: str = "", *, _now: float | None = None) -> CanaryStage:
        """Roll back to DISABLED. Record reason."""
        now = _now if _now is not None else time.time()
        self._history.append({
            "action": "rollback",
            "from_stage": self._current_stage.value,
            "to_stage": CanaryStage.DISABLED.value,
            "reason": reason,
            "timestamp": now,
        })
        self._current_stage = CanaryStage.DISABLED
        self._stage_started_at = now
        return CanaryStage.DISABLED

    def status(self) -> dict:
        """Return full status: stage, percentage, started_at, can_advance, history."""
        return {
            "stage": self._current_stage.value,
            "percentage": self.percentage,
            "started_at": self._stage_started_at,
            "can_advance": self.can_advance(),
            "history": list(self._history),
        }

    @property
    def history(self) -> list[dict]:
        """List of stage transitions with timestamps and reasons."""
        return list(self._history)
