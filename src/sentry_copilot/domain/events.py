from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

from .enums import EvidenceKind, Phase, StageType
from .strategy_selection import StrategySelectionParticipant, StrategySelectionSnapshot


class EventBase(BaseModel):
    timestamp: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    evidence: EvidenceKind = EvidenceKind.OBSERVED
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class PlayerAvatarObserved(EventBase):
    type: Literal["player_avatar_observed"] = "player_avatar_observed"
    slot: int = Field(ge=1, le=4)
    avatar_visual_key: str


class PlayerHealthObserved(EventBase):
    type: Literal["player_health_observed"] = "player_health_observed"
    slot: int = Field(ge=1, le=4)
    hp: int


class PlayerStrategyObserved(EventBase):
    type: Literal["player_strategy_observed"] = "player_strategy_observed"
    slot: int = Field(ge=1, le=4)
    selected_player_slot: int = Field(ge=1, le=4)
    strategy_id: str


class MapObserved(EventBase):
    type: Literal["map_observed"] = "map_observed"
    map_id: str


class StageObserved(EventBase):
    type: Literal["stage_observed"] = "stage_observed"
    stage_type: StageType
    phase: Phase
    round_number: int | None = Field(default=None, ge=1)
    display_round: str | None = None


class StrategySelectionSnapshotObserved(EventBase):
    type: Literal["strategy_selection_snapshot_observed"] = (
        "strategy_selection_snapshot_observed"
    )
    snapshot: StrategySelectionSnapshot


class StrategySelectionSnapshotFrozen(EventBase):
    type: Literal["strategy_selection_snapshot_frozen"] = "strategy_selection_snapshot_frozen"
    session_id: str
    ruleset_id: str


class StrategySelectionSnapshotCorrected(EventBase):
    type: Literal["strategy_selection_snapshot_corrected"] = (
        "strategy_selection_snapshot_corrected"
    )
    evidence: Literal[EvidenceKind.MANUAL] = EvidenceKind.MANUAL
    session_id: str
    ruleset_id: str
    replacements: list[StrategySelectionParticipant] = Field(min_length=1, max_length=4)


SessionEvent = (
    PlayerAvatarObserved
    | PlayerHealthObserved
    | PlayerStrategyObserved
    | MapObserved
    | StageObserved
    | StrategySelectionSnapshotObserved
    | StrategySelectionSnapshotFrozen
    | StrategySelectionSnapshotCorrected
)
