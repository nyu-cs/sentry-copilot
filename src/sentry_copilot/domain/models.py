from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from .enums import GameMode, Phase, PlayerStatus, Server, StageType


class PlayerState(BaseModel):
    """State for one player slot.

    `avatar_visual_key` is an opaque visual fingerprint. It is never a strategy identifier.
    """

    model_config = ConfigDict(validate_assignment=True)

    slot: int = Field(ge=1, le=4)
    is_self: bool = False
    avatar_visual_key: str | None = None
    hp: int | None = None
    status: PlayerStatus = PlayerStatus.UNKNOWN
    strategy_id: str | None = None
    strategy_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    strategy_observed_at: datetime | None = None


class StageState(BaseModel):
    stage_type: StageType = StageType.UNKNOWN
    phase: Phase = Phase.UNKNOWN
    round_number: int | None = Field(default=None, ge=1)
    display_round: str | None = None


class SessionState(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    session_id: str
    server: Server = Server.CN
    locale: str = "zh_CN"
    ruleset_id: str = "unknown"
    mode: GameMode = GameMode.SOLO
    current_map_id: str | None = None
    stage: StageState = Field(default_factory=StageState)
    players: list[PlayerState] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def player(self, slot: int) -> PlayerState:
        for player in self.players:
            if player.slot == slot:
                return player
        raise KeyError(f"player slot {slot} does not exist")
