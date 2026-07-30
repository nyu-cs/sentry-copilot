from __future__ import annotations

from collections.abc import Iterator, Mapping
from enum import StrEnum
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

from .evidence import EvidenceRecord as EvidenceRecord

PlayerTag = Annotated[str, StringConstraints(strict=True, pattern=r"^\d{4}$")]


class ParticipantField(StrEnum):
    PLAYER_TAG = "player_tag"
    DISPLAY_NAME = "display_name"
    AVATAR = "avatar"
    STRATEGY = "strategy"
    READY = "ready"
    IS_SELF = "is_self"
    SELECTION_OUTCOME = "selection_outcome"


class SelectionOutcome(StrEnum):
    ENTERED_BATTLE = "entered_battle"
    LEFT_UNREADY = "left_unready"
    EXITED_BEFORE_STRATEGY = "exited_before_strategy"
    EXITED_AFTER_STRATEGY = "exited_after_strategy"
    UNKNOWN = "unknown"


class SnapshotCompleteness(StrEnum):
    PARTIAL = "partial"
    STRATEGIES_COMPLETE = "strategies_complete"
    FULLY_IDENTIFIED = "fully_identified"


class FrozenEvidenceMap(Mapping[ParticipantField, EvidenceRecord]):
    """Small immutable mapping that keeps evidence JSON-compatible."""

    __slots__ = ("_items",)
    _items: tuple[tuple[ParticipantField, EvidenceRecord], ...]

    def __init__(
        self,
        values: Mapping[ParticipantField, EvidenceRecord] | None = None,
    ) -> None:
        object.__setattr__(self, "_items", tuple((values or {}).items()))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("FrozenEvidenceMap is immutable")

    def __getitem__(self, key: ParticipantField) -> EvidenceRecord:
        for item_key, item_value in self._items:
            if item_key == key:
                return item_value
        raise KeyError(key)

    def __iter__(self) -> Iterator[ParticipantField]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __deepcopy__(self, memo: dict[int, object]) -> FrozenEvidenceMap:
        return self

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Mapping):
            return NotImplemented
        return dict(self.items()) == dict(other.items())


class StrategySelectionParticipant(BaseModel):
    """One session-local participant shown on the strategy selection screen."""

    model_config = ConfigDict(frozen=True, validate_default=True)

    session_player_id: str
    selection_row: int = Field(ge=1, le=4)
    player_tag: PlayerTag | None = None
    display_name: str | None = None
    avatar_visual_key: str | None = None
    strategy_id: str | None = None
    ready: bool | None = None
    is_self: bool | None = None
    selection_outcome: SelectionOutcome = SelectionOutcome.UNKNOWN
    field_evidence: Mapping[ParticipantField, EvidenceRecord] = Field(
        default_factory=FrozenEvidenceMap
    )

    @field_validator(
        "session_player_id",
        "display_name",
        "avatar_visual_key",
        "strategy_id",
    )
    @classmethod
    def present_strings_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("participant strings cannot be blank")
        return value

    @model_validator(mode="after")
    def known_fields_require_evidence(self) -> StrategySelectionParticipant:
        field_attributes = {
            ParticipantField.PLAYER_TAG: "player_tag",
            ParticipantField.DISPLAY_NAME: "display_name",
            ParticipantField.AVATAR: "avatar_visual_key",
            ParticipantField.STRATEGY: "strategy_id",
            ParticipantField.READY: "ready",
            ParticipantField.IS_SELF: "is_self",
            ParticipantField.SELECTION_OUTCOME: "selection_outcome",
        }
        missing_evidence = [
            field_name.value
            for field_name, attribute in field_attributes.items()
            if self._field_value_is_known(field_name, getattr(self, attribute))
            and field_name not in self.field_evidence
        ]
        if missing_evidence:
            raise ValueError(
                "known participant fields require evidence: " + ", ".join(missing_evidence)
            )
        return self

    @field_validator("field_evidence", mode="after")
    @classmethod
    def field_evidence_must_be_immutable(
        cls,
        value: Mapping[ParticipantField, EvidenceRecord],
    ) -> FrozenEvidenceMap:
        if isinstance(value, FrozenEvidenceMap):
            return value
        return FrozenEvidenceMap(value)

    @field_serializer("field_evidence")
    def serialize_field_evidence(
        self,
        value: Mapping[ParticipantField, EvidenceRecord],
    ) -> dict[ParticipantField, EvidenceRecord]:
        return dict(value)

    @staticmethod
    def _field_value_is_known(field_name: ParticipantField, value: object) -> bool:
        if field_name == ParticipantField.SELECTION_OUTCOME:
            return value != SelectionOutcome.UNKNOWN
        return value is not None


class StrategySelectionSnapshot(BaseModel):
    """Reducer-owned current strategy state for one session."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    ruleset_id: str
    expected_participant_count: int | None = Field(default=None, ge=1, le=4)
    captured_at: AwareDatetime
    participants: tuple[StrategySelectionParticipant, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
    frozen: bool = False
    evidence: tuple[EvidenceRecord, ...] = Field(default_factory=tuple)

    @field_validator("session_id", "ruleset_id")
    @classmethod
    def identifiers_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("snapshot identifiers cannot be blank")
        return value

    @model_validator(mode="after")
    def participants_are_session_unique(self) -> StrategySelectionSnapshot:
        self._require_unique(
            [participant.session_player_id for participant in self.participants],
            "session_player_id",
        )
        self._require_unique(
            [participant.selection_row for participant in self.participants],
            "selection_row",
        )
        self._require_unique(
            [
                participant.player_tag
                for participant in self.participants
                if participant.player_tag is not None
            ],
            "player_tag",
        )
        self._require_unique(
            [
                participant.strategy_id
                for participant in self.participants
                if participant.selection_outcome == SelectionOutcome.ENTERED_BATTLE
                and participant.strategy_id is not None
            ],
            "strategy_id",
        )
        if sum(participant.is_self is True for participant in self.participants) > 1:
            raise ValueError("at most one participant can be self")
        return self

    @property
    def strategy_complete(self) -> bool:
        if not self.frozen or self.expected_participant_count is None:
            return False
        entered_participants = [
            participant
            for participant in self.participants
            if participant.selection_outcome == SelectionOutcome.ENTERED_BATTLE
        ]
        if len(entered_participants) != self.expected_participant_count:
            return False
        strategy_ids = [
            participant.strategy_id
            for participant in entered_participants
            if participant.strategy_id is not None
        ]
        return (
            len(strategy_ids) == self.expected_participant_count
            and len(strategy_ids) == len(set(strategy_ids))
        )

    @property
    def identity_complete(self) -> bool:
        if not self.strategy_complete:
            return False
        player_tags = [
            participant.player_tag
            for participant in self.participants
            if participant.selection_outcome == SelectionOutcome.ENTERED_BATTLE
            and participant.player_tag is not None
        ]
        return (
            len(player_tags) == self.expected_participant_count
            and len(player_tags) == len(set(player_tags))
        )

    @property
    def completeness_level(self) -> SnapshotCompleteness:
        if not self.strategy_complete:
            return SnapshotCompleteness.PARTIAL
        if self.identity_complete:
            return SnapshotCompleteness.FULLY_IDENTIFIED
        return SnapshotCompleteness.STRATEGIES_COMPLETE

    @staticmethod
    def _require_unique(values: list[object], field_name: str) -> None:
        if len(values) != len(set(values)):
            raise ValueError(f"{field_name} values must be unique within one snapshot")
