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


class NormalizedRoi(BaseModel):
    """A normalized region within the source game-content viewport."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def region_stays_inside_viewport(self) -> NormalizedRoi:
        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise ValueError("normalized ROI must stay inside the content viewport")
        return self


class PrebattleObservationKind(StrEnum):
    STRATEGY_CANDIDATE = "strategy_candidate"
    READY_CHECK = "ready_check"
    READY_FALSE_POSITIVE_CORRECTION = "ready_false_positive_correction"
    BATTLE_ENTRY_CONFIRMED = "battle_entry_confirmed"
    BATTLE_ENTRY_NOT_CONFIRMED = "battle_entry_not_confirmed"
    STRATEGY_SELECTION_CONFIRMED = "strategy_selection_confirmed"


class BattleEntryNotConfirmedReason(StrEnum):
    """Why battle entry cannot be established from the available frame history."""

    FIRST_STABLE_FRAME_ALREADY_INACTIVE = "first_stable_frame_already_inactive"
    NORMAL_PARTICIPATION_NOT_OBSERVED = "normal_participation_not_observed"


class StrategySelectionConfirmationSource(StrEnum):
    """Strong concrete evidence that also proves some strategy was selected."""

    DIRECT_STRATEGY_OBSERVATION = "direct_strategy_observation"
    MANUAL_STRATEGY_CONFIRMATION = "manual_strategy_confirmation"


class PrebattleObservationBase(BaseModel):
    """Immutable raw prebattle evidence tied to one known session participant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: EvidenceId
    session_id: SessionId
    session_player_id: SessionParticipantId
    timestamp: AwareDatetime
    provenance: EvidenceKind
    confidence: float = Field(ge=0.0, le=1.0)
    source_detail: str | None = None
    frame_reference: str | None = None
    roi: NormalizedRoi | None = None
    observed_visual_cue: str | None = None
    observed_text: str | None = None
    manual_note: str | None = None

    @field_validator(
        "source_detail",
        "frame_reference",
        "observed_visual_cue",
        "observed_text",
        "manual_note",
    )
    @classmethod
    def optional_text_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("prebattle evidence text fields cannot be blank")
        return value

    @model_validator(mode="after")
    def includes_raw_observation_reference(self) -> PrebattleObservationBase:
        if not any(
            (
                self.frame_reference,
                self.roi,
                self.observed_visual_cue,
                self.observed_text,
                self.manual_note,
            )
        ):
            raise ValueError(
                "prebattle observation requires a frame, ROI, visual cue, or observed text"
            )
        return self


class StrategyCandidateObserved(PrebattleObservationBase):
    """A raw visual/text candidate; it is not a normalized strategy interpretation."""

    type: Literal["prebattle_strategy_candidate_observed"] = (
        "prebattle_strategy_candidate_observed"
    )
    kind: Literal[PrebattleObservationKind.STRATEGY_CANDIDATE] = (
        PrebattleObservationKind.STRATEGY_CANDIDATE
    )


class ReadyCheckObserved(PrebattleObservationBase):
    """Positive evidence that the participant's ready check was visible."""

    type: Literal["prebattle_ready_check_observed"] = "prebattle_ready_check_observed"
    kind: Literal[PrebattleObservationKind.READY_CHECK] = (
        PrebattleObservationKind.READY_CHECK
    )
    ready_check_visible: Literal[True] = True


class BattleEntryConfirmed(PrebattleObservationBase):
    """Evidence that normal active participation was actually observed in battle."""

    type: Literal["battle_entry_confirmed"] = "battle_entry_confirmed"
    kind: Literal[PrebattleObservationKind.BATTLE_ENTRY_CONFIRMED] = (
        PrebattleObservationKind.BATTLE_ENTRY_CONFIRMED
    )
    normal_participation_visible: Literal[True] = True


class BattleEntryNotConfirmed(PrebattleObservationBase):
    """Conservative evidence that displayed-in-UI does not prove battle entry."""

    type: Literal["battle_entry_not_confirmed"] = "battle_entry_not_confirmed"
    kind: Literal[PrebattleObservationKind.BATTLE_ENTRY_NOT_CONFIRMED] = (
        PrebattleObservationKind.BATTLE_ENTRY_NOT_CONFIRMED
    )
    reason: BattleEntryNotConfirmedReason


class StrategySelectionConfirmedEvidence(PrebattleObservationBase):
    """Direct/manual concrete evidence that also confirms a formal selection."""

    type: Literal["strategy_selection_confirmed_evidence"] = (
        "strategy_selection_confirmed_evidence"
    )
    kind: Literal[PrebattleObservationKind.STRATEGY_SELECTION_CONFIRMED] = (
        PrebattleObservationKind.STRATEGY_SELECTION_CONFIRMED
    )
    confirmation_source: StrategySelectionConfirmationSource
    manual_reason: str | None = None

    @model_validator(mode="after")
    def confirmation_source_matches_provenance(
        self,
    ) -> StrategySelectionConfirmedEvidence:
        if (
            self.confirmation_source
            == StrategySelectionConfirmationSource.MANUAL_STRATEGY_CONFIRMATION
        ):
            if self.provenance != EvidenceKind.MANUAL:
                raise ValueError("manual strategy confirmation requires manual provenance")
            if self.manual_reason is None or not self.manual_reason.strip():
                raise ValueError("manual strategy confirmation requires a reason")
        elif self.provenance == EvidenceKind.MANUAL:
            raise ValueError("direct strategy observation cannot use manual provenance")
        return self


class ReadyFalsePositiveCorrected(BaseModel):
    """Manual correction that invalidates false-positive ready evidence.

    This corrects the assistant record. It does not represent an in-game unready action.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["prebattle_ready_false_positive_corrected"] = (
        "prebattle_ready_false_positive_corrected"
    )
    kind: Literal[PrebattleObservationKind.READY_FALSE_POSITIVE_CORRECTION] = (
        PrebattleObservationKind.READY_FALSE_POSITIVE_CORRECTION
    )
    evidence_id: EvidenceId
    session_id: SessionId
    session_player_id: SessionParticipantId
    timestamp: AwareDatetime
    provenance: Literal[EvidenceKind.MANUAL] = EvidenceKind.MANUAL
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    invalidated_ready_evidence_ids: tuple[EvidenceId, ...] = Field(min_length=1)
    reason: str

    @field_validator("invalidated_ready_evidence_ids")
    @classmethod
    def target_ids_must_be_unique(
        cls,
        value: tuple[EvidenceId, ...],
    ) -> tuple[EvidenceId, ...]:
        if len(value) != len(set(value)):
            raise ValueError("invalidated ready evidence IDs must be unique")
        return value

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ready false-positive correction reason cannot be blank")
        return value


PrebattleEvidenceEntry = Annotated[
    StrategyCandidateObserved
    | ReadyCheckObserved
    | BattleEntryConfirmed
    | BattleEntryNotConfirmed
    | StrategySelectionConfirmedEvidence
    | ReadyFalsePositiveCorrected,
    Field(discriminator="type"),
]


class PrebattleEvidenceLedger(BaseModel):
    """Append-only, evidence-ID-addressed prebattle history for one session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    entries: tuple[PrebattleEvidenceEntry, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def entries_are_session_consistent_and_id_unique(self) -> PrebattleEvidenceLedger:
        evidence_ids = [entry.evidence_id for entry in self.entries]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("prebattle evidence IDs must be unique")
        if any(entry.session_id != self.session_id for entry in self.entries):
            raise ValueError("prebattle evidence entry session_id must match its ledger")

        by_id = {entry.evidence_id: entry for entry in self.entries}
        positions = {
            entry.evidence_id: index for index, entry in enumerate(self.entries)
        }
        for entry_index, entry in enumerate(self.entries):
            if not isinstance(entry, ReadyFalsePositiveCorrected):
                continue
            for target_id in entry.invalidated_ready_evidence_ids:
                target = by_id.get(target_id)
                if not isinstance(target, ReadyCheckObserved):
                    raise ValueError(
                        "ready correction targets must reference ready-check evidence"
                    )
                if positions[target_id] >= entry_index:
                    raise ValueError(
                        "ready correction targets must precede the correction"
                    )
                if target.session_player_id != entry.session_player_id:
                    raise ValueError(
                        "ready correction targets must belong to the same participant"
                    )
                if entry.timestamp < target.timestamp:
                    raise ValueError(
                        "ready correction cannot precede its target evidence"
                    )
        return self

    def get(self, evidence_id: EvidenceId) -> PrebattleEvidenceEntry | None:
        for entry in self.entries:
            if entry.evidence_id == evidence_id:
                return entry
        return None

    @property
    def invalidated_ready_evidence_ids(self) -> frozenset[EvidenceId]:
        return frozenset(
            target_id
            for entry in self.entries
            if isinstance(entry, ReadyFalsePositiveCorrected)
            for target_id in entry.invalidated_ready_evidence_ids
        )
