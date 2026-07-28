from __future__ import annotations

from datetime import UTC

from .enums import PlayerStatus
from .events import (
    MapObserved,
    PlayerAvatarObserved,
    PlayerHealthObserved,
    PlayerStrategyObserved,
    SessionEvent,
    StageObserved,
)
from .models import SessionState


class InvalidObservationError(ValueError):
    """Raised when an observation cannot safely be assigned to session state."""


def reduce_session(state: SessionState, event: SessionEvent) -> SessionState:
    """Apply one event while enforcing domain invariants."""

    next_state = state.model_copy(deep=True)

    if isinstance(event, PlayerAvatarObserved):
        player = next_state.player(event.slot)
        player.avatar_visual_key = event.avatar_visual_key
        # A personalized avatar must never mutate strategy_id.
    elif isinstance(event, PlayerHealthObserved):
        player = next_state.player(event.slot)
        player.hp = event.hp
        player.status = PlayerStatus.ELIMINATED if event.hp <= 0 else PlayerStatus.ACTIVE
    elif isinstance(event, PlayerStrategyObserved):
        if event.slot != event.selected_player_slot:
            raise InvalidObservationError(
                "strategy observation slot does not match the explicitly selected player slot"
            )
        player = next_state.player(event.slot)
        player.strategy_id = event.strategy_id
        player.strategy_confidence = event.confidence
        player.strategy_observed_at = event.timestamp
    elif isinstance(event, MapObserved):
        next_state.current_map_id = event.map_id
    elif isinstance(event, StageObserved):
        next_state.stage.stage_type = event.stage_type
        next_state.stage.phase = event.phase
        next_state.stage.round_number = event.round_number
        next_state.stage.display_round = event.display_round
    else:  # pragma: no cover
        raise TypeError(f"unsupported event: {type(event)!r}")

    next_state.updated_at = event.timestamp.astimezone(UTC)
    return next_state
