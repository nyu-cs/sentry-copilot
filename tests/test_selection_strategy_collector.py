from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import numpy as np
import pytest

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
from sentry_copilot.vision.strategy_selection_participant_status import (
    SelectionCompletionPresentationObservation,
    SelectionCompletionPresentationState,
    SelectionExitCompletionState,
    SelectionParticipantStatusObservation,
    SelectionParticipantStatusState,
)
from sentry_copilot.vision.strategy_selection_probe import StrategySelectionProbeStatus
from sentry_copilot.vision.strategy_selection_render_context import SelectionRenderContextState
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi
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


def _status_observations(
    frame: Frame,
    *,
    exit_row: int,
) -> tuple[SelectionParticipantStatusObservation, ...]:
    return tuple(
        SelectionParticipantStatusObservation(
            selection_row=row,
            state=(
                SelectionParticipantStatusState.EXIT
                if row == exit_row
                else SelectionParticipantStatusState.NO_STATUS_OVERLAY
            ),
            pixel_bounds=PixelRoi(x=0, y=0, width=62, height=70),
            render_context=SelectionRenderContextState.SELECTION_GRID,
            dark_fraction=0.5,
            low_saturation_white_fraction=0.2,
            bottom_right_white_occupancy=0.5 if row == exit_row else 0.0,
            frame_id=frame.frame_id,
            frame_index=frame.frame_index,
            processed_at=frame.processed_at,
            source_timestamp=frame.source_timestamp,
            source_type=frame.source_type,
            source_id=frame.source_id,
            source_reference=frame.source_reference,
        )
        for row in range(1, 5)
    )


def _completion_observations(
    frame: Frame,
    *,
    row: int,
    state: SelectionCompletionPresentationState,
) -> tuple[SelectionCompletionPresentationObservation, ...]:
    return tuple(
        SelectionCompletionPresentationObservation(
            selection_row=current_row,
            state=state if current_row == row else SelectionCompletionPresentationState.UNRESOLVED,
            pixel_bounds=PixelRoi(x=0, y=0, width=88, height=70),
            grayscale_standard_deviation=30.0
            if current_row == row and state is not SelectionCompletionPresentationState.UNRESOLVED
            else None,
            ellipsis_component_count=(
                3
                if current_row == row
                and state is SelectionCompletionPresentationState.ELLIPSIS_PLACEHOLDER
                else (
                    0
                    if current_row == row
                    and state is SelectionCompletionPresentationState.STRATEGY_PORTRAIT_PRESENT
                    else None
                )
            ),
            frame_id=frame.frame_id,
            frame_index=frame.frame_index,
            processed_at=frame.processed_at,
            source_timestamp=frame.source_timestamp,
            source_type=frame.source_type,
            source_id=frame.source_id,
            source_reference=frame.source_reference,
        )
        for current_row in range(1, 5)
    )


def _apply_exit_frame(
    state: SelectionSessionStrategyCollectorState,
    index: int,
    *,
    exit_row: int,
    completion_state: SelectionCompletionPresentationState,
    observations: tuple[StrategySelectionCandidateObservation, ...] = (),
) -> SelectionSessionStrategyCollectorState:
    frame = _frame(index)
    return state.apply_frame(
        frame,
        ContentViewport.full_frame(frame),
        SelectionConfirmationRenderContext.SELECTION_GRID,
        observations,
        _status_observations(frame, exit_row=exit_row),
        _completion_observations(frame, row=exit_row, state=completion_state),
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


def test_two_exit_observations_with_explicit_ellipsis_are_terminal_and_block_later_strategy(
) -> None:
    state = _apply_exit_frame(
        SelectionSessionStrategyCollectorState(),
        1,
        exit_row=1,
        completion_state=SelectionCompletionPresentationState.ELLIPSIS_PLACEHOLDER,
    )
    state = _apply_exit_frame(
        state,
        2,
        exit_row=1,
        completion_state=SelectionCompletionPresentationState.ELLIPSIS_PLACEHOLDER,
        observations=(_candidate(1, "strategy.synthetic.must-not-be-collected"),),
    )

    assert state.exit_completion_state(1) is SelectionExitCompletionState.EXITED_UNCONFIRMED
    assert state.finalize()[0].state is ConfirmedSelectionStrategyState.NOT_CONFIRMED


def test_confirmed_strategy_is_preserved_when_the_row_later_exits_with_a_portrait() -> None:
    state = _apply(SelectionSessionStrategyCollectorState(), 1, confirmed_rows=(1,))
    state = _apply(
        state,
        2,
        confirmed_rows=(1,),
        observations=(_candidate(1, "strategy.synthetic.preserved"),),
    )
    state = _apply_exit_frame(
        state,
        3,
        exit_row=1,
        completion_state=SelectionCompletionPresentationState.STRATEGY_PORTRAIT_PRESENT,
    )
    state = _apply_exit_frame(
        state,
        4,
        exit_row=1,
        completion_state=SelectionCompletionPresentationState.STRATEGY_PORTRAIT_PRESENT,
        observations=(_candidate(1, "strategy.synthetic.must-not-replace"),),
    )

    assert state.exit_completion_state(1) is SelectionExitCompletionState.CONFIRMED_THEN_EXITED
    result = state.finalize()[0]
    assert result.state is ConfirmedSelectionStrategyState.CONFIRMED_IDENTIFIED
    assert result.strategy_id == "strategy.synthetic.preserved"


def test_status_observations_require_full_same_frame_source_provenance() -> None:
    frame = _frame(1)
    statuses = list(_status_observations(frame, exit_row=1))
    statuses[0] = replace(statuses[0], source_reference="different-synthetic-frame")

    with pytest.raises(ValueError, match="belong to the supplied frame"):
        SelectionSessionStrategyCollectorState().apply_frame(
            frame,
            ContentViewport.full_frame(frame),
            SelectionConfirmationRenderContext.SELECTION_GRID,
            (),
            tuple(statuses),
            _completion_observations(
                frame,
                row=1,
                state=SelectionCompletionPresentationState.ELLIPSIS_PLACEHOLDER,
            ),
        )
