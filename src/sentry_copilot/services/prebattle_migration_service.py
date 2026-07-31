from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Never

from pydantic import TypeAdapter, ValidationError

from sentry_copilot.catalogs.repository import (
    CatalogLookupError,
    StrategyCatalogRepository,
)
from sentry_copilot.domain.commands import ImportLegacyStrategySnapshotEvidence
from sentry_copilot.domain.events import LegacyPrebattleSnapshotMigrated
from sentry_copilot.domain.identifiers import (
    EvidenceId,
    SessionParticipantId,
    SnapshotFingerprint,
    StrategyId,
    StrategyIdentificationRecordId,
)
from sentry_copilot.domain.models import SessionState
from sentry_copilot.domain.prebattle import (
    LegacyReadySnapshotImported,
    LegacyStrategyInterpretationImported,
)
from sentry_copilot.domain.prebattle_migration import LegacySnapshotMigrationRecord
from sentry_copilot.domain.reducer import InvalidObservationError, reduce_session
from sentry_copilot.domain.strategy_identification import (
    StrategyIdentificationBasis,
    StrategyIdentificationRecord,
)
from sentry_copilot.domain.strategy_selection import (
    ParticipantField,
    StrategySelectionSnapshot,
)

_STRATEGY_ID_ADAPTER = TypeAdapter(StrategyId)


class LegacyMigrationErrorCode(StrEnum):
    SESSION_MISMATCH = "session_mismatch"
    SNAPSHOT_MISSING = "snapshot_missing"
    SNAPSHOT_FINGERPRINT_MISMATCH = "snapshot_fingerprint_mismatch"
    OPERATION_ID_COLLISION = "operation_id_collision"
    INVALID_MIGRATION = "invalid_migration"


class LegacyMigrationCommandError(ValueError):
    """Typed rejection for explicit legacy snapshot migration."""

    def __init__(self, code: LegacyMigrationErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class LegacyPrebattleSnapshotMigrationService:
    """Convert one legacy materialized snapshot into audited, idempotent evidence."""

    def __init__(self, catalog_repository: StrategyCatalogRepository) -> None:
        self._catalog_repository = catalog_repository

    @staticmethod
    def fingerprint_snapshot(
        snapshot: StrategySelectionSnapshot,
    ) -> SnapshotFingerprint:
        payload = json.dumps(
            snapshot.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def migrate(
        self,
        state: SessionState,
        command: ImportLegacyStrategySnapshotEvidence,
    ) -> SessionState:
        """Import ready and weak strategy interpretation facts atomically."""

        if state.session_id != command.session_id:
            self._reject(
                LegacyMigrationErrorCode.SESSION_MISMATCH,
                "migration command session_id does not match SessionState",
            )
        migrations = state.legacy_prebattle_migrations
        existing_operation = (
            migrations.for_operation(command.migration_operation_id)
            if migrations is not None
            else None
        )
        if existing_operation is not None:
            if not self._record_matches_command(existing_operation, command):
                self._reject(
                    LegacyMigrationErrorCode.OPERATION_ID_COLLISION,
                    "migration operation ID already has different content",
                )
            return state
        if (
            migrations is not None
            and migrations.for_snapshot(command.snapshot_fingerprint) is not None
        ):
            return state

        snapshot = state.strategy_selection
        if snapshot is None:
            self._reject(
                LegacyMigrationErrorCode.SNAPSHOT_MISSING,
                "legacy migration requires a strategy selection snapshot",
            )
        actual_fingerprint = self.fingerprint_snapshot(snapshot)
        if actual_fingerprint != command.snapshot_fingerprint:
            self._reject(
                LegacyMigrationErrorCode.SNAPSHOT_FINGERPRINT_MISMATCH,
                "command fingerprint does not match the current legacy snapshot",
            )

        ready_entries: list[LegacyReadySnapshotImported] = []
        strategy_entries: list[LegacyStrategyInterpretationImported] = []
        identification_records: list[StrategyIdentificationRecord] = []
        available_strategy_ids = self._available_strategy_ids(state)
        dependency_stamp = state.ruleset_dependency_stamp

        for participant in sorted(
            snapshot.participants,
            key=lambda item: item.selection_row,
        ):
            if participant.ready is True:
                ready_field_evidence = participant.field_evidence[ParticipantField.READY]
                ready_entries.append(
                    LegacyReadySnapshotImported(
                        evidence_id=self._evidence_id(
                            actual_fingerprint,
                            participant.session_player_id,
                            "ready",
                        ),
                        session_id=state.session_id,
                        session_player_id=participant.session_player_id,
                        migration_operation_id=command.migration_operation_id,
                        snapshot_fingerprint=actual_fingerprint,
                        timestamp=ready_field_evidence.observed_at,
                        migrated_at=command.migrated_at,
                        legacy_field_evidence=ready_field_evidence,
                    )
                )
            if participant.strategy_id is None:
                continue
            strategy_field_evidence = participant.field_evidence[
                ParticipantField.STRATEGY
            ]
            strategy_evidence = LegacyStrategyInterpretationImported(
                evidence_id=self._evidence_id(
                    actual_fingerprint,
                    participant.session_player_id,
                    "strategy",
                ),
                session_id=state.session_id,
                session_player_id=participant.session_player_id,
                migration_operation_id=command.migration_operation_id,
                snapshot_fingerprint=actual_fingerprint,
                timestamp=strategy_field_evidence.observed_at,
                migrated_at=command.migrated_at,
                legacy_field_evidence=strategy_field_evidence,
                legacy_strategy_id=participant.strategy_id,
            )
            strategy_entries.append(strategy_evidence)
            normalized_strategy_id = self._normalized_strategy_id(
                participant.strategy_id
            )
            if (
                normalized_strategy_id is None
                or dependency_stamp is None
                or normalized_strategy_id not in available_strategy_ids
            ):
                continue
            identification_records.append(
                StrategyIdentificationRecord(
                    record_id=self._identification_id(
                        actual_fingerprint,
                        participant.session_player_id,
                    ),
                    session_player_id=participant.session_player_id,
                    strategy_id=normalized_strategy_id,
                    basis=(
                        StrategyIdentificationBasis.LEGACY_SNAPSHOT_INTERPRETATION
                    ),
                    identified_at=strategy_field_evidence.observed_at,
                    evidence_ids=(strategy_evidence.evidence_id,),
                    dependency_stamp=dependency_stamp,
                    reason="imported legacy snapshot interpretation",
                )
            )

        event = LegacyPrebattleSnapshotMigrated(
            session_id=state.session_id,
            migration_record=LegacySnapshotMigrationRecord(
                operation_id=command.migration_operation_id,
                session_id=state.session_id,
                snapshot_fingerprint=actual_fingerprint,
                snapshot_captured_at=snapshot.captured_at,
                migrated_at=command.migrated_at,
                ready_evidence_ids=tuple(
                    entry.evidence_id for entry in ready_entries
                ),
                strategy_evidence_ids=tuple(
                    entry.evidence_id for entry in strategy_entries
                ),
                identification_record_ids=tuple(
                    record.record_id for record in identification_records
                ),
                reason=command.reason,
            ),
            evidence_entries=(*ready_entries, *strategy_entries),
            identification_records=tuple(identification_records),
        )
        try:
            candidate = reduce_session(state, event)
            return SessionState.model_validate(candidate.model_dump())
        except (InvalidObservationError, ValidationError) as exc:
            raise LegacyMigrationCommandError(
                LegacyMigrationErrorCode.INVALID_MIGRATION,
                "legacy snapshot migration failed whole-state validation",
            ) from exc

    def _available_strategy_ids(self, state: SessionState) -> frozenset[StrategyId]:
        stamp = state.ruleset_dependency_stamp
        if stamp is None:
            return frozenset()
        try:
            return self._catalog_repository.available_strategy_ids(
                catalog_version=stamp.catalog_version,
                ruleset_revision_id=stamp.ruleset_revision_id,
            )
        except CatalogLookupError:
            return frozenset()

    @staticmethod
    def _normalized_strategy_id(value: str) -> StrategyId | None:
        try:
            return _STRATEGY_ID_ADAPTER.validate_python(value)
        except ValidationError:
            return None

    @staticmethod
    def _record_matches_command(
        record: LegacySnapshotMigrationRecord,
        command: ImportLegacyStrategySnapshotEvidence,
    ) -> bool:
        return (
            record.session_id == command.session_id
            and record.operation_id == command.migration_operation_id
            and record.snapshot_fingerprint == command.snapshot_fingerprint
            and record.migrated_at == command.migrated_at
            and record.reason == command.reason
        )

    @staticmethod
    def _evidence_id(
        fingerprint: SnapshotFingerprint,
        participant_id: SessionParticipantId,
        field_name: str,
    ) -> EvidenceId:
        return f"evidence.legacy.{fingerprint}.{participant_id}.{field_name}"

    @staticmethod
    def _identification_id(
        fingerprint: SnapshotFingerprint,
        participant_id: SessionParticipantId,
    ) -> StrategyIdentificationRecordId:
        return f"identification.legacy.{fingerprint}.{participant_id}.strategy"

    @staticmethod
    def _reject(code: LegacyMigrationErrorCode, message: str) -> Never:
        raise LegacyMigrationCommandError(code, message)
