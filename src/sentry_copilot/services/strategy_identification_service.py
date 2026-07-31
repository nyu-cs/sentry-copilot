from __future__ import annotations

from enum import StrEnum
from typing import Never

from pydantic import ValidationError

from sentry_copilot.catalogs.repository import (
    CatalogLookupError,
    StrategyCatalogRepository,
)
from sentry_copilot.domain.commands import (
    CorrectStrategyIdentifications,
    RecordStrategyIdentification,
)
from sentry_copilot.domain.events import StrategyIdentificationRecordsAppended
from sentry_copilot.domain.identifiers import (
    SessionId,
    SessionParticipantId,
    StrategyId,
)
from sentry_copilot.domain.models import SessionState
from sentry_copilot.domain.prebattle import (
    BattleEntryConfirmed,
    BattleEntryNotConfirmed,
    PrebattleEvidenceEntry,
    StrategyCandidateObserved,
    StrategySelectionConfirmationSource,
    StrategySelectionConfirmedEvidence,
)
from sentry_copilot.domain.reducer import InvalidObservationError, reduce_session
from sentry_copilot.domain.rulesets import RulesetDependencyStamp
from sentry_copilot.domain.strategy_identification import (
    ParticipantStrategyIdentification,
    StrategyIdentificationBasis,
    StrategyIdentificationConflict,
    StrategyIdentificationConflictType,
    StrategyIdentificationRecord,
    StrategyOccupancy,
    StrategyOccupancyView,
    derive_strategy_occupancy_view,
)


class StrategyIdentificationErrorCode(StrEnum):
    SESSION_MISMATCH = "session_mismatch"
    PARTICIPANT_UNKNOWN = "participant_unknown"
    COMMITMENT_REQUIRED = "commitment_required"
    RULESET_CONTEXT_NOT_SELECTED = "ruleset_context_not_selected"
    EVIDENCE_MISSING = "evidence_missing"
    EVIDENCE_PARTICIPANT_MISMATCH = "evidence_participant_mismatch"
    EVIDENCE_BASIS_MISMATCH = "evidence_basis_mismatch"
    RECORD_ID_COLLISION = "record_id_collision"
    SUPERSESSION_INVALID = "supersession_invalid"
    CATALOG_DERIVED_STALE = "catalog_derived_stale"
    STRATEGY_NOT_AVAILABLE = "strategy_not_available"
    INVALID_IDENTIFICATION = "invalid_identification"


class StrategyIdentificationCommandError(ValueError):
    """Typed rejection for concrete identification and reconciliation operations."""

    def __init__(self, code: StrategyIdentificationErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class StrategyIdentificationService:
    """Validate concrete claims against session/catalog context and derive occupancy."""

    def __init__(self, catalog_repository: StrategyCatalogRepository) -> None:
        self._catalog_repository = catalog_repository

    def identify(
        self,
        state: SessionState,
        command: RecordStrategyIdentification,
    ) -> SessionState:
        """Atomically add optional commitment evidence and one concrete claim."""

        self._require_session(state, command.session_id)
        self._require_known_participant(state, command.record.session_player_id)
        existing = self._existing_record(state, command.record)
        if existing:
            return (
                self._apply_event(state, command.commitment_evidence)
                if command.commitment_evidence is not None
                else state
            )

        candidate = state
        if command.commitment_evidence is not None:
            candidate = self._apply_event(candidate, command.commitment_evidence)
        self._require_commitment(candidate, command.record.session_player_id)
        self._require_record_evidence(candidate, command.record)
        stamp, available_strategy_ids = self._current_catalog(candidate)
        self._validate_record_against_catalog(
            command.record,
            current_stamp=stamp,
            available_strategy_ids=available_strategy_ids,
        )
        event = StrategyIdentificationRecordsAppended(
            session_id=command.session_id,
            records=(command.record,),
            timestamp=command.record.identified_at,
        )
        return self._apply_event(candidate, event)

    def correct(
        self,
        state: SessionState,
        command: CorrectStrategyIdentifications,
    ) -> SessionState:
        """Atomically append explicit manual records that supersede prior claims."""

        self._require_session(state, command.session_id)
        if self._all_records_already_exist(state, command.records):
            replayed = state
            for evidence in command.correction_evidence:
                replayed = self._apply_event(replayed, evidence)
            return replayed
        candidate = state
        for evidence in command.correction_evidence:
            candidate = self._apply_event(candidate, evidence)
        stamp, available_strategy_ids = self._current_catalog(candidate)
        for record in command.records:
            self._require_known_participant(candidate, record.session_player_id)
            self._require_commitment(candidate, record.session_player_id)
            self._require_superseded_records(candidate, record)
            self._require_record_evidence(candidate, record)
            self._validate_record_against_catalog(
                record,
                current_stamp=stamp,
                available_strategy_ids=available_strategy_ids,
            )
        event = StrategyIdentificationRecordsAppended(
            session_id=command.session_id,
            records=command.records,
            timestamp=max(record.identified_at for record in command.records),
        )
        return self._apply_event(candidate, event)

    def reconcile_battle_entry(
        self,
        state: SessionState,
        evidence: BattleEntryConfirmed | BattleEntryNotConfirmed,
    ) -> SessionState:
        """Record entry evidence without constructing a BattleRoster or runtime slot."""

        self._require_session(state, evidence.session_id)
        self._require_known_participant(state, evidence.session_player_id)
        return self._apply_event(state, evidence)

    def get_participant_strategy_identification(
        self,
        state: SessionState,
        session_player_id: SessionParticipantId,
    ) -> ParticipantStrategyIdentification | None:
        """Return a current identification only when no unresolved conflict applies."""

        view = self._occupancy_view(state)
        for identification in view.identifications:
            if identification.session_player_id == session_player_id:
                return identification
        return None

    def get_uncontested_strategy_occupancies(
        self,
        state: SessionState,
    ) -> tuple[StrategyOccupancy, ...]:
        return self._occupancy_view(state).occupancies

    def get_strategy_identification_conflicts(
        self,
        state: SessionState,
    ) -> tuple[StrategyIdentificationConflict, ...]:
        return self._occupancy_view(state).conflicts

    def get_duplicate_confirmed_strategy_claims(
        self,
        state: SessionState,
    ) -> tuple[StrategyIdentificationConflict, ...]:
        return tuple(
            conflict
            for conflict in self._occupancy_view(state).conflicts
            if conflict.conflict_type
            == StrategyIdentificationConflictType.DUPLICATE_CONFIRMED_STRATEGY_CLAIM
        )

    def get_strategy_occupancy_view(self, state: SessionState) -> StrategyOccupancyView:
        return self._occupancy_view(state)

    def _occupancy_view(self, state: SessionState) -> StrategyOccupancyView:
        stamp, available_strategy_ids = self._current_catalog(state)
        committed_participant_ids = frozenset(
            commitment.session_player_id
            for commitment in (
                state.strategy_commitments.commitments
                if state.strategy_commitments is not None
                else ()
            )
        )
        return derive_strategy_occupancy_view(
            state.strategy_identifications,
            committed_participant_ids=committed_participant_ids,
            current_dependency_stamp=stamp,
            available_strategy_ids=available_strategy_ids,
        )

    def _current_catalog(
        self,
        state: SessionState,
    ) -> tuple[RulesetDependencyStamp, frozenset[StrategyId]]:
        stamp = state.ruleset_dependency_stamp
        if stamp is None:
            self._reject(
                StrategyIdentificationErrorCode.RULESET_CONTEXT_NOT_SELECTED,
                "concrete strategy operations require a selected ruleset revision",
            )
        try:
            available = self._catalog_repository.available_strategy_ids(
                catalog_version=stamp.catalog_version,
                ruleset_revision_id=stamp.ruleset_revision_id,
            )
        except CatalogLookupError:
            self._reject(
                StrategyIdentificationErrorCode.RULESET_CONTEXT_NOT_SELECTED,
                "current session catalog context is unavailable",
            )
        return stamp, available

    def _validate_record_against_catalog(
        self,
        record: StrategyIdentificationRecord,
        *,
        current_stamp: RulesetDependencyStamp,
        available_strategy_ids: frozenset[StrategyId],
    ) -> None:
        if record.basis == StrategyIdentificationBasis.CATALOG_DERIVED:
            if record.dependency_stamp != current_stamp:
                self._reject(
                    StrategyIdentificationErrorCode.CATALOG_DERIVED_STALE,
                    "catalog-derived identification must use the current dependency stamp",
                )
            if record.strategy_id not in available_strategy_ids:
                self._reject(
                    StrategyIdentificationErrorCode.STRATEGY_NOT_AVAILABLE,
                    "catalog-derived strategy is not available in the current revision",
                )

    @staticmethod
    def _require_session(state: SessionState, session_id: SessionId) -> None:
        if state.session_id != session_id:
            StrategyIdentificationService._reject(
                StrategyIdentificationErrorCode.SESSION_MISMATCH,
                "command/evidence session_id does not match SessionState",
            )

    @staticmethod
    def _require_known_participant(
        state: SessionState,
        session_player_id: SessionParticipantId,
    ) -> None:
        snapshot = state.strategy_selection
        if snapshot is None or not any(
            participant.session_player_id == session_player_id
            for participant in snapshot.participants
        ):
            StrategyIdentificationService._reject(
                StrategyIdentificationErrorCode.PARTICIPANT_UNKNOWN,
                "strategy participant does not belong to the session",
            )

    @staticmethod
    def _require_commitment(
        state: SessionState,
        session_player_id: SessionParticipantId,
    ) -> None:
        if (
            state.strategy_commitments is None
            or state.strategy_commitments.for_participant(session_player_id) is None
        ):
            StrategyIdentificationService._reject(
                StrategyIdentificationErrorCode.COMMITMENT_REQUIRED,
                "concrete identification requires a ready-confirmed commitment",
            )

    @staticmethod
    def _require_record_evidence(
        state: SessionState,
        record: StrategyIdentificationRecord,
    ) -> None:
        ledger = state.prebattle_evidence
        if ledger is None:
            StrategyIdentificationService._reject(
                StrategyIdentificationErrorCode.EVIDENCE_MISSING,
                "strategy identification requires prebattle evidence",
            )
        entries: list[PrebattleEvidenceEntry] = []
        for evidence_id in record.evidence_ids:
            entry = ledger.get(evidence_id)
            if entry is None:
                StrategyIdentificationService._reject(
                    StrategyIdentificationErrorCode.EVIDENCE_MISSING,
                    f"missing strategy identification evidence: {evidence_id}",
                )
            if entry.session_player_id != record.session_player_id:
                StrategyIdentificationService._reject(
                    StrategyIdentificationErrorCode.EVIDENCE_PARTICIPANT_MISMATCH,
                    "strategy identification evidence cannot cross participants",
                )
            entries.append(entry)

        expected_source = {
            StrategyIdentificationBasis.DIRECT_OBSERVATION: (
                StrategySelectionConfirmationSource.DIRECT_STRATEGY_OBSERVATION
            ),
            StrategyIdentificationBasis.MANUAL_CONFIRMATION: (
                StrategySelectionConfirmationSource.MANUAL_STRATEGY_CONFIRMATION
            ),
        }.get(record.basis)
        if (
            record.basis == StrategyIdentificationBasis.CATALOG_DERIVED
            and not any(isinstance(entry, StrategyCandidateObserved) for entry in entries)
        ):
            StrategyIdentificationService._reject(
                StrategyIdentificationErrorCode.EVIDENCE_BASIS_MISMATCH,
                "catalog-derived identification requires raw strategy candidate evidence",
            )
        if expected_source is not None and not any(
            isinstance(entry, StrategySelectionConfirmedEvidence)
            and entry.confirmation_source == expected_source
            for entry in entries
        ):
            StrategyIdentificationService._reject(
                StrategyIdentificationErrorCode.EVIDENCE_BASIS_MISMATCH,
                "direct/manual identification lacks matching evidence provenance",
            )

    @staticmethod
    def _require_superseded_records(
        state: SessionState,
        record: StrategyIdentificationRecord,
    ) -> None:
        identification_state = state.strategy_identifications
        for record_id in record.supersedes_record_ids:
            superseded = (
                identification_state.get(record_id)
                if identification_state is not None
                else None
            )
            if superseded is None or (
                superseded.session_player_id != record.session_player_id
            ):
                StrategyIdentificationService._reject(
                    StrategyIdentificationErrorCode.SUPERSESSION_INVALID,
                    "manual correction must supersede existing same-participant records",
                )

    @staticmethod
    def _existing_record(
        state: SessionState,
        record: StrategyIdentificationRecord,
    ) -> bool:
        identification_state = state.strategy_identifications
        existing = (
            identification_state.get(record.record_id)
            if identification_state is not None
            else None
        )
        if existing is None:
            return False
        if existing != record:
            StrategyIdentificationService._reject(
                StrategyIdentificationErrorCode.RECORD_ID_COLLISION,
                "strategy identification record ID has different content",
            )
        return True

    @staticmethod
    def _all_records_already_exist(
        state: SessionState,
        records: tuple[StrategyIdentificationRecord, ...],
    ) -> bool:
        identification_state = state.strategy_identifications
        if identification_state is None:
            return False
        result = True
        for record in records:
            existing = identification_state.get(record.record_id)
            if existing is None:
                result = False
            elif existing != record:
                StrategyIdentificationService._reject(
                    StrategyIdentificationErrorCode.RECORD_ID_COLLISION,
                    "strategy identification record ID has different content",
                )
        return result

    @staticmethod
    def _apply_event(
        state: SessionState,
        event: (
            BattleEntryConfirmed
            | BattleEntryNotConfirmed
            | StrategySelectionConfirmedEvidence
            | StrategyIdentificationRecordsAppended
        ),
    ) -> SessionState:
        try:
            candidate = reduce_session(state, event)
            return SessionState.model_validate(candidate.model_dump())
        except (InvalidObservationError, ValidationError) as exc:
            raise StrategyIdentificationCommandError(
                StrategyIdentificationErrorCode.INVALID_IDENTIFICATION,
                "strategy identification failed whole-state validation",
            ) from exc

    @staticmethod
    def _reject(code: StrategyIdentificationErrorCode, message: str) -> Never:
        raise StrategyIdentificationCommandError(code, message)
