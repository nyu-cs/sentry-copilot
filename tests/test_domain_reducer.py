import pytest

from sentry_copilot.domain.enums import PlayerStatus
from sentry_copilot.domain.events import (
    PlayerAvatarObserved,
    PlayerHealthObserved,
    PlayerStrategyObserved,
)
from sentry_copilot.domain.models import PlayerState, SessionState
from sentry_copilot.domain.reducer import InvalidObservationError, reduce_session


def state() -> SessionState:
    return SessionState(
        session_id="test",
        players=[PlayerState(slot=slot, is_self=slot == 1) for slot in range(1, 5)],
    )


def test_avatar_never_sets_strategy() -> None:
    result = reduce_session(state(), PlayerAvatarObserved(slot=2, avatar_visual_key="hash"))
    assert result.player(2).avatar_visual_key == "hash"
    assert result.player(2).strategy_id is None


def test_zero_health_eliminates_player() -> None:
    result = reduce_session(state(), PlayerHealthObserved(slot=3, hp=0))
    assert result.player(3).status == PlayerStatus.ELIMINATED


def test_positive_health_marks_player_active() -> None:
    result = reduce_session(state(), PlayerHealthObserved(slot=3, hp=19))
    assert result.player(3).status == PlayerStatus.ACTIVE


def test_strategy_requires_matching_selected_slot() -> None:
    with pytest.raises(InvalidObservationError):
        reduce_session(
            state(),
            PlayerStrategyObserved(
                slot=2,
                selected_player_slot=3,
                strategy_id="strategy.example",
                confidence=0.9,
            ),
        )


def test_strategy_applies_with_explicit_slot_context() -> None:
    result = reduce_session(
        state(),
        PlayerStrategyObserved(
            slot=2,
            selected_player_slot=2,
            strategy_id="strategy.example",
            confidence=0.91,
        ),
    )
    assert result.player(2).strategy_id == "strategy.example"
    assert result.player(2).strategy_confidence == 0.91
