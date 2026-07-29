from __future__ import annotations

from pydantic import BaseModel

from .models import SessionState
from .strategy_selection import SelectionOutcome, SnapshotCompleteness


class TeamStrategyParticipantContext(BaseModel):
    session_player_id: str
    selection_row: int
    player_tag: str | None
    display_name: str | None
    strategy_id: str | None
    ready: bool | None


class TeamStrategyContext(BaseModel):
    session_id: str
    ruleset_id: str
    frozen: bool
    completeness_level: SnapshotCompleteness
    participants: list[TeamStrategyParticipantContext]

    @property
    def strategy_ids(self) -> list[str]:
        return [
            participant.strategy_id
            for participant in self.participants
            if participant.strategy_id is not None
        ]


def build_team_strategy_context(state: SessionState) -> TeamStrategyContext | None:
    """Build the historical battle-entry strategy view for all ENTERED_BATTLE players.

    Players remain included after later leaving, disconnecting, being eliminated, or reaching
    non-positive HP. This is not a current active-team query; that requires a separate future
    query interface.
    """

    snapshot = state.strategy_selection
    if snapshot is None:
        return None
    return TeamStrategyContext(
        session_id=snapshot.session_id,
        ruleset_id=snapshot.ruleset_id,
        frozen=snapshot.frozen,
        completeness_level=snapshot.completeness_level,
        participants=[
            TeamStrategyParticipantContext(
                session_player_id=participant.session_player_id,
                selection_row=participant.selection_row,
                player_tag=participant.player_tag,
                display_name=participant.display_name,
                strategy_id=participant.strategy_id,
                ready=participant.ready,
            )
            for participant in sorted(
                (
                    participant
                    for participant in snapshot.participants
                    if participant.selection_outcome == SelectionOutcome.ENTERED_BATTLE
                ),
                key=lambda participant: participant.selection_row,
            )
        ],
    )
