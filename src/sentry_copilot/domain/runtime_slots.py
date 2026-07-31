from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .battle_roster import InactivePresentation
from .enums import EvidenceKind
from .identifiers import (
    EvidenceId,
    RuntimeSlotId,
    RuntimeSlotLayoutId,
    SessionId,
    SessionParticipantId,
    SlotAssociationCorrectionId,
    SlotAssociationRecordId,
)
from .prebattle import NormalizedRoi
from .strategy_selection import PlayerTag


class RuntimeSlotPresentation(StrEnum):
    NORMAL_ACTIVE = "normal_active"
    DEPARTED = "departed"
    SPECTATING = "spectating"
    INACTIVE_UNKNOWN = "inactive_unknown"
    VISIBLE_UNKNOWN = "visible_unknown"


class RuntimeSlotObservation(BaseModel):
    """Immutable direct screen evidence with no participant interpretation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["runtime_slot_observed"] = "runtime_slot_observed"
    evidence_id: EvidenceId
    session_id: SessionId
    layout_id: RuntimeSlotLayoutId
    runtime_slot_id: RuntimeSlotId
    observed_at: AwareDatetime
    visual_index: int = Field(ge=1)
    roi: NormalizedRoi
    slot_visible: bool
    normal_active_presentation_visible: bool = False
    inactive_presentation: InactivePresentation | None = None
    observed_display_name: str | None = None
    observed_player_tag: PlayerTag | None = None
    self_marker_visible: bool = False
    provenance: EvidenceKind
    confidence: float = Field(ge=0.0, le=1.0)
    frame_reference: str | None = None
    source_detail: str | None = None

    @field_validator("observed_display_name", "frame_reference", "source_detail")
    @classmethod
    def optional_text_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("runtime slot observation text cannot be blank")
        return value

    @model_validator(mode="after")
    def visible_fields_are_consistent(self) -> RuntimeSlotObservation:
        if self.provenance == EvidenceKind.MANUAL:
            raise ValueError("raw runtime slot observation cannot use manual provenance")
        if not self.slot_visible and any(
            (
                self.normal_active_presentation_visible,
                self.inactive_presentation is not None,
                self.observed_display_name is not None,
                self.observed_player_tag is not None,
                self.self_marker_visible,
            )
        ):
            raise ValueError("invisible slot cannot carry visible identity or presentation")
        if (
            self.normal_active_presentation_visible
            and self.inactive_presentation is not None
        ):
            raise ValueError("slot cannot be active and inactive in one observation")
        return self


class RuntimeSlotObservationCorrected(BaseModel):
    """Manual invalidation of mistaken visual evidence, not a game slot event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["runtime_slot_observation_corrected"] = (
        "runtime_slot_observation_corrected"
    )
    evidence_id: EvidenceId
    session_id: SessionId
    layout_id: RuntimeSlotLayoutId
    runtime_slot_id: RuntimeSlotId
    corrected_at: AwareDatetime
    invalidated_observation_ids: tuple[EvidenceId, ...] = Field(min_length=1)
    provenance: Literal[EvidenceKind.MANUAL] = EvidenceKind.MANUAL
    reason: str

    @field_validator("invalidated_observation_ids")
    @classmethod
    def targets_are_unique(
        cls,
        value: tuple[EvidenceId, ...],
    ) -> tuple[EvidenceId, ...]:
        if len(value) != len(set(value)):
            raise ValueError("slot observation correction targets must be unique")
        return value

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("slot observation correction reason cannot be blank")
        return value


RuntimeSlotEvidenceEntry = Annotated[
    RuntimeSlotObservation | RuntimeSlotObservationCorrected,
    Field(discriminator="type"),
]


class RuntimeSlotEvidenceLedger(BaseModel):
    """Append-only raw slot observations and assistant-record corrections."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    entries: tuple[RuntimeSlotEvidenceEntry, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def history_is_consistent(self) -> RuntimeSlotEvidenceLedger:
        evidence_ids = [entry.evidence_id for entry in self.entries]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("runtime slot evidence IDs must be unique")
        if any(entry.session_id != self.session_id for entry in self.entries):
            raise ValueError("runtime slot evidence session_id must match its ledger")

        by_id: dict[EvidenceId, RuntimeSlotEvidenceEntry] = {}
        invalidated_ids: set[EvidenceId] = set()
        layout_by_slot: dict[RuntimeSlotId, RuntimeSlotLayoutId] = {}
        for entry in self.entries:
            if isinstance(entry, RuntimeSlotObservation):
                existing_layout = layout_by_slot.get(entry.runtime_slot_id)
                if existing_layout is not None and existing_layout != entry.layout_id:
                    raise ValueError(
                        "runtime slot ID cannot be reused across layout epochs"
                    )
                layout_by_slot[entry.runtime_slot_id] = entry.layout_id
                by_id[entry.evidence_id] = entry
                continue
            for target_id in entry.invalidated_observation_ids:
                target = by_id.get(target_id)
                if not isinstance(target, RuntimeSlotObservation):
                    raise ValueError(
                        "slot observation correction target must precede correction"
                    )
                if (
                    target.layout_id != entry.layout_id
                    or target.runtime_slot_id != entry.runtime_slot_id
                ):
                    raise ValueError(
                        "slot observation correction cannot cross layout or slot"
                    )
                if entry.corrected_at < target.observed_at:
                    raise ValueError(
                        "slot observation correction cannot precede its target"
                    )
                if target_id in invalidated_ids:
                    raise ValueError("slot observation was already invalidated")
                invalidated_ids.add(target_id)
            by_id[entry.evidence_id] = entry
        return self

    def get(self, evidence_id: EvidenceId) -> RuntimeSlotEvidenceEntry | None:
        return next(
            (entry for entry in self.entries if entry.evidence_id == evidence_id),
            None,
        )

    @property
    def invalidated_observation_ids(self) -> frozenset[EvidenceId]:
        return frozenset(
            target_id
            for entry in self.entries
            if isinstance(entry, RuntimeSlotObservationCorrected)
            for target_id in entry.invalidated_observation_ids
        )

    @property
    def effective_observations(self) -> tuple[RuntimeSlotObservation, ...]:
        invalidated = self.invalidated_observation_ids
        return tuple(
            entry
            for entry in self.entries
            if isinstance(entry, RuntimeSlotObservation)
            and entry.evidence_id not in invalidated
        )


class BattleRuntimeSlot(BaseModel):
    """Current query projection of one visual slot within one layout epoch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    layout_id: RuntimeSlotLayoutId
    runtime_slot_id: RuntimeSlotId
    first_seen_at: AwareDatetime
    last_seen_at: AwareDatetime
    current_visual_index: int = Field(ge=1)
    current_roi: NormalizedRoi
    current_presentation: RuntimeSlotPresentation
    observation_evidence_ids: tuple[EvidenceId, ...] = Field(min_length=1)
    has_effective_association: bool = False


class RuntimeSlotView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    current_layout_id: RuntimeSlotLayoutId | None = None
    slots: tuple[BattleRuntimeSlot, ...] = Field(default_factory=tuple)

    def get(self, runtime_slot_id: RuntimeSlotId) -> BattleRuntimeSlot | None:
        return next(
            (slot for slot in self.slots if slot.runtime_slot_id == runtime_slot_id),
            None,
        )


class SlotParticipantAssociationBasis(StrEnum):
    DIRECT_PLAYER_TAG = "direct_player_tag"
    DIRECT_SELF_MARKER = "direct_self_marker"
    MANUAL_CONFIRMATION = "manual_confirmation"


class SlotParticipantAssociationRecord(BaseModel):
    """One immutable strong claim linking a slot and confirmed entrant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: SlotAssociationRecordId
    session_id: SessionId
    layout_id: RuntimeSlotLayoutId
    runtime_slot_id: RuntimeSlotId
    session_player_id: SessionParticipantId
    basis: SlotParticipantAssociationBasis
    associated_at: AwareDatetime
    evidence_ids: tuple[EvidenceId, ...] = Field(min_length=1)
    supersedes_record_ids: tuple[SlotAssociationRecordId, ...] = Field(
        default_factory=tuple
    )
    manual_reason: str | None = None

    @field_validator("evidence_ids", "supersedes_record_ids")
    @classmethod
    def references_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("slot association references must be unique")
        return value

    @field_validator("manual_reason")
    @classmethod
    def manual_reason_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("manual association reason cannot be blank")
        return value

    @model_validator(mode="after")
    def basis_controls_manual_fields(self) -> SlotParticipantAssociationRecord:
        if self.basis == SlotParticipantAssociationBasis.MANUAL_CONFIRMATION:
            if self.manual_reason is None:
                raise ValueError("manual association requires an audit reason")
        elif self.manual_reason is not None or self.supersedes_record_ids:
            raise ValueError("direct association cannot carry manual correction fields")
        if self.supersedes_record_ids and self.basis != (
            SlotParticipantAssociationBasis.MANUAL_CONFIRMATION
        ):
            raise ValueError("association supersession must be manual")
        return self


class SlotAssociationCorrection(BaseModel):
    """Audit envelope for one atomic batch of manual replacement records."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    correction_id: SlotAssociationCorrectionId
    session_id: SessionId
    corrected_at: AwareDatetime
    replacement_record_ids: tuple[SlotAssociationRecordId, ...] = Field(min_length=1)
    provenance: Literal[EvidenceKind.MANUAL] = EvidenceKind.MANUAL
    reason: str

    @field_validator("replacement_record_ids")
    @classmethod
    def record_ids_are_unique(
        cls,
        value: tuple[SlotAssociationRecordId, ...],
    ) -> tuple[SlotAssociationRecordId, ...]:
        if len(value) != len(set(value)):
            raise ValueError("correction replacement record IDs must be unique")
        return value

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("slot association correction reason cannot be blank")
        return value


class SlotAssociationState(BaseModel):
    """Append-only association claims and correction audit envelopes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    records: tuple[SlotParticipantAssociationRecord, ...] = Field(
        default_factory=tuple
    )
    corrections: tuple[SlotAssociationCorrection, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def history_is_consistent(self) -> SlotAssociationState:
        record_ids = [record.record_id for record in self.records]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("slot association record IDs must be unique")
        correction_ids = [item.correction_id for item in self.corrections]
        if len(correction_ids) != len(set(correction_ids)):
            raise ValueError("slot association correction IDs must be unique")
        if any(record.session_id != self.session_id for record in self.records):
            raise ValueError("association record session_id must match its state")
        if any(item.session_id != self.session_id for item in self.corrections):
            raise ValueError("association correction session_id must match its state")

        records_by_id = {record.record_id: record for record in self.records}
        positions = {
            record.record_id: index for index, record in enumerate(self.records)
        }
        corrected_record_ids: set[SlotAssociationRecordId] = set()
        superseded_ids: set[SlotAssociationRecordId] = set()
        for correction in self.corrections:
            for replacement_id in correction.replacement_record_ids:
                replacement = records_by_id.get(replacement_id)
                if replacement is None:
                    raise ValueError("correction replacement record must exist")
                if replacement_id in corrected_record_ids:
                    raise ValueError("replacement record belongs to multiple corrections")
                corrected_record_ids.add(replacement_id)
                if (
                    replacement.basis
                    != SlotParticipantAssociationBasis.MANUAL_CONFIRMATION
                    or not replacement.supersedes_record_ids
                ):
                    raise ValueError(
                        "correction replacement must be a manual supersession record"
                    )
                if replacement.associated_at != correction.corrected_at:
                    raise ValueError(
                        "replacement associated_at must equal correction time"
                    )
                if replacement.manual_reason != correction.reason:
                    raise ValueError("replacement and correction reasons must match")
                for superseded_id in replacement.supersedes_record_ids:
                    superseded = records_by_id.get(superseded_id)
                    if (
                        superseded is None
                        or positions[superseded_id] >= positions[replacement_id]
                    ):
                        raise ValueError(
                            "superseded association record must already exist"
                        )
                    if superseded.session_id != replacement.session_id:
                        raise ValueError("association correction cannot cross sessions")
                    if superseded.layout_id != replacement.layout_id:
                        raise ValueError("association correction cannot cross layouts")
                    if superseded_id in superseded_ids:
                        raise ValueError("association record was already superseded")
                    superseded_ids.add(superseded_id)

        unregistered_corrections = [
            record.record_id
            for record in self.records
            if record.supersedes_record_ids
            and record.record_id not in corrected_record_ids
        ]
        if unregistered_corrections:
            raise ValueError("manual supersession records require a correction envelope")
        return self

    def get_record(
        self,
        record_id: SlotAssociationRecordId,
    ) -> SlotParticipantAssociationRecord | None:
        return next(
            (record for record in self.records if record.record_id == record_id),
            None,
        )

    def get_correction(
        self,
        correction_id: SlotAssociationCorrectionId,
    ) -> SlotAssociationCorrection | None:
        return next(
            (item for item in self.corrections if item.correction_id == correction_id),
            None,
        )

    @property
    def superseded_record_ids(self) -> frozenset[SlotAssociationRecordId]:
        return frozenset(
            record_id
            for record in self.records
            for record_id in record.supersedes_record_ids
        )

    @property
    def unsuperseded_records(self) -> tuple[SlotParticipantAssociationRecord, ...]:
        superseded = self.superseded_record_ids
        return tuple(
            record for record in self.records if record.record_id not in superseded
        )


class SlotAssociationConflictType(StrEnum):
    SLOT_MULTIPLE_PARTICIPANT_CLAIMS = "slot_multiple_participant_claims"
    PARTICIPANT_MULTIPLE_SLOT_CLAIMS = "participant_multiple_slot_claims"


class EffectiveSlotParticipantAssociation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    layout_id: RuntimeSlotLayoutId
    runtime_slot_id: RuntimeSlotId
    session_player_id: SessionParticipantId
    supporting_record_ids: tuple[SlotAssociationRecordId, ...] = Field(min_length=1)
    evidence_ids: tuple[EvidenceId, ...] = Field(min_length=1)
    bases: tuple[SlotParticipantAssociationBasis, ...] = Field(min_length=1)


class SlotAssociationConflict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    conflict_type: SlotAssociationConflictType
    layout_id: RuntimeSlotLayoutId
    runtime_slot_ids: tuple[RuntimeSlotId, ...] = Field(min_length=1)
    session_player_ids: tuple[SessionParticipantId, ...] = Field(min_length=1)
    record_ids: tuple[SlotAssociationRecordId, ...] = Field(min_length=1)


class SlotAssociationView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    current_layout_id: RuntimeSlotLayoutId | None = None
    associations: tuple[EffectiveSlotParticipantAssociation, ...] = Field(
        default_factory=tuple
    )
    conflicts: tuple[SlotAssociationConflict, ...] = Field(default_factory=tuple)
    ineligible_record_ids: tuple[SlotAssociationRecordId, ...] = Field(
        default_factory=tuple
    )
    superseded_record_ids: tuple[SlotAssociationRecordId, ...] = Field(
        default_factory=tuple
    )

    def for_slot(
        self,
        runtime_slot_id: RuntimeSlotId,
    ) -> EffectiveSlotParticipantAssociation | None:
        return next(
            (
                association
                for association in self.associations
                if association.runtime_slot_id == runtime_slot_id
            ),
            None,
        )


def current_runtime_layout_id(
    ledger: RuntimeSlotEvidenceLedger | None,
) -> RuntimeSlotLayoutId | None:
    if ledger is None or not ledger.effective_observations:
        return None
    latest_by_layout: dict[RuntimeSlotLayoutId, AwareDatetime] = {}
    for observation in ledger.effective_observations:
        current = latest_by_layout.get(observation.layout_id)
        if current is None or observation.observed_at > current:
            latest_by_layout[observation.layout_id] = observation.observed_at
    latest_time = max(latest_by_layout.values())
    latest_layouts = [
        layout_id
        for layout_id, observed_at in latest_by_layout.items()
        if observed_at == latest_time
    ]
    return latest_layouts[0] if len(latest_layouts) == 1 else None


def derive_runtime_slot_view(
    *,
    session_id: SessionId,
    ledger: RuntimeSlotEvidenceLedger | None,
    associated_slot_ids: frozenset[RuntimeSlotId] = frozenset(),
) -> RuntimeSlotView:
    layout_id = current_runtime_layout_id(ledger)
    if ledger is None or layout_id is None:
        return RuntimeSlotView(session_id=session_id, current_layout_id=layout_id)

    observations_by_slot: dict[RuntimeSlotId, list[RuntimeSlotObservation]] = {}
    for observation in ledger.effective_observations:
        if observation.layout_id == layout_id:
            observations_by_slot.setdefault(
                observation.runtime_slot_id,
                [],
            ).append(observation)

    slots: list[BattleRuntimeSlot] = []
    for runtime_slot_id, observations in sorted(observations_by_slot.items()):
        ordered = sorted(
            observations,
            key=lambda item: (item.observed_at, item.evidence_id),
        )
        latest = ordered[-1]
        if not latest.slot_visible:
            continue
        slots.append(
            BattleRuntimeSlot(
                layout_id=layout_id,
                runtime_slot_id=runtime_slot_id,
                first_seen_at=ordered[0].observed_at,
                last_seen_at=latest.observed_at,
                current_visual_index=latest.visual_index,
                current_roi=latest.roi,
                current_presentation=_presentation(latest),
                observation_evidence_ids=tuple(
                    item.evidence_id for item in ordered
                ),
                has_effective_association=runtime_slot_id in associated_slot_ids,
            )
        )
    return RuntimeSlotView(
        session_id=session_id,
        current_layout_id=layout_id,
        slots=tuple(slots),
    )


def derive_slot_association_view(
    *,
    session_id: SessionId,
    ledger: RuntimeSlotEvidenceLedger | None,
    association_state: SlotAssociationState | None,
    entrant_ids: frozenset[SessionParticipantId],
    player_tags: dict[SessionParticipantId, PlayerTag],
    self_participant_id: SessionParticipantId | None,
) -> SlotAssociationView:
    layout_id = current_runtime_layout_id(ledger)
    if association_state is None or ledger is None or layout_id is None:
        return SlotAssociationView(
            session_id=session_id,
            current_layout_id=layout_id,
        )

    slot_view = derive_runtime_slot_view(session_id=session_id, ledger=ledger)
    current_slot_ids = frozenset(slot.runtime_slot_id for slot in slot_view.slots)
    effective_evidence = {
        item.evidence_id: item for item in ledger.effective_observations
    }
    candidates: list[SlotParticipantAssociationRecord] = []
    ineligible: list[SlotAssociationRecordId] = []
    for record in association_state.unsuperseded_records:
        if _record_is_current_and_supported(
            record,
            layout_id=layout_id,
            current_slot_ids=current_slot_ids,
            entrant_ids=entrant_ids,
            player_tags=player_tags,
            self_participant_id=self_participant_id,
            effective_evidence=effective_evidence,
        ):
            candidates.append(record)
        else:
            ineligible.append(record.record_id)

    pair_records: dict[
        tuple[RuntimeSlotId, SessionParticipantId],
        list[SlotParticipantAssociationRecord],
    ] = {}
    for record in candidates:
        pair_records.setdefault(
            (record.runtime_slot_id, record.session_player_id),
            [],
        ).append(record)

    participant_ids_by_slot: dict[RuntimeSlotId, set[SessionParticipantId]] = {}
    slot_ids_by_participant: dict[SessionParticipantId, set[RuntimeSlotId]] = {}
    for runtime_slot_id, participant_id in pair_records:
        participant_ids_by_slot.setdefault(runtime_slot_id, set()).add(participant_id)
        slot_ids_by_participant.setdefault(participant_id, set()).add(runtime_slot_id)

    conflict_slots = {
        runtime_slot_id
        for runtime_slot_id, participant_ids in participant_ids_by_slot.items()
        if len(participant_ids) > 1
    }
    conflict_participants = {
        participant_id
        for participant_id, runtime_slot_ids in slot_ids_by_participant.items()
        if len(runtime_slot_ids) > 1
    }
    conflicts: list[SlotAssociationConflict] = []
    for runtime_slot_id in sorted(conflict_slots):
        participant_ids = participant_ids_by_slot[runtime_slot_id]
        records = [
            record
            for (slot_id, _), values in pair_records.items()
            if slot_id == runtime_slot_id
            for record in values
        ]
        conflicts.append(
            SlotAssociationConflict(
                conflict_type=(
                    SlotAssociationConflictType.SLOT_MULTIPLE_PARTICIPANT_CLAIMS
                ),
                layout_id=layout_id,
                runtime_slot_ids=(runtime_slot_id,),
                session_player_ids=tuple(sorted(participant_ids)),
                record_ids=tuple(sorted(record.record_id for record in records)),
            )
        )
    for participant_id in sorted(conflict_participants):
        runtime_slot_ids = slot_ids_by_participant[participant_id]
        records = [
            record
            for (slot_id, claimed_participant_id), values in pair_records.items()
            if slot_id in runtime_slot_ids
            and claimed_participant_id == participant_id
            for record in values
        ]
        conflicts.append(
            SlotAssociationConflict(
                conflict_type=(
                    SlotAssociationConflictType.PARTICIPANT_MULTIPLE_SLOT_CLAIMS
                ),
                layout_id=layout_id,
                runtime_slot_ids=tuple(sorted(runtime_slot_ids)),
                session_player_ids=(participant_id,),
                record_ids=tuple(sorted(record.record_id for record in records)),
            )
        )

    associations: list[EffectiveSlotParticipantAssociation] = []
    for (runtime_slot_id, participant_id), records in sorted(pair_records.items()):
        if (
            runtime_slot_id in conflict_slots
            or participant_id in conflict_participants
        ):
            continue
        associations.append(
            EffectiveSlotParticipantAssociation(
                layout_id=layout_id,
                runtime_slot_id=runtime_slot_id,
                session_player_id=participant_id,
                supporting_record_ids=tuple(
                    sorted(record.record_id for record in records)
                ),
                evidence_ids=tuple(
                    sorted(
                        {
                            evidence_id
                            for record in records
                            for evidence_id in record.evidence_ids
                            if evidence_id in effective_evidence
                        }
                    )
                ),
                bases=tuple(sorted({record.basis for record in records})),
            )
        )
    return SlotAssociationView(
        session_id=session_id,
        current_layout_id=layout_id,
        associations=tuple(associations),
        conflicts=tuple(conflicts),
        ineligible_record_ids=tuple(sorted(ineligible)),
        superseded_record_ids=tuple(
            sorted(association_state.superseded_record_ids)
        ),
    )


def _record_is_current_and_supported(
    record: SlotParticipantAssociationRecord,
    *,
    layout_id: RuntimeSlotLayoutId,
    current_slot_ids: frozenset[RuntimeSlotId],
    entrant_ids: frozenset[SessionParticipantId],
    player_tags: dict[SessionParticipantId, PlayerTag],
    self_participant_id: SessionParticipantId | None,
    effective_evidence: dict[EvidenceId, RuntimeSlotObservation],
) -> bool:
    if (
        record.layout_id != layout_id
        or record.runtime_slot_id not in current_slot_ids
        or record.session_player_id not in entrant_ids
    ):
        return False
    supporting = tuple(
        effective_evidence[evidence_id]
        for evidence_id in record.evidence_ids
        if evidence_id in effective_evidence
        and effective_evidence[evidence_id].layout_id == record.layout_id
        and effective_evidence[evidence_id].runtime_slot_id == record.runtime_slot_id
    )
    if not supporting:
        return False
    if record.basis == SlotParticipantAssociationBasis.DIRECT_PLAYER_TAG:
        expected_tag = player_tags.get(record.session_player_id)
        return expected_tag is not None and any(
            observation.observed_player_tag == expected_tag
            for observation in supporting
        )
    if record.basis == SlotParticipantAssociationBasis.DIRECT_SELF_MARKER:
        return record.session_player_id == self_participant_id and any(
            observation.self_marker_visible for observation in supporting
        )
    return record.basis == SlotParticipantAssociationBasis.MANUAL_CONFIRMATION


def _presentation(observation: RuntimeSlotObservation) -> RuntimeSlotPresentation:
    if observation.normal_active_presentation_visible:
        return RuntimeSlotPresentation.NORMAL_ACTIVE
    if observation.inactive_presentation == InactivePresentation.DEPARTED:
        return RuntimeSlotPresentation.DEPARTED
    if observation.inactive_presentation == InactivePresentation.SPECTATING:
        return RuntimeSlotPresentation.SPECTATING
    if observation.inactive_presentation == InactivePresentation.UNKNOWN:
        return RuntimeSlotPresentation.INACTIVE_UNKNOWN
    return RuntimeSlotPresentation.VISIBLE_UNKNOWN
