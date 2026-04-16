from __future__ import annotations

import pytest

from autoservice.canary import CanaryRouter, CanaryStage
from autoservice.rollback_command import RollbackCommand


class TestRollbackCommand:
    """Tests for RollbackCommand — /rollback operator command."""

    def test_import_and_instantiate(self):
        router = CanaryRouter()
        cmd = RollbackCommand(router)
        assert cmd is not None

    @pytest.mark.asyncio
    async def test_rollback_from_stage_5(self):
        router = CanaryRouter(observation_hours=0)
        router.advance()  # DISABLED -> STAGE_5
        cmd = RollbackCommand(router)

        result = await cmd.execute(actor_id="op1", reason="too many errors")

        assert result["success"] is True
        assert result["previous_stage"] == "stage_5"
        assert result["current_stage"] == "disabled"
        assert result["reason"] == "too many errors"
        assert result["rolled_back_by"] == "op1"
        assert "timestamp" in result
        assert router.current_stage == CanaryStage.DISABLED

    @pytest.mark.asyncio
    async def test_rollback_from_stage_25(self):
        router = CanaryRouter(observation_hours=0)
        router.advance()  # STAGE_5
        router.advance()  # STAGE_25
        cmd = RollbackCommand(router)

        result = await cmd.execute(actor_id="op2", reason="regression detected")

        assert result["success"] is True
        assert result["previous_stage"] == "stage_25"
        assert result["current_stage"] == "disabled"
        assert router.current_stage == CanaryStage.DISABLED

    @pytest.mark.asyncio
    async def test_rollback_from_stage_100(self):
        router = CanaryRouter(observation_hours=0)
        router.advance()  # STAGE_5
        router.advance()  # STAGE_25
        router.advance()  # STAGE_100
        cmd = RollbackCommand(router)

        result = await cmd.execute(actor_id="admin", reason="critical bug")

        assert result["success"] is True
        assert result["previous_stage"] == "stage_100"
        assert result["current_stage"] == "disabled"
        assert router.current_stage == CanaryStage.DISABLED

    @pytest.mark.asyncio
    async def test_rollback_when_already_disabled_is_idempotent(self):
        router = CanaryRouter()
        cmd = RollbackCommand(router)

        result = await cmd.execute(actor_id="op1", reason="just in case")

        assert result["success"] is True
        assert result["previous_stage"] == "disabled"
        assert result["current_stage"] == "disabled"
        assert router.current_stage == CanaryStage.DISABLED

    @pytest.mark.asyncio
    async def test_rollback_records_reason_and_actor(self):
        router = CanaryRouter(observation_hours=0)
        router.advance()  # STAGE_5
        cmd = RollbackCommand(router)

        result = await cmd.execute(actor_id="operator_xyz", reason="latency spike")

        assert result["reason"] == "latency spike"
        assert result["rolled_back_by"] == "operator_xyz"
        # Verify reason is also recorded in canary router history
        last_entry = router.history[-1]
        assert last_entry["action"] == "rollback"
        assert last_entry["reason"] == "latency spike"

    def test_status_delegates_to_canary_router(self):
        router = CanaryRouter(observation_hours=0)
        router.advance()  # STAGE_5
        cmd = RollbackCommand(router)

        status = cmd.status()

        assert status == router.status()
        assert status["stage"] == "stage_5"
        assert status["percentage"] == 5
        assert "history" in status

    def test_is_rollback_needed_false_when_disabled(self):
        router = CanaryRouter()
        cmd = RollbackCommand(router)

        assert cmd.is_rollback_needed is False

    def test_is_rollback_needed_true_when_not_disabled(self):
        router = CanaryRouter(observation_hours=0)
        router.advance()  # STAGE_5
        cmd = RollbackCommand(router)

        assert cmd.is_rollback_needed is True
