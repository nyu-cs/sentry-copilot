from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from .enums import EvidenceKind, Phase, StageType


class EventBase(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
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


SessionEvent = (
    PlayerAvatarObserved
    | PlayerHealthObserved
    | PlayerStrategyObserved
    | MapObserved
    | StageObserved
)
