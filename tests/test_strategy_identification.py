from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from sentry_copilot.catalogs.repository import StrategyCatalogRepository
from sentry_copilot.domain.commands import (
    CorrectSessionRulesetRevision,
    CorrectStrategyIdentifications,
    RecordStrategyIdentification,
)
from sentry_copilot.domain.enums import EvidenceKind
from sentry_copilot.domain.events import (
    PlayerHealthObserved,
    StrategySelectionSnapshotObserved,
)
from sentry_copilot.domain.evidence import EvidenceRecord
from sentry_copilot.domain.identifiers import LocaleId
from sentry_copilot.domain.models import PlayerState, SessionState
from sentry_copilot.domain.prebattle import (
    BattleEntryConfirmed,
    BattleEntryNotConfirmed,
    BattleEntryNotConfirmedReason,
    ReadyCheckObserved,
    ReadyFalsePositiveCorrected,
    StrategyCandidateObserved,
    StrategySelectionConfirmationSource,
    StrategySelectionConfirmedEvidence,
)
from sentry_copilot.domain.queries import (
    build_prebattle_commitment_context,
    get_ready_confirmed_commitment,
)
from sentry_copilot.domain.reducer import reduce_session
from sentry_copilot.domain.rulesets import (
    RevisionSelectionMethod,
    RulesetDependencyStamp,
    SessionRulesetContext,
)
from sentry_copilot.domain.strategy_commitment import ParticipantCommitmentLevel
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
from sentry_copilot.services.ruleset_context_service import RulesetContextService
from sentry_copilot.services.strategy_identification_service import (
    StrategyIdentificationCommandError,
    StrategyIdentificationErrorCode,
    StrategyIdentificationService,
)

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)
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
def service(repository: StrategyCatalogRepository) -> StrategyIdentificationService:
    return StrategyIdentificationService(repository)


def selected_context() -> SessionRulesetContext:
    return SessionRulesetContext(
        ruleset_id=RULESET_ID,
        ruleset_revision_id=EARLY_REVISION,
        locale_id=LocaleId.ZH_CN,
        catalog_version=CATALOG_VERSION,
        selection_method=RevisionSelectionMethod.MANUAL,
        selected_at=NOW,
        selection_reason="synthetic test context",
        context_generation=1,
    )


def session_state(
    *,
    participant_ids: tuple[str, ...] = (P1, P2),
) -> SessionState:
    return SessionState(
        session_id=SESSION_ID,
        ruleset_context=selected_context(),
        strategy_selection=StrategySelectionSnapshot(
            session_id=SESSION_ID,
            ruleset_id=RULESET_ID,
            captured_at=NOW,
            participants=tuple(
                StrategySelectionParticipant(
                    session_player_id=participant_id,
                    selection_row=index,
                )
                for index, participant_id in enumerate(participant_ids, start=1)
            ),
        ),
        updated_at=NOW,
    )


def ready(
    participant_id: str,
    *,
    evidence_id: str,
    timestamp: datetime = NOW,
) -> ReadyCheckObserved:
    return ReadyCheckObserved(
        evidence_id=evidence_id,
        session_id=SESSION_ID,
        session_player_id=participant_id,
        timestamp=timestamp,
        provenance=EvidenceKind.OBSERVED,
        confidence=0.97,
        frame_reference=f"private/synthetic/{evidence_id}.png",
        observed_visual_cue="synthetic ready check",
    )


def candidate(
    participant_id: str,
    *,
    evidence_id: str,
) -> StrategyCandidateObserved:
    return StrategyCandidateObserved(
        evidence_id=evidence_id,
        session_id=SESSION_ID,
        session_player_id=participant_id,
        timestamp=NOW,
        provenance=EvidenceKind.OBSERVED,
        confidence=0.83,
        frame_reference=f"private/synthetic/{evidence_id}.png",
        observed_visual_cue="same synthetic candidate visual",
    )


def battle_entry(
    participant_id: str = P1,
    *,
    evidence_id: str = "evidence.battle-entry.1",
    timestamp: datetime = NOW,
) -> BattleEntryConfirmed:
    return BattleEntryConfirmed(
        evidence_id=evidence_id,
        session_id=SESSION_ID,
        session_player_id=participant_id,
        timestamp=timestamp,
        provenance=EvidenceKind.OBSERVED,
        confidence=0.98,
        frame_reference=f"private/synthetic/{evidence_id}.png",
        observed_visual_cue="synthetic normal active battle participation",
    )


def entry_not_confirmed(
    participant_id: str = P1,
    *,
    evidence_id: str = "evidence.battle-entry-not-confirmed.1",
) -> BattleEntryNotConfirmed:
    return BattleEntryNotConfirmed(
        evidence_id=evidence_id,
        session_id=SESSION_ID,
        session_player_id=participant_id,
        timestamp=NOW,
        provenance=EvidenceKind.OBSERVED,
        confidence=0.97,
        frame_reference=f"private/synthetic/{evidence_id}.png",
        observed_visual_cue="synthetic first stable frame already inactive",
        reason=BattleEntryNotConfirmedReason.FIRST_STABLE_FRAME_ALREADY_INACTIVE,
    )


def direct_evidence(
    participant_id: str,
    *,
    evidence_id: str,
    timestamp: datetime = NOW,
) -> StrategySelectionConfirmedEvidence:
    return StrategySelectionConfirmedEvidence(
        evidence_id=evidence_id,
        session_id=SESSION_ID,
        session_player_id=participant_id,
        timestamp=timestamp,
        provenance=EvidenceKind.OBSERVED,
        confidence=0.99,
        frame_reference=f"private/synthetic/{evidence_id}.png",
        observed_visual_cue="synthetic direct strategy panel evidence",
        confirmation_source=(
            StrategySelectionConfirmationSource.DIRECT_STRATEGY_OBSERVATION
        ),
    )


def manual_evidence(
    participant_id: str,
    *,
    evidence_id: str,
    timestamp: datetime = NOW,
) -> StrategySelectionConfirmedEvidence:
    return StrategySelectionConfirmedEvidence(
        evidence_id=evidence_id,
        session_id=SESSION_ID,
        session_player_id=participant_id,
        timestamp=timestamp,
        provenance=EvidenceKind.MANUAL,
        confidence=1.0,
        manual_note="synthetic user confirmation",
        confirmation_source=(
            StrategySelectionConfirmationSource.MANUAL_STRATEGY_CONFIRMATION
        ),
        manual_reason="synthetic manual strategy confirmation",
    )


def record(
    participant_id: str,
    strategy_id: str,
    *,
    record_id: str,
    evidence_id: str,
    basis: StrategyIdentificationBasis,
    stamp: RulesetDependencyStamp | None = None,
    supersedes: tuple[str, ...] = (),
    timestamp: datetime = NOW,
) -> StrategyIdentificationRecord:
    return StrategyIdentificationRecord(
        record_id=record_id,
        session_player_id=participant_id,
        strategy_id=strategy_id,
        basis=basis,
        identified_at=timestamp,
        evidence_ids=(evidence_id,),
        dependency_stamp=stamp,
        supersedes_record_ids=supersedes,
        reason=(
            "synthetic manual correction"
            if basis == StrategyIdentificationBasis.MANUAL_CONFIRMATION
            else None
        ),
    )


def add_ready_and_candidate(
    state: SessionState,
    participant_id: str,
    *,
    ready_id: str,
    candidate_id: str,
) -> SessionState:
    state = reduce_session(state, ready(participant_id, evidence_id=ready_id))
    return reduce_session(
        state,
        candidate(participant_id, evidence_id=candidate_id),
    )


def add_catalog_identification(
    service: StrategyIdentificationService,
    state: SessionState,
    participant_id: str,
    strategy_id: str,
    *,
    record_id: str,
    evidence_id: str,
) -> SessionState:
    assert state.ruleset_dependency_stamp is not None
    return service.identify(
        state,
        RecordStrategyIdentification(
            session_id=SESSION_ID,
            record=record(
                participant_id,
                strategy_id,
                record_id=record_id,
                evidence_id=evidence_id,
                basis=StrategyIdentificationBasis.CATALOG_DERIVED,
                stamp=state.ruleset_dependency_stamp,
            ),
        ),
    )


def add_direct_identification(
    service: StrategyIdentificationService,
    state: SessionState,
    participant_id: str,
    strategy_id: str,
    *,
    record_id: str,
    evidence_id: str,
) -> SessionState:
    evidence = direct_evidence(participant_id, evidence_id=evidence_id)
    return service.identify(
        state,
        RecordStrategyIdentification(
            session_id=SESSION_ID,
            record=record(
                participant_id,
                strategy_id,
                record_id=record_id,
                evidence_id=evidence_id,
                basis=StrategyIdentificationBasis.DIRECT_OBSERVATION,
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


def test_ready_commitment_accepts_catalog_derived_identification(
    service: StrategyIdentificationService,
) -> None:
    state = add_ready_and_candidate(
        session_state(),
        P1,
        ready_id="evidence.ready.1",
        candidate_id="evidence.candidate.1",
    )
    identified = add_catalog_identification(
        service,
        state,
        P1,
        GUARD,
        record_id="identification.catalog.1",
        evidence_id="evidence.candidate.1",
    )
    occupancy = service.get_uncontested_strategy_occupancies(identified)
    assert [(item.strategy_id, item.session_player_id) for item in occupancy] == [
        (GUARD, P1)
    ]


def test_battle_entry_confirmed_creates_strategy_unknown_commitment(
    service: StrategyIdentificationService,
) -> None:
    state = service.reconcile_battle_entry(session_state(), battle_entry())
    commitment = get_ready_confirmed_commitment(state, P1)
    assert commitment is not None
    assert commitment.ready_evidence_ids == ()
    assert commitment.battle_entry_evidence_ids == ("evidence.battle-entry.1",)
    assert service.get_uncontested_strategy_occupancies(state) == ()
    context = build_prebattle_commitment_context(state)
    assert context is not None
    assert context.participants[0].level == (
        ParticipantCommitmentLevel.READY_CONFIRMED_STRATEGY_UNKNOWN
    )


def test_battle_entry_contains_no_strategy_identity() -> None:
    assert "strategy_id" not in BattleEntryConfirmed.model_fields


def test_battle_entry_cannot_be_used_as_catalog_identification_evidence(
    service: StrategyIdentificationService,
) -> None:
    state = service.reconcile_battle_entry(session_state(), battle_entry())
    assert state.ruleset_dependency_stamp is not None
    command = RecordStrategyIdentification(
        session_id=SESSION_ID,
        record=record(
            P1,
            GUARD,
            record_id="identification.catalog.invalid-entry",
            evidence_id="evidence.battle-entry.1",
            basis=StrategyIdentificationBasis.CATALOG_DERIVED,
            stamp=state.ruleset_dependency_stamp,
        ),
    )
    with pytest.raises(StrategyIdentificationCommandError) as exc_info:
        service.identify(state, command)
    assert exc_info.value.code == StrategyIdentificationErrorCode.EVIDENCE_BASIS_MISMATCH
    assert state.strategy_identifications is None


def test_catalog_claim_without_commitment_is_rejected(
    service: StrategyIdentificationService,
) -> None:
    state = reduce_session(
        session_state(),
        candidate(P1, evidence_id="evidence.candidate.1"),
    )
    assert state.ruleset_dependency_stamp is not None
    before = state.model_dump(mode="json")
    command = RecordStrategyIdentification(
        session_id=SESSION_ID,
        record=record(
            P1,
            GUARD,
            record_id="identification.catalog.1",
            evidence_id="evidence.candidate.1",
            basis=StrategyIdentificationBasis.CATALOG_DERIVED,
            stamp=state.ruleset_dependency_stamp,
        ),
    )
    with pytest.raises(StrategyIdentificationCommandError) as exc_info:
        service.identify(state, command)
    assert exc_info.value.code == StrategyIdentificationErrorCode.COMMITMENT_REQUIRED
    assert state.model_dump(mode="json") == before


def test_direct_panel_evidence_atomically_creates_commitment_and_identification(
    service: StrategyIdentificationService,
) -> None:
    state = add_direct_identification(
        service,
        session_state(),
        P1,
        GUARD,
        record_id="identification.direct.1",
        evidence_id="evidence.direct.1",
    )
    assert get_ready_confirmed_commitment(state, P1) is not None
    identification = service.get_participant_strategy_identification(state, P1)
    assert identification is not None
    assert identification.strategy_id == GUARD


def test_manual_confirmation_atomically_creates_commitment_and_identification(
    service: StrategyIdentificationService,
) -> None:
    evidence = manual_evidence(P1, evidence_id="evidence.manual.1")
    command = RecordStrategyIdentification(
        session_id=SESSION_ID,
        record=record(
            P1,
            GUARD,
            record_id="identification.manual.1",
            evidence_id=evidence.evidence_id,
            basis=StrategyIdentificationBasis.MANUAL_CONFIRMATION,
        ),
        commitment_evidence=evidence,
    )
    state = service.identify(session_state(), command)
    assert get_ready_confirmed_commitment(state, P1) is not None
    assert service.get_participant_strategy_identification(state, P1) is not None


def test_catalog_derived_record_requires_dependency_stamp() -> None:
    with pytest.raises(ValidationError, match="requires a dependency stamp"):
        record(
            P1,
            GUARD,
            record_id="identification.catalog.1",
            evidence_id="evidence.candidate.1",
            basis=StrategyIdentificationBasis.CATALOG_DERIVED,
        )


def test_identification_record_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError):
        record(
            P1,
            GUARD,
            record_id="identification.naive.1",
            evidence_id="evidence.direct.1",
            basis=StrategyIdentificationBasis.DIRECT_OBSERVATION,
            timestamp=datetime(2026, 8, 2, 10, 0),
        )


@pytest.mark.parametrize(
    "basis",
    [
        StrategyIdentificationBasis.DIRECT_OBSERVATION,
        StrategyIdentificationBasis.MANUAL_CONFIRMATION,
    ],
)
def test_direct_and_manual_records_reject_dependency_stamps(
    basis: StrategyIdentificationBasis,
) -> None:
    stamp = selected_context().dependency_stamp
    assert stamp is not None
    with pytest.raises(ValidationError, match="cannot carry"):
        record(
            P1,
            GUARD,
            record_id="identification.invalid.1",
            evidence_id="evidence.direct.1",
            basis=basis,
            stamp=stamp,
        )


def test_catalog_derived_record_becomes_stale_after_generation_change(
    repository: StrategyCatalogRepository,
    service: StrategyIdentificationService,
) -> None:
    state = add_ready_and_candidate(
        session_state(),
        P1,
        ready_id="evidence.ready.1",
        candidate_id="evidence.candidate.1",
    )
    state = add_catalog_identification(
        service,
        state,
        P1,
        GUARD,
        record_id="identification.catalog.1",
        evidence_id="evidence.candidate.1",
    )
    corrected = correct_revision(
        repository,
        state,
        LATE_REVISION,
        selected_at=NOW + timedelta(minutes=1),
    )
    view = service.get_strategy_occupancy_view(corrected)
    assert view.occupancies == ()
    assert view.stale_record_ids == ("identification.catalog.1",)


def test_early_late_early_does_not_revive_old_derived_record(
    repository: StrategyCatalogRepository,
    service: StrategyIdentificationService,
) -> None:
    state = add_ready_and_candidate(
        session_state(),
        P1,
        ready_id="evidence.ready.1",
        candidate_id="evidence.candidate.1",
    )
    state = add_catalog_identification(
        service,
        state,
        P1,
        GUARD,
        record_id="identification.catalog.1",
        evidence_id="evidence.candidate.1",
    )
    state = correct_revision(
        repository,
        state,
        LATE_REVISION,
        selected_at=NOW + timedelta(minutes=1),
    )
    state = correct_revision(
        repository,
        state,
        EARLY_REVISION,
        selected_at=NOW + timedelta(minutes=2),
    )
    view = service.get_strategy_occupancy_view(state)
    assert state.ruleset_dependency_stamp is not None
    assert state.ruleset_dependency_stamp.context_generation == 3
    assert view.stale_record_ids == ("identification.catalog.1",)
    assert view.occupancies == ()


@pytest.mark.parametrize(
    "basis",
    [
        StrategyIdentificationBasis.DIRECT_OBSERVATION,
        StrategyIdentificationBasis.MANUAL_CONFIRMATION,
    ],
)
def test_direct_and_manual_records_do_not_stale_on_generation_change(
    repository: StrategyCatalogRepository,
    service: StrategyIdentificationService,
    basis: StrategyIdentificationBasis,
) -> None:
    evidence = (
        direct_evidence(P1, evidence_id="evidence.strong.1")
        if basis == StrategyIdentificationBasis.DIRECT_OBSERVATION
        else manual_evidence(P1, evidence_id="evidence.strong.1")
    )
    state = service.identify(
        session_state(),
        RecordStrategyIdentification(
            session_id=SESSION_ID,
            record=record(
                P1,
                GUARD,
                record_id="identification.strong.1",
                evidence_id=evidence.evidence_id,
                basis=basis,
            ),
            commitment_evidence=evidence,
        ),
    )
    state = correct_revision(
        repository,
        state,
        LATE_REVISION,
        selected_at=NOW + timedelta(minutes=1),
    )
    view = service.get_strategy_occupancy_view(state)
    assert view.stale_record_ids == ()
    assert len(view.occupancies) == 1


def test_candidate_duplicates_are_legal() -> None:
    state = reduce_session(
        session_state(),
        candidate(P1, evidence_id="evidence.candidate.1"),
    )
    state = reduce_session(
        state,
        candidate(P2, evidence_id="evidence.candidate.2"),
    )
    assert state.prebattle_evidence is not None
    assert len(state.prebattle_evidence.entries) == 2
    assert state.strategy_identifications is None


def duplicate_claim_state(
    service: StrategyIdentificationService,
) -> SessionState:
    state = add_ready_and_candidate(
        session_state(),
        P1,
        ready_id="evidence.ready.1",
        candidate_id="evidence.candidate.1",
    )
    state = add_ready_and_candidate(
        state,
        P2,
        ready_id="evidence.ready.2",
        candidate_id="evidence.candidate.2",
    )
    state = add_catalog_identification(
        service,
        state,
        P1,
        GUARD,
        record_id="identification.catalog.1",
        evidence_id="evidence.candidate.1",
    )
    return add_catalog_identification(
        service,
        state,
        P2,
        GUARD,
        record_id="identification.catalog.2",
        evidence_id="evidence.candidate.2",
    )


def test_duplicate_concrete_claims_are_interpretation_conflict_not_occupancy(
    service: StrategyIdentificationService,
) -> None:
    state = duplicate_claim_state(service)
    view = service.get_strategy_occupancy_view(state)
    assert view.occupancies == ()
    duplicate = service.get_duplicate_confirmed_strategy_claims(state)
    assert len(duplicate) == 1
    assert duplicate[0].conflict_type == (
        StrategyIdentificationConflictType.DUPLICATE_CONFIRMED_STRATEGY_CLAIM
    )
    assert duplicate[0].participant_ids == (P1, P2)


def test_duplicate_conflict_preserves_both_records_and_evidence(
    service: StrategyIdentificationService,
) -> None:
    state = duplicate_claim_state(service)
    assert state.strategy_identifications is not None
    assert len(state.strategy_identifications.records) == 2
    assert state.prebattle_evidence is not None
    assert state.prebattle_evidence.get("evidence.candidate.1") is not None
    assert state.prebattle_evidence.get("evidence.candidate.2") is not None


def test_same_participant_strong_claims_form_participant_conflict(
    service: StrategyIdentificationService,
) -> None:
    state = add_direct_identification(
        service,
        session_state(),
        P1,
        GUARD,
        record_id="identification.direct.1",
        evidence_id="evidence.direct.1",
    )
    state = add_direct_identification(
        service,
        state,
        P1,
        GROWTH,
        record_id="identification.direct.2",
        evidence_id="evidence.direct.2",
    )
    view = service.get_strategy_occupancy_view(state)
    assert view.occupancies == ()
    assert {
        conflict.conflict_type for conflict in view.conflicts
    } == {StrategyIdentificationConflictType.PARTICIPANT_STRATEGY_IDENTIFICATION_CONFLICT}


@pytest.mark.parametrize(
    "basis",
    [
        StrategyIdentificationBasis.DIRECT_OBSERVATION,
        StrategyIdentificationBasis.MANUAL_CONFIRMATION,
    ],
)
def test_direct_manual_incompatible_claim_forms_catalog_conflict(
    service: StrategyIdentificationService,
    basis: StrategyIdentificationBasis,
) -> None:
    evidence = (
        direct_evidence(P1, evidence_id="evidence.incompatible.1")
        if basis == StrategyIdentificationBasis.DIRECT_OBSERVATION
        else manual_evidence(P1, evidence_id="evidence.incompatible.1")
    )
    state = service.identify(
        session_state(),
        RecordStrategyIdentification(
            session_id=SESSION_ID,
            record=record(
                P1,
                SUPPORT,
                record_id="identification.incompatible.1",
                evidence_id=evidence.evidence_id,
                basis=basis,
            ),
            commitment_evidence=evidence,
        ),
    )
    view = service.get_strategy_occupancy_view(state)
    assert view.occupancies == ()
    assert view.conflicts[0].conflict_type == (
        StrategyIdentificationConflictType.STRATEGY_CATALOG_COMPATIBILITY_CONFLICT
    )


def manual_correction_command(
    participant_id: str,
    strategy_id: str,
    *,
    record_id: str,
    supersedes: tuple[str, ...],
    evidence_id: str,
) -> CorrectStrategyIdentifications:
    evidence = manual_evidence(
        participant_id,
        evidence_id=evidence_id,
        timestamp=NOW + timedelta(seconds=30),
    )
    return CorrectStrategyIdentifications(
        session_id=SESSION_ID,
        records=(
            record(
                participant_id,
                strategy_id,
                record_id=record_id,
                evidence_id=evidence_id,
                basis=StrategyIdentificationBasis.MANUAL_CONFIRMATION,
                supersedes=supersedes,
                timestamp=NOW + timedelta(seconds=30),
            ),
        ),
        correction_evidence=(evidence,),
    )


def test_manual_correction_explicitly_supersedes_and_preserves_old_record(
    service: StrategyIdentificationService,
) -> None:
    state = add_direct_identification(
        service,
        session_state(),
        P1,
        GUARD,
        record_id="identification.direct.1",
        evidence_id="evidence.direct.1",
    )
    corrected = service.correct(
        state,
        manual_correction_command(
            P1,
            GROWTH,
            record_id="identification.correction.1",
            supersedes=("identification.direct.1",),
            evidence_id="evidence.correction.1",
        ),
    )
    assert corrected.strategy_identifications is not None
    assert len(corrected.strategy_identifications.records) == 2
    assert corrected.strategy_identifications.records[1].supersedes_record_ids == (
        "identification.direct.1",
    )
    occupancy = service.get_uncontested_strategy_occupancies(corrected)
    assert [(item.strategy_id, item.session_player_id) for item in occupancy] == [
        (GROWTH, P1)
    ]


def test_correction_changes_assistant_record_not_game_commitment(
    service: StrategyIdentificationService,
) -> None:
    state = add_direct_identification(
        service,
        session_state(),
        P1,
        GUARD,
        record_id="identification.direct.1",
        evidence_id="evidence.direct.1",
    )
    before_commitment = get_ready_confirmed_commitment(state, P1)
    corrected = service.correct(
        state,
        manual_correction_command(
            P1,
            GROWTH,
            record_id="identification.correction.1",
            supersedes=("identification.direct.1",),
            evidence_id="evidence.correction.1",
        ),
    )
    after_commitment = get_ready_confirmed_commitment(corrected, P1)
    assert before_commitment is not None and after_commitment is not None
    assert after_commitment.confirmed_at == before_commitment.confirmed_at
    assert all(
        value not in {"unready", "released"}
        for value in ParticipantCommitmentLevel
    )


def test_correction_recomputes_unique_occupancies_after_duplicate_conflict(
    service: StrategyIdentificationService,
) -> None:
    state = duplicate_claim_state(service)
    corrected = service.correct(
        state,
        manual_correction_command(
            P2,
            GROWTH,
            record_id="identification.correction.2",
            supersedes=("identification.catalog.2",),
            evidence_id="evidence.correction.2",
        ),
    )
    occupancy = service.get_uncontested_strategy_occupancies(corrected)
    assert {(item.strategy_id, item.session_player_id) for item in occupancy} == {
        (GUARD, P1),
        (GROWTH, P2),
    }
    assert service.get_duplicate_confirmed_strategy_claims(corrected) == ()


def test_failed_correction_is_atomic(
    service: StrategyIdentificationService,
) -> None:
    state = add_direct_identification(
        service,
        session_state(),
        P1,
        GUARD,
        record_id="identification.direct.1",
        evidence_id="evidence.direct.1",
    )
    before = state.model_dump(mode="json")
    command = manual_correction_command(
        P1,
        GROWTH,
        record_id="identification.correction.invalid",
        supersedes=("identification.missing",),
        evidence_id="evidence.correction.invalid",
    )
    with pytest.raises(StrategyIdentificationCommandError) as exc_info:
        service.correct(state, command)
    assert exc_info.value.code == StrategyIdentificationErrorCode.SUPERSESSION_INVALID
    assert state.model_dump(mode="json") == before


def test_multi_participant_correction_second_failure_is_atomic(
    service: StrategyIdentificationService,
) -> None:
    state = add_direct_identification(
        service,
        session_state(),
        P1,
        GUARD,
        record_id="identification.direct.1",
        evidence_id="evidence.direct.1",
    )
    state = add_direct_identification(
        service,
        state,
        P2,
        GROWTH,
        record_id="identification.direct.2",
        evidence_id="evidence.direct.2",
    )
    evidence_1 = manual_evidence(P1, evidence_id="evidence.correction.1")
    evidence_2 = manual_evidence(P2, evidence_id="evidence.correction.2")
    command = CorrectStrategyIdentifications(
        session_id=SESSION_ID,
        records=(
            record(
                P1,
                GROWTH,
                record_id="identification.correction.1",
                evidence_id=evidence_1.evidence_id,
                basis=StrategyIdentificationBasis.MANUAL_CONFIRMATION,
                supersedes=("identification.direct.1",),
            ),
            record(
                P2,
                GUARD,
                record_id="identification.correction.2",
                evidence_id=evidence_2.evidence_id,
                basis=StrategyIdentificationBasis.MANUAL_CONFIRMATION,
                supersedes=("identification.missing",),
            ),
        ),
        correction_evidence=(evidence_1, evidence_2),
    )
    before = state.model_dump(mode="json")
    with pytest.raises(StrategyIdentificationCommandError) as exc_info:
        service.correct(state, command)
    assert exc_info.value.code == StrategyIdentificationErrorCode.SUPERSESSION_INVALID
    assert state.model_dump(mode="json") == before


def test_identification_command_rejects_cross_session_reference(
    service: StrategyIdentificationService,
) -> None:
    state = add_ready_and_candidate(
        session_state(),
        P1,
        ready_id="evidence.ready.1",
        candidate_id="evidence.candidate.1",
    )
    assert state.ruleset_dependency_stamp is not None
    command = RecordStrategyIdentification(
        session_id="session.other",
        record=record(
            P1,
            GUARD,
            record_id="identification.cross-session.1",
            evidence_id="evidence.candidate.1",
            basis=StrategyIdentificationBasis.CATALOG_DERIVED,
            stamp=state.ruleset_dependency_stamp,
        ),
    )
    with pytest.raises(StrategyIdentificationCommandError) as exc_info:
        service.identify(state, command)
    assert exc_info.value.code == StrategyIdentificationErrorCode.SESSION_MISMATCH


def test_identification_command_rejects_unknown_participant(
    service: StrategyIdentificationService,
) -> None:
    unknown = "session-player-unknown"
    evidence = direct_evidence(unknown, evidence_id="evidence.direct.unknown")
    command = RecordStrategyIdentification(
        session_id=SESSION_ID,
        record=record(
            unknown,
            GUARD,
            record_id="identification.direct.unknown",
            evidence_id=evidence.evidence_id,
            basis=StrategyIdentificationBasis.DIRECT_OBSERVATION,
        ),
        commitment_evidence=evidence,
    )
    with pytest.raises(StrategyIdentificationCommandError) as exc_info:
        service.identify(session_state(), command)
    assert exc_info.value.code == StrategyIdentificationErrorCode.PARTICIPANT_UNKNOWN


def test_selection_stage_exit_does_not_release_known_occupancy(
    service: StrategyIdentificationService,
) -> None:
    state = add_direct_identification(
        service,
        session_state(),
        P1,
        GUARD,
        record_id="identification.direct.1",
        evidence_id="evidence.direct.1",
    )
    outcome_evidence = EvidenceRecord(
        source=EvidenceKind.OBSERVED,
        confidence=0.96,
        observed_at=NOW + timedelta(seconds=10),
    )
    exited = StrategySelectionSnapshot(
        session_id=SESSION_ID,
        ruleset_id=RULESET_ID,
        captured_at=NOW + timedelta(seconds=10),
        participants=(
            StrategySelectionParticipant(
                session_player_id=P1,
                selection_row=1,
                selection_outcome=SelectionOutcome.EXITED_AFTER_STRATEGY,
                field_evidence={
                    ParticipantField.SELECTION_OUTCOME: outcome_evidence,
                },
            ),
        ),
    )
    state = reduce_session(
        state,
        StrategySelectionSnapshotObserved(
            timestamp=NOW + timedelta(seconds=10),
            snapshot=exited,
        ),
    )
    occupancy = service.get_uncontested_strategy_occupancies(state)
    assert len(occupancy) == 1
    assert occupancy[0].strategy_id == GUARD


def test_runtime_hp_depletion_does_not_mutate_concrete_occupancy(
    service: StrategyIdentificationService,
) -> None:
    state = add_direct_identification(
        service,
        session_state(),
        P1,
        GUARD,
        record_id="identification.direct.1",
        evidence_id="evidence.direct.1",
    )
    payload = state.model_dump()
    payload["players"] = [PlayerState(slot=1)]
    state = SessionState.model_validate(payload)
    after_hp = reduce_session(state, PlayerHealthObserved(slot=1, hp=0))
    assert after_hp.strategy_identifications == state.strategy_identifications
    assert service.get_uncontested_strategy_occupancies(after_hp) == (
        service.get_uncontested_strategy_occupancies(state)
    )


def test_first_stable_battle_frame_already_inactive_does_not_confirm_entry(
    service: StrategyIdentificationService,
) -> None:
    state = service.reconcile_battle_entry(session_state(), entry_not_confirmed())
    assert get_ready_confirmed_commitment(state, P1) is None
    assert service.get_uncontested_strategy_occupancies(state) == ()
    assert state.strategy_identifications is None
    assert not hasattr(state, "strategy_annotation")
    assert not hasattr(state, "strategy_follow_up_tasks")


def test_first_frame_inactive_participant_does_not_block_other_occupancy(
    service: StrategyIdentificationService,
) -> None:
    state = service.reconcile_battle_entry(session_state(), entry_not_confirmed())
    state = add_direct_identification(
        service,
        state,
        P2,
        GUARD,
        record_id="identification.direct.2",
        evidence_id="evidence.direct.2",
    )
    occupancy = service.get_uncontested_strategy_occupancies(state)
    assert [(item.strategy_id, item.session_player_id) for item in occupancy] == [
        (GUARD, P2)
    ]


def test_first_frame_inactive_preserves_prior_ready_without_inferring_strategy(
    service: StrategyIdentificationService,
) -> None:
    state = reduce_session(
        session_state(),
        ready(P1, evidence_id="evidence.ready.1"),
    )
    state = service.reconcile_battle_entry(state, entry_not_confirmed())
    assert get_ready_confirmed_commitment(state, P1) is not None
    assert service.get_participant_strategy_identification(state, P1) is None
    assert service.get_uncontested_strategy_occupancies(state) == ()


def test_later_not_confirmed_evidence_does_not_undo_confirmed_entry(
    service: StrategyIdentificationService,
) -> None:
    state = service.reconcile_battle_entry(session_state(), battle_entry())
    later_not_confirmed = entry_not_confirmed(
        evidence_id="evidence.battle-entry-not-confirmed.2"
    ).model_copy(update={"timestamp": NOW + timedelta(seconds=20)})
    state = service.reconcile_battle_entry(state, later_not_confirmed)
    commitment = get_ready_confirmed_commitment(state, P1)
    assert commitment is not None
    assert commitment.confirmed_at == NOW


def test_repeated_battle_entry_reconciliation_is_idempotent(
    service: StrategyIdentificationService,
) -> None:
    evidence = battle_entry()
    state = service.reconcile_battle_entry(session_state(), evidence)
    replayed = service.reconcile_battle_entry(state, evidence)
    assert replayed == state
    assert state.prebattle_evidence is not None
    assert len(state.prebattle_evidence.entries) == 1


def test_battle_entry_strengthens_existing_ready_without_moving_confirmed_at(
    service: StrategyIdentificationService,
) -> None:
    state = reduce_session(
        session_state(),
        ready(P1, evidence_id="evidence.ready.1"),
    )
    state = service.reconcile_battle_entry(
        state,
        battle_entry(timestamp=NOW + timedelta(seconds=10)),
    )
    commitment = get_ready_confirmed_commitment(state, P1)
    assert commitment is not None
    assert commitment.confirmed_at == NOW
    assert commitment.ready_evidence_ids == ("evidence.ready.1",)
    assert commitment.battle_entry_evidence_ids == ("evidence.battle-entry.1",)


def test_corrected_ready_does_not_remove_independent_battle_entry_commitment() -> None:
    state = reduce_session(
        session_state(),
        ready(P1, evidence_id="evidence.ready.1"),
    )
    state = reduce_session(
        state,
        battle_entry(timestamp=NOW + timedelta(seconds=5)),
    )
    state = reduce_session(
        state,
        ReadyFalsePositiveCorrected(
            evidence_id="evidence.ready-correction.1",
            session_id=SESSION_ID,
            session_player_id=P1,
            timestamp=NOW + timedelta(seconds=10),
            invalidated_ready_evidence_ids=("evidence.ready.1",),
            reason="synthetic false-positive correction",
        ),
    )
    commitment = get_ready_confirmed_commitment(state, P1)
    assert commitment is not None
    assert commitment.confirmed_at == NOW + timedelta(seconds=5)
    assert commitment.ready_evidence_ids == ()
    assert commitment.battle_entry_evidence_ids == ("evidence.battle-entry.1",)


def test_identification_record_replay_is_idempotent_and_collision_is_rejected(
    service: StrategyIdentificationService,
) -> None:
    evidence = direct_evidence(P1, evidence_id="evidence.direct.1")
    command = RecordStrategyIdentification(
        session_id=SESSION_ID,
        record=record(
            P1,
            GUARD,
            record_id="identification.direct.1",
            evidence_id=evidence.evidence_id,
            basis=StrategyIdentificationBasis.DIRECT_OBSERVATION,
        ),
        commitment_evidence=evidence,
    )
    state = service.identify(session_state(), command)
    assert service.identify(state, command) == state

    collision = RecordStrategyIdentification(
        session_id=SESSION_ID,
        record=command.record.model_copy(update={"strategy_id": GROWTH}),
        commitment_evidence=evidence,
    )
    with pytest.raises(StrategyIdentificationCommandError) as exc_info:
        service.identify(state, collision)
    assert exc_info.value.code == StrategyIdentificationErrorCode.RECORD_ID_COLLISION

    evidence_collision = command.model_copy(
        update={
            "commitment_evidence": evidence.model_copy(
                update={"observed_visual_cue": "different synthetic observation"}
            )
        }
    )
    with pytest.raises(StrategyIdentificationCommandError) as evidence_exc_info:
        service.identify(state, evidence_collision)
    assert evidence_exc_info.value.code == (
        StrategyIdentificationErrorCode.INVALID_IDENTIFICATION
    )


def test_identification_state_round_trips_through_session_json(
    service: StrategyIdentificationService,
) -> None:
    state = add_direct_identification(
        service,
        session_state(),
        P1,
        GUARD,
        record_id="identification.direct.1",
        evidence_id="evidence.direct.1",
    )
    assert SessionState.model_validate_json(state.model_dump_json()) == state
