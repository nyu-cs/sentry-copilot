from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from .identifiers import (
    EvidenceId,
    LegacyMigrationOperationId,
    SessionId,
    SnapshotFingerprint,
    StrategyIdentificationRecordId,
)


class LegacySnapshotMigrationRecord(BaseModel):
    """One explicit, audited import of a legacy prebattle materialized snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: LegacyMigrationOperationId
    session_id: SessionId
    snapshot_fingerprint: SnapshotFingerprint
    snapshot_captured_at: AwareDatetime
    migrated_at: AwareDatetime
    ready_evidence_ids: tuple[EvidenceId, ...] = Field(default_factory=tuple)
    strategy_evidence_ids: tuple[EvidenceId, ...] = Field(default_factory=tuple)
    identification_record_ids: tuple[StrategyIdentificationRecordId, ...] = Field(
        default_factory=tuple
    )
    reason: str | None = None

    @field_validator(
        "ready_evidence_ids",
        "strategy_evidence_ids",
        "identification_record_ids",
    )
    @classmethod
    def reference_ids_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy migration reference IDs must be unique")
        return value

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("legacy migration reason cannot be blank")
        return value


class LegacyPrebattleMigrationState(BaseModel):
    """Immutable migration history keyed by operation and canonical snapshot identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    records: tuple[LegacySnapshotMigrationRecord, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def operation_and_snapshot_ids_are_unique(self) -> LegacyPrebattleMigrationState:
        operation_ids = [record.operation_id for record in self.records]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("legacy migration operation IDs must be unique")
        fingerprints = [record.snapshot_fingerprint for record in self.records]
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError("each legacy snapshot fingerprint may be migrated only once")
        if any(record.session_id != self.session_id for record in self.records):
            raise ValueError("legacy migration record session_id must match its state")
        return self

    def for_operation(
        self,
        operation_id: LegacyMigrationOperationId,
    ) -> LegacySnapshotMigrationRecord | None:
        return next(
            (record for record in self.records if record.operation_id == operation_id),
            None,
        )

    def for_snapshot(
        self,
        fingerprint: SnapshotFingerprint,
    ) -> LegacySnapshotMigrationRecord | None:
        return next(
            (
                record
                for record in self.records
                if record.snapshot_fingerprint == fingerprint
            ),
            None,
        )
