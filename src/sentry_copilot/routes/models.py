from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sentry_copilot.domain.enums import StageType


class ActorType(StrEnum):
    ENEMY = "enemy"
    BOSS = "boss"


class RouteVerification(StrEnum):
    PLACEHOLDER = "placeholder"
    COMMUNITY = "community"
    VIDEO_VERIFIED = "video_verified"
    OWNER_VERIFIED = "owner_verified"


class Point(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class PixelPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: float
    y: float


class MoveStep(BaseModel):
    type: Literal["move"] = "move"
    points: list[Point] = Field(min_length=2)
    label: str | None = None


class WaitStep(BaseModel):
    type: Literal["wait"] = "wait"
    at: Point
    label: str | None = None


class TeleportStep(BaseModel):
    type: Literal["teleport"] = "teleport"
    from_point: Point
    to_point: Point
    label: str | None = None


class PhaseChangeStep(BaseModel):
    type: Literal["phase_change"] = "phase_change"
    at: Point
    phase_id: str
    label: str | None = None


RouteStep = Annotated[
    MoveStep | WaitStep | TeleportStep | PhaseChangeStep,
    Field(discriminator="type"),
]


class RouteCondition(BaseModel):
    stage_types: set[StageType] = Field(default_factory=set)
    waves: set[int] = Field(default_factory=set)
    enemy_profiles: set[str] = Field(default_factory=set)
    boss_phases: set[str] = Field(default_factory=set)

    @model_validator(mode="after")
    def validate_waves(self) -> RouteCondition:
        if any(wave < 1 for wave in self.waves):
            raise ValueError("wave numbers must be positive")
        return self


class RouteDefinition(BaseModel):
    route_id: str
    label: str
    actor_type: ActorType
    actor_ids: set[str] = Field(default_factory=set)
    priority: int = 0
    conditions: RouteCondition = Field(default_factory=RouteCondition)
    steps: list[RouteStep] = Field(min_length=1)
    verification: RouteVerification = RouteVerification.PLACEHOLDER
    notes: str | None = None


class MapDefinition(BaseModel):
    schema_version: int = 1
    map_id: str
    ruleset_ids: set[str] = Field(default_factory=set)
    names: dict[str, str]
    routes: list[RouteDefinition] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def route_ids_are_unique(self) -> MapDefinition:
        route_ids = [route.route_id for route in self.routes]
        if len(route_ids) != len(set(route_ids)):
            raise ValueError("route IDs must be unique within one map")
        return self


class MapCalibration(BaseModel):
    frame_width: int = Field(gt=0)
    frame_height: int = Field(gt=0)
    battlefield_corners: list[PixelPoint] = Field(min_length=4, max_length=4)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: str = "manual"


class RouteQuery(BaseModel):
    map_id: str
    ruleset_id: str
    actor_type: ActorType
    stage_type: StageType
    wave: int | None = Field(default=None, ge=1)
    actor_id: str | None = None
    enemy_profiles: set[str] = Field(default_factory=set)
    boss_phase: str | None = None
