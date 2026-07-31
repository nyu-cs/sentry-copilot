from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from sentry_copilot.domain.battle_roster import (
    BattleEntryStatus,
    BattleInactivationCorrected,
    BattleInactivationReplacement,
    BattleParticipantInactivated,
    BattleParticipationState,
    BattleRuntimeStageType,
    InactivePresentation,
    PlayerInactivationReason,
    PlayerParticipationStatus,
)
from sentry_copilot.domain.enums import EvidenceKind
from sentry_copilot.domain.events import StrategyIdentificationRecordsAppended
from sentry_copilot.domain.models import PlayerState, SessionState
from sentry_copilot.domain.prebattle import (
    BattleEntryConfirmed,
    BattleEntryFalsePositiveCorrected,
    BattleEntryNotConfirmed,
    BattleEntryNotConfirmedReason,
    ReadyCheckObserved,
    StrategySelectionConfirmationSource,
    StrategySelectionConfirmedEvidence,
)
from sentry_copilot.domain.queries import (
    build_battle_roster,
    get_active_battle_participants,
    get_battle_entry_status,
)
from sentry_copilot.domain.reducer import InvalidObservationError, reduce_session
from sentry_copilot.domain.strategy_identification import (
    StrategyIdentificationBasis,
    StrategyIdentificationRecord,
    derive_strategy_occupancy_view,
)
from sentry_copilot.domain.strategy_selection import (
    StrategySelectionParticipant,
    StrategySelectionSnapshot,
)

NOW = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)
SESSION_ID = "session.synthetic"
RULESET_ID = "demo.synthetic_covenant_latter"
P1 = "session-player-1"
P2 = "session-player-2"
STRATEGY_ID = "strategy.synthetic.guard"


def session_state(*, include_legacy_player: bool = False) -> SessionState:
    return SessionState(
        session_id=SESSION_ID,
        ruleset_id=RULESET_ID,
        players=(
            [PlayerState(slot=1, hp=8)] if include_legacy_player else []
        ),
        strategy_selection=StrategySelectionSnapshot(
            session_id=SESSION_ID,
            ruleset_id=RULESET_ID,
            captured_at=NOW,
            participants=(
                StrategySelectionParticipant(
                    session_player_id=P1,
                    selection_row=1,
                ),
                StrategySelectionParticipant(
                    session_player_id=P2,
                    selection_row=2,
                ),
            ),
        ),
        updated_at=NOW,
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
        observed_visual_cue="synthetic normal participation",
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


def entry_correction(
    *target_ids: str,
    participant_id: str = P1,
    evidence_id: str = "correction.battle-entry.1",
    timestamp: datetime = NOW + timedelta(seconds=5),
) -> BattleEntryFalsePositiveCorrected:
    return BattleEntryFalsePositiveCorrected(
        evidence_id=evidence_id,
        session_id=SESSION_ID,
        session_player_id=participant_id,
        timestamp=timestamp,
        invalidated_battle_entry_evidence_ids=target_ids,
        reason="synthetic false-positive entry correction",
    )


def inactivation(
    *,
    participant_id: str = P1,
    evidence_id: str = "evidence.inactivation.1",
    observed_at: datetime = NOW + timedelta(seconds=10),
    stage_type: BattleRuntimeStageType = BattleRuntimeStageType.NORMAL,
    round_number: int | None = 2,
    wave_number: int | None = 3,
    reason: PlayerInactivationReason = (
        PlayerInactivationReason.LEFT_OR_DISCONNECTED
    ),
    presentation: InactivePresentation = InactivePresentation.DEPARTED,
    hp: int | None = None,
) -> BattleParticipantInactivated:
    return BattleParticipantInactivated(
        evidence_id=evidence_id,
        session_id=SESSION_ID,
        session_player_id=participant_id,
        observed_at=observed_at,
        provenance=EvidenceKind.OBSERVED,
        confidence=0.96,
        evidence_reference=f"private/synthetic/{evidence_id}.png",
        observed_visual_cue="synthetic inactive presentation",
        stage_type=stage_type,
        round_number=round_number,
        wave_number=wave_number,
        reason=reason,
        presentation=presentation,
        hp=hp,
    )


def inactivation_correction(
    target_id: str = "evidence.inactivation.1",
    *,
    evidence_id: str = "correction.inactivation.1",
    replacement: BattleInactivationReplacement | None = None,
    participant_id: str = P1,
    corrected_at: datetime = NOW + timedelta(seconds=20),
) -> BattleInactivationCorrected:
    return BattleInactivationCorrected(
        evidence_id=evidence_id,
        session_id=SESSION_ID,
        session_player_id=participant_id,
        corrected_at=corrected_at,
        invalidated_inactivation_evidence_id=target_id,
        replacement=replacement,
        reason="synthetic assistant-record correction",
    )


def ready() -> ReadyCheckObserved:
    return ReadyCheckObserved(
        evidence_id="evidence.ready.1",
        session_id=SESSION_ID,
        session_player_id=P1,
        timestamp=NOW,
        provenance=EvidenceKind.OBSERVED,
        confidence=0.99,
        frame_reference="private/synthetic/ready.png",
        observed_visual_cue="synthetic ready check",
    )


def direct_strategy_evidence() -> StrategySelectionConfirmedEvidence:
    return StrategySelectionConfirmedEvidence(
        evidence_id="evidence.strategy.direct.1",
        session_id=SESSION_ID,
        session_player_id=P1,
        timestamp=NOW,
        provenance=EvidenceKind.OBSERVED,
        confidence=0.99,
        frame_reference="private/synthetic/strategy-panel.png",
        observed_visual_cue="synthetic participant-bound strategy panel",
        confirmation_source=(
            StrategySelectionConfirmationSource.DIRECT_STRATEGY_OBSERVATION
        ),
    )


def with_entry(state: SessionState | None = None) -> SessionState:
    return reduce_session(state or session_state(), battle_entry())


def test_confirmed_entry_derives_active_roster_participant() -> None:
    state = with_entry()

    roster = build_battle_roster(state)

    assert roster.session_id == SESSION_ID
    assert len(roster.participants) == 1
    assert roster.participants[0].session_player_id == P1
    assert roster.participants[0].participation_status == (
        PlayerParticipationStatus.ACTIVE
    )
    assert get_battle_entry_status(state, P1) == BattleEntryStatus.CONFIRMED


def test_first_stable_frame_already_inactive_is_not_an_entrant() -> None:
    state = reduce_session(session_state(), entry_not_confirmed())

    assert build_battle_roster(state).participants == ()
    assert get_active_battle_participants(state) == ()
    assert get_battle_entry_status(state, P1) == BattleEntryStatus.NOT_CONFIRMED


def test_ready_without_confirmed_entry_does_not_create_entrant() -> None:
    state = reduce_session(session_state(), ready())

    assert state.strategy_commitments is not None
    assert build_battle_roster(state).participants == ()


def test_legacy_snapshot_presence_does_not_create_entrant() -> None:
    assert build_battle_roster(session_state()).participants == ()
    assert get_battle_entry_status(session_state(), P1) == BattleEntryStatus.UNKNOWN


def test_false_positive_entry_correction_preserves_history_and_removes_entrant() -> None:
    state = with_entry()
    corrected = reduce_session(
        state,
        entry_correction("evidence.battle-entry.1"),
    )

    assert corrected.prebattle_evidence is not None
    assert len(corrected.prebattle_evidence.entries) == 2
    assert corrected.prebattle_evidence.get("evidence.battle-entry.1") == (
        battle_entry()
    )
    assert build_battle_roster(corrected).participants == ()
    assert get_battle_entry_status(corrected, P1) == BattleEntryStatus.UNKNOWN


def test_correcting_one_of_two_entry_facts_keeps_earliest_effective_entry() -> None:
    state = with_entry()
    second_time = NOW + timedelta(seconds=2)
    state = reduce_session(
        state,
        battle_entry(
            evidence_id="evidence.battle-entry.2",
            timestamp=second_time,
        ),
    )
    state = reduce_session(
        state,
        entry_correction("evidence.battle-entry.1"),
    )

    participant = build_battle_roster(state).participants[0]
    assert participant.entered_at == second_time
    assert participant.entry_evidence_ids == ("evidence.battle-entry.2",)


def test_entry_correction_removes_entry_only_commitment() -> None:
    state = with_entry()
    assert state.strategy_commitments is not None
    assert state.strategy_commitments.for_participant(P1) is not None

    state = reduce_session(state, entry_correction("evidence.battle-entry.1"))

    assert state.strategy_commitments is not None
    assert state.strategy_commitments.for_participant(P1) is None


def test_entry_correction_does_not_remove_independent_ready_commitment() -> None:
    state = reduce_session(session_state(), ready())
    state = reduce_session(state, battle_entry())

    state = reduce_session(state, entry_correction("evidence.battle-entry.1"))

    assert state.strategy_commitments is not None
    commitment = state.strategy_commitments.for_participant(P1)
    assert commitment is not None
    assert commitment.ready_evidence_ids == ("evidence.ready.1",)
    assert commitment.battle_entry_evidence_ids == ()
    assert build_battle_roster(state).participants == ()


def test_entry_correction_is_idempotent_and_rejects_id_collision() -> None:
    state = with_entry()
    correction = entry_correction("evidence.battle-entry.1")
    corrected = reduce_session(state, correction)

    assert reduce_session(corrected, correction) is corrected
    collision = correction.model_copy(update={"reason": "different correction"})
    with pytest.raises(InvalidObservationError):
        reduce_session(corrected, collision)


def test_failed_entry_correction_is_atomic() -> None:
    state = with_entry()
    before = state.model_dump()

    with pytest.raises(InvalidObservationError):
        reduce_session(
            state,
            entry_correction("evidence.missing", evidence_id="correction.invalid"),
        )

    assert state.model_dump() == before


def test_only_confirmed_entrant_can_become_inactive() -> None:
    with pytest.raises(InvalidObservationError):
        reduce_session(session_state(), inactivation())

    not_entered = reduce_session(session_state(), entry_not_confirmed())
    with pytest.raises(InvalidObservationError):
        reduce_session(not_entered, inactivation())


def test_left_or_disconnected_inactivation_is_retained_in_roster() -> None:
    state = reduce_session(with_entry(), inactivation())

    participant = build_battle_roster(state).participants[0]
    assert participant.participation_status == PlayerParticipationStatus.INACTIVE
    assert participant.inactivation_reason == (
        PlayerInactivationReason.LEFT_OR_DISCONNECTED
    )
    assert participant.inactive_presentation == InactivePresentation.DEPARTED
    assert participant.stage_type == BattleRuntimeStageType.NORMAL
    assert participant.round_number == 2
    assert participant.wave_number == 3
    assert get_active_battle_participants(state) == ()


@pytest.mark.parametrize(
    ("presentation", "hp"),
    (
        (InactivePresentation.DEPARTED, 0),
        (InactivePresentation.SPECTATING, 0),
    ),
)
def test_hp_depleted_inactivation_can_depart_or_spectate(
    presentation: InactivePresentation,
    hp: int,
) -> None:
    state = reduce_session(
        with_entry(),
        inactivation(
            reason=PlayerInactivationReason.HP_DEPLETED,
            presentation=presentation,
            hp=hp,
        ),
    )

    participant = build_battle_roster(state).participants[0]
    assert participant.inactivation_reason == PlayerInactivationReason.HP_DEPLETED
    assert participant.inactive_presentation == presentation
    assert participant.hp == 0


def test_departed_presentation_alone_allows_unknown_reason() -> None:
    event = inactivation(
        reason=PlayerInactivationReason.UNKNOWN,
        presentation=InactivePresentation.DEPARTED,
    )

    state = reduce_session(with_entry(), event)

    assert build_battle_roster(state).participants[0].inactivation_reason == (
        PlayerInactivationReason.UNKNOWN
    )


@pytest.mark.parametrize(
    "updates",
    (
        {
            "reason": PlayerInactivationReason.UNKNOWN,
            "presentation": InactivePresentation.SPECTATING,
        },
        {
            "reason": PlayerInactivationReason.LEFT_OR_DISCONNECTED,
            "presentation": InactivePresentation.UNKNOWN,
        },
        {
            "reason": PlayerInactivationReason.UNKNOWN,
            "presentation": InactivePresentation.DEPARTED,
            "hp": 0,
        },
        {
            "reason": PlayerInactivationReason.HP_DEPLETED,
            "presentation": InactivePresentation.DEPARTED,
            "hp": 1,
        },
    ),
)
def test_inactivation_reason_and_presentation_invariants(
    updates: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        inactivation(**updates)


def test_secret_core_records_wave_without_fake_round_number() -> None:
    state = reduce_session(
        with_entry(),
        inactivation(
            stage_type=BattleRuntimeStageType.SECRET_CORE,
            round_number=None,
            wave_number=4,
        ),
    )

    participant = build_battle_roster(state).participants[0]
    assert participant.stage_type == BattleRuntimeStageType.SECRET_CORE
    assert participant.round_number is None
    assert participant.wave_number == 4


def test_secret_core_rejects_normal_round_number() -> None:
    with pytest.raises(ValidationError):
        inactivation(
            stage_type=BattleRuntimeStageType.SECRET_CORE,
            round_number=3,
        )


def test_inactive_is_terminal_for_game_observations() -> None:
    state = reduce_session(with_entry(), inactivation())
    before = state.model_dump()

    with pytest.raises(InvalidObservationError):
        reduce_session(
            state,
            inactivation(
                evidence_id="evidence.inactivation.2",
                observed_at=NOW + timedelta(seconds=30),
            ),
        )

    assert state.model_dump() == before


def test_false_positive_inactivation_correction_restores_query_to_active() -> None:
    state = reduce_session(with_entry(), inactivation())
    corrected = reduce_session(state, inactivation_correction())

    participant = build_battle_roster(corrected).participants[0]
    assert participant.participation_status == PlayerParticipationStatus.ACTIVE
    assert corrected.battle_participation is not None
    assert len(corrected.battle_participation.entries) == 2
    assert corrected.battle_participation.get("evidence.inactivation.1") == (
        inactivation()
    )
    assert not hasattr(PlayerParticipationStatus, "REACTIVATED")


def test_reason_and_presentation_correction_is_auditable() -> None:
    state = reduce_session(
        with_entry(),
        inactivation(
            reason=PlayerInactivationReason.UNKNOWN,
            presentation=InactivePresentation.DEPARTED,
        ),
    )
    replacement = BattleInactivationReplacement(
        inactivated_at=NOW + timedelta(seconds=10),
        stage_type=BattleRuntimeStageType.NORMAL,
        round_number=2,
        wave_number=3,
        reason=PlayerInactivationReason.HP_DEPLETED,
        presentation=InactivePresentation.SPECTATING,
        hp=0,
    )

    corrected = reduce_session(
        state,
        inactivation_correction(replacement=replacement),
    )

    participant = build_battle_roster(corrected).participants[0]
    assert participant.participation_status == PlayerParticipationStatus.INACTIVE
    assert participant.inactivation_reason == PlayerInactivationReason.HP_DEPLETED
    assert participant.inactive_presentation == InactivePresentation.SPECTATING
    assert participant.inactivation_evidence_ids == ("correction.inactivation.1",)
    assert corrected.battle_participation is not None
    assert len(corrected.battle_participation.entries) == 2


def test_inactivation_correction_is_idempotent_and_rejects_id_collision() -> None:
    state = reduce_session(with_entry(), inactivation())
    correction = inactivation_correction()
    corrected = reduce_session(state, correction)

    assert reduce_session(corrected, correction) is corrected
    collision = correction.model_copy(update={"reason": "different correction"})
    with pytest.raises(InvalidObservationError):
        reduce_session(corrected, collision)


def test_inactivation_observation_is_idempotent_and_rejects_id_collision() -> None:
    state = with_entry()
    event = inactivation()
    inactive = reduce_session(state, event)

    assert reduce_session(inactive, event) is inactive
    collision = event.model_copy(update={"confidence": 0.5})
    with pytest.raises(InvalidObservationError):
        reduce_session(inactive, collision)


def test_failed_inactivation_correction_is_atomic() -> None:
    state = reduce_session(with_entry(), inactivation())
    before = state.model_dump()

    with pytest.raises(InvalidObservationError):
        reduce_session(
            state,
            inactivation_correction(
                target_id="evidence.missing",
                evidence_id="correction.invalid",
            ),
        )

    assert state.model_dump() == before


def test_inactivation_correction_cannot_cross_participants() -> None:
    state = reduce_session(with_entry(), inactivation())

    with pytest.raises(InvalidObservationError):
        reduce_session(
            state,
            inactivation_correction(participant_id=P2),
        )


def test_correction_can_be_corrected_without_a_game_reactivation_event() -> None:
    state = reduce_session(with_entry(), inactivation())
    first_replacement = BattleInactivationReplacement(
        inactivated_at=NOW + timedelta(seconds=10),
        stage_type=BattleRuntimeStageType.NORMAL,
        round_number=2,
        wave_number=3,
        reason=PlayerInactivationReason.UNKNOWN,
        presentation=InactivePresentation.DEPARTED,
    )
    first = inactivation_correction(replacement=first_replacement)
    state = reduce_session(state, first)
    replacement = BattleInactivationReplacement(
        inactivated_at=NOW + timedelta(seconds=10),
        stage_type=BattleRuntimeStageType.NORMAL,
        round_number=2,
        wave_number=3,
        reason=PlayerInactivationReason.LEFT_OR_DISCONNECTED,
        presentation=InactivePresentation.DEPARTED,
    )

    state = reduce_session(
        state,
        inactivation_correction(
            target_id=first.evidence_id,
            evidence_id="correction.inactivation.2",
            replacement=replacement,
            corrected_at=NOW + timedelta(seconds=30),
        ),
    )

    participant = build_battle_roster(state).participants[0]
    assert participant.participation_status == PlayerParticipationStatus.INACTIVE
    assert participant.inactivation_evidence_ids == ("correction.inactivation.2",)


def test_inactivation_does_not_mutate_snapshot_commitment_or_identification() -> None:
    state = reduce_session(session_state(), direct_strategy_evidence())
    state = reduce_session(state, battle_entry())
    record = StrategyIdentificationRecord(
        record_id="identification.synthetic.1",
        session_player_id=P1,
        strategy_id=STRATEGY_ID,
        basis=StrategyIdentificationBasis.DIRECT_OBSERVATION,
        identified_at=NOW,
        evidence_ids=("evidence.strategy.direct.1",),
    )
    state = reduce_session(
        state,
        StrategyIdentificationRecordsAppended(
            session_id=SESSION_ID,
            records=(record,),
            timestamp=NOW,
        ),
    )
    before_snapshot = state.strategy_selection
    before_commitments = state.strategy_commitments
    before_identifications = state.strategy_identifications
    occupancy_before = derive_strategy_occupancy_view(
        state.strategy_identifications,
        committed_participant_ids=frozenset((P1,)),
        current_dependency_stamp=None,
        available_strategy_ids=frozenset((STRATEGY_ID,)),
    )

    state = reduce_session(state, inactivation())
    occupancy_after = derive_strategy_occupancy_view(
        state.strategy_identifications,
        committed_participant_ids=frozenset((P1,)),
        current_dependency_stamp=None,
        available_strategy_ids=frozenset((STRATEGY_ID,)),
    )

    assert state.strategy_selection == before_snapshot
    assert state.strategy_commitments == before_commitments
    assert state.strategy_identifications == before_identifications
    assert occupancy_after == occupancy_before
    assert occupancy_after.occupancies[0].strategy_id == STRATEGY_ID


def test_legacy_hp_zero_does_not_mutate_new_battle_roster() -> None:
    from sentry_copilot.domain.events import PlayerHealthObserved

    state = with_entry(session_state(include_legacy_player=True))
    before = build_battle_roster(state)

    state = reduce_session(
        state,
        PlayerHealthObserved(slot=1, hp=0, timestamp=NOW + timedelta(seconds=4)),
    )

    assert state.players[0].hp == 0
    assert build_battle_roster(state) == before


def test_later_active_entry_does_not_reactivate_an_inactive_participant() -> None:
    state = reduce_session(with_entry(), inactivation())
    before = state.model_dump()

    with pytest.raises(InvalidObservationError):
        reduce_session(
            state,
            battle_entry(
                evidence_id="evidence.battle-entry.after-inactivation",
                timestamp=NOW + timedelta(seconds=30),
            ),
        )

    assert state.model_dump() == before


def test_roster_is_query_derived_not_a_session_state_field() -> None:
    state = with_entry()

    assert "battle_roster" not in SessionState.model_fields
    assert build_battle_roster(state).participants


def test_participation_models_are_immutable_and_json_round_trip() -> None:
    state = reduce_session(with_entry(), inactivation())
    participation = state.battle_participation
    assert participation is not None

    with pytest.raises(ValidationError):
        participation.entries[0].reason = PlayerInactivationReason.UNKNOWN
    with pytest.raises(ValidationError):
        participation.entries += (inactivation(evidence_id="evidence.other"),)

    assert BattleParticipationState.model_validate_json(
        participation.model_dump_json()
    ) == participation


@pytest.mark.parametrize(
    "time_value",
    (
        datetime(2026, 8, 3, 9, 0),
        datetime(2026, 8, 3, 9, 0, tzinfo=timezone(timedelta(hours=9))),
    ),
)
def test_public_times_reject_naive_and_accept_aware(time_value: datetime) -> None:
    if time_value.tzinfo is None:
        with pytest.raises(ValidationError):
            inactivation(observed_at=time_value)
    else:
        assert inactivation(observed_at=time_value).observed_at == time_value


def test_correction_times_reject_naive_datetime() -> None:
    with pytest.raises(ValidationError):
        inactivation_correction(corrected_at=datetime(2026, 8, 3, 9, 0))
    with pytest.raises(ValidationError):
        BattleInactivationReplacement(
            inactivated_at=datetime(2026, 8, 3, 9, 0),
            stage_type=BattleRuntimeStageType.NORMAL,
            reason=PlayerInactivationReason.UNKNOWN,
            presentation=InactivePresentation.DEPARTED,
        )


def test_session_and_participant_mismatch_are_rejected() -> None:
    state = with_entry()
    wrong_session = inactivation().model_copy(update={"session_id": "session.other"})
    unknown_participant = inactivation().model_copy(
        update={"session_player_id": "session-player-unknown"}
    )

    with pytest.raises(InvalidObservationError):
        reduce_session(state, wrong_session)
    with pytest.raises(InvalidObservationError):
        reduce_session(state, unknown_participant)
