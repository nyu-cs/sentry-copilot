from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from sentry_copilot.domain.enums import EvidenceKind
from sentry_copilot.domain.strategy_selection import (
    EvidenceRecord,
    ParticipantField,
    SelectionOutcome,
    SnapshotCompleteness,
    StrategySelectionParticipant,
    StrategySelectionSnapshot,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def evidence(source: EvidenceKind = EvidenceKind.OBSERVED) -> EvidenceRecord:
    return EvidenceRecord(source=source, confidence=0.95, observed_at=NOW)


def participant(
    index: int,
    *,
    player_tag: str | None = None,
    display_name: str | None = None,
    avatar_visual_key: str | None = None,
    strategy_id: str | None = None,
    ready: bool | None = None,
    is_self: bool | None = None,
    selection_outcome: SelectionOutcome = SelectionOutcome.UNKNOWN,
) -> StrategySelectionParticipant:
    values = {
        ParticipantField.PLAYER_TAG: player_tag,
        ParticipantField.DISPLAY_NAME: display_name,
        ParticipantField.AVATAR: avatar_visual_key,
        ParticipantField.STRATEGY: strategy_id,
        ParticipantField.READY: ready,
        ParticipantField.IS_SELF: is_self,
        ParticipantField.SELECTION_OUTCOME: (
            None
            if selection_outcome == SelectionOutcome.UNKNOWN
            else selection_outcome
        ),
    }
    return StrategySelectionParticipant(
        session_player_id=f"session-player-{index}",
        selection_row=index,
        player_tag=player_tag,
        display_name=display_name,
        avatar_visual_key=avatar_visual_key,
        strategy_id=strategy_id,
        ready=ready,
        is_self=is_self,
        selection_outcome=selection_outcome,
        field_evidence={
            field_name: evidence() for field_name, value in values.items() if value is not None
        },
    )


def snapshot(
    participants: list[StrategySelectionParticipant],
    *,
    expected_participant_count: int | None = None,
    frozen: bool = False,
) -> StrategySelectionSnapshot:
    return StrategySelectionSnapshot(
        session_id="session.synthetic",
        ruleset_id="demo.v1",
        expected_participant_count=expected_participant_count,
        captured_at=NOW,
        participants=tuple(participants),
        frozen=frozen,
    )


def test_player_tag_preserves_leading_zero() -> None:
    result = participant(1, player_tag="0038")
    assert result.player_tag == "0038"
    assert result.model_dump()["player_tag"] == "0038"


@pytest.mark.parametrize("invalid_tag", ["038", "00038", "#0038", 38])
def test_invalid_player_tag_is_rejected(invalid_tag: object) -> None:
    with pytest.raises(ValidationError):
        StrategySelectionParticipant.model_validate(
            {
                "session_player_id": "session-player-1",
                "selection_row": 1,
                "player_tag": invalid_tag,
                "field_evidence": {ParticipantField.PLAYER_TAG: evidence()},
            }
        )


def test_partial_fields_can_be_unknown() -> None:
    result = participant(1)
    assert result.player_tag is None
    assert result.strategy_id is None
    assert result.field_evidence == {}


def test_known_field_requires_field_evidence() -> None:
    with pytest.raises(ValidationError, match="require evidence"):
        StrategySelectionParticipant(
            session_player_id="session-player-1",
            selection_row=1,
            strategy_id="strategy.synthetic.guard",
        )


def test_fields_keep_independent_evidence() -> None:
    tag_evidence = evidence(EvidenceKind.MANUAL)
    strategy_evidence = evidence(EvidenceKind.OBSERVED)
    result = StrategySelectionParticipant(
        session_player_id="session-player-1",
        selection_row=1,
        player_tag="0038",
        strategy_id="strategy.synthetic.guard",
        field_evidence={
            ParticipantField.PLAYER_TAG: tag_evidence,
            ParticipantField.STRATEGY: strategy_evidence,
        },
    )
    assert result.field_evidence[ParticipantField.PLAYER_TAG].source == EvidenceKind.MANUAL
    assert (
        result.field_evidence[ParticipantField.STRATEGY].source
        == EvidenceKind.OBSERVED
    )


def test_field_evidence_enum_keys_round_trip_through_python_and_json() -> None:
    result = participant(
        1,
        player_tag="0038",
        strategy_id="strategy.synthetic.guard",
    )
    python_dump = result.model_dump()
    json_dump = result.model_dump_json()
    python_round_trip = StrategySelectionParticipant.model_validate(python_dump)
    json_round_trip = StrategySelectionParticipant.model_validate_json(json_dump)
    assert set(python_dump["field_evidence"]) == {
        ParticipantField.PLAYER_TAG,
        ParticipantField.STRATEGY,
    }
    assert python_round_trip == result
    assert json_round_trip == result
    assert set(json_round_trip.field_evidence) == {
        ParticipantField.PLAYER_TAG,
        ParticipantField.STRATEGY,
    }


def test_evidence_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        EvidenceRecord(
            source=EvidenceKind.OBSERVED,
            confidence=0.95,
            observed_at=datetime(2026, 1, 1),
        )


def test_snapshot_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        StrategySelectionSnapshot(
            session_id="session.synthetic",
            ruleset_id="demo.v1",
            captured_at=datetime(2026, 1, 1),
        )


@pytest.mark.parametrize(
    "aware_datetime",
    [
        NOW,
        datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=9))),
    ],
)
def test_strategy_selection_times_accept_timezone_aware_datetime(
    aware_datetime: datetime,
) -> None:
    observed = EvidenceRecord(
        source=EvidenceKind.OBSERVED,
        confidence=0.95,
        observed_at=aware_datetime,
    )
    result = StrategySelectionSnapshot(
        session_id="session.synthetic",
        ruleset_id="demo.v1",
        captured_at=aware_datetime,
        evidence=(observed,),
    )
    assert result.captured_at.utcoffset() is not None
    assert result.evidence[0].observed_at.utcoffset() is not None


def test_participant_and_field_evidence_are_immutable() -> None:
    result = participant(1, strategy_id="strategy.synthetic.1")
    with pytest.raises(ValidationError, match="frozen"):
        result.strategy_id = "strategy.synthetic.changed"
    with pytest.raises(AttributeError):
        result.field_evidence.clear()
    assert result.strategy_id == "strategy.synthetic.1"
    assert ParticipantField.STRATEGY in result.field_evidence


def test_snapshot_participants_and_evidence_are_immutable() -> None:
    first = participant(
        1,
        strategy_id="strategy.synthetic.1",
        selection_outcome=SelectionOutcome.ENTERED_BATTLE,
    )
    result = snapshot(
        [first],
        expected_participant_count=1,
        frozen=True,
    )
    with pytest.raises(AttributeError):
        result.participants.append(participant(2))
    with pytest.raises(TypeError):
        result.participants[0] = participant(2)
    with pytest.raises(ValidationError, match="frozen"):
        result.participants = (first, participant(2))
    with pytest.raises(AttributeError):
        result.evidence.append(evidence())
    assert result.strategy_complete is True
    assert len(result.participants) == 1


def test_nested_mutation_cannot_forge_completeness() -> None:
    result = snapshot(
        [
            participant(
                1,
                strategy_id="strategy.synthetic.1",
                selection_outcome=SelectionOutcome.ENTERED_BATTLE,
            ),
            participant(
                2,
                strategy_id="strategy.synthetic.2",
                selection_outcome=SelectionOutcome.ENTERED_BATTLE,
            ),
        ],
        expected_participant_count=2,
        frozen=True,
    )
    assert result.strategy_complete is True
    with pytest.raises(ValidationError, match="frozen"):
        result.participants[1].strategy_id = "strategy.synthetic.1"
    assert result.strategy_complete is True
    assert [participant.strategy_id for participant in result.participants] == [
        "strategy.synthetic.1",
        "strategy.synthetic.2",
    ]


def test_non_empty_player_tags_are_unique() -> None:
    with pytest.raises(ValidationError, match="player_tag"):
        snapshot([participant(1, player_tag="0038"), participant(2, player_tag="0038")])


def test_duplicate_legacy_strategy_observations_are_valid_materialized_data() -> None:
    result = snapshot(
        [
            participant(
                1,
                strategy_id="strategy.synthetic.guard",
                selection_outcome=SelectionOutcome.ENTERED_BATTLE,
            ),
            participant(
                2,
                strategy_id="strategy.synthetic.guard",
                selection_outcome=SelectionOutcome.ENTERED_BATTLE,
            ),
        ],
        expected_participant_count=2,
        frozen=True,
    )
    assert result.strategy_complete is True
    assert [item.strategy_id for item in result.participants] == [
        "strategy.synthetic.guard",
        "strategy.synthetic.guard",
    ]


def test_selection_rows_are_unique() -> None:
    duplicate = participant(2).model_copy(update={"selection_row": 1})
    with pytest.raises(ValidationError, match="selection_row"):
        snapshot([participant(1), duplicate])


def test_snapshot_accepts_at_most_four_participants() -> None:
    fifth = participant(4).model_copy(update={"session_player_id": "session-player-5"})
    with pytest.raises(ValidationError):
        snapshot([participant(1), participant(2), participant(3), participant(4), fifth])


def test_duplicate_avatars_are_allowed() -> None:
    result = snapshot(
        [
            participant(1, avatar_visual_key="avatar.shared"),
            participant(2, avatar_visual_key="avatar.shared"),
        ]
    )
    assert len(result.participants) == 2


def test_four_strategies_are_complete_without_identity() -> None:
    result = snapshot(
        [
            participant(
                index,
                strategy_id=f"strategy.synthetic.{index}",
                selection_outcome=SelectionOutcome.ENTERED_BATTLE,
            )
            for index in range(1, 5)
        ],
        expected_participant_count=4,
        frozen=True,
    )
    assert result.strategy_complete is True
    assert result.identity_complete is False
    assert result.completeness_level == SnapshotCompleteness.STRATEGIES_COMPLETE


def test_missing_strategy_is_partial() -> None:
    result = snapshot(
        [
            participant(
                index,
                player_tag=f"{index:04d}",
                strategy_id=None if index == 4 else f"strategy.synthetic.{index}",
                selection_outcome=SelectionOutcome.ENTERED_BATTLE,
            )
            for index in range(1, 5)
        ],
        expected_participant_count=4,
        frozen=True,
    )
    assert result.strategy_complete is False
    assert result.identity_complete is False
    assert result.completeness_level == SnapshotCompleteness.PARTIAL


def test_four_strategies_and_tags_are_fully_identified_without_names() -> None:
    result = snapshot(
        [
            participant(
                index,
                player_tag=f"{index:04d}",
                strategy_id=f"strategy.synthetic.{index}",
                selection_outcome=SelectionOutcome.ENTERED_BATTLE,
            )
            for index in range(1, 5)
        ],
        expected_participant_count=4,
        frozen=True,
    )
    assert result.strategy_complete is True
    assert result.identity_complete is True
    assert result.completeness_level == SnapshotCompleteness.FULLY_IDENTIFIED


def test_single_player_strategy_can_be_complete() -> None:
    result = snapshot(
        [
            participant(
                1,
                strategy_id="strategy.synthetic.1",
                selection_outcome=SelectionOutcome.ENTERED_BATTLE,
            )
        ],
        expected_participant_count=1,
        frozen=True,
    )
    assert result.strategy_complete is True
    assert result.identity_complete is False
    assert result.completeness_level == SnapshotCompleteness.STRATEGIES_COMPLETE


def test_single_player_strategy_and_tag_are_fully_identified() -> None:
    result = snapshot(
        [
            participant(
                1,
                player_tag="0038",
                strategy_id="strategy.synthetic.1",
                selection_outcome=SelectionOutcome.ENTERED_BATTLE,
            )
        ],
        expected_participant_count=1,
        frozen=True,
    )
    assert result.strategy_complete is True
    assert result.identity_complete is True
    assert result.completeness_level == SnapshotCompleteness.FULLY_IDENTIFIED


def test_three_observed_players_are_partial_when_four_are_expected() -> None:
    result = snapshot(
        [
            participant(
                index,
                strategy_id=f"strategy.synthetic.{index}",
                selection_outcome=SelectionOutcome.ENTERED_BATTLE,
            )
            for index in range(1, 4)
        ],
        expected_participant_count=4,
        frozen=True,
    )
    assert result.strategy_complete is False
    assert result.completeness_level == SnapshotCompleteness.PARTIAL


def test_three_entered_players_can_be_strategy_complete() -> None:
    result = snapshot(
        [
            participant(
                index,
                strategy_id=f"strategy.synthetic.{index}",
                selection_outcome=SelectionOutcome.ENTERED_BATTLE,
            )
            for index in range(1, 4)
        ],
        expected_participant_count=3,
        frozen=True,
    )
    assert result.strategy_complete is True
    assert result.completeness_level == SnapshotCompleteness.STRATEGIES_COMPLETE


def test_expected_participant_count_is_not_inferred() -> None:
    result = snapshot(
        [
            participant(
                index,
                strategy_id=f"strategy.synthetic.{index}",
                selection_outcome=SelectionOutcome.ENTERED_BATTLE,
            )
            for index in range(1, 5)
        ],
        expected_participant_count=None,
        frozen=True,
    )
    assert result.strategy_complete is False
    assert result.completeness_level == SnapshotCompleteness.PARTIAL


@pytest.mark.parametrize("invalid_count", [0, 5])
def test_expected_participant_count_must_be_between_one_and_four(
    invalid_count: int,
) -> None:
    with pytest.raises(ValidationError):
        snapshot([], expected_participant_count=invalid_count)


def test_left_unready_participant_is_not_counted_as_entered() -> None:
    participants = [
        participant(
            index,
            strategy_id=f"strategy.synthetic.{index}",
            selection_outcome=SelectionOutcome.ENTERED_BATTLE,
        )
        for index in range(1, 4)
    ]
    participants.append(
        participant(
            4,
            strategy_id="strategy.synthetic.departed",
            selection_outcome=SelectionOutcome.LEFT_UNREADY,
        )
    )
    result = snapshot(participants, expected_participant_count=3, frozen=True)
    assert result.strategy_complete is True
    assert result.completeness_level == SnapshotCompleteness.STRATEGIES_COMPLETE


def test_exited_before_strategy_can_have_no_strategy() -> None:
    result = participant(
        1,
        strategy_id=None,
        selection_outcome=SelectionOutcome.EXITED_BEFORE_STRATEGY,
    )
    assert result.strategy_id is None
    assert result.selection_outcome == SelectionOutcome.EXITED_BEFORE_STRATEGY


def test_exited_after_strategy_retains_temporary_strategy() -> None:
    result = participant(
        1,
        strategy_id="strategy.synthetic.temporary",
        selection_outcome=SelectionOutcome.EXITED_AFTER_STRATEGY,
    )
    assert result.strategy_id == "strategy.synthetic.temporary"
    assert result.selection_outcome == SelectionOutcome.EXITED_AFTER_STRATEGY


def test_unknown_outcome_is_not_counted_as_entered() -> None:
    result = snapshot(
        [
            participant(
                1,
                strategy_id="strategy.synthetic.1",
                selection_outcome=SelectionOutcome.ENTERED_BATTLE,
            ),
            participant(
                2,
                strategy_id="strategy.synthetic.2",
                selection_outcome=SelectionOutcome.ENTERED_BATTLE,
            ),
            participant(3, strategy_id="strategy.synthetic.3"),
        ],
        expected_participant_count=3,
        frozen=True,
    )
    assert result.strategy_complete is False
    assert result.completeness_level == SnapshotCompleteness.PARTIAL


def test_legacy_snapshot_preserves_repeated_exited_and_entered_interpretations() -> None:
    result = snapshot(
        [
            participant(
                1,
                strategy_id="strategy.synthetic.shared",
                selection_outcome=SelectionOutcome.ENTERED_BATTLE,
            ),
            participant(
                2,
                strategy_id="strategy.synthetic.shared",
                selection_outcome=SelectionOutcome.EXITED_AFTER_STRATEGY,
            ),
        ],
        expected_participant_count=1,
        frozen=True,
    )
    assert result.strategy_complete is True
    assert [item.strategy_id for item in result.participants] == [
        "strategy.synthetic.shared",
        "strategy.synthetic.shared",
    ]
