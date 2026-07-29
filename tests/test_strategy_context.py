from datetime import UTC, datetime

import pytest

from sentry_copilot.domain.enums import EvidenceKind, PlayerStatus
from sentry_copilot.domain.models import PlayerState, SessionState
from sentry_copilot.domain.queries import build_team_strategy_context
from sentry_copilot.domain.strategy_selection import (
    EvidenceRecord,
    ParticipantField,
    SelectionOutcome,
    SnapshotCompleteness,
    StrategySelectionParticipant,
    StrategySelectionSnapshot,
)


def test_team_strategy_context_reads_snapshot_without_runtime_mapping() -> None:
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    strategy_evidence = EvidenceRecord(
        source=EvidenceKind.OBSERVED,
        confidence=0.95,
        observed_at=observed_at,
    )
    participants = [
        StrategySelectionParticipant(
            session_player_id=f"session-player-{index}",
            selection_row=5 - index,
            strategy_id=f"strategy.synthetic.{index}",
            selection_outcome=SelectionOutcome.ENTERED_BATTLE,
            field_evidence={
                ParticipantField.STRATEGY: strategy_evidence,
                ParticipantField.SELECTION_OUTCOME: strategy_evidence,
            },
        )
        for index in range(1, 5)
    ]
    state = SessionState(
        session_id="session.synthetic",
        ruleset_id="demo.v1",
        players=[
            PlayerState(slot=slot, strategy_id=f"legacy.strategy.{slot}")
            for slot in range(1, 5)
        ],
        strategy_selection=StrategySelectionSnapshot(
            session_id="session.synthetic",
            ruleset_id="demo.v1",
            expected_participant_count=4,
            captured_at=observed_at,
            participants=tuple(participants),
            frozen=True,
        ),
    )
    context = build_team_strategy_context(state)
    assert context is not None
    assert context.completeness_level == SnapshotCompleteness.STRATEGIES_COMPLETE
    assert context.strategy_ids == [
        "strategy.synthetic.4",
        "strategy.synthetic.3",
        "strategy.synthetic.2",
        "strategy.synthetic.1",
    ]
    assert [participant.selection_row for participant in context.participants] == [1, 2, 3, 4]


def test_team_strategy_context_is_absent_without_snapshot() -> None:
    assert build_team_strategy_context(SessionState(session_id="session.synthetic")) is None


@pytest.mark.parametrize(
    "legacy_runtime_status",
    [
        PlayerStatus.LEFT,
        PlayerStatus.DISCONNECTED,
        PlayerStatus.ELIMINATED,
    ],
)
def test_legacy_runtime_exit_labels_keep_historical_strategy_context(
    legacy_runtime_status: PlayerStatus,
) -> None:
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    observed = EvidenceRecord(
        source=EvidenceKind.OBSERVED,
        confidence=0.95,
        observed_at=observed_at,
    )
    participant = StrategySelectionParticipant(
        session_player_id="session-player-1",
        selection_row=1,
        strategy_id="strategy.synthetic.1",
        selection_outcome=SelectionOutcome.ENTERED_BATTLE,
        field_evidence={
            ParticipantField.STRATEGY: observed,
            ParticipantField.SELECTION_OUTCOME: observed,
        },
    )
    state = SessionState(
        session_id="session.synthetic",
        ruleset_id="demo.v1",
        players=[PlayerState(slot=1, status=legacy_runtime_status)],
        strategy_selection=StrategySelectionSnapshot(
            session_id="session.synthetic",
            ruleset_id="demo.v1",
            expected_participant_count=1,
            captured_at=observed_at,
            participants=(participant,),
            frozen=True,
        ),
    )
    context = build_team_strategy_context(state)
    assert context is not None
    assert context.strategy_ids == ["strategy.synthetic.1"]
    assert context.completeness_level == SnapshotCompleteness.STRATEGIES_COMPLETE
    assert state.strategy_selection is not None
    assert state.strategy_selection.expected_participant_count == 1
    assert (
        state.strategy_selection.participants[0].selection_outcome
        == SelectionOutcome.ENTERED_BATTLE
    )


def test_partial_context_returns_all_participants_including_unknown_strategy() -> None:
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    observed = EvidenceRecord(
        source=EvidenceKind.OBSERVED,
        confidence=0.95,
        observed_at=observed_at,
    )
    participants = (
        StrategySelectionParticipant(
            session_player_id="session-player-1",
            selection_row=1,
            strategy_id="strategy.synthetic.1",
            selection_outcome=SelectionOutcome.ENTERED_BATTLE,
            field_evidence={
                ParticipantField.STRATEGY: observed,
                ParticipantField.SELECTION_OUTCOME: observed,
            },
        ),
        StrategySelectionParticipant(
            session_player_id="session-player-2",
            selection_row=2,
            strategy_id=None,
            selection_outcome=SelectionOutcome.ENTERED_BATTLE,
            field_evidence={ParticipantField.SELECTION_OUTCOME: observed},
        ),
    )
    state = SessionState(
        session_id="session.synthetic",
        ruleset_id="demo.v1",
        strategy_selection=StrategySelectionSnapshot(
            session_id="session.synthetic",
            ruleset_id="demo.v1",
            expected_participant_count=2,
            captured_at=observed_at,
            participants=participants,
            frozen=True,
        ),
    )
    context = build_team_strategy_context(state)
    assert context is not None
    assert context.completeness_level == SnapshotCompleteness.PARTIAL
    assert len(context.participants) == 2
    assert context.participants[1].strategy_id is None
    assert context.strategy_ids == ["strategy.synthetic.1"]


def test_default_context_excludes_selection_stage_exits_but_snapshot_keeps_history() -> None:
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    observed = EvidenceRecord(
        source=EvidenceKind.OBSERVED,
        confidence=0.95,
        observed_at=observed_at,
    )

    def selection_participant(
        row: int,
        outcome: SelectionOutcome,
        strategy_id: str | None,
    ) -> StrategySelectionParticipant:
        field_evidence = {ParticipantField.SELECTION_OUTCOME: observed}
        if strategy_id is not None:
            field_evidence[ParticipantField.STRATEGY] = observed
        return StrategySelectionParticipant(
            session_player_id=f"session-player-{row}",
            selection_row=row,
            strategy_id=strategy_id,
            selection_outcome=outcome,
            field_evidence=field_evidence,
        )

    participants = (
        selection_participant(
            1,
            SelectionOutcome.ENTERED_BATTLE,
            "strategy.synthetic.shared",
        ),
        selection_participant(
            2,
            SelectionOutcome.LEFT_UNREADY,
            "strategy.synthetic.temporary-left",
        ),
        selection_participant(
            3,
            SelectionOutcome.EXITED_BEFORE_STRATEGY,
            None,
        ),
        selection_participant(
            4,
            SelectionOutcome.EXITED_AFTER_STRATEGY,
            "strategy.synthetic.shared",
        ),
    )
    snapshot = StrategySelectionSnapshot(
        session_id="session.synthetic",
        ruleset_id="demo.v1",
        expected_participant_count=1,
        captured_at=observed_at,
        participants=participants,
        frozen=True,
    )
    state = SessionState(
        session_id="session.synthetic",
        ruleset_id="demo.v1",
        strategy_selection=snapshot,
    )
    context = build_team_strategy_context(state)
    assert context is not None
    assert [participant.session_player_id for participant in context.participants] == [
        "session-player-1"
    ]
    assert context.strategy_ids == ["strategy.synthetic.shared"]
    assert len(snapshot.participants) == 4
    assert snapshot.participants[3].strategy_id == "strategy.synthetic.shared"
