from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import numpy as np

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.domain.enums import EvidenceKind
from sentry_copilot.vision.confirmed_selection_strategies import (
    ConfirmedSelectionStrategyAccumulator,
    ConfirmedSelectionStrategyState,
)
from sentry_copilot.vision.local_feature_matching import LocalFeatureVisualMatchResult
from sentry_copilot.vision.strategy_selection_observations import (
    StrategySelectionCandidateObservation,
)
from sentry_copilot.vision.strategy_selection_probe import StrategySelectionProbeStatus
from sentry_copilot.vision.visual_references import VisualMatchStatus


def _frame(index: int = 0) -> Frame:
    return Frame(
        frame_id=f"synthetic:{index}",
        frame_index=index,
        processed_at=datetime.now(UTC),
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic",
        width=8,
        height=8,
        image=np.zeros((8, 8, 3), dtype=np.uint8),
        source_reference=f"synthetic:{index}",
    )


def _observation(
    row: int,
    strategy_id: str | None,
    *,
    vision_status: StrategySelectionProbeStatus = StrategySelectionProbeStatus.MATCHED_STRATEGY,
    matcher_status: VisualMatchStatus = VisualMatchStatus.MATCHED,
    selected_identity: str | None = None,
) -> StrategySelectionCandidateObservation:
    selected = (
        SimpleNamespace(
            identity_id=selected_identity if selected_identity is not None else strategy_id
        )
        if strategy_id is not None
        else None
    )
    matcher = cast(
        LocalFeatureVisualMatchResult,
        SimpleNamespace(status=matcher_status, selected_identity=selected),
    )
    return StrategySelectionCandidateObservation(
        selection_row=row,
        strategy_id=strategy_id,
        vision_status=vision_status,
        provenance=EvidenceKind.OBSERVED,
        source="synthetic-selection-matcher",
        matcher_result=matcher,
    )


def _apply(
    accumulator: ConfirmedSelectionStrategyAccumulator,
    row: int,
    strategy_id: str | None,
    *,
    frame_index: int = 0,
    locked: frozenset[int] | None = None,
    vision_status: StrategySelectionProbeStatus = StrategySelectionProbeStatus.MATCHED_STRATEGY,
    matcher_status: VisualMatchStatus = VisualMatchStatus.MATCHED,
) -> ConfirmedSelectionStrategyAccumulator:
    return accumulator.apply(
        _frame(frame_index),
        locked if locked is not None else frozenset({row}),
        (
            _observation(
                row,
                strategy_id,
                vision_status=vision_status,
                matcher_status=matcher_status,
            ),
        ),
    )


def test_preconfirmation_previews_are_ignored_even_when_they_change() -> None:
    accumulator = ConfirmedSelectionStrategyAccumulator()
    accumulator = _apply(accumulator, 1, "strategy.synthetic.a", locked=frozenset())
    accumulator = _apply(accumulator, 1, "strategy.synthetic.b", locked=frozenset())

    result = accumulator.finalize_row(1)

    assert result.state is ConfirmedSelectionStrategyState.NOT_CONFIRMED
    assert not accumulator.evidence


def test_later_confirmation_does_not_backfill_preconfirmation_preview_history() -> None:
    accumulator = ConfirmedSelectionStrategyAccumulator()
    accumulator = _apply(accumulator, 1, "strategy.synthetic.a", locked=frozenset())
    accumulator = _apply(accumulator, 1, "strategy.synthetic.b", locked=frozenset())
    accumulator = accumulator.apply(_frame(2), frozenset({1}), ())

    result = accumulator.finalize_row(1)

    assert result.state is ConfirmedSelectionStrategyState.CONFIRMED_BUT_UNRESOLVED
    assert not result.evidence


def test_same_frame_that_is_sticky_locked_can_accumulate_strategy_evidence() -> None:
    accumulator = _apply(
        ConfirmedSelectionStrategyAccumulator(),
        1,
        "strategy.synthetic.locked",
        locked=frozenset({1}),
    )

    result = accumulator.finalize_row(1)

    assert result.state is ConfirmedSelectionStrategyState.CONFIRMED_IDENTIFIED
    assert result.strategy_id == "strategy.synthetic.locked"
    assert result.evidence[0].frame_id == "synthetic:0"


def test_repeated_same_identity_remains_identified_and_preserves_all_evidence() -> None:
    accumulator = _apply(
        ConfirmedSelectionStrategyAccumulator(), 1, "strategy.synthetic.a", frame_index=1
    )
    accumulator = _apply(accumulator, 1, "strategy.synthetic.a", frame_index=2)

    result = accumulator.finalize_row(1)

    assert result.state is ConfirmedSelectionStrategyState.CONFIRMED_IDENTIFIED
    assert result.strategy_ids == ("strategy.synthetic.a",)
    assert len(result.evidence) == 2


def test_confirmed_row_without_eligible_evidence_is_unresolved() -> None:
    accumulator = ConfirmedSelectionStrategyAccumulator().apply(_frame(), frozenset({1}), ())

    assert (
        accumulator.finalize_row(1).state
        is ConfirmedSelectionStrategyState.CONFIRMED_BUT_UNRESOLVED
    )


def test_unresolved_or_ambiguous_matcher_results_do_not_identify_confirmed_row() -> None:
    accumulator = _apply(
        ConfirmedSelectionStrategyAccumulator(),
        1,
        None,
        vision_status=StrategySelectionProbeStatus.UNRESOLVED_STRATEGY,
        matcher_status=VisualMatchStatus.UNRESOLVED,
    )
    accumulator = _apply(
        accumulator,
        1,
        "strategy.synthetic.ambiguous",
        vision_status=StrategySelectionProbeStatus.MATCHED_STRATEGY,
        matcher_status=VisualMatchStatus.AMBIGUOUS,
    )

    assert (
        accumulator.finalize_row(1).state
        is ConfirmedSelectionStrategyState.CONFIRMED_BUT_UNRESOLVED
    )


def test_two_distinct_postconfirmation_identities_are_a_conflict_without_winner() -> None:
    accumulator = _apply(
        ConfirmedSelectionStrategyAccumulator(), 1, "strategy.synthetic.a", frame_index=1
    )
    accumulator = _apply(accumulator, 1, "strategy.synthetic.a", frame_index=2)
    accumulator = _apply(accumulator, 1, "strategy.synthetic.b", frame_index=3)

    result = accumulator.finalize_row(1)

    assert result.state is ConfirmedSelectionStrategyState.CONFIRMED_STRATEGY_CONFLICT
    assert result.strategy_id is None
    assert result.strategy_ids == ("strategy.synthetic.a", "strategy.synthetic.b")
    assert len(result.evidence) == 3


def test_later_missing_or_disappearing_strategy_observation_does_not_erase_history() -> None:
    accumulator = _apply(ConfirmedSelectionStrategyAccumulator(), 1, "strategy.synthetic.a")
    accumulator = accumulator.apply(_frame(1), frozenset({1}), ())
    accumulator = _apply(
        accumulator,
        1,
        None,
        frame_index=2,
        vision_status=StrategySelectionProbeStatus.UNRESOLVED_STRATEGY,
        matcher_status=VisualMatchStatus.UNRESOLVED,
    )

    result = accumulator.finalize_row(1)

    assert result.state is ConfirmedSelectionStrategyState.CONFIRMED_IDENTIFIED
    assert result.strategy_id == "strategy.synthetic.a"
    assert len(result.evidence) == 1


def test_unconfirmed_row_cannot_finalize_preview_even_if_other_rows_are_confirmed() -> None:
    accumulator = _apply(
        ConfirmedSelectionStrategyAccumulator(),
        2,
        "strategy.synthetic.preview",
        locked=frozenset({1}),
    )

    assert accumulator.finalize_row(2).state is ConfirmedSelectionStrategyState.NOT_CONFIRMED
    assert not accumulator.evidence


def test_rows_finalize_independently_and_query_is_deterministic() -> None:
    accumulator = ConfirmedSelectionStrategyAccumulator()
    accumulator = _apply(accumulator, 1, "strategy.synthetic.a", locked=frozenset({1, 2}))
    accumulator = _apply(accumulator, 2, "strategy.synthetic.b", locked=frozenset({1, 2}))
    accumulator = _apply(accumulator, 3, "strategy.synthetic.preview", locked=frozenset({1, 2}))

    first = accumulator.finalize()
    second = accumulator.finalize()

    assert first == second
    assert [item.state for item in first] == [
        ConfirmedSelectionStrategyState.CONFIRMED_IDENTIFIED,
        ConfirmedSelectionStrategyState.CONFIRMED_IDENTIFIED,
        ConfirmedSelectionStrategyState.NOT_CONFIRMED,
        ConfirmedSelectionStrategyState.NOT_CONFIRMED,
    ]
    assert accumulator.evidence[0].strategy_observation.source == "synthetic-selection-matcher"


def test_accumulator_is_immutable_and_preserves_prior_value() -> None:
    initial = ConfirmedSelectionStrategyAccumulator()
    updated = _apply(initial, 1, "strategy.synthetic.a")

    assert initial is not updated
    assert not initial.locked_confirmed_rows
    assert not initial.evidence
    assert updated.locked_confirmed_rows == frozenset({1})
