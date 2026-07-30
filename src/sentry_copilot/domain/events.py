from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from .enums import EvidenceKind, Phase, StageType
from .evidence import EvidenceRecord
from .identifiers import (
    CatalogVersion,
    LocaleId,
    RulesetId,
    RulesetRevisionId,
)
from .rulesets import RevisionSelectionMethod
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


class AcceptedRulesetContextEvent(BaseModel):
    """A catalog-validated context fact accepted by the command service."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str = Field(min_length=1)
    ruleset_id: RulesetId
    ruleset_revision_id: RulesetRevisionId
    locale_id: LocaleId
    catalog_version: CatalogVersion
    selected_at: AwareDatetime
    selection_evidence: tuple[EvidenceRecord, ...] = Field(default_factory=tuple)
    reason: str | None = None

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("accepted ruleset context reason cannot be blank")
        return value


class SessionRulesetContextSelected(AcceptedRulesetContextEvent):
    type: Literal["session_ruleset_context_selected"] = (
        "session_ruleset_context_selected"
    )
    selection_method: RevisionSelectionMethod

    @field_validator("selection_method")
    @classmethod
    def method_must_be_supported(
        cls,
        value: RevisionSelectionMethod,
    ) -> RevisionSelectionMethod:
        if value not in (
            RevisionSelectionMethod.MANUAL,
            RevisionSelectionMethod.IMPORTED_FROM_REPLAY_METADATA,
        ):
            raise ValueError(
                "selected context must be manual or imported from replay metadata"
            )
        return value


class SessionRulesetRevisionCorrected(AcceptedRulesetContextEvent):
    type: Literal["session_ruleset_revision_corrected"] = (
        "session_ruleset_revision_corrected"
    )
    selection_method: Literal[RevisionSelectionMethod.MANUAL] = (
        RevisionSelectionMethod.MANUAL
    )


SessionEvent = (
    PlayerAvatarObserved
    | PlayerHealthObserved
    | PlayerStrategyObserved
    | MapObserved
    | StageObserved
    | StrategySelectionSnapshotObserved
    | StrategySelectionSnapshotFrozen
    | StrategySelectionSnapshotCorrected
    | SessionRulesetContextSelected
    | SessionRulesetRevisionCorrected
)
