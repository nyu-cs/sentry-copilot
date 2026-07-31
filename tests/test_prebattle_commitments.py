from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from sentry_copilot.domain.enums import EvidenceKind
from sentry_copilot.domain.events import (
    PlayerHealthObserved,
    StrategySelectionSnapshotObserved,
)
from sentry_copilot.domain.evidence import EvidenceRecord
from sentry_copilot.domain.models import PlayerState, SessionState
from sentry_copilot.domain.prebattle import (
    NormalizedRoi,
    PrebattleEvidenceLedger,
    ReadyCheckObserved,
    ReadyFalsePositiveCorrected,
    StrategyCandidateObserved,
)
from sentry_copilot.domain.queries import (
    build_prebattle_commitment_context,
    get_prebattle_evidence_ledger,
    get_ready_confirmed_commitment,
)
from sentry_copilot.domain.reducer import InvalidObservationError, reduce_session
from sentry_copilot.domain.strategy_commitment import (
    ParticipantCommitmentLevel,
    StrategyCommitmentState,
)
from sentry_copilot.domain.strategy_selection import (
    ParticipantField,
    SelectionOutcome,
    StrategySelectionParticipant,
    StrategySelectionSnapshot,
)

NOW = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
SESSION_ID = "session.synthetic"
PARTICIPANT_ID = "session-player-1"


def session_state(
    *,
    participant_ids: tuple[str, ...] = (PARTICIPANT_ID,),
    frozen: bool = False,
) -> SessionState:
    return SessionState(
        session_id=SESSION_ID,
        ruleset_id="demo.synthetic",
        strategy_selection=StrategySelectionSnapshot(
            session_id=SESSION_ID,
            ruleset_id="demo.synthetic",
            captured_at=NOW,
            participants=tuple(
                StrategySelectionParticipant(
                    session_player_id=participant_id,
                    selection_row=index,
                )
                for index, participant_id in enumerate(participant_ids, start=1)
            ),
            frozen=frozen,
        ),
        updated_at=NOW,
    )


def candidate(
    evidence_id: str = "evidence.candidate.1",
    *,
    participant_id: str = PARTICIPANT_ID,
    timestamp: datetime = NOW,
) -> StrategyCandidateObserved:
    return StrategyCandidateObserved(
        evidence_id=evidence_id,
        session_id=SESSION_ID,
        session_player_id=participant_id,
        timestamp=timestamp,
        provenance=EvidenceKind.OBSERVED,
        confidence=0.82,
        frame_reference="private/replay.synthetic/frame-001.png",
        roi=NormalizedRoi(x=0.1, y=0.2, width=0.2, height=0.2),
        observed_visual_cue="synthetic shield-shaped candidate",
    )


def ready(
    evidence_id: str = "evidence.ready.1",
    *,
    participant_id: str = PARTICIPANT_ID,
    timestamp: datetime = NOW,
) -> ReadyCheckObserved:
    return ReadyCheckObserved(
        evidence_id=evidence_id,
        session_id=SESSION_ID,
        session_player_id=participant_id,
        timestamp=timestamp,
        provenance=EvidenceKind.OBSERVED,
        confidence=0.96,
        frame_reference="private/replay.synthetic/frame-002.png",
        observed_visual_cue="synthetic ready check visible",
    )


def correction(
    evidence_id: str = "evidence.correction.1",
    *,
    participant_id: str = PARTICIPANT_ID,
    targets: tuple[str, ...] = ("evidence.ready.1",),
    timestamp: datetime = NOW + timedelta(seconds=10),
) -> ReadyFalsePositiveCorrected:
    return ReadyFalsePositiveCorrected(
        evidence_id=evidence_id,
        session_id=SESSION_ID,
        session_player_id=participant_id,
        timestamp=timestamp,
        invalidated_ready_evidence_ids=targets,
        reason="synthetic manual review found no ready check",
    )


def test_candidate_is_raw_evidence_without_strategy_id() -> None:
    observation = candidate()
    assert "strategy_id" not in type(observation).model_fields
    assert observation.observed_visual_cue == "synthetic shield-shaped candidate"
    assert StrategyCandidateObserved.model_validate_json(
        observation.model_dump_json()
    ) == observation


def test_observation_requires_raw_reference_and_aware_datetime() -> None:
    payload = candidate().model_dump()
    for field_name in (
        "frame_reference",
        "roi",
        "observed_visual_cue",
        "observed_text",
    ):
        payload[field_name] = None
    with pytest.raises(ValidationError, match="requires a frame"):
        StrategyCandidateObserved.model_validate(payload)

    with pytest.raises(ValidationError, match="timezone"):
        StrategyCandidateObserved.model_validate(
            {**candidate().model_dump(), "timestamp": datetime(2026, 8, 1)}
        )


def test_normalized_roi_cannot_escape_content_viewport() -> None:
    with pytest.raises(ValidationError, match="inside the content viewport"):
        NormalizedRoi(x=0.9, y=0.2, width=0.2, height=0.2)


def test_same_evidence_id_is_idempotent() -> None:
    original = session_state()
    event = candidate()
    observed = reduce_session(original, event)
    replayed = reduce_session(observed, event)
    assert replayed is observed
    assert original.prebattle_evidence is None
    assert original.strategy_commitments is None
    assert observed.prebattle_evidence is not None
    assert len(observed.prebattle_evidence.entries) == 1


def test_same_evidence_id_cannot_refer_to_different_evidence() -> None:
    original = session_state()
    observed = reduce_session(original, candidate())
    collision = candidate().model_copy(
        update={"observed_visual_cue": "different synthetic visual"}
    )
    with pytest.raises(InvalidObservationError, match="already refers"):
        reduce_session(observed, collision)
    assert observed.prebattle_evidence is not None
    assert observed.prebattle_evidence.entries == (candidate(),)


def test_distinct_ids_preserve_identical_frame_observations() -> None:
    state = reduce_session(session_state(), candidate())
    second = candidate("evidence.candidate.2")
    state = reduce_session(state, second)
    assert state.prebattle_evidence is not None
    assert [entry.evidence_id for entry in state.prebattle_evidence.entries] == [
        "evidence.candidate.1",
        "evidence.candidate.2",
    ]


def test_replaying_the_same_event_sequence_produces_the_same_state() -> None:
    events = (
        candidate(),
        ready(),
        ready("evidence.ready.2", timestamp=NOW + timedelta(seconds=1)),
    )
    once = session_state()
    for event in events:
        once = reduce_session(once, event)
    replayed = once
    for event in events:
        replayed = reduce_session(replayed, event)
    assert replayed == once


def test_first_ready_creates_strategy_unknown_commitment() -> None:
    state = reduce_session(session_state(), ready())
    commitment = get_ready_confirmed_commitment(state, PARTICIPANT_ID)
    assert commitment is not None
    assert commitment.confirmed_at == NOW
    assert commitment.ready_evidence_ids == ("evidence.ready.1",)

    context = build_prebattle_commitment_context(state)
    assert context is not None
    assert context.participants[0].level == (
        ParticipantCommitmentLevel.READY_CONFIRMED_STRATEGY_UNKNOWN
    )
    assert not hasattr(context.participants[0], "strategy_id")


def test_repeated_ready_appends_evidence_without_moving_confirmed_at() -> None:
    state = reduce_session(session_state(), ready())
    state = reduce_session(
        state,
        ready("evidence.ready.2", timestamp=NOW + timedelta(seconds=5)),
    )
    assert state.strategy_commitments is not None
    assert len(state.strategy_commitments.commitments) == 1
    commitment = state.strategy_commitments.commitments[0]
    assert commitment.confirmed_at == NOW
    assert commitment.ready_evidence_ids == (
        "evidence.ready.1",
        "evidence.ready.2",
    )


def test_ready_commitments_are_participant_specific() -> None:
    state = session_state(
        participant_ids=(PARTICIPANT_ID, "session-player-2")
    )
    state = reduce_session(state, ready())
    state = reduce_session(
        state,
        ready(
            "evidence.ready.2",
            participant_id="session-player-2",
            timestamp=NOW + timedelta(seconds=2),
        ),
    )
    assert state.strategy_commitments is not None
    assert len(state.strategy_commitments.commitments) == 2


def test_correcting_one_ready_keeps_other_effective_evidence() -> None:
    state = reduce_session(session_state(), ready())
    state = reduce_session(
        state,
        ready("evidence.ready.2", timestamp=NOW + timedelta(seconds=5)),
    )
    corrected = reduce_session(state, correction())
    commitment = get_ready_confirmed_commitment(corrected, PARTICIPANT_ID)
    assert commitment is not None
    assert commitment.confirmed_at == NOW + timedelta(seconds=5)
    assert commitment.ready_evidence_ids == ("evidence.ready.2",)
    assert corrected.prebattle_evidence is not None
    assert len(corrected.prebattle_evidence.entries) == 3
    assert corrected.prebattle_evidence.get("evidence.ready.1") == ready()


def test_correcting_all_ready_evidence_removes_assistant_commitment_only() -> None:
    state = reduce_session(session_state(), ready())
    corrected = reduce_session(state, correction())
    assert get_ready_confirmed_commitment(corrected, PARTICIPANT_ID) is None
    assert corrected.prebattle_evidence is not None
    assert corrected.prebattle_evidence.get("evidence.ready.1") == ready()
    assert corrected.prebattle_evidence.invalidated_ready_evidence_ids == {
        "evidence.ready.1"
    }
    context = build_prebattle_commitment_context(corrected)
    assert context is not None
    assert context.participants[0].level == ParticipantCommitmentLevel.OBSERVING


def test_new_ready_evidence_can_restore_corrected_interpretation() -> None:
    state = reduce_session(session_state(), ready())
    state = reduce_session(state, correction())
    restored = reduce_session(
        state,
        ready("evidence.ready.2", timestamp=NOW + timedelta(seconds=20)),
    )
    commitment = get_ready_confirmed_commitment(restored, PARTICIPANT_ID)
    assert commitment is not None
    assert commitment.confirmed_at == NOW + timedelta(seconds=20)
    assert commitment.ready_evidence_ids == ("evidence.ready.2",)


def test_ready_correction_failure_is_atomic() -> None:
    state = reduce_session(session_state(), ready())
    invalid = correction(targets=("evidence.ready.missing",))
    with pytest.raises(InvalidObservationError, match="not ready evidence"):
        reduce_session(state, invalid)
    assert get_ready_confirmed_commitment(state, PARTICIPANT_ID) is not None
    assert state.prebattle_evidence is not None
    assert len(state.prebattle_evidence.entries) == 1


def test_ready_correction_cannot_cross_participants() -> None:
    state = session_state(
        participant_ids=(PARTICIPANT_ID, "session-player-2")
    )
    state = reduce_session(state, ready())
    invalid = correction(participant_id="session-player-2")
    with pytest.raises(InvalidObservationError, match="cross participants"):
        reduce_session(state, invalid)


def test_ready_correction_is_idempotent_by_its_own_evidence_id() -> None:
    state = reduce_session(session_state(), ready())
    event = correction()
    corrected = reduce_session(state, event)
    assert reduce_session(corrected, event) is corrected


def test_ready_correction_requires_manual_provenance() -> None:
    with pytest.raises(ValidationError):
        ReadyFalsePositiveCorrected.model_validate(
            {
                **correction().model_dump(),
                "provenance": EvidenceKind.OBSERVED,
            }
        )


def test_ready_correction_cannot_precede_target_evidence() -> None:
    state = reduce_session(session_state(), ready())
    invalid = correction(timestamp=NOW - timedelta(seconds=1))
    with pytest.raises(InvalidObservationError, match="violates session invariants"):
        reduce_session(state, invalid)
    assert get_ready_confirmed_commitment(state, PARTICIPANT_ID) is not None


def test_ready_correction_cannot_target_candidate_evidence() -> None:
    state = reduce_session(session_state(), candidate())
    invalid = correction(targets=("evidence.candidate.1",))
    with pytest.raises(InvalidObservationError, match="not ready evidence"):
        reduce_session(state, invalid)
    assert state.prebattle_evidence is not None
    assert state.prebattle_evidence.entries == (candidate(),)


def test_prebattle_event_rejects_cross_session_and_unknown_participant() -> None:
    original = session_state()
    cross_session = candidate().model_copy(update={"session_id": "session.other"})
    with pytest.raises(InvalidObservationError, match="does not match"):
        reduce_session(original, cross_session)

    unknown_participant = candidate().model_copy(
        update={"session_player_id": "session-player-9"}
    )
    with pytest.raises(InvalidObservationError, match="does not belong"):
        reduce_session(original, unknown_participant)
    assert original.prebattle_evidence is None


def test_selection_stage_exit_does_not_remove_ready_commitment() -> None:
    state = reduce_session(session_state(), ready())
    exit_evidence = EvidenceRecord(
        source=EvidenceKind.OBSERVED,
        confidence=0.94,
        observed_at=NOW + timedelta(seconds=5),
    )
    exited_snapshot = StrategySelectionSnapshot(
        session_id=SESSION_ID,
        ruleset_id="demo.synthetic",
        captured_at=NOW + timedelta(seconds=5),
        participants=(
            StrategySelectionParticipant(
                session_player_id=PARTICIPANT_ID,
                selection_row=1,
                selection_outcome=SelectionOutcome.EXITED_AFTER_STRATEGY,
                field_evidence={
                    ParticipantField.SELECTION_OUTCOME: exit_evidence,
                },
            ),
        ),
    )
    exited = reduce_session(
        state,
        StrategySelectionSnapshotObserved(
            timestamp=NOW + timedelta(seconds=5),
            snapshot=exited_snapshot,
        ),
    )
    assert get_ready_confirmed_commitment(exited, PARTICIPANT_ID) is not None


def test_runtime_hp_depletion_does_not_remove_ready_commitment() -> None:
    initial = session_state()
    initial.players.append(PlayerState(slot=1))
    state = reduce_session(initial, ready())
    eliminated = reduce_session(
        state,
        PlayerHealthObserved(
            timestamp=NOW + timedelta(seconds=5),
            slot=1,
            hp=0,
        ),
    )
    assert get_ready_confirmed_commitment(eliminated, PARTICIPANT_ID) is not None


def test_frozen_legacy_snapshot_does_not_block_new_ready_evidence() -> None:
    state = reduce_session(session_state(frozen=True), ready())
    assert get_ready_confirmed_commitment(state, PARTICIPANT_ID) is not None
    assert state.strategy_selection is not None
    assert state.strategy_selection.frozen


def test_commitment_models_and_nested_values_are_immutable() -> None:
    state = reduce_session(session_state(), ready())
    assert state.strategy_commitments is not None
    commitment = state.strategy_commitments.commitments[0]
    with pytest.raises(ValidationError, match="frozen"):
        commitment.confirmed_at = NOW + timedelta(seconds=1)
    with pytest.raises(AttributeError):
        state.strategy_commitments.commitments.append(commitment)


def test_session_state_rejects_forged_commitment_materialization() -> None:
    state = reduce_session(session_state(), ready())
    payload = state.model_dump()
    payload["strategy_commitments"] = StrategyCommitmentState(
        session_id=SESSION_ID
    )
    with pytest.raises(ValidationError, match="effective confirmation evidence"):
        SessionState.model_validate(payload)


def test_ledger_and_session_state_round_trip_through_json() -> None:
    state = reduce_session(session_state(), candidate())
    state = reduce_session(state, ready())
    ledger = get_prebattle_evidence_ledger(state)
    assert ledger is not None
    assert PrebattleEvidenceLedger.model_validate_json(
        ledger.model_dump_json()
    ) == ledger
    assert SessionState.model_validate_json(state.model_dump_json()) == state


def test_m0_2b_1_has_no_game_unready_or_release_state() -> None:
    values = {level.value for level in ParticipantCommitmentLevel}
    assert "unready" not in values
    assert "released" not in values


def test_new_identifiers_reject_non_normalized_or_non_string_values() -> None:
    with pytest.raises(ValidationError):
        StrategyCandidateObserved.model_validate(
            {**candidate().model_dump(), "session_player_id": "PLAYER 1"}
        )
    with pytest.raises(ValidationError):
        StrategyCandidateObserved.model_validate(
            {**candidate().model_dump(), "evidence_id": 38}
        )
