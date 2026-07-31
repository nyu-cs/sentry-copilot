from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from sentry_copilot.catalogs.repository import StrategyCatalogRepository
from sentry_copilot.domain.commands import (
    CorrectSessionRulesetRevision,
    CorrectStrategyIdentifications,
    ImportLegacyStrategySnapshotEvidence,
    RecordStrategyIdentification,
)
from sentry_copilot.domain.enums import EvidenceKind
from sentry_copilot.domain.events import LegacyPrebattleSnapshotMigrated
from sentry_copilot.domain.evidence import EvidenceRecord
from sentry_copilot.domain.identifiers import LocaleId
from sentry_copilot.domain.models import SessionState
from sentry_copilot.domain.prebattle import (
    BattleEntryNotConfirmed,
    BattleEntryNotConfirmedReason,
    LegacyReadySnapshotImported,
    LegacyStrategyInterpretationImported,
    ReadyCheckObserved,
    ReadyFalsePositiveCorrected,
    StrategySelectionConfirmationSource,
    StrategySelectionConfirmedEvidence,
)
from sentry_copilot.domain.prebattle_migration import LegacySnapshotMigrationRecord
from sentry_copilot.domain.queries import (
    build_team_strategy_context,
    get_legacy_prebattle_migration_state,
    get_ready_confirmed_commitment,
)
from sentry_copilot.domain.reducer import reduce_session
from sentry_copilot.domain.rulesets import (
    RevisionSelectionMethod,
    SessionRulesetContext,
)
from sentry_copilot.domain.strategy_identification import (
    StrategyIdentificationBasis,
    StrategyIdentificationConflictType,
    StrategyIdentificationRecord,
)
from sentry_copilot.domain.strategy_selection import (
    ParticipantField,
    SelectionOutcome,
    StrategySelectionParticipant,
    StrategySelectionSnapshot,
)
from sentry_copilot.services.prebattle_migration_service import (
    LegacyMigrationCommandError,
    LegacyMigrationErrorCode,
    LegacyPrebattleSnapshotMigrationService,
)
from sentry_copilot.services.ruleset_context_service import RulesetContextService
from sentry_copilot.services.strategy_identification_service import (
    StrategyIdentificationService,
)

NOW = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
SESSION_ID = "session.synthetic"
RULESET_ID = "demo.synthetic_covenant_latter"
EARLY_REVISION = "demo.synthetic_covenant_latter.pre_update"
LATE_REVISION = "demo.synthetic_covenant_latter.post_update"
CATALOG_VERSION = "catalog.synthetic.v1"
GUARD = "strategy.synthetic.guard"
GROWTH = "strategy.synthetic.growth"
SUPPORT = "strategy.synthetic.support"
P1 = "session-player-1"
P2 = "session-player-2"


@pytest.fixture
def repository() -> StrategyCatalogRepository:
    return StrategyCatalogRepository.from_directory("data/strategy_catalogs")


@pytest.fixture
def migration_service(
    repository: StrategyCatalogRepository,
) -> LegacyPrebattleSnapshotMigrationService:
    return LegacyPrebattleSnapshotMigrationService(repository)


@pytest.fixture
def identification_service(
    repository: StrategyCatalogRepository,
) -> StrategyIdentificationService:
    return StrategyIdentificationService(repository)


def field_evidence(
    *,
    observed_at: datetime = NOW,
    confidence: float = 0.82,
) -> EvidenceRecord:
    return EvidenceRecord(
        source=EvidenceKind.OBSERVED,
        confidence=confidence,
        observed_at=observed_at,
        source_detail="synthetic legacy snapshot field",
    )


def participant(
    participant_id: str,
    row: int,
    *,
    ready: bool | None = None,
    strategy_id: str | None = None,
    outcome: SelectionOutcome = SelectionOutcome.UNKNOWN,
    observed_at: datetime = NOW,
) -> StrategySelectionParticipant:
    evidence: dict[ParticipantField, EvidenceRecord] = {}
    if ready is not None:
        evidence[ParticipantField.READY] = field_evidence(observed_at=observed_at)
    if strategy_id is not None:
        evidence[ParticipantField.STRATEGY] = field_evidence(
            observed_at=observed_at,
            confidence=0.73,
        )
    if outcome != SelectionOutcome.UNKNOWN:
        evidence[ParticipantField.SELECTION_OUTCOME] = field_evidence(
            observed_at=observed_at
        )
    return StrategySelectionParticipant(
        session_player_id=participant_id,
        selection_row=row,
        strategy_id=strategy_id,
        ready=ready,
        selection_outcome=outcome,
        field_evidence=evidence,
    )


def snapshot(
    participants: tuple[StrategySelectionParticipant, ...],
    *,
    frozen: bool = True,
) -> StrategySelectionSnapshot:
    return StrategySelectionSnapshot(
        session_id=SESSION_ID,
        ruleset_id=RULESET_ID,
        expected_participant_count=None,
        captured_at=NOW + timedelta(seconds=10),
        participants=participants,
        frozen=frozen,
    )


def context(
    revision_id: str = EARLY_REVISION,
    *,
    generation: int = 1,
    selected_at: datetime = NOW,
) -> SessionRulesetContext:
    return SessionRulesetContext(
        ruleset_id=RULESET_ID,
        ruleset_revision_id=revision_id,
        locale_id=LocaleId.ZH_CN,
        catalog_version=CATALOG_VERSION,
        selection_method=RevisionSelectionMethod.MANUAL,
        selected_at=selected_at,
        selection_reason="synthetic test context",
        context_generation=generation,
    )


def state_with_snapshot(value: StrategySelectionSnapshot) -> SessionState:
    return SessionState(
        session_id=SESSION_ID,
        ruleset_context=context(),
        strategy_selection=value,
        updated_at=NOW,
    )


def migration_command(
    service: LegacyPrebattleSnapshotMigrationService,
    value: StrategySelectionSnapshot,
    *,
    operation_id: str = "migration.synthetic.1",
    migrated_at: datetime = NOW + timedelta(minutes=1),
    reason: str = "synthetic explicit legacy import",
) -> ImportLegacyStrategySnapshotEvidence:
    return ImportLegacyStrategySnapshotEvidence(
        session_id=SESSION_ID,
        migration_operation_id=operation_id,
        snapshot_fingerprint=service.fingerprint_snapshot(value),
        migrated_at=migrated_at,
        reason=reason,
    )


def migrate(
    service: LegacyPrebattleSnapshotMigrationService,
    value: StrategySelectionSnapshot,
) -> SessionState:
    return service.migrate(
        state_with_snapshot(value),
        migration_command(service, value),
    )


def direct_evidence(
    participant_id: str,
    evidence_id: str,
    *,
    observed_at: datetime = NOW + timedelta(minutes=2),
    manual: bool = False,
) -> StrategySelectionConfirmedEvidence:
    return StrategySelectionConfirmedEvidence(
        evidence_id=evidence_id,
        session_id=SESSION_ID,
        session_player_id=participant_id,
        timestamp=observed_at,
        provenance=EvidenceKind.MANUAL if manual else EvidenceKind.OBSERVED,
        confidence=1.0,
        manual_note="synthetic manual correction" if manual else None,
        frame_reference=None if manual else "private/synthetic/direct.png",
        confirmation_source=(
            StrategySelectionConfirmationSource.MANUAL_STRATEGY_CONFIRMATION
            if manual
            else StrategySelectionConfirmationSource.DIRECT_STRATEGY_OBSERVATION
        ),
        manual_reason="synthetic correction" if manual else None,
    )


def identify_direct(
    service: StrategyIdentificationService,
    state: SessionState,
    participant_id: str,
    strategy_id: str,
    suffix: str,
) -> SessionState:
    evidence = direct_evidence(participant_id, f"evidence.direct.{suffix}")
    return service.identify(
        state,
        RecordStrategyIdentification(
            session_id=SESSION_ID,
            record=StrategyIdentificationRecord(
                record_id=f"identification.direct.{suffix}",
                session_player_id=participant_id,
                strategy_id=strategy_id,
                basis=StrategyIdentificationBasis.DIRECT_OBSERVATION,
                identified_at=evidence.timestamp,
                evidence_ids=(evidence.evidence_id,),
            ),
            commitment_evidence=evidence,
        ),
    )


def correct_revision(
    repository: StrategyCatalogRepository,
    state: SessionState,
    revision_id: str,
    *,
    selected_at: datetime,
) -> SessionState:
    return RulesetContextService(repository).correct(
        state,
        CorrectSessionRulesetRevision(
            session_id=SESSION_ID,
            ruleset_id=RULESET_ID,
            ruleset_revision_id=revision_id,
            locale_id=LocaleId.ZH_CN,
            catalog_version=CATALOG_VERSION,
            selected_at=selected_at,
            reason="synthetic revision correction",
        ),
    )


def test_legacy_ready_true_imports_typed_evidence_and_commitment(
    migration_service: LegacyPrebattleSnapshotMigrationService,
) -> None:
    value = snapshot((participant(P1, 1, ready=True),))
    state = migrate(migration_service, value)
    commitment = get_ready_confirmed_commitment(state, P1)
    assert commitment is not None
    assert commitment.confirmed_at == NOW
    assert state.prebattle_evidence is not None
    imported = state.prebattle_evidence.get(commitment.ready_evidence_ids[0])
    assert isinstance(imported, LegacyReadySnapshotImported)
    assert imported.provenance == "legacy_snapshot_migration"
    assert imported.legacy_field_evidence == value.participants[0].field_evidence[
        ParticipantField.READY
    ]


def test_migration_event_rejects_strong_identification_injection(
    migration_service: LegacyPrebattleSnapshotMigrationService,
) -> None:
    value = snapshot((participant(P1, 1, strategy_id=GUARD),))
    fingerprint = migration_service.fingerprint_snapshot(value)
    evidence = LegacyStrategyInterpretationImported(
        evidence_id="evidence.legacy.synthetic.guard",
        session_id=SESSION_ID,
        session_player_id=P1,
        migration_operation_id="migration.synthetic.strong-injection",
        snapshot_fingerprint=fingerprint,
        timestamp=NOW,
        migrated_at=NOW + timedelta(minutes=1),
        legacy_field_evidence=value.participants[0].field_evidence[
            ParticipantField.STRATEGY
        ],
        legacy_strategy_id=GUARD,
    )
    strong_record = StrategyIdentificationRecord(
        record_id="identification.synthetic.strong-injection",
        session_player_id=P1,
        strategy_id=GUARD,
        basis=StrategyIdentificationBasis.DIRECT_OBSERVATION,
        identified_at=NOW,
        evidence_ids=(evidence.evidence_id,),
    )
    migration_record = LegacySnapshotMigrationRecord(
        operation_id=evidence.migration_operation_id,
        session_id=SESSION_ID,
        snapshot_fingerprint=fingerprint,
        snapshot_captured_at=value.captured_at,
        migrated_at=evidence.migrated_at,
        strategy_evidence_ids=(evidence.evidence_id,),
        identification_record_ids=(strong_record.record_id,),
    )

    with pytest.raises(ValidationError, match="only weak legacy records"):
        LegacyPrebattleSnapshotMigrated(
            session_id=SESSION_ID,
            migration_record=migration_record,
            evidence_entries=(evidence,),
            identification_records=(strong_record,),
        )


def test_same_migration_command_is_idempotent(
    migration_service: LegacyPrebattleSnapshotMigrationService,
) -> None:
    value = snapshot((participant(P1, 1, ready=True, strategy_id=GUARD),))
    command = migration_command(migration_service, value)
    state = migration_service.migrate(state_with_snapshot(value), command)
    replayed = migration_service.migrate(state, command)
    assert replayed == state
    assert replayed.prebattle_evidence is not None
    assert len(replayed.prebattle_evidence.entries) == 2
    assert replayed.legacy_prebattle_migrations is not None
    assert len(replayed.legacy_prebattle_migrations.records) == 1


def test_same_operation_id_with_different_content_is_rejected(
    migration_service: LegacyPrebattleSnapshotMigrationService,
) -> None:
    value = snapshot((participant(P1, 1, ready=True),))
    command = migration_command(migration_service, value)
    state = migration_service.migrate(state_with_snapshot(value), command)
    changed = command.model_copy(
        update={"migrated_at": command.migrated_at + timedelta(seconds=1)}
    )
    with pytest.raises(LegacyMigrationCommandError) as exc_info:
        migration_service.migrate(state, changed)
    assert exc_info.value.code == LegacyMigrationErrorCode.OPERATION_ID_COLLISION


def test_different_operation_for_same_snapshot_does_not_duplicate_import(
    migration_service: LegacyPrebattleSnapshotMigrationService,
) -> None:
    value = snapshot((participant(P1, 1, ready=True, strategy_id=GUARD),))
    state = migrate(migration_service, value)
    second = migration_command(
        migration_service,
        value,
        operation_id="migration.synthetic.2",
        migrated_at=NOW + timedelta(minutes=2),
    )
    replayed = migration_service.migrate(state, second)
    assert replayed == state
    assert replayed.legacy_prebattle_migrations is not None
    assert len(replayed.legacy_prebattle_migrations.records) == 1


def test_fingerprint_must_match_current_snapshot(
    migration_service: LegacyPrebattleSnapshotMigrationService,
) -> None:
    value = snapshot((participant(P1, 1, ready=True),))
    other = snapshot((participant(P1, 1, ready=False),))
    command = migration_command(migration_service, other)
    with pytest.raises(LegacyMigrationCommandError) as exc_info:
        migration_service.migrate(state_with_snapshot(value), command)
    assert exc_info.value.code == (
        LegacyMigrationErrorCode.SNAPSHOT_FINGERPRINT_MISMATCH
    )


def test_legacy_ready_false_does_not_remove_existing_commitment(
    migration_service: LegacyPrebattleSnapshotMigrationService,
) -> None:
    value = snapshot((participant(P1, 1, ready=False),))
    state = reduce_session(
        state_with_snapshot(value),
        ReadyCheckObserved(
            evidence_id="evidence.ready.direct",
            session_id=SESSION_ID,
            session_player_id=P1,
            timestamp=NOW - timedelta(seconds=5),
            provenance=EvidenceKind.OBSERVED,
            confidence=0.99,
            observed_visual_cue="synthetic direct ready check",
        ),
    )
    migrated = migration_service.migrate(
        state,
        migration_command(migration_service, value),
    )
    commitment = get_ready_confirmed_commitment(migrated, P1)
    assert commitment is not None
    assert commitment.ready_evidence_ids == ("evidence.ready.direct",)


def test_legacy_strategy_is_preserved_but_never_directly_occupies(
    migration_service: LegacyPrebattleSnapshotMigrationService,
    identification_service: StrategyIdentificationService,
) -> None:
    value = snapshot((participant(P1, 1, ready=True, strategy_id=GUARD),))
    state = migrate(migration_service, value)
    assert state.prebattle_evidence is not None
    strategy_entries = [
        entry
        for entry in state.prebattle_evidence.entries
        if isinstance(entry, LegacyStrategyInterpretationImported)
    ]
    assert len(strategy_entries) == 1
    assert strategy_entries[0].legacy_strategy_id == GUARD
    assert strategy_entries[0].legacy_field_evidence == (
        value.participants[0].field_evidence[ParticipantField.STRATEGY]
    )
    view = identification_service.get_strategy_occupancy_view(state)
    assert view.occupancies == ()
    assert len(view.legacy_record_ids) == 1


def test_duplicate_legacy_strategy_values_are_valid_and_non_occupying(
    migration_service: LegacyPrebattleSnapshotMigrationService,
    identification_service: StrategyIdentificationService,
) -> None:
    value = snapshot(
        (
            participant(P1, 1, ready=True, strategy_id=GUARD),
            participant(P2, 2, ready=True, strategy_id=GUARD),
        )
    )
    state = migrate(migration_service, value)
    assert state.strategy_selection == value
    view = identification_service.get_strategy_occupancy_view(state)
    assert view.occupancies == ()
    assert view.conflicts == ()
    assert len(view.legacy_record_ids) == 2


def test_duplicate_strong_claims_after_migration_use_conflict_query(
    migration_service: LegacyPrebattleSnapshotMigrationService,
    identification_service: StrategyIdentificationService,
) -> None:
    value = snapshot(
        (
            participant(P1, 1, ready=True, strategy_id=GUARD),
            participant(P2, 2, ready=True, strategy_id=GUARD),
        )
    )
    state = migrate(migration_service, value)
    state = identify_direct(identification_service, state, P1, GUARD, "p1")
    state = identify_direct(identification_service, state, P2, GUARD, "p2")
    conflicts = identification_service.get_duplicate_confirmed_strategy_claims(state)
    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == (
        StrategyIdentificationConflictType.DUPLICATE_CONFIRMED_STRATEGY_CLAIM
    )
    assert identification_service.get_uncontested_strategy_occupancies(state) == ()


def test_exited_after_strategy_without_ready_does_not_create_commitment(
    migration_service: LegacyPrebattleSnapshotMigrationService,
    identification_service: StrategyIdentificationService,
) -> None:
    value = snapshot(
        (
            participant(
                P1,
                1,
                strategy_id=GUARD,
                outcome=SelectionOutcome.EXITED_AFTER_STRATEGY,
            ),
        )
    )
    state = migrate(migration_service, value)
    assert get_ready_confirmed_commitment(state, P1) is None
    assert identification_service.get_uncontested_strategy_occupancies(state) == ()


def test_ready_and_selection_exit_preserve_commitment(
    migration_service: LegacyPrebattleSnapshotMigrationService,
) -> None:
    value = snapshot(
        (
            participant(
                P1,
                1,
                ready=True,
                strategy_id=GUARD,
                outcome=SelectionOutcome.EXITED_AFTER_STRATEGY,
            ),
        )
    )
    state = migrate(migration_service, value)
    assert get_ready_confirmed_commitment(state, P1) is not None


def test_frozen_snapshot_allows_migration_and_direct_identification(
    migration_service: LegacyPrebattleSnapshotMigrationService,
    identification_service: StrategyIdentificationService,
) -> None:
    value = snapshot((participant(P1, 1, ready=True, strategy_id=GUARD),), frozen=True)
    state = migrate(migration_service, value)
    state = identify_direct(identification_service, state, P1, GUARD, "frozen")
    assert state.strategy_selection is not None and state.strategy_selection.frozen
    occupancy = identification_service.get_uncontested_strategy_occupancies(state)
    assert [(item.strategy_id, item.session_player_id) for item in occupancy] == [
        (GUARD, P1)
    ]


def test_migration_does_not_move_earlier_confirmed_at(
    migration_service: LegacyPrebattleSnapshotMigrationService,
) -> None:
    value = snapshot(
        (participant(P1, 1, ready=True, observed_at=NOW + timedelta(seconds=5)),)
    )
    state = reduce_session(
        state_with_snapshot(value),
        ReadyCheckObserved(
            evidence_id="evidence.ready.earlier",
            session_id=SESSION_ID,
            session_player_id=P1,
            timestamp=NOW,
            provenance=EvidenceKind.OBSERVED,
            confidence=0.99,
            observed_visual_cue="synthetic earlier ready",
        ),
    )
    state = migration_service.migrate(
        state,
        migration_command(migration_service, value),
    )
    commitment = get_ready_confirmed_commitment(state, P1)
    assert commitment is not None
    assert commitment.confirmed_at == NOW
    assert len(commitment.ready_evidence_ids) == 2


def test_repeated_migration_does_not_restore_corrected_legacy_ready(
    migration_service: LegacyPrebattleSnapshotMigrationService,
) -> None:
    value = snapshot((participant(P1, 1, ready=True),))
    command = migration_command(migration_service, value)
    state = migration_service.migrate(state_with_snapshot(value), command)
    assert state.legacy_prebattle_migrations is not None
    ready_id = state.legacy_prebattle_migrations.records[0].ready_evidence_ids[0]
    state = reduce_session(
        state,
        ReadyFalsePositiveCorrected(
            evidence_id="evidence.correction.legacy-ready",
            session_id=SESSION_ID,
            session_player_id=P1,
            timestamp=NOW + timedelta(minutes=2),
            invalidated_ready_evidence_ids=(ready_id,),
            reason="synthetic legacy ready was a false positive",
        ),
    )
    replayed = migration_service.migrate(state, command)
    assert get_ready_confirmed_commitment(replayed, P1) is None
    assert replayed.prebattle_evidence == state.prebattle_evidence


def test_revision_correction_preserves_evidence_commitment_and_stales_legacy_record(
    repository: StrategyCatalogRepository,
    migration_service: LegacyPrebattleSnapshotMigrationService,
    identification_service: StrategyIdentificationService,
) -> None:
    value = snapshot((participant(P1, 1, ready=True, strategy_id=GUARD),))
    state = migrate(migration_service, value)
    before_evidence = state.prebattle_evidence
    before_commitment = state.strategy_commitments
    state = correct_revision(
        repository,
        state,
        LATE_REVISION,
        selected_at=NOW + timedelta(minutes=2),
    )
    view = identification_service.get_strategy_occupancy_view(state)
    assert state.prebattle_evidence == before_evidence
    assert state.strategy_commitments == before_commitment
    assert len(view.stale_record_ids) == 1
    assert view.occupancies == ()


def test_early_late_early_does_not_revive_legacy_interpretation(
    repository: StrategyCatalogRepository,
    migration_service: LegacyPrebattleSnapshotMigrationService,
    identification_service: StrategyIdentificationService,
) -> None:
    value = snapshot((participant(P1, 1, ready=True, strategy_id=GUARD),))
    state = migrate(migration_service, value)
    state = correct_revision(
        repository,
        state,
        LATE_REVISION,
        selected_at=NOW + timedelta(minutes=2),
    )
    state = correct_revision(
        repository,
        state,
        EARLY_REVISION,
        selected_at=NOW + timedelta(minutes=3),
    )
    view = identification_service.get_strategy_occupancy_view(state)
    assert state.ruleset_dependency_stamp is not None
    assert state.ruleset_dependency_stamp.context_generation == 3
    assert len(view.stale_record_ids) == 1
    assert view.legacy_record_ids == ()


def test_direct_compatible_claim_survives_revision_correction(
    repository: StrategyCatalogRepository,
    migration_service: LegacyPrebattleSnapshotMigrationService,
    identification_service: StrategyIdentificationService,
) -> None:
    value = snapshot((participant(P1, 1, ready=True),))
    state = migrate(migration_service, value)
    state = identify_direct(identification_service, state, P1, GUARD, "compatible")
    state = correct_revision(
        repository,
        state,
        LATE_REVISION,
        selected_at=NOW + timedelta(minutes=3),
    )
    assert len(identification_service.get_uncontested_strategy_occupancies(state)) == 1


def test_direct_incompatible_claim_becomes_catalog_conflict(
    repository: StrategyCatalogRepository,
    migration_service: LegacyPrebattleSnapshotMigrationService,
    identification_service: StrategyIdentificationService,
) -> None:
    value = snapshot((participant(P1, 1, ready=True),))
    late_state = state_with_snapshot(value).model_copy(
        update={"ruleset_context": context(LATE_REVISION)}
    )
    late_state = SessionState.model_validate(late_state.model_dump())
    state = migration_service.migrate(
        late_state,
        migration_command(migration_service, value),
    )
    state = identify_direct(identification_service, state, P1, SUPPORT, "support")
    state = correct_revision(
        repository,
        state,
        EARLY_REVISION,
        selected_at=NOW + timedelta(minutes=3),
    )
    conflicts = identification_service.get_strategy_identification_conflicts(state)
    assert conflicts[0].conflict_type == (
        StrategyIdentificationConflictType.STRATEGY_CATALOG_COMPATIBILITY_CONFLICT
    )
    assert identification_service.get_uncontested_strategy_occupancies(state) == ()


def test_manual_correction_supersedes_legacy_interpretation_and_replay_does_not_revive(
    migration_service: LegacyPrebattleSnapshotMigrationService,
    identification_service: StrategyIdentificationService,
) -> None:
    value = snapshot((participant(P1, 1, ready=True, strategy_id=GUARD),))
    command = migration_command(migration_service, value)
    state = migration_service.migrate(state_with_snapshot(value), command)
    assert state.strategy_identifications is not None
    legacy_record = state.strategy_identifications.records[0]
    evidence = direct_evidence(P1, "evidence.manual.correction", manual=True)
    state = identification_service.correct(
        state,
        CorrectStrategyIdentifications(
            session_id=SESSION_ID,
            records=(
                StrategyIdentificationRecord(
                    record_id="identification.manual.correction",
                    session_player_id=P1,
                    strategy_id=GROWTH,
                    basis=StrategyIdentificationBasis.MANUAL_CONFIRMATION,
                    identified_at=evidence.timestamp,
                    evidence_ids=(evidence.evidence_id,),
                    supersedes_record_ids=(legacy_record.record_id,),
                    reason="synthetic correction of legacy interpretation",
                ),
            ),
            correction_evidence=(evidence,),
        ),
    )
    replayed = migration_service.migrate(state, command)
    occupancy = identification_service.get_uncontested_strategy_occupancies(replayed)
    assert [(item.strategy_id, item.session_player_id) for item in occupancy] == [
        (GROWTH, P1)
    ]
    assert replayed.strategy_identifications is not None
    assert len(replayed.strategy_identifications.records) == 2


def test_legacy_query_keeps_snapshot_semantics_while_occupancy_is_independent(
    migration_service: LegacyPrebattleSnapshotMigrationService,
    identification_service: StrategyIdentificationService,
) -> None:
    value = snapshot(
        (
            participant(
                P1,
                1,
                ready=True,
                strategy_id=GUARD,
                outcome=SelectionOutcome.ENTERED_BATTLE,
            ),
        )
    )
    state = migrate(migration_service, value)
    legacy = build_team_strategy_context(state)
    assert legacy is not None
    assert legacy.strategy_ids == [GUARD]
    assert identification_service.get_uncontested_strategy_occupancies(state) == ()


def test_migration_history_query_is_read_only(
    migration_service: LegacyPrebattleSnapshotMigrationService,
) -> None:
    value = snapshot((participant(P1, 1, ready=True),))
    state = migrate(migration_service, value)
    before = state.model_dump(mode="json")
    history = get_legacy_prebattle_migration_state(state)
    assert history is not None and len(history.records) == 1
    assert state.model_dump(mode="json") == before


def test_first_battle_frame_already_inactive_still_does_not_create_commitment(
    migration_service: LegacyPrebattleSnapshotMigrationService,
    identification_service: StrategyIdentificationService,
) -> None:
    value = snapshot((participant(P1, 1, ready=None, strategy_id=None),))
    state = migrate(migration_service, value)
    state = identification_service.reconcile_battle_entry(
        state,
        BattleEntryNotConfirmed(
            evidence_id="evidence.entry-not-confirmed.legacy",
            session_id=SESSION_ID,
            session_player_id=P1,
            timestamp=NOW + timedelta(minutes=2),
            provenance=EvidenceKind.OBSERVED,
            confidence=0.99,
            observed_visual_cue="synthetic first stable frame already inactive",
            reason=BattleEntryNotConfirmedReason.FIRST_STABLE_FRAME_ALREADY_INACTIVE,
        ),
    )
    assert get_ready_confirmed_commitment(state, P1) is None
    assert identification_service.get_uncontested_strategy_occupancies(state) == ()


def test_migration_state_round_trips_through_json(
    migration_service: LegacyPrebattleSnapshotMigrationService,
) -> None:
    value = snapshot((participant(P1, 1, ready=True, strategy_id=GUARD),))
    state = migrate(migration_service, value)
    assert SessionState.model_validate_json(state.model_dump_json()) == state
