from __future__ import annotations

import time

import pytest

from autoservice.canary import CanaryRouter, CanaryStage, STAGE_PERCENTAGE


class TestCanaryRouter:
    """Tests for CanaryRouter gradual rollout."""

    def test_import_and_instantiate_starts_disabled(self):
        router = CanaryRouter()
        assert router.current_stage == CanaryStage.DISABLED
        assert router.percentage == 0

    def test_should_apply_returns_false_when_disabled(self):
        router = CanaryRouter()
        for i in range(50):
            assert router.should_apply(f"conv_{i}") is False

    def test_advance_disabled_to_stage_5(self):
        router = CanaryRouter(observation_hours=0)
        new = router.advance()
        assert new == CanaryStage.STAGE_5
        assert router.current_stage == CanaryStage.STAGE_5
        assert router.percentage == 5

    def test_advance_stage_5_to_stage_25(self):
        router = CanaryRouter(observation_hours=0)
        router.advance()
        new = router.advance()
        assert new == CanaryStage.STAGE_25
        assert router.percentage == 25

    def test_advance_stage_25_to_stage_100(self):
        router = CanaryRouter(observation_hours=0)
        router.advance()
        router.advance()
        new = router.advance()
        assert new == CanaryStage.STAGE_100
        assert router.percentage == 100

    def test_advance_raises_when_observation_not_elapsed(self):
        router = CanaryRouter(observation_hours=24)
        with pytest.raises(ValueError, match="Observation period"):
            router.advance()

    def test_can_advance_false_before_observation(self):
        router = CanaryRouter(observation_hours=24)
        assert router.can_advance() is False

    def test_can_advance_true_after_observation(self):
        router = CanaryRouter(observation_hours=1)
        # Simulate time passing by backdating stage_started_at
        router._stage_started_at = time.time() - 3601
        assert router.can_advance() is True

    def test_should_apply_deterministic(self):
        router = CanaryRouter(observation_hours=0)
        router.advance()  # STAGE_5
        conv_id = "test-conversation-abc"
        result1 = router.should_apply(conv_id)
        result2 = router.should_apply(conv_id)
        assert result1 == result2

    def test_should_apply_respects_percentage(self):
        router = CanaryRouter(observation_hours=0)
        router.advance()  # STAGE_5 → 5%
        applied = sum(
            1 for i in range(1000) if router.should_apply(f"conv_{i}")
        )
        # With 5%, expect roughly 50 out of 1000. Allow wide margin.
        assert 10 < applied < 120, f"Expected ~50 applied, got {applied}"

    def test_rollback_returns_to_disabled(self):
        router = CanaryRouter(observation_hours=0)
        router.advance()  # STAGE_5
        router.advance()  # STAGE_25
        result = router.rollback(reason="error rate too high")
        assert result == CanaryStage.DISABLED
        assert router.current_stage == CanaryStage.DISABLED
        assert router.percentage == 0
        # Check reason recorded in history
        last = router.history[-1]
        assert last["action"] == "rollback"
        assert last["reason"] == "error rate too high"

    def test_status_returns_correct_structure(self):
        router = CanaryRouter(observation_hours=0)
        router.advance()
        s = router.status()
        assert s["stage"] == "stage_5"
        assert s["percentage"] == 5
        assert "started_at" in s
        assert "can_advance" in s
        assert "history" in s
        assert isinstance(s["history"], list)

    def test_history_tracks_all_transitions(self):
        router = CanaryRouter(observation_hours=0)
        router.advance()
        router.advance()
        router.rollback(reason="test")
        h = router.history
        assert len(h) == 3
        assert h[0]["action"] == "advance"
        assert h[0]["from_stage"] == "disabled"
        assert h[0]["to_stage"] == "stage_5"
        assert h[1]["action"] == "advance"
        assert h[1]["from_stage"] == "stage_5"
        assert h[1]["to_stage"] == "stage_25"
        assert h[2]["action"] == "rollback"
        assert h[2]["from_stage"] == "stage_25"
        assert h[2]["to_stage"] == "disabled"
        assert h[2]["reason"] == "test"
