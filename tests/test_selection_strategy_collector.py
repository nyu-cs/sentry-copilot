from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import numpy as np

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.domain.enums import EvidenceKind
from sentry_copilot.vision.confirmed_selection_strategies import (
    ConfirmedSelectionStrategyState,
)
from sentry_copilot.vision.local_feature_matching import LocalFeatureVisualMatchResult
from sentry_copilot.vision.selection_strategy_collector import (
    SelectionSessionStrategyCollectorState,
)
from sentry_copilot.vision.strategy_selection_confirmation import (
    SelectionConfirmationRenderContext,
    selection_confirmation_roi,
)
from sentry_copilot.vision.strategy_selection_observations import (
    StrategySelectionCandidateObservation,
)
from sentry_copilot.vision.strategy_selection_probe import StrategySelectionProbeStatus
from sentry_copilot.vision.viewport import ContentViewport
from sentry_copilot.vision.visual_references import VisualMatchStatus


def _frame(
    index: int,
    *,
    confirmed_rows: tuple[int, ...] = (),
    selection: bool = True,
) -> Frame:
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    if selection:
        image[35:115, 540:820] = (255, 255, 0)
    for row in confirmed_rows:
        roi = selection_confirmation_roi(SelectionConfirmationRenderContext.SELECTION_GRID, row)
        x, y = roi.x + 11, roi.y + 11
        image[y : y + 51, x : x + 51] = (255, 255, 0)
        image[y + 4 : y + 47, x + 4 : x + 47] = (0, 0, 0)
        image[y + 9 : y + 42, x + 9 : x + 42] = (255, 255, 0)
    return Frame(
        frame_id=f"synthetic:{index}",
        frame_index=index,
        processed_at=datetime.now(UTC),
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic",
        width=1920,
        height=1080,
        image=image,
        source_reference=f"synthetic:{index}",
    )


def _candidate(
    row: int,
    strategy_id: str | None,
    *,
    matcher_status: VisualMatchStatus = VisualMatchStatus.MATCHED,
) -> StrategySelectionCandidateObservation:
    selected = SimpleNamespace(identity_id=strategy_id) if strategy_id is not None else None
    matcher = cast(
        LocalFeatureVisualMatchResult,
        SimpleNamespace(status=matcher_status, selected_identity=selected),
    )
    return StrategySelectionCandidateObservation(
        selection_row=row,
        strategy_id=strategy_id,
        vision_status=(
            StrategySelectionProbeStatus.MATCHED_STRATEGY
            if strategy_id is not None
            else StrategySelectionProbeStatus.UNRESOLVED_STRATEGY
        ),
        provenance=EvidenceKind.OBSERVED,
        source="synthetic-selection-matcher",
        matcher_result=matcher,
    )


def _apply(
    state: SelectionSessionStrategyCollectorState,
    index: int,
    *,
    confirmed_rows: tuple[int, ...] = (),
    observations: tuple[StrategySelectionCandidateObservation, ...] = (),
    selection: bool = True,
) -> SelectionSessionStrategyCollectorState:
    frame = _frame(index, confirmed_rows=confirmed_rows, selection=selection)
    return state.apply_frame(
        frame,
        ContentViewport.full_frame(frame),
        SelectionConfirmationRenderContext.SELECTION_GRID,
        observations,
    )


def test_preconfirmation_strategy_and_first_positive_are_ignored() -> None:
    state = _apply(
        SelectionSessionStrategyCollectorState(),
        1,
        observations=(_candidate(1, "strategy.synthetic.preview"),),
    )
    state = _apply(
        state,
        2,
        confirmed_rows=(1,),
        observations=(_candidate(1, "strategy.synthetic.first-positive"),),
    )

    assert not state.confirmation_tracker.is_confirmed(1)
    assert not state.strategy_accumulator.evidence


def test_debounce_lock_then_same_frame_strategy_is_eligible_in_mandatory_order() -> None:
    state = _apply(
        SelectionSessionStrategyCollectorState(),
        1,
        confirmed_rows=(1,),
        observations=(_candidate(1, "strategy.synthetic.first"),),
    )

    updated = _apply(
        state,
        2,
        confirmed_rows=(1,),
        observations=(_candidate(1, "strategy.synthetic.locked"),),
    )

    result = updated.finalize()[0]
    assert updated.confirmation_tracker.is_confirmed(1)
    assert result.state is ConfirmedSelectionStrategyState.CONFIRMED_IDENTIFIED
    assert result.strategy_id == "strategy.synthetic.locked"
    assert result.evidence[0].frame_id == "synthetic:2"


def test_preconfirmation_a_b_then_confirmation_c_finalizes_c_only() -> None:
    state = _apply(
        SelectionSessionStrategyCollectorState(),
        1,
        observations=(_candidate(1, "strategy.synthetic.a"),),
    )
    state = _apply(
        state,
        2,
        observations=(_candidate(1, "strategy.synthetic.b"),),
    )
    state = _apply(
        state,
        3,
        confirmed_rows=(1,),
        observations=(_candidate(1, "strategy.synthetic.preview-c"),),
    )
    state = _apply(
        state,
        4,
        confirmed_rows=(1,),
        observations=(_candidate(1, "strategy.synthetic.c"),),
    )

    result = state.finalize()[0]
    assert result.strategy_ids == ("strategy.synthetic.c",)
    assert len(result.evidence) == 1


def test_later_same_match_and_unresolved_or_negative_confirmation_do_not_erase_history() -> None:
    state = _apply(SelectionSessionStrategyCollectorState(), 1, confirmed_rows=(1,))
    state = _apply(
        state,
        2,
        confirmed_rows=(1,),
        observations=(_candidate(1, "strategy.synthetic.a"),),
    )
    state = _apply(
        state,
        3,
        confirmed_rows=(1,),
        observations=(_candidate(1, "strategy.synthetic.a"),),
    )
    state = _apply(state, 4, selection=False)
    state = _apply(state, 5, observations=())

    result = state.finalize()[0]
    assert state.confirmation_tracker.is_confirmed(1)
    assert result.state is ConfirmedSelectionStrategyState.CONFIRMED_IDENTIFIED
    assert len(result.evidence) == 2


def test_distinct_postconfirmation_results_conflict_without_winner() -> None:
    state = _apply(SelectionSessionStrategyCollectorState(), 1, confirmed_rows=(1,))
    state = _apply(
        state,
        2,
        confirmed_rows=(1,),
        observations=(_candidate(1, "strategy.synthetic.a"),),
    )
    state = _apply(
        state,
        3,
        confirmed_rows=(1,),
        observations=(_candidate(1, "strategy.synthetic.b"),),
    )

    result = state.finalize()[0]
    assert result.state is ConfirmedSelectionStrategyState.CONFIRMED_STRATEGY_CONFLICT
    assert result.strategy_id is None


def test_four_rows_operate_independently_and_finalize_is_deterministic() -> None:
    state = SelectionSessionStrategyCollectorState()
    state = _apply(state, 1, confirmed_rows=(1, 2))
    state = _apply(
        state,
        2,
        confirmed_rows=(1, 2),
        observations=(
            _candidate(1, "strategy.synthetic.a"),
            _candidate(2, "strategy.synthetic.b"),
        ),
    )
    state = _apply(state, 3, confirmed_rows=(3,))
    state = _apply(
        state,
        4,
        confirmed_rows=(3,),
        observations=(_candidate(3, "strategy.synthetic.c"),),
    )

    first = state.finalize()
    assert first == state.finalize()
    assert [item.state for item in first] == [
        ConfirmedSelectionStrategyState.CONFIRMED_IDENTIFIED,
        ConfirmedSelectionStrategyState.CONFIRMED_IDENTIFIED,
        ConfirmedSelectionStrategyState.CONFIRMED_IDENTIFIED,
        ConfirmedSelectionStrategyState.NOT_CONFIRMED,
    ]


def test_prior_orchestration_state_remains_immutable_after_apply() -> None:
    initial = SelectionSessionStrategyCollectorState()
    updated = _apply(initial, 1, confirmed_rows=(1,))

    assert initial is not updated
    assert not initial.confirmation_tracker.locked_confirmed_rows
    assert not initial.strategy_accumulator.evidence
