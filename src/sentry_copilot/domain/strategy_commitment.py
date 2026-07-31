from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .identifiers import EvidenceId, SessionId, SessionParticipantId
from .prebattle import (
    BattleEntryConfirmed,
    LegacyReadySnapshotImported,
    PrebattleEvidenceLedger,
    ReadyCheckObserved,
    StrategySelectionConfirmedEvidence,
)


class ParticipantCommitmentLevel(StrEnum):
    """Current assistant interpretation of one participant's ready commitment."""

    OBSERVING = "observing"
    READY_CONFIRMED_STRATEGY_UNKNOWN = "ready_confirmed_strategy_unknown"


class ReadyConfirmedCommitment(BaseModel):
    """Current interpretation of an irreversible in-game ready confirmation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_player_id: SessionParticipantId
    confirmed_at: AwareDatetime
    ready_evidence_ids: tuple[EvidenceId, ...] = Field(default_factory=tuple)
    battle_entry_evidence_ids: tuple[EvidenceId, ...] = Field(default_factory=tuple)
    strategy_confirmation_evidence_ids: tuple[EvidenceId, ...] = Field(
        default_factory=tuple
    )

    @model_validator(mode="after")
    def evidence_ids_are_unique(self) -> ReadyConfirmedCommitment:
        evidence_ids = (
            *self.ready_evidence_ids,
            *self.battle_entry_evidence_ids,
            *self.strategy_confirmation_evidence_ids,
        )
        if not evidence_ids:
            raise ValueError("a commitment requires effective confirmation evidence")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("commitment evidence IDs must be unique")
        return self


class StrategyCommitmentState(BaseModel):
    """Immutable materialization of effective formal-selection evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    commitments: tuple[ReadyConfirmedCommitment, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def participants_are_unique(self) -> StrategyCommitmentState:
        participant_ids = [
            commitment.session_player_id for commitment in self.commitments
        ]
        if len(participant_ids) != len(set(participant_ids)):
            raise ValueError("strategy commitments must be participant-unique")
        return self

    def for_participant(
        self,
        session_player_id: SessionParticipantId,
    ) -> ReadyConfirmedCommitment | None:
        for commitment in self.commitments:
            if commitment.session_player_id == session_player_id:
                return commitment
        return None


def derive_strategy_commitments(
    ledger: PrebattleEvidenceLedger,
) -> StrategyCommitmentState:
    """Derive commitments from ready, entry, or concrete-selection confirmation."""

    invalidated_ids = ledger.invalidated_ready_evidence_ids
    invalidated_entry_ids = ledger.invalidated_battle_entry_evidence_ids
    effective_confirmation = [
        entry
        for entry in ledger.entries
        if (
            isinstance(
                entry,
                (
                    ReadyCheckObserved,
                    LegacyReadySnapshotImported,
                    BattleEntryConfirmed,
                    StrategySelectionConfirmedEvidence,
                ),
            )
            and entry.evidence_id not in invalidated_ids
            and not (
                isinstance(entry, BattleEntryConfirmed)
                and entry.evidence_id in invalidated_entry_ids
            )
        )
    ]
    participant_ids = sorted(
        {entry.session_player_id for entry in effective_confirmation}
    )
    commitments: list[ReadyConfirmedCommitment] = []
    for participant_id in participant_ids:
        participant_evidence = sorted(
            (
                entry
                for entry in effective_confirmation
                if entry.session_player_id == participant_id
            ),
            key=lambda entry: (entry.timestamp, entry.evidence_id),
        )
        commitments.append(
            ReadyConfirmedCommitment(
                session_player_id=participant_id,
                confirmed_at=participant_evidence[0].timestamp,
                ready_evidence_ids=tuple(
                    entry.evidence_id for entry in participant_evidence
                    if isinstance(
                        entry,
                        (ReadyCheckObserved, LegacyReadySnapshotImported),
                    )
                ),
                battle_entry_evidence_ids=tuple(
                    entry.evidence_id for entry in participant_evidence
                    if isinstance(entry, BattleEntryConfirmed)
                ),
                strategy_confirmation_evidence_ids=tuple(
                    entry.evidence_id for entry in participant_evidence
                    if isinstance(entry, StrategySelectionConfirmedEvidence)
                ),
            )
        )
    return StrategyCommitmentState(
        session_id=ledger.session_id,
        commitments=tuple(commitments),
    )
