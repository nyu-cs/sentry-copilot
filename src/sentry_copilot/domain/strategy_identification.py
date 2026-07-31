from __future__ import annotations

from enum import StrEnum

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .identifiers import (
    EvidenceId,
    SessionId,
    SessionParticipantId,
    StrategyId,
    StrategyIdentificationRecordId,
)
from .rulesets import RulesetDependencyStamp


class StrategyIdentificationBasis(StrEnum):
    CATALOG_DERIVED = "catalog_derived"
    DIRECT_OBSERVATION = "direct_observation"
    MANUAL_CONFIRMATION = "manual_confirmation"


class StrategyIdentificationConflictType(StrEnum):
    DUPLICATE_CONFIRMED_STRATEGY_CLAIM = "duplicate_confirmed_strategy_claim"
    PARTICIPANT_STRATEGY_IDENTIFICATION_CONFLICT = (
        "participant_strategy_identification_conflict"
    )
    STRATEGY_CATALOG_COMPATIBILITY_CONFLICT = (
        "strategy_catalog_compatibility_conflict"
    )


class StrategyIdentificationRecord(BaseModel):
    """One immutable concrete strategy claim and its audit relationship."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: StrategyIdentificationRecordId
    session_player_id: SessionParticipantId
    strategy_id: StrategyId
    basis: StrategyIdentificationBasis
    identified_at: AwareDatetime
    evidence_ids: tuple[EvidenceId, ...] = Field(min_length=1)
    dependency_stamp: RulesetDependencyStamp | None = None
    supersedes_record_ids: tuple[StrategyIdentificationRecordId, ...] = Field(
        default_factory=tuple
    )
    reason: str | None = None

    @field_validator("evidence_ids", "supersedes_record_ids")
    @classmethod
    def identifier_tuples_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("identification reference IDs must be unique")
        return value

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("identification reason cannot be blank")
        return value

    @model_validator(mode="after")
    def basis_controls_dependencies_and_correction(self) -> StrategyIdentificationRecord:
        if self.basis == StrategyIdentificationBasis.CATALOG_DERIVED:
            if self.dependency_stamp is None:
                raise ValueError("catalog-derived identification requires a dependency stamp")
        elif self.dependency_stamp is not None:
            raise ValueError("direct/manual identification cannot carry a dependency stamp")

        if self.supersedes_record_ids and self.basis != (
            StrategyIdentificationBasis.MANUAL_CONFIRMATION
        ):
            raise ValueError("only manual correction may supersede identification records")
        if (
            self.basis == StrategyIdentificationBasis.MANUAL_CONFIRMATION
            and self.reason is None
        ):
            raise ValueError("manual identification requires an audit reason")
        return self


class StrategyIdentificationState(BaseModel):
    """Append-only concrete claims; occupancy is deliberately not persisted here."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    records: tuple[StrategyIdentificationRecord, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def record_ids_and_supersession_are_valid(self) -> StrategyIdentificationState:
        record_ids = [record.record_id for record in self.records]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("strategy identification record IDs must be unique")
        by_id = {record.record_id: record for record in self.records}
        positions = {
            record.record_id: index for index, record in enumerate(self.records)
        }
        for index, record in enumerate(self.records):
            for superseded_id in record.supersedes_record_ids:
                superseded = by_id.get(superseded_id)
                if superseded is None or positions[superseded_id] >= index:
                    raise ValueError("superseded records must already exist in history")
                if superseded.session_player_id != record.session_player_id:
                    raise ValueError("identification correction cannot cross participants")
        return self

    def get(
        self,
        record_id: StrategyIdentificationRecordId,
    ) -> StrategyIdentificationRecord | None:
        for record in self.records:
            if record.record_id == record_id:
                return record
        return None

    @property
    def unsuperseded_records(self) -> tuple[StrategyIdentificationRecord, ...]:
        superseded_ids = {
            record_id
            for record in self.records
            for record_id in record.supersedes_record_ids
        }
        return tuple(
            record for record in self.records if record.record_id not in superseded_ids
        )


class ParticipantStrategyIdentification(BaseModel):
    """One unconflicted current identification supported by one or more records."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_player_id: SessionParticipantId
    strategy_id: StrategyId
    supporting_record_ids: tuple[StrategyIdentificationRecordId, ...] = Field(
        min_length=1
    )


class StrategyOccupancy(BaseModel):
    """One uncontested concrete strategy occupancy derived from current claims."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: StrategyId
    session_player_id: SessionParticipantId
    supporting_record_ids: tuple[StrategyIdentificationRecordId, ...] = Field(
        min_length=1
    )


class StrategyIdentificationConflict(BaseModel):
    """An explicit assistant interpretation conflict, never a valid game state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    conflict_type: StrategyIdentificationConflictType
    participant_ids: tuple[SessionParticipantId, ...] = Field(min_length=1)
    strategy_ids: tuple[StrategyId, ...] = Field(min_length=1)
    record_ids: tuple[StrategyIdentificationRecordId, ...] = Field(min_length=1)


class StrategyOccupancyView(BaseModel):
    """Derived current identifications, unique occupancies, conflicts, and stale records."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identifications: tuple[ParticipantStrategyIdentification, ...] = Field(
        default_factory=tuple
    )
    occupancies: tuple[StrategyOccupancy, ...] = Field(default_factory=tuple)
    conflicts: tuple[StrategyIdentificationConflict, ...] = Field(default_factory=tuple)
    stale_record_ids: tuple[StrategyIdentificationRecordId, ...] = Field(
        default_factory=tuple
    )


def derive_strategy_occupancy_view(
    identification_state: StrategyIdentificationState | None,
    *,
    committed_participant_ids: frozenset[SessionParticipantId],
    current_dependency_stamp: RulesetDependencyStamp | None,
    available_strategy_ids: frozenset[StrategyId],
) -> StrategyOccupancyView:
    """Resolve claims conservatively without persisting an occupancy mirror."""

    if identification_state is None:
        return StrategyOccupancyView()

    stale_record_ids: list[StrategyIdentificationRecordId] = []
    eligible_records: list[StrategyIdentificationRecord] = []
    conflicts: list[StrategyIdentificationConflict] = []
    catalog_conflict_participants: set[SessionParticipantId] = set()

    for record in identification_state.unsuperseded_records:
        if record.session_player_id not in committed_participant_ids:
            continue
        if (
            record.basis == StrategyIdentificationBasis.CATALOG_DERIVED
            and record.dependency_stamp != current_dependency_stamp
        ):
            stale_record_ids.append(record.record_id)
            continue
        if record.strategy_id not in available_strategy_ids:
            conflicts.append(
                StrategyIdentificationConflict(
                    conflict_type=(
                        StrategyIdentificationConflictType.STRATEGY_CATALOG_COMPATIBILITY_CONFLICT
                    ),
                    participant_ids=(record.session_player_id,),
                    strategy_ids=(record.strategy_id,),
                    record_ids=(record.record_id,),
                )
            )
            catalog_conflict_participants.add(record.session_player_id)
            continue
        eligible_records.append(record)

    records_by_participant: dict[
        SessionParticipantId,
        list[StrategyIdentificationRecord],
    ] = {}
    records_by_strategy: dict[StrategyId, list[StrategyIdentificationRecord]] = {}
    for record in eligible_records:
        records_by_participant.setdefault(record.session_player_id, []).append(record)
        records_by_strategy.setdefault(record.strategy_id, []).append(record)

    participant_conflicts: set[SessionParticipantId] = set()
    for participant_id, records in sorted(records_by_participant.items()):
        strategy_ids = sorted({record.strategy_id for record in records})
        if len(strategy_ids) <= 1:
            continue
        participant_conflicts.add(participant_id)
        conflicts.append(
            StrategyIdentificationConflict(
                conflict_type=(
                    StrategyIdentificationConflictType.PARTICIPANT_STRATEGY_IDENTIFICATION_CONFLICT
                ),
                participant_ids=(participant_id,),
                strategy_ids=tuple(strategy_ids),
                record_ids=tuple(sorted(record.record_id for record in records)),
            )
        )

    duplicate_strategies: set[StrategyId] = set()
    for strategy_id, records in sorted(records_by_strategy.items()):
        participant_ids = sorted({record.session_player_id for record in records})
        if len(participant_ids) <= 1:
            continue
        duplicate_strategies.add(strategy_id)
        conflicts.append(
            StrategyIdentificationConflict(
                conflict_type=(
                    StrategyIdentificationConflictType.DUPLICATE_CONFIRMED_STRATEGY_CLAIM
                ),
                participant_ids=tuple(participant_ids),
                strategy_ids=(strategy_id,),
                record_ids=tuple(sorted(record.record_id for record in records)),
            )
        )

    identifications: list[ParticipantStrategyIdentification] = []
    occupancies: list[StrategyOccupancy] = []
    for participant_id, records in sorted(records_by_participant.items()):
        participant_strategy_ids = {record.strategy_id for record in records}
        if len(participant_strategy_ids) != 1:
            continue
        strategy_id = next(iter(participant_strategy_ids))
        if (
            participant_id in participant_conflicts
            or participant_id in catalog_conflict_participants
            or strategy_id in duplicate_strategies
        ):
            continue
        supporting_record_ids = tuple(
            sorted(record.record_id for record in records)
        )
        identifications.append(
            ParticipantStrategyIdentification(
                session_player_id=participant_id,
                strategy_id=strategy_id,
                supporting_record_ids=supporting_record_ids,
            )
        )
        occupancies.append(
            StrategyOccupancy(
                strategy_id=strategy_id,
                session_player_id=participant_id,
                supporting_record_ids=supporting_record_ids,
            )
        )

    return StrategyOccupancyView(
        identifications=tuple(identifications),
        occupancies=tuple(sorted(occupancies, key=lambda item: item.strategy_id)),
        conflicts=tuple(
            sorted(
                conflicts,
                key=lambda item: (
                    item.conflict_type,
                    item.participant_ids,
                    item.strategy_ids,
                    item.record_ids,
                ),
            )
        ),
        stale_record_ids=tuple(sorted(stale_record_ids)),
    )
