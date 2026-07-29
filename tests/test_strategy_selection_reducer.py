from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from sentry_copilot.domain.enums import EvidenceKind, PlayerStatus, StageType
from sentry_copilot.domain.events import (
    PlayerAvatarObserved,
    PlayerHealthObserved,
    StrategySelectionSnapshotCorrected,
    StrategySelectionSnapshotFrozen,
    StrategySelectionSnapshotObserved,
)
from sentry_copilot.domain.models import PlayerState, SessionState
from sentry_copilot.domain.queries import build_team_strategy_context
from sentry_copilot.domain.reducer import InvalidObservationError, reduce_session
from sentry_copilot.domain.strategy_selection import (
    EvidenceRecord,
    ParticipantField,
    SelectionOutcome,
    StrategySelectionParticipant,
    StrategySelectionSnapshot,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def evidence(
    *,
    source: EvidenceKind = EvidenceKind.OBSERVED,
    confidence: float = 0.9,
    observed_at: datetime = NOW,
) -> EvidenceRecord:
    return EvidenceRecord(
        source=source,
        confidence=confidence,
        observed_at=observed_at,
    )


def participant(
    index: int,
    *,
    strategy_id: str | None,
    player_tag: str | None = None,
    strategy_evidence: EvidenceRecord | None = None,
    player_tag_evidence: EvidenceRecord | None = None,
    selection_outcome: SelectionOutcome = SelectionOutcome.ENTERED_BATTLE,
) -> StrategySelectionParticipant:
    field_evidence: dict[ParticipantField, EvidenceRecord] = {}
    if strategy_id is not None:
        field_evidence[ParticipantField.STRATEGY] = strategy_evidence or evidence()
    if player_tag is not None:
        field_evidence[ParticipantField.PLAYER_TAG] = player_tag_evidence or evidence()
    if selection_outcome != SelectionOutcome.UNKNOWN:
        field_evidence[ParticipantField.SELECTION_OUTCOME] = evidence()
    return StrategySelectionParticipant(
        session_player_id=f"session-player-{index}",
        selection_row=index,
        player_tag=player_tag,
        strategy_id=strategy_id,
        selection_outcome=selection_outcome,
        field_evidence=field_evidence,
    )


def snapshot(
    participants: list[StrategySelectionParticipant],
    *,
    frozen: bool = False,
    captured_at: datetime = NOW,
    expected_participant_count: int | None = 4,
) -> StrategySelectionSnapshot:
    return StrategySelectionSnapshot(
        session_id="session.synthetic",
        ruleset_id="demo.v1",
        expected_participant_count=expected_participant_count,
        captured_at=captured_at,
        participants=tuple(participants),
        frozen=frozen,
    )


def state() -> SessionState:
    return SessionState(
        session_id="session.synthetic",
        ruleset_id="demo.v1",
        players=[PlayerState(slot=slot) for slot in range(1, 5)],
    )


def observed_event(value: StrategySelectionSnapshot) -> StrategySelectionSnapshotObserved:
    return StrategySelectionSnapshotObserved(
        snapshot=value,
        timestamp=value.captured_at,
        confidence=0.9,
    )


def full_snapshot(*, frozen: bool = False) -> StrategySelectionSnapshot:
    return snapshot(
        [
            participant(index, strategy_id=f"strategy.synthetic.{index}")
            for index in range(1, 5)
        ],
        frozen=frozen,
    )


def test_snapshot_observation_is_written_to_session_state() -> None:
    observed = reduce_session(state(), observed_event(full_snapshot()))
    assert observed.strategy_selection is not None
    assert observed.strategy_selection.strategy_complete is False
    result = reduce_session(
        observed,
        StrategySelectionSnapshotFrozen(
            session_id="session.synthetic",
            ruleset_id="demo.v1",
        ),
    )
    assert result.strategy_selection is not None
    assert result.strategy_selection.expected_participant_count == 4
    assert result.strategy_selection.strategy_complete is True


def test_manual_field_evidence_requires_correction_event() -> None:
    manual = evidence(source=EvidenceKind.MANUAL, confidence=1.0)
    value = snapshot(
        [participant(1, strategy_id="strategy.synthetic.1", strategy_evidence=manual)]
    )
    with pytest.raises(InvalidObservationError, match="manual"):
        reduce_session(state(), observed_event(value))


def test_partial_snapshot_can_be_frozen() -> None:
    with_snapshot = reduce_session(
        state(),
        observed_event(snapshot([participant(1, strategy_id=None)])),
    )
    result = reduce_session(
        with_snapshot,
        StrategySelectionSnapshotFrozen(
            session_id="session.synthetic",
            ruleset_id="demo.v1",
        ),
    )
    assert result.strategy_selection is not None
    assert result.strategy_selection.frozen is True
    assert result.strategy_selection.strategy_complete is False


def test_frozen_strategy_rejects_conflicting_ordinary_observation() -> None:
    current = state().model_copy(update={"strategy_selection": full_snapshot(frozen=True)})
    conflicting = snapshot(
        [
            participant(
                1,
                strategy_id="strategy.synthetic.changed",
                strategy_evidence=evidence(
                    confidence=0.1,
                    observed_at=NOW + timedelta(seconds=1),
                ),
            )
        ],
        captured_at=NOW + timedelta(seconds=1),
    )
    with pytest.raises(InvalidObservationError, match="frozen"):
        reduce_session(current, observed_event(conflicting))
    assert current.strategy_selection is not None
    assert current.strategy_selection.participants[0].strategy_id == "strategy.synthetic.1"


def test_frozen_snapshot_accepts_missing_strategy_fill() -> None:
    current_snapshot = snapshot(
        [
            participant(1, strategy_id=None),
            participant(2, strategy_id="strategy.synthetic.2"),
        ],
        frozen=True,
    )
    current = state().model_copy(update={"strategy_selection": current_snapshot})
    incoming = snapshot(
        [participant(1, strategy_id="strategy.synthetic.1")],
        captured_at=NOW + timedelta(seconds=1),
    )
    result = reduce_session(current, observed_event(incoming))
    assert result.strategy_selection is not None
    assert result.strategy_selection.participants[0].strategy_id == "strategy.synthetic.1"


def test_stronger_field_evidence_updates_draft_field() -> None:
    weak = evidence(confidence=0.4)
    strong = evidence(confidence=0.95, observed_at=NOW + timedelta(seconds=1))
    current_snapshot = snapshot(
        [participant(1, strategy_id="strategy.synthetic.old", strategy_evidence=weak)]
    )
    current = state().model_copy(update={"strategy_selection": current_snapshot})
    incoming = snapshot(
        [participant(1, strategy_id="strategy.synthetic.new", strategy_evidence=strong)],
        captured_at=NOW + timedelta(seconds=1),
    )
    result = reduce_session(current, observed_event(incoming))
    assert result.strategy_selection is not None
    updated = result.strategy_selection.participants[0]
    assert updated.strategy_id == "strategy.synthetic.new"
    assert updated.field_evidence[ParticipantField.STRATEGY] == strong
    assert current.strategy_selection is not None
    assert current.strategy_selection.participants[0].strategy_id == "strategy.synthetic.old"
    assert result.strategy_selection is not current.strategy_selection


def test_complete_evidence_source_priority() -> None:
    predicted = evidence(
        source=EvidenceKind.PREDICTED,
        confidence=1.0,
        observed_at=NOW + timedelta(seconds=3),
    )
    current = state().model_copy(
        update={
            "strategy_selection": snapshot(
                [
                    participant(
                        1,
                        strategy_id="strategy.synthetic.1",
                        strategy_evidence=predicted,
                    )
                ]
            )
        }
    )
    for source in (EvidenceKind.DERIVED, EvidenceKind.OBSERVED):
        incoming_evidence = evidence(
            source=source,
            confidence=0.1,
            observed_at=NOW,
        )
        incoming = snapshot(
            [
                participant(
                    1,
                    strategy_id="strategy.synthetic.1",
                    strategy_evidence=incoming_evidence,
                )
            ]
        )
        current = reduce_session(current, observed_event(incoming))
        assert current.strategy_selection is not None
        assert (
            current.strategy_selection.participants[0]
            .field_evidence[ParticipantField.STRATEGY]
            .source
            == source
        )

    manual = evidence(
        source=EvidenceKind.MANUAL,
        confidence=0.01,
        observed_at=NOW,
    )
    result = reduce_session(
        current,
        StrategySelectionSnapshotCorrected(
            session_id="session.synthetic",
            ruleset_id="demo.v1",
            replacements=[
                participant(
                    1,
                    strategy_id="strategy.synthetic.1",
                    strategy_evidence=manual,
                )
            ],
        ),
    )
    assert result.strategy_selection is not None
    assert (
        result.strategy_selection.participants[0]
        .field_evidence[ParticipantField.STRATEGY]
        .source
        == EvidenceKind.MANUAL
    )


def test_newer_evidence_wins_when_source_and_confidence_match() -> None:
    older = evidence(confidence=0.9, observed_at=NOW)
    newer = evidence(confidence=0.9, observed_at=NOW + timedelta(seconds=1))
    current = state().model_copy(
        update={
            "strategy_selection": snapshot(
                [
                    participant(
                        1,
                        strategy_id="strategy.synthetic.1",
                        strategy_evidence=older,
                    )
                ]
            )
        }
    )
    incoming = snapshot(
        [
            participant(
                1,
                strategy_id="strategy.synthetic.1",
                strategy_evidence=newer,
            )
        ],
        captured_at=NOW + timedelta(seconds=1),
    )
    result = reduce_session(current, observed_event(incoming))
    assert result.strategy_selection is not None
    assert (
        result.strategy_selection.participants[0].field_evidence[
            ParticipantField.STRATEGY
        ]
        == newer
    )


def test_manual_correction_updates_frozen_strategy() -> None:
    current = state().model_copy(update={"strategy_selection": full_snapshot(frozen=True)})
    replacement = participant(
        1,
        strategy_id="strategy.synthetic.corrected",
        strategy_evidence=evidence(source=EvidenceKind.MANUAL, confidence=1.0),
    )
    result = reduce_session(
        current,
        StrategySelectionSnapshotCorrected(
            session_id="session.synthetic",
            ruleset_id="demo.v1",
            replacements=[replacement],
        ),
    )
    assert result.strategy_selection is not None
    assert result.strategy_selection.frozen is True
    assert (
        result.strategy_selection.participants[0].strategy_id
        == "strategy.synthetic.corrected"
    )


def test_tag_correction_does_not_downgrade_strategy_evidence() -> None:
    strong_strategy = evidence(source=EvidenceKind.OBSERVED, confidence=0.99)
    weak_strategy = evidence(source=EvidenceKind.PREDICTED, confidence=0.01)
    manual_tag = evidence(source=EvidenceKind.MANUAL, confidence=1.0)
    current_snapshot = snapshot(
        [
            participant(
                1,
                strategy_id="strategy.synthetic.1",
                strategy_evidence=strong_strategy,
            )
        ],
        frozen=True,
        expected_participant_count=1,
    )
    current = state().model_copy(update={"strategy_selection": current_snapshot})
    replacement = participant(
        1,
        player_tag="0038",
        strategy_id="strategy.synthetic.1",
        strategy_evidence=weak_strategy,
        player_tag_evidence=manual_tag,
    )
    result = reduce_session(
        current,
        StrategySelectionSnapshotCorrected(
            session_id="session.synthetic",
            ruleset_id="demo.v1",
            replacements=[replacement],
        ),
    )
    assert result.strategy_selection is not None
    updated = result.strategy_selection.participants[0]
    assert updated.player_tag == "0038"
    assert updated.field_evidence[ParticipantField.PLAYER_TAG] == manual_tag
    assert updated.field_evidence[ParticipantField.STRATEGY] == strong_strategy


def test_correction_upgrades_stronger_same_value_evidence() -> None:
    weak_strategy = evidence(source=EvidenceKind.PREDICTED, confidence=0.1)
    strong_strategy = evidence(source=EvidenceKind.OBSERVED, confidence=0.9)
    current = state().model_copy(
        update={
            "strategy_selection": snapshot(
                [
                    participant(
                        1,
                        strategy_id="strategy.synthetic.1",
                        strategy_evidence=weak_strategy,
                    )
                ],
                frozen=True,
                expected_participant_count=1,
            )
        }
    )
    replacement = participant(
        1,
        strategy_id="strategy.synthetic.1",
        strategy_evidence=strong_strategy,
    )
    result = reduce_session(
        current,
        StrategySelectionSnapshotCorrected(
            session_id="session.synthetic",
            ruleset_id="demo.v1",
            replacements=[replacement],
        ),
    )
    assert result.strategy_selection is not None
    assert (
        result.strategy_selection.participants[0].field_evidence[
            ParticipantField.STRATEGY
        ]
        == strong_strategy
    )


def test_manual_strategy_swap_is_atomic() -> None:
    current = state().model_copy(update={"strategy_selection": full_snapshot(frozen=True)})
    manual = evidence(source=EvidenceKind.MANUAL, confidence=1.0)
    replacements = [
        participant(1, strategy_id="strategy.synthetic.2", strategy_evidence=manual),
        participant(2, strategy_id="strategy.synthetic.1", strategy_evidence=manual),
    ]
    result = reduce_session(
        current,
        StrategySelectionSnapshotCorrected(
            session_id="session.synthetic",
            ruleset_id="demo.v1",
            replacements=replacements,
        ),
    )
    assert result.strategy_selection is not None
    assert [
        participant.strategy_id
        for participant in result.strategy_selection.participants[:2]
    ] == ["strategy.synthetic.2", "strategy.synthetic.1"]


def test_invalid_manual_correction_leaves_original_snapshot_unchanged() -> None:
    current = state().model_copy(update={"strategy_selection": full_snapshot(frozen=True)})
    original_snapshot = current.strategy_selection
    duplicate = participant(
        1,
        strategy_id="strategy.synthetic.4",
        strategy_evidence=evidence(source=EvidenceKind.MANUAL, confidence=1.0),
    )
    with pytest.raises(InvalidObservationError, match="invariants"):
        reduce_session(
            current,
            StrategySelectionSnapshotCorrected(
                session_id="session.synthetic",
                ruleset_id="demo.v1",
                replacements=[duplicate],
            ),
        )
    assert current.strategy_selection == original_snapshot


def test_second_invalid_batch_correction_leaves_first_unapplied() -> None:
    current = state().model_copy(update={"strategy_selection": full_snapshot(frozen=True)})
    original_snapshot = current.strategy_selection
    replacements = [
        participant(
            1,
            strategy_id="strategy.synthetic.corrected",
            strategy_evidence=evidence(source=EvidenceKind.MANUAL, confidence=1.0),
        ),
        participant(
            2,
            strategy_id="strategy.synthetic.invalid",
            strategy_evidence=evidence(source=EvidenceKind.OBSERVED, confidence=1.0),
        ),
    ]
    with pytest.raises(InvalidObservationError, match="manual evidence"):
        reduce_session(
            current,
            StrategySelectionSnapshotCorrected(
                session_id="session.synthetic",
                ruleset_id="demo.v1",
                replacements=replacements,
            ),
        )
    assert current.strategy_selection == original_snapshot
    assert current.strategy_selection is not None
    assert current.strategy_selection.participants[0].strategy_id == "strategy.synthetic.1"


def test_manual_correction_cannot_create_participant() -> None:
    current = state().model_copy(update={"strategy_selection": full_snapshot(frozen=True)})
    replacement = participant(
        4,
        strategy_id="strategy.synthetic.5",
        strategy_evidence=evidence(source=EvidenceKind.MANUAL),
    ).model_copy(update={"session_player_id": "session-player-5"})
    with pytest.raises(InvalidObservationError, match="cannot create"):
        reduce_session(
            current,
            StrategySelectionSnapshotCorrected(
                session_id="session.synthetic",
                ruleset_id="demo.v1",
                replacements=[replacement],
            ),
        )


def test_avatar_observation_does_not_change_strategy_snapshot() -> None:
    current = state().model_copy(update={"strategy_selection": full_snapshot(frozen=True)})
    result = reduce_session(
        current,
        PlayerAvatarObserved(slot=1, avatar_visual_key="avatar.changed"),
    )
    assert result.player(1).avatar_visual_key == "avatar.changed"
    assert result.strategy_selection == current.strategy_selection


@pytest.mark.parametrize("stage_type", [StageType.REGULAR, StageType.SECRET_CORE])
def test_zero_hp_does_not_remove_strategy_snapshot_participant(
    stage_type: StageType,
) -> None:
    current = state().model_copy(update={"strategy_selection": full_snapshot(frozen=True)})
    current.stage.stage_type = stage_type
    current.stage.round_number = None if stage_type == StageType.SECRET_CORE else 3
    result = reduce_session(current, PlayerHealthObserved(slot=1, hp=0))
    assert result.player(1).status == PlayerStatus.ELIMINATED
    assert result.strategy_selection == current.strategy_selection
    assert result.strategy_selection is not None
    assert len(result.strategy_selection.participants) == 4
    assert result.strategy_selection.expected_participant_count == 4
    assert all(
        participant.selection_outcome == SelectionOutcome.ENTERED_BATTLE
        for participant in result.strategy_selection.participants
    )
    assert result.strategy_selection.strategy_complete is True
    context = build_team_strategy_context(result)
    assert context is not None
    assert len(context.participants) == 4
    assert "strategy.synthetic.1" in context.strategy_ids


def test_selection_rows_do_not_populate_legacy_runtime_strategies() -> None:
    result = reduce_session(state(), observed_event(full_snapshot()))
    assert [player.strategy_id for player in result.players] == [None, None, None, None]


def test_snapshot_context_must_match_session_state() -> None:
    wrong_session = full_snapshot().model_copy(update={"session_id": "other.session"})
    with pytest.raises(InvalidObservationError, match="session_id"):
        reduce_session(state(), observed_event(wrong_session))


def test_strategy_selection_event_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        StrategySelectionSnapshotFrozen(
            session_id="session.synthetic",
            ruleset_id="demo.v1",
            timestamp=datetime(2026, 1, 1),
        )
