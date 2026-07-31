from __future__ import annotations

from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .evidence import EvidenceRecord
from .identifiers import (
    CatalogVersion,
    LocaleId,
    RulesetId,
    RulesetRevisionId,
    SessionId,
)
from .prebattle import (
    StrategySelectionConfirmationSource,
    StrategySelectionConfirmedEvidence,
)
from .rulesets import RevisionSelectionMethod
from .strategy_identification import (
    StrategyIdentificationBasis,
    StrategyIdentificationRecord,
)


class RulesetContextCommand(BaseModel):
    """Shared immutable input for explicit ruleset-context operations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
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
            raise ValueError("ruleset context command reason cannot be blank")
        return value


class SelectSessionRulesetContext(RulesetContextCommand):
    """Select a concrete revision manually or from explicit replay metadata."""

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
                "initial selection must be manual or imported from replay metadata"
            )
        return value


class CorrectSessionRulesetRevision(RulesetContextCommand):
    """Explicitly correct the current revision or catalog version."""

    selection_method: Literal[RevisionSelectionMethod.MANUAL] = (
        RevisionSelectionMethod.MANUAL
    )


class RecordStrategyIdentification(BaseModel):
    """Request one concrete claim, optionally with atomic commitment evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    record: StrategyIdentificationRecord
    commitment_evidence: StrategySelectionConfirmedEvidence | None = None

    @model_validator(mode="after")
    def evidence_matches_record(self) -> RecordStrategyIdentification:
        if self.record.supersedes_record_ids:
            raise ValueError("initial identification cannot supersede existing records")
        evidence = self.commitment_evidence
        if evidence is None:
            return self
        if evidence.session_id != self.session_id:
            raise ValueError("commitment evidence session_id must match the command")
        if evidence.session_player_id != self.record.session_player_id:
            raise ValueError("commitment evidence participant must match the record")
        if evidence.evidence_id not in self.record.evidence_ids:
            raise ValueError("identification must reference its commitment evidence")
        expected_source = {
            StrategyIdentificationBasis.DIRECT_OBSERVATION: (
                StrategySelectionConfirmationSource.DIRECT_STRATEGY_OBSERVATION
            ),
            StrategyIdentificationBasis.MANUAL_CONFIRMATION: (
                StrategySelectionConfirmationSource.MANUAL_STRATEGY_CONFIRMATION
            ),
        }.get(self.record.basis)
        if expected_source is None or evidence.confirmation_source != expected_source:
            raise ValueError(
                "commitment evidence source must match direct/manual identification basis"
            )
        return self


class CorrectStrategyIdentifications(BaseModel):
    """Atomically append one or more explicit manual supersession records."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    records: tuple[StrategyIdentificationRecord, ...] = Field(min_length=1)
    correction_evidence: tuple[StrategySelectionConfirmedEvidence, ...] = Field(
        default_factory=tuple
    )

    @model_validator(mode="after")
    def records_are_manual_corrections(self) -> CorrectStrategyIdentifications:
        record_ids = [record.record_id for record in self.records]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("correction record IDs must be unique")
        if any(
            record.basis != StrategyIdentificationBasis.MANUAL_CONFIRMATION
            or not record.supersedes_record_ids
            for record in self.records
        ):
            raise ValueError(
                "identification corrections require manual supersession records"
            )
        evidence_ids = [evidence.evidence_id for evidence in self.correction_evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("correction evidence IDs must be unique")
        for evidence in self.correction_evidence:
            if evidence.session_id != self.session_id:
                raise ValueError("correction evidence session_id must match the command")
            if evidence.confirmation_source != (
                StrategySelectionConfirmationSource.MANUAL_STRATEGY_CONFIRMATION
            ):
                raise ValueError("correction evidence must be an explicit manual confirmation")
            matching_records = [
                record
                for record in self.records
                if record.session_player_id == evidence.session_player_id
                and evidence.evidence_id in record.evidence_ids
            ]
            if not matching_records:
                raise ValueError(
                    "manual correction record must reference its correction evidence"
                )
        return self
