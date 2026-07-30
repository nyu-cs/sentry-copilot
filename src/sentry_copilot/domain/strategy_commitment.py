from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .identifiers import EvidenceId, SessionId, SessionParticipantId
from .prebattle import PrebattleEvidenceLedger, ReadyCheckObserved


class ParticipantCommitmentLevel(StrEnum):
    """Current assistant interpretation of one participant's ready commitment."""

    OBSERVING = "observing"
    READY_CONFIRMED_STRATEGY_UNKNOWN = "ready_confirmed_strategy_unknown"


class ReadyConfirmedCommitment(BaseModel):
    """Current interpretation of an irreversible in-game ready confirmation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_player_id: SessionParticipantId
    confirmed_at: AwareDatetime
    ready_evidence_ids: tuple[EvidenceId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def evidence_ids_are_unique(self) -> ReadyConfirmedCommitment:
        if len(self.ready_evidence_ids) != len(set(self.ready_evidence_ids)):
            raise ValueError("commitment ready evidence IDs must be unique")
        return self


class StrategyCommitmentState(BaseModel):
    """Immutable materialization of currently effective ready evidence."""

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
    """Derive current commitments without deleting corrected historical evidence."""

    invalidated_ids = ledger.invalidated_ready_evidence_ids
    effective_ready = [
        entry
        for entry in ledger.entries
        if isinstance(entry, ReadyCheckObserved)
        and entry.evidence_id not in invalidated_ids
    ]
    participant_ids = sorted({entry.session_player_id for entry in effective_ready})
    commitments: list[ReadyConfirmedCommitment] = []
    for participant_id in participant_ids:
        participant_evidence = sorted(
            (
                entry
                for entry in effective_ready
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
                ),
            )
        )
    return StrategyCommitmentState(
        session_id=ledger.session_id,
        commitments=tuple(commitments),
    )
