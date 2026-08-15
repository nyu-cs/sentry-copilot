from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from sentry_copilot.catalogs.repository import StrategyCatalogRepository
from sentry_copilot.domain.battle_roster import (
    BattleParticipantInactivated,
    BattleRuntimeStageType,
    InactivePresentation,
    PlayerInactivationReason,
    PlayerParticipationStatus,
)
from sentry_copilot.domain.commands import (
    CorrectSessionRulesetRevision,
    RecordStrategyIdentification,
)
from sentry_copilot.domain.enums import EvidenceKind
from sentry_copilot.domain.events import SlotAssociationRecordsAppended
from sentry_copilot.domain.evidence import EvidenceRecord
from sentry_copilot.domain.models import PlayerState, SessionState
from sentry_copilot.domain.prebattle import (
    BattleEntryConfirmed,
    ReadyCheckObserved,
    StrategyCandidateObserved,
    StrategySelectionConfirmationSource,
    StrategySelectionConfirmedEvidence,
)
from sentry_copilot.domain.reducer import reduce_session
from sentry_copilot.domain.rulesets import RevisionSelectionMethod, SessionRulesetContext
from sentry_copilot.domain.runtime_slots import (
    RuntimeSlotObservation,
    SlotParticipantAssociationBasis,
    SlotParticipantAssociationRecord,
)
from sentry_copilot.domain.slot_strategy_assignments import (
    SlotStrategyAssignmentUnresolvedReason,
    SlotStrategyAssignmentView,
)
from sentry_copilot.domain.strategy_identification import (
    StrategyIdentificationBasis,
    StrategyIdentificationRecord,
)
from sentry_copilot.domain.strategy_selection import (
    ParticipantField,
    StrategySelectionParticipant,
    StrategySelectionSnapshot,
)
from sentry_copilot.services.ruleset_context_service import RulesetContextService
from sentry_copilot.services.slot_strategy_assignment_service import (
    SlotStrategyAssignmentService,
)
from sentry_copilot.services.strategy_identification_service import (
    StrategyIdentificationService,
)

NOW = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
SESSION_ID = "session.synthetic"
RULESET_ID = "demo.synthetic_covenant_latter"
EARLY = "demo.synthetic_covenant_latter.pre_update"
LATE = "demo.synthetic_covenant_latter.post_update"
CATALOG_VERSION = "catalog.synthetic.v1"
P1 = "session-player-1"
P2 = "session-player-2"
SLOT_1 = "runtime-slot.synthetic.1"
SLOT_2 = "runtime-slot.synthetic.2"
LAYOUT = "runtime-layout.synthetic.1"
GUARD = "strategy.synthetic.guard"
GROWTH = "strategy.synthetic.growth"
SUPPORT = "strategy.synthetic.support"


@pytest.fixture
def repository() -> StrategyCatalogRepository:
    return StrategyCatalogRepository.from_directory("data/strategy_catalogs")


@pytest.fixture
def assignment_service(
    repository: StrategyCatalogRepository,
) -> SlotStrategyAssignmentService:
    return SlotStrategyAssignmentService(repository)


@pytest.fixture
def identification_service(
    repository: StrategyCatalogRepository,
) -> StrategyIdentificationService:
    return StrategyIdentificationService(repository)


def context(revision: str = EARLY, generation: int = 1) -> SessionRulesetContext:
    return SessionRulesetContext(
        ruleset_id=RULESET_ID,
        ruleset_revision_id=revision,
        locale_id="zh_CN",
        catalog_version=CATALOG_VERSION,
        selection_method=RevisionSelectionMethod.MANUAL,
        selected_at=NOW,
        selection_reason="synthetic assignment test",
        context_generation=generation,
    )


def state(participants: tuple[str, ...] = (P1, P2)) -> SessionState:
    tags = {P1: "0038", P2: "1042"}
    return SessionState(
        session_id=SESSION_ID,
        ruleset_context=context(),
        players=[
            PlayerState(
                slot=1,
                avatar_visual_key="avatar.synthetic.ignore",
                hp=999,
                strategy_id=SUPPORT,
            )
        ],
        strategy_selection=StrategySelectionSnapshot(
            session_id=SESSION_ID,
            ruleset_id=RULESET_ID,
            captured_at=NOW,
            participants=tuple(
                StrategySelectionParticipant(
                    session_player_id=participant_id,
                    selection_row=3 + index,
                    player_tag=tags[participant_id],
                    strategy_id=SUPPORT,
                    field_evidence={
                        ParticipantField.PLAYER_TAG: evidence(),
                        ParticipantField.STRATEGY: evidence(),
                    },
                )
                for index, participant_id in enumerate(participants)
            ),
        ),
        updated_at=NOW,
    )


def evidence() -> EvidenceRecord:
    return EvidenceRecord(
        source=EvidenceKind.OBSERVED,
        confidence=0.99,
        observed_at=NOW,
    )


def enter(current: SessionState, participant_id: str) -> SessionState:
    return reduce_session(
        current,
        BattleEntryConfirmed(
            evidence_id=f"evidence.entry.{participant_id}",
            session_id=SESSION_ID,
            session_player_id=participant_id,
            timestamp=NOW,
            provenance=EvidenceKind.OBSERVED,
            confidence=0.99,
            frame_reference="private/synthetic/entry.png",
            observed_visual_cue="synthetic normal active entry",
        ),
    )


def observe_slot(
    current: SessionState,
    *,
    slot_id: str = SLOT_1,
    participant_id: str = P1,
    evidence_id: str | None = None,
    observed_at: datetime = NOW + timedelta(seconds=1),
) -> SessionState:
    tag = {P1: "0038", P2: "1042"}[participant_id]
    return reduce_session(
        current,
        RuntimeSlotObservation(
            evidence_id=evidence_id or f"evidence.slot.{slot_id}.{participant_id}",
            session_id=SESSION_ID,
            layout_id=LAYOUT,
            runtime_slot_id=slot_id,
            observed_at=observed_at,
            visual_index=1 if slot_id == SLOT_1 else 2,
            roi={"x": 0.01, "y": 0.1, "width": 0.1, "height": 0.1},
            slot_visible=True,
            normal_active_presentation_visible=True,
            observed_player_tag=tag,
            provenance=EvidenceKind.OBSERVED,
            confidence=0.99,
            frame_reference="private/synthetic/slot.png",
            source_detail="synthetic slot observation",
        ),
    )


def associate(
    current: SessionState,
    *,
    participant_id: str = P1,
    slot_id: str = SLOT_1,
    evidence_id: str | None = None,
    record_id: str | None = None,
) -> SessionState:
    return reduce_session(
        current,
        SlotAssociationRecordsAppended(
            session_id=SESSION_ID,
            records=(
                SlotParticipantAssociationRecord(
                    record_id=record_id
                    or f"association.{slot_id}.{participant_id}",
                    session_id=SESSION_ID,
                    layout_id=LAYOUT,
                    runtime_slot_id=slot_id,
                    session_player_id=participant_id,
                    basis=SlotParticipantAssociationBasis.DIRECT_PLAYER_TAG,
                    associated_at=NOW + timedelta(seconds=2),
                    evidence_ids=(
                        evidence_id or f"evidence.slot.{slot_id}.{participant_id}",
                    ),
                ),
            ),
            timestamp=NOW + timedelta(seconds=2),
        ),
    )


def direct_identify(
    service: StrategyIdentificationService,
    current: SessionState,
    *,
    participant_id: str = P1,
    strategy_id: str = GUARD,
    record_id: str | None = None,
) -> SessionState:
    evidence_id = f"evidence.panel.{record_id or participant_id}"
    panel = StrategySelectionConfirmedEvidence(
        evidence_id=evidence_id,
        session_id=SESSION_ID,
        session_player_id=participant_id,
        timestamp=NOW + timedelta(seconds=3),
        provenance=EvidenceKind.OBSERVED,
        confidence=0.99,
        frame_reference="private/synthetic/panel.png",
        observed_visual_cue="synthetic participant-bound panel",
        confirmation_source=(
            StrategySelectionConfirmationSource.DIRECT_STRATEGY_OBSERVATION
        ),
    )
    return service.identify(
        current,
        RecordStrategyIdentification(
            session_id=SESSION_ID,
            record=StrategyIdentificationRecord(
                record_id=record_id or f"identification.{participant_id}.{strategy_id}",
                session_player_id=participant_id,
                strategy_id=strategy_id,
                basis=StrategyIdentificationBasis.DIRECT_OBSERVATION,
                identified_at=NOW + timedelta(seconds=3),
                evidence_ids=(evidence_id,),
            ),
            commitment_evidence=panel,
        ),
    )


def manual_identify(
    service: StrategyIdentificationService,
    current: SessionState,
) -> SessionState:
    evidence_id = "evidence.panel.manual"
    panel = StrategySelectionConfirmedEvidence(
        evidence_id=evidence_id,
        session_id=SESSION_ID,
        session_player_id=P1,
        timestamp=NOW + timedelta(seconds=3),
        provenance=EvidenceKind.MANUAL,
        confidence=1.0,
        manual_note="synthetic manual panel confirmation",
        confirmation_source=(
            StrategySelectionConfirmationSource.MANUAL_STRATEGY_CONFIRMATION
        ),
        manual_reason="synthetic manual assignment confirmation",
    )
    return service.identify(
        current,
        RecordStrategyIdentification(
            session_id=SESSION_ID,
            record=StrategyIdentificationRecord(
                record_id="identification.manual",
                session_player_id=P1,
                strategy_id=GUARD,
                basis=StrategyIdentificationBasis.MANUAL_CONFIRMATION,
                identified_at=NOW + timedelta(seconds=3),
                evidence_ids=(evidence_id,),
                reason="synthetic manual assignment confirmation",
            ),
            commitment_evidence=panel,
        ),
    )


def catalog_identify(
    service: StrategyIdentificationService,
    current: SessionState,
) -> SessionState:
    ready = ReadyCheckObserved(
        evidence_id="evidence.ready.catalog",
        session_id=SESSION_ID,
        session_player_id=P1,
        timestamp=NOW,
        provenance=EvidenceKind.OBSERVED,
        confidence=0.99,
        frame_reference="private/synthetic/ready.png",
        observed_visual_cue="synthetic ready check",
    )
    candidate = StrategyCandidateObserved(
        evidence_id="evidence.candidate.catalog",
        session_id=SESSION_ID,
        session_player_id=P1,
        timestamp=NOW + timedelta(seconds=1),
        provenance=EvidenceKind.OBSERVED,
        confidence=0.95,
        frame_reference="private/synthetic/candidate.png",
        observed_visual_cue="synthetic candidate visual",
    )
    current = reduce_session(current, ready)
    current = reduce_session(current, candidate)
    assert current.ruleset_dependency_stamp is not None
    return service.identify(
        current,
        RecordStrategyIdentification(
            session_id=SESSION_ID,
            record=StrategyIdentificationRecord(
                record_id="identification.catalog",
                session_player_id=P1,
                strategy_id=GUARD,
                basis=StrategyIdentificationBasis.CATALOG_DERIVED,
                identified_at=NOW + timedelta(seconds=3),
                evidence_ids=(candidate.evidence_id,),
                dependency_stamp=current.ruleset_dependency_stamp,
            ),
        ),
    )


def associated_entrant_state() -> SessionState:
    current = enter(state(), P1)
    current = observe_slot(current)
    return associate(current)


def test_complete_authority_chain_derives_assignment(
    assignment_service: SlotStrategyAssignmentService,
    identification_service: StrategyIdentificationService,
) -> None:
    current = direct_identify(identification_service, associated_entrant_state())

    result = assignment_service.get_current_slot_assignment(current, SLOT_1)

    assert result is not None
    assert result.strategy_id == GUARD
    assert result.session_player_id == P1
    assert result.participation_status == PlayerParticipationStatus.ACTIVE
    assert result.dependency_stamp == current.ruleset_dependency_stamp
    assert assignment_service.get_all_current_slot_assignments(current) == (result,)


def test_unknown_association_is_unresolved(
    assignment_service: SlotStrategyAssignmentService,
) -> None:
    current = observe_slot(enter(state(), P1))

    unresolved = assignment_service.get_unresolved_slot_assignments(current)

    assert unresolved[0].reason == (
        SlotStrategyAssignmentUnresolvedReason.PARTICIPANT_ASSOCIATION_UNKNOWN
    )


def test_association_conflict_is_unresolved(
    assignment_service: SlotStrategyAssignmentService,
) -> None:
    current = enter(enter(state(), P1), P2)
    current = observe_slot(current, participant_id=P1)
    current = observe_slot(
        current,
        participant_id=P2,
        evidence_id="evidence.slot.conflict.p2",
        observed_at=NOW + timedelta(seconds=2),
    )
    current = associate(current, participant_id=P1)
    current = associate(
        current,
        participant_id=P2,
        evidence_id="evidence.slot.conflict.p2",
        record_id="association.conflict.p2",
    )

    unresolved = assignment_service.get_unresolved_slot_assignments(current)

    assert unresolved[0].reason == (
        SlotStrategyAssignmentUnresolvedReason.PARTICIPANT_ASSOCIATION_CONFLICT
    )


def test_unknown_identification_is_unresolved(
    assignment_service: SlotStrategyAssignmentService,
) -> None:
    unresolved = assignment_service.get_unresolved_slot_assignments(associated_entrant_state())

    assert unresolved[0].reason == (
        SlotStrategyAssignmentUnresolvedReason.STRATEGY_IDENTIFICATION_UNKNOWN
    )


@pytest.mark.parametrize(
    ("strategy_ids", "expected_reason"),
    [
        (
            (GUARD, GROWTH),
            SlotStrategyAssignmentUnresolvedReason.PARTICIPANT_STRATEGY_IDENTIFICATION_CONFLICT,
        ),
    ],
)
def test_participant_identification_conflict_is_unresolved(
    assignment_service: SlotStrategyAssignmentService,
    identification_service: StrategyIdentificationService,
    strategy_ids: tuple[str, str],
    expected_reason: SlotStrategyAssignmentUnresolvedReason,
) -> None:
    current = direct_identify(
        identification_service,
        associated_entrant_state(),
        strategy_id=strategy_ids[0],
        record_id="identification.one",
    )
    current = direct_identify(
        identification_service,
        current,
        strategy_id=strategy_ids[1],
        record_id="identification.two",
    )

    assert assignment_service.get_unresolved_slot_assignments(current)[0].reason == expected_reason


def test_duplicate_confirmed_strategy_claim_is_unresolved(
    assignment_service: SlotStrategyAssignmentService,
    identification_service: StrategyIdentificationService,
) -> None:
    current = enter(enter(state(), P1), P2)
    current = associate(observe_slot(current, participant_id=P1), participant_id=P1)
    current = observe_slot(current, slot_id=SLOT_2, participant_id=P2)
    current = associate(current, slot_id=SLOT_2, participant_id=P2)
    current = direct_identify(identification_service, current, record_id="identification.p1")
    current = direct_identify(
        identification_service,
        current,
        participant_id=P2,
        record_id="identification.p2",
    )

    unresolved = assignment_service.get_unresolved_slot_assignments(current)

    assert {item.reason for item in unresolved} == {
        SlotStrategyAssignmentUnresolvedReason.DUPLICATE_CONFIRMED_STRATEGY_CLAIM
    }


def test_catalog_compatibility_conflict_is_unresolved(
    assignment_service: SlotStrategyAssignmentService,
    identification_service: StrategyIdentificationService,
) -> None:
    current = direct_identify(
        identification_service,
        associated_entrant_state(),
        strategy_id=SUPPORT,
    )

    assert assignment_service.get_unresolved_slot_assignments(current)[0].reason == (
        SlotStrategyAssignmentUnresolvedReason.STRATEGY_CATALOG_COMPATIBILITY_CONFLICT
    )


def test_stale_catalog_derived_identification_is_unresolved(
    assignment_service: SlotStrategyAssignmentService,
    identification_service: StrategyIdentificationService,
    repository: StrategyCatalogRepository,
) -> None:
    current = catalog_identify(identification_service, associated_entrant_state())
    current = RulesetContextService(repository).correct(
        current,
        CorrectSessionRulesetRevision(
            session_id=SESSION_ID,
            ruleset_id=RULESET_ID,
            ruleset_revision_id=LATE,
            locale_id="zh_CN",
            catalog_version=CATALOG_VERSION,
            selected_at=NOW + timedelta(seconds=10),
            reason="synthetic revision correction",
        ),
    )

    assert assignment_service.get_unresolved_slot_assignments(current)[0].reason == (
        SlotStrategyAssignmentUnresolvedReason.STRATEGY_IDENTIFICATION_STALE
    )


@pytest.mark.parametrize(
    "basis",
    [
        StrategyIdentificationBasis.DIRECT_OBSERVATION,
        StrategyIdentificationBasis.MANUAL_CONFIRMATION,
    ],
)
def test_compatible_direct_or_manual_identification_assigns(
    assignment_service: SlotStrategyAssignmentService,
    identification_service: StrategyIdentificationService,
    repository: StrategyCatalogRepository,
    basis: StrategyIdentificationBasis,
) -> None:
    if basis == StrategyIdentificationBasis.DIRECT_OBSERVATION:
        current = direct_identify(identification_service, associated_entrant_state())
    else:
        current = manual_identify(identification_service, associated_entrant_state())

    current = RulesetContextService(repository).correct(
        current,
        CorrectSessionRulesetRevision(
            session_id=SESSION_ID,
            ruleset_id=RULESET_ID,
            ruleset_revision_id=LATE,
            locale_id="zh_CN",
            catalog_version=CATALOG_VERSION,
            selected_at=NOW + timedelta(seconds=10),
            reason="synthetic revision correction",
        ),
    )

    assert assignment_service.get_current_slot_assignment(current, SLOT_1) is not None


def test_legacy_snapshot_selection_row_avatar_and_hp_are_ignored(
    assignment_service: SlotStrategyAssignmentService,
    identification_service: StrategyIdentificationService,
) -> None:
    current = direct_identify(identification_service, associated_entrant_state())

    assignment = assignment_service.get_current_slot_assignment(current, SLOT_1)

    assert assignment is not None
    assert assignment.strategy_id == GUARD
    assert current.strategy_selection is not None
    assert assignment.strategy_id != current.strategy_selection.participants[0].strategy_id
    assert current.strategy_selection.participants[0].selection_row != 1
    assert current.players[0].strategy_id == SUPPORT
    assert current.players[0].hp == 999


def test_inactive_known_assignment_is_retained_with_status(
    assignment_service: SlotStrategyAssignmentService,
    identification_service: StrategyIdentificationService,
) -> None:
    current = direct_identify(identification_service, associated_entrant_state())
    current = reduce_session(
        current,
        BattleParticipantInactivated(
            evidence_id="evidence.inactive.1",
            session_id=SESSION_ID,
            session_player_id=P1,
            observed_at=NOW + timedelta(seconds=20),
            provenance=EvidenceKind.OBSERVED,
            confidence=0.99,
            evidence_reference="private/synthetic/inactive.png",
            observed_visual_cue="synthetic departed",
            stage_type=BattleRuntimeStageType.NORMAL,
            round_number=1,
            wave_number=1,
            reason=PlayerInactivationReason.HP_DEPLETED,
            presentation=InactivePresentation.SPECTATING,
            hp=0,
        ),
    )

    assignment = assignment_service.get_current_slot_assignment(current, SLOT_1)

    assert assignment is not None
    assert assignment.participation_status == PlayerParticipationStatus.INACTIVE


def test_inactive_unknown_strategy_remains_unresolved(
    assignment_service: SlotStrategyAssignmentService,
) -> None:
    current = associated_entrant_state()
    current = reduce_session(
        current,
        BattleParticipantInactivated(
            evidence_id="evidence.inactive.unknown",
            session_id=SESSION_ID,
            session_player_id=P1,
            observed_at=NOW + timedelta(seconds=20),
            provenance=EvidenceKind.OBSERVED,
            confidence=0.99,
            evidence_reference="private/synthetic/inactive.png",
            observed_visual_cue="synthetic departed",
            stage_type=BattleRuntimeStageType.NORMAL,
            round_number=1,
            wave_number=1,
            reason=PlayerInactivationReason.LEFT_OR_DISCONNECTED,
            presentation=InactivePresentation.DEPARTED,
        ),
    )

    assert assignment_service.get_unresolved_slot_assignments(current)[0].reason == (
        SlotStrategyAssignmentUnresolvedReason.STRATEGY_IDENTIFICATION_UNKNOWN
    )


def test_solo_slot_and_query_are_immutable_and_round_trip(
    assignment_service: SlotStrategyAssignmentService,
    identification_service: StrategyIdentificationService,
) -> None:
    current = enter(state((P1,)), P1)
    current = observe_slot(current)
    current = associate(current)
    current = direct_identify(identification_service, current)
    before = current.model_dump(mode="json")

    view = assignment_service.get_current_slot_assignment_view(current)

    assert len(view.assignments) == 1
    with pytest.raises(ValidationError):
        view.assignments[0].strategy_id = GROWTH
    assert SlotStrategyAssignmentView.model_validate_json(view.model_dump_json()) == view
    assert current.model_dump(mode="json") == before
