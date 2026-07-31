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

from .enums import EvidenceKind
from .identifiers import EvidenceId, SessionId, SessionParticipantId
from .prebattle import (
    BattleEntryConfirmed,
    BattleEntryNotConfirmed,
    PrebattleEvidenceLedger,
)


class PlayerParticipationStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class PlayerInactivationReason(StrEnum):
    LEFT_OR_DISCONNECTED = "left_or_disconnected"
    HP_DEPLETED = "hp_depleted"
    UNKNOWN = "unknown"


class InactivePresentation(StrEnum):
    DEPARTED = "departed"
    SPECTATING = "spectating"
    UNKNOWN = "unknown"


class BattleRuntimeStageType(StrEnum):
    NORMAL = "normal"
    SECRET_CORE = "secret_core"


class BattleEntryStatus(StrEnum):
    CONFIRMED = "confirmed"
    NOT_CONFIRMED = "not_confirmed"
    UNKNOWN = "unknown"


class InactivationDetails(BaseModel):
    """Immutable business details for one effective inactivation fact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage_type: BattleRuntimeStageType
    round_number: int | None = Field(default=None, ge=1)
    wave_number: int | None = Field(default=None, ge=1)
    reason: PlayerInactivationReason
    presentation: InactivePresentation
    hp: int | None = None

    @model_validator(mode="after")
    def details_are_consistent(self) -> InactivationDetails:
        if (
            self.stage_type == BattleRuntimeStageType.SECRET_CORE
            and self.round_number is not None
        ):
            raise ValueError("secret-core inactivation cannot use a normal round number")
        if self.presentation == InactivePresentation.SPECTATING and self.reason != (
            PlayerInactivationReason.HP_DEPLETED
        ):
            raise ValueError("spectating requires HP-depleted inactivation")
        if self.reason == PlayerInactivationReason.LEFT_OR_DISCONNECTED and (
            self.presentation != InactivePresentation.DEPARTED
        ):
            raise ValueError("left-or-disconnected inactivation must be departed")
        if self.hp is not None and self.hp <= 0 and self.reason != (
            PlayerInactivationReason.HP_DEPLETED
        ):
            raise ValueError("non-positive HP requires HP-depleted inactivation")
        if self.hp is not None and self.hp > 0 and self.reason == (
            PlayerInactivationReason.HP_DEPLETED
        ):
            raise ValueError("HP-depleted inactivation cannot carry positive HP")
        return self


class BattleParticipantInactivated(InactivationDetails):
    """Observed terminal game transition for one confirmed battle entrant."""

    type: Literal["battle_participant_inactivated"] = (
        "battle_participant_inactivated"
    )
    evidence_id: EvidenceId
    session_id: SessionId
    session_player_id: SessionParticipantId
    observed_at: AwareDatetime
    previous_status: Literal[PlayerParticipationStatus.ACTIVE] = (
        PlayerParticipationStatus.ACTIVE
    )
    new_status: Literal[PlayerParticipationStatus.INACTIVE] = (
        PlayerParticipationStatus.INACTIVE
    )
    provenance: EvidenceKind
    confidence: float = Field(ge=0.0, le=1.0)
    source_detail: str | None = None
    evidence_reference: str | None = None
    observed_visual_cue: str | None = None

    @field_validator("source_detail", "evidence_reference", "observed_visual_cue")
    @classmethod
    def optional_text_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("inactivation evidence text cannot be blank")
        return value

    @model_validator(mode="after")
    def includes_evidence_reference(self) -> BattleParticipantInactivated:
        if not any(
            (self.source_detail, self.evidence_reference, self.observed_visual_cue)
        ):
            raise ValueError("inactivation requires evidence detail or reference")
        return self


class BattleInactivationReplacement(InactivationDetails):
    """Corrected assistant interpretation of the original transition fact."""

    inactivated_at: AwareDatetime


class BattleInactivationCorrected(BaseModel):
    """Manual audit correction; it is not an in-game reactivation event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["battle_inactivation_corrected"] = "battle_inactivation_corrected"
    evidence_id: EvidenceId
    session_id: SessionId
    session_player_id: SessionParticipantId
    corrected_at: AwareDatetime
    provenance: Literal[EvidenceKind.MANUAL] = EvidenceKind.MANUAL
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    invalidated_inactivation_evidence_id: EvidenceId
    replacement: BattleInactivationReplacement | None = None
    reason: str

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("inactivation correction reason cannot be blank")
        return value

    @model_validator(mode="after")
    def replacement_cannot_follow_correction(self) -> BattleInactivationCorrected:
        if (
            self.replacement is not None
            and self.replacement.inactivated_at > self.corrected_at
        ):
            raise ValueError("corrected inactivation cannot occur after its correction")
        return self


BattleParticipationEntry = Annotated[
    BattleParticipantInactivated | BattleInactivationCorrected,
    Field(discriminator="type"),
]


class EffectiveBattleInactivation(InactivationDetails):
    """Current assistant interpretation derived from immutable history."""

    session_player_id: SessionParticipantId
    source_evidence_id: EvidenceId
    inactivated_at: AwareDatetime


class BattleParticipationState(BaseModel):
    """Append-only inactivation observations and manual correction history."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    entries: tuple[BattleParticipationEntry, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def history_is_consistent(self) -> BattleParticipationState:
        evidence_ids = [entry.evidence_id for entry in self.entries]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("battle participation evidence IDs must be unique")
        if any(entry.session_id != self.session_id for entry in self.entries):
            raise ValueError("battle participation entry session_id must match its state")

        effective: dict[SessionParticipantId, EffectiveBattleInactivation] = {}
        sources: dict[EvidenceId, SessionParticipantId] = {}
        source_times: dict[EvidenceId, AwareDatetime] = {}
        for entry in self.entries:
            if isinstance(entry, BattleParticipantInactivated):
                if entry.session_player_id in effective:
                    raise ValueError("inactive participant cannot transition again")
                effective[entry.session_player_id] = _effective_from_observation(entry)
                sources[entry.evidence_id] = entry.session_player_id
                source_times[entry.evidence_id] = entry.observed_at
                continue

            target_participant = sources.get(
                entry.invalidated_inactivation_evidence_id
            )
            if target_participant is None:
                raise ValueError("inactivation correction target must be effective")
            if target_participant != entry.session_player_id:
                raise ValueError("inactivation correction cannot cross participants")
            if entry.corrected_at < source_times[entry.invalidated_inactivation_evidence_id]:
                raise ValueError("inactivation correction cannot precede its target")
            current = effective.get(entry.session_player_id)
            if (
                current is None
                or current.source_evidence_id
                != entry.invalidated_inactivation_evidence_id
            ):
                raise ValueError("inactivation correction target was already superseded")
            del effective[entry.session_player_id]
            if entry.replacement is not None:
                corrected = _effective_from_correction(entry)
                effective[entry.session_player_id] = corrected
                sources[entry.evidence_id] = entry.session_player_id
                source_times[entry.evidence_id] = entry.corrected_at
        return self

    def get(self, evidence_id: EvidenceId) -> BattleParticipationEntry | None:
        return next(
            (entry for entry in self.entries if entry.evidence_id == evidence_id),
            None,
        )

    @property
    def effective_inactivations(self) -> tuple[EffectiveBattleInactivation, ...]:
        effective: dict[SessionParticipantId, EffectiveBattleInactivation] = {}
        for entry in self.entries:
            if isinstance(entry, BattleParticipantInactivated):
                effective[entry.session_player_id] = _effective_from_observation(entry)
                continue
            effective.pop(entry.session_player_id, None)
            if entry.replacement is not None:
                effective[entry.session_player_id] = _effective_from_correction(entry)
        return tuple(effective[key] for key in sorted(effective))


class BattleRosterParticipant(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_player_id: SessionParticipantId
    entered_at: AwareDatetime
    entry_evidence_ids: tuple[EvidenceId, ...] = Field(min_length=1)
    participation_status: PlayerParticipationStatus
    inactivated_at: AwareDatetime | None = None
    inactivation_reason: PlayerInactivationReason | None = None
    inactive_presentation: InactivePresentation | None = None
    stage_type: BattleRuntimeStageType | None = None
    round_number: int | None = Field(default=None, ge=1)
    wave_number: int | None = Field(default=None, ge=1)
    hp: int | None = None
    inactivation_evidence_ids: tuple[EvidenceId, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def status_controls_inactivation_fields(self) -> BattleRosterParticipant:
        details = (
            self.inactivated_at,
            self.inactivation_reason,
            self.inactive_presentation,
            self.stage_type,
        )
        if self.participation_status == PlayerParticipationStatus.ACTIVE:
            if (
                any(value is not None for value in details)
                or self.round_number is not None
                or self.wave_number is not None
                or self.hp is not None
                or self.inactivation_evidence_ids
            ):
                raise ValueError("active roster participant cannot have inactivation state")
        elif (
            any(value is None for value in details)
            or not self.inactivation_evidence_ids
        ):
            raise ValueError("inactive roster participant requires inactivation state")
        elif self.inactivated_at is not None and self.inactivated_at < self.entered_at:
            raise ValueError("inactivation cannot precede effective battle entry")
        return self


class BattleRoster(BaseModel):
    """Query-derived confirmed entrants and their current participation state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    participants: tuple[BattleRosterParticipant, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def participants_are_unique(self) -> BattleRoster:
        participant_ids = [item.session_player_id for item in self.participants]
        if len(participant_ids) != len(set(participant_ids)):
            raise ValueError("battle roster participants must be unique")
        return self

    def for_participant(
        self,
        session_player_id: SessionParticipantId,
    ) -> BattleRosterParticipant | None:
        return next(
            (
                participant
                for participant in self.participants
                if participant.session_player_id == session_player_id
            ),
            None,
        )


def derive_battle_roster(
    *,
    session_id: SessionId,
    prebattle_evidence: PrebattleEvidenceLedger | None,
    participation_state: BattleParticipationState | None,
) -> BattleRoster:
    """Derive entrants without treating UI presence, ready, or occupancy as entry."""

    invalidated_entry_ids = (
        prebattle_evidence.invalidated_battle_entry_evidence_ids
        if prebattle_evidence is not None
        else frozenset()
    )
    entry_by_participant: dict[SessionParticipantId, list[BattleEntryConfirmed]] = {}
    if prebattle_evidence is not None:
        for entry in prebattle_evidence.entries:
            if (
                isinstance(entry, BattleEntryConfirmed)
                and entry.evidence_id not in invalidated_entry_ids
            ):
                entry_by_participant.setdefault(
                    entry.session_player_id,
                    [],
                ).append(entry)

    inactivation_by_participant = {
        item.session_player_id: item
        for item in (
            participation_state.effective_inactivations
            if participation_state is not None
            else ()
        )
    }
    participants: list[BattleRosterParticipant] = []
    for participant_id, entry_evidence in sorted(entry_by_participant.items()):
        ordered_entry = sorted(
            entry_evidence,
            key=lambda item: (item.timestamp, item.evidence_id),
        )
        inactivation = inactivation_by_participant.get(participant_id)
        participants.append(
            BattleRosterParticipant(
                session_player_id=participant_id,
                entered_at=ordered_entry[0].timestamp,
                entry_evidence_ids=tuple(item.evidence_id for item in ordered_entry),
                participation_status=(
                    PlayerParticipationStatus.INACTIVE
                    if inactivation is not None
                    else PlayerParticipationStatus.ACTIVE
                ),
                inactivated_at=(
                    inactivation.inactivated_at if inactivation is not None else None
                ),
                inactivation_reason=(
                    inactivation.reason if inactivation is not None else None
                ),
                inactive_presentation=(
                    inactivation.presentation if inactivation is not None else None
                ),
                stage_type=(
                    inactivation.stage_type if inactivation is not None else None
                ),
                round_number=(
                    inactivation.round_number if inactivation is not None else None
                ),
                wave_number=(
                    inactivation.wave_number if inactivation is not None else None
                ),
                hp=inactivation.hp if inactivation is not None else None,
                inactivation_evidence_ids=(
                    (inactivation.source_evidence_id,)
                    if inactivation is not None
                    else ()
                ),
            )
        )
    return BattleRoster(session_id=session_id, participants=tuple(participants))


def battle_entry_status(
    ledger: PrebattleEvidenceLedger | None,
    session_player_id: SessionParticipantId,
) -> BattleEntryStatus:
    if ledger is None:
        return BattleEntryStatus.UNKNOWN
    if any(
        isinstance(entry, BattleEntryConfirmed)
        and entry.session_player_id == session_player_id
        and entry.evidence_id not in ledger.invalidated_battle_entry_evidence_ids
        for entry in ledger.entries
    ):
        return BattleEntryStatus.CONFIRMED
    if any(
        isinstance(entry, BattleEntryNotConfirmed)
        and entry.session_player_id == session_player_id
        for entry in ledger.entries
    ):
        return BattleEntryStatus.NOT_CONFIRMED
    return BattleEntryStatus.UNKNOWN


def _effective_from_observation(
    entry: BattleParticipantInactivated,
) -> EffectiveBattleInactivation:
    return EffectiveBattleInactivation(
        session_player_id=entry.session_player_id,
        source_evidence_id=entry.evidence_id,
        inactivated_at=entry.observed_at,
        stage_type=entry.stage_type,
        round_number=entry.round_number,
        wave_number=entry.wave_number,
        reason=entry.reason,
        presentation=entry.presentation,
        hp=entry.hp,
    )


def _effective_from_correction(
    entry: BattleInactivationCorrected,
) -> EffectiveBattleInactivation:
    replacement = entry.replacement
    if replacement is None:
        raise ValueError("correction without replacement has no inactivation fact")
    return EffectiveBattleInactivation(
        session_player_id=entry.session_player_id,
        source_evidence_id=entry.evidence_id,
        inactivated_at=replacement.inactivated_at,
        stage_type=replacement.stage_type,
        round_number=replacement.round_number,
        wave_number=replacement.wave_number,
        reason=replacement.reason,
        presentation=replacement.presentation,
        hp=replacement.hp,
    )
