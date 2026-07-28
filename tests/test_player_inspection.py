import pytest

from sentry_copilot.player.inspection import InspectionStep, PlayerInspectionWorkflow


def test_user_guided_workflow() -> None:
    workflow = PlayerInspectionWorkflow([2, 3])
    assert workflow.progress.current_slot == 2
    workflow.acknowledge_player_selected(2)
    workflow.acknowledge_strategy_panel_opened(2)
    workflow.record_strategy(2, "strategy.alpha")
    assert workflow.progress.current_slot == 3
    workflow.acknowledge_player_selected(3)
    workflow.acknowledge_strategy_panel_opened(3)
    workflow.record_strategy(3, "strategy.beta")
    assert workflow.progress.step == InspectionStep.COMPLETE
    assert workflow.progress.completed_strategy_ids == {
        2: "strategy.alpha",
        3: "strategy.beta",
    }


def test_wrong_slot_is_rejected() -> None:
    workflow = PlayerInspectionWorkflow([2])
    with pytest.raises(ValueError):
        workflow.acknowledge_player_selected(3)
