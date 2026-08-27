from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.vision.strategy_selection_confirmation import (
    JP_MUMU_SELECTION_CONFIRMATION_THRESHOLD,
    SelectionConfirmationRenderContext,
    SelectionRowConfirmationObservation,
    SelectionRowConfirmationState,
    SelectionRowConfirmationTracker,
    observe_jp_mumu_selection_row_confirmations,
    selection_confirmation_roi,
)
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi


def _frame(*, selection: bool = True, width: int = 1920, height: int = 1080) -> Frame:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    if selection and width >= 820 and height >= 115:
        image[35:115, 540:820] = (255, 255, 0)
    return Frame(
        frame_id=f"synthetic:{width}x{height}",
        frame_index=3,
        processed_at=datetime.now(UTC),
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic",
        width=width,
        height=height,
        image=image,
        source_reference="synthetic",
    )


def _with_marker(
    frame: Frame,
    context: SelectionConfirmationRenderContext,
    row: int,
) -> Frame:
    image = np.array(frame.image, copy=True)
    roi = selection_confirmation_roi(context, row)
    _draw_check_like_marker(image, roi)
    return Frame(
        frame_id=f"{frame.frame_id}:marker-{context}-{row}",
        frame_index=frame.frame_index,
        processed_at=frame.processed_at,
        source_timestamp=frame.source_timestamp,
        source_type=frame.source_type,
        source_id=frame.source_id,
        width=frame.width,
        height=frame.height,
        image=image,
        source_reference=frame.source_reference,
    )


def _draw_check_like_marker(image: np.ndarray, roi: PixelRoi) -> None:
    """Draw a synthetic outer marker frame plus separate cyan check interior."""

    x, y = roi.x + 11, roi.y + 11
    image[y : y + 51, x : x + 51] = (255, 255, 0)
    image[y + 4 : y + 47, x + 4 : x + 47] = (0, 0, 0)
    image[y + 9 : y + 42, x + 9 : x + 42] = (255, 255, 0)


def _observe(
    frame: Frame,
    context: SelectionConfirmationRenderContext = SelectionConfirmationRenderContext.SELECTION_GRID,
) -> tuple[SelectionRowConfirmationObservation, ...]:
    return observe_jp_mumu_selection_row_confirmations(
        frame, ContentViewport.full_frame(frame), context
    )


def test_grid_marker_confirms_only_its_row_and_preserves_frame() -> None:
    frame = _with_marker(_frame(), SelectionConfirmationRenderContext.SELECTION_GRID, 1)
    original = np.array(frame.image, copy=True)

    observations = _observe(frame)

    assert observations[0].state is SelectionRowConfirmationState.CONFIRMED
    assert observations[0].cyan_pixel_count is not None
    assert observations[0].cyan_pixel_count >= JP_MUMU_SELECTION_CONFIRMATION_THRESHOLD
    assert [item.state for item in observations[1:]] == [
        SelectionRowConfirmationState.NOT_CONFIRMED,
        SelectionRowConfirmationState.NOT_CONFIRMED,
        SelectionRowConfirmationState.NOT_CONFIRMED,
    ]
    assert np.array_equal(frame.image, original)


@pytest.mark.parametrize("row, expected_y", [(2, 484), (3, 638), (4, 792)])
def test_grid_rows_use_shared_vertical_geometry(row: int, expected_y: int) -> None:
    frame = _with_marker(_frame(), SelectionConfirmationRenderContext.SELECTION_GRID, row)

    observation = _observe(frame)[row - 1]

    assert observation.state is SelectionRowConfirmationState.CONFIRMED
    assert observation.pixel_bounds == PixelRoi(x=735, y=expected_y, width=85, height=75)


def test_detail_context_uses_its_own_horizontal_geometry() -> None:
    frame = _with_marker(_frame(), SelectionConfirmationRenderContext.STRATEGY_DETAIL, 3)

    observation = _observe(frame, SelectionConfirmationRenderContext.STRATEGY_DETAIL)[2]

    assert observation.state is SelectionRowConfirmationState.CONFIRMED
    assert observation.pixel_bounds == PixelRoi(x=410, y=638, width=85, height=75)


@pytest.mark.parametrize(
    ("marker_context", "observed_context"),
    [
        (
            SelectionConfirmationRenderContext.SELECTION_GRID,
            SelectionConfirmationRenderContext.STRATEGY_DETAIL,
        ),
        (
            SelectionConfirmationRenderContext.STRATEGY_DETAIL,
            SelectionConfirmationRenderContext.SELECTION_GRID,
        ),
    ],
)
def test_explicit_render_context_does_not_combine_rois(
    marker_context: SelectionConfirmationRenderContext,
    observed_context: SelectionConfirmationRenderContext,
) -> None:
    frame = _with_marker(_frame(), marker_context, 1)

    observation = _observe(frame, observed_context)[0]

    assert observation.state is SelectionRowConfirmationState.NOT_CONFIRMED
    assert observation.cyan_pixel_count == 0


def test_below_threshold_marker_is_not_confirmed() -> None:
    frame = _frame()
    image = np.array(frame.image, copy=True)
    roi = selection_confirmation_roi(SelectionConfirmationRenderContext.SELECTION_GRID, 1)
    image[roi.y : roi.y + 10, roi.x : roi.x + 10] = (255, 255, 0)
    sparse = Frame(
        frame_id="synthetic:sparse", frame_index=0, processed_at=datetime.now(UTC),
        source_timestamp=None, source_type=FrameSourceType.IMAGE_SEQUENCE, source_id="synthetic",
        width=1920, height=1080, image=image, source_reference="synthetic",
    )

    observation = _observe(sparse)[0]

    assert observation.state is SelectionRowConfirmationState.NOT_CONFIRMED
    assert observation.cyan_pixel_count == 100


@pytest.mark.parametrize(
    "shape",
    [
        (0, 0, 85, 32),
        (0, 0, 85, 75),
        (0, 10, 50, 60),
    ],
)
def test_large_or_edge_touching_cyan_animation_is_not_confirmed(
    shape: tuple[int, int, int, int],
) -> None:
    frame = _frame()
    image = np.array(frame.image, copy=True)
    roi = selection_confirmation_roi(SelectionConfirmationRenderContext.SELECTION_GRID, 3)
    x, y, width, height = shape
    image[roi.y + y : roi.y + y + height, roi.x + x : roi.x + x + width] = (255, 255, 0)
    nuisance = Frame(
        frame_id="synthetic:animation",
        frame_index=0,
        processed_at=frame.processed_at,
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic",
        width=1920,
        height=1080,
        image=image,
        source_reference="synthetic",
    )

    observation = _observe(nuisance)[2]

    assert observation.cyan_pixel_count is not None
    assert observation.cyan_pixel_count >= JP_MUMU_SELECTION_CONFIRMATION_THRESHOLD
    assert observation.state is SelectionRowConfirmationState.NOT_CONFIRMED


def test_check_like_marker_with_unrelated_cyan_noise_confirms() -> None:
    frame = _with_marker(_frame(), SelectionConfirmationRenderContext.SELECTION_GRID, 2)
    image = np.array(frame.image, copy=True)
    roi = selection_confirmation_roi(SelectionConfirmationRenderContext.SELECTION_GRID, 2)
    image[roi.y : roi.y + 4, roi.x : roi.x + 4] = (255, 255, 0)
    noisy = Frame(
        frame_id="synthetic:marker-noise",
        frame_index=0,
        processed_at=frame.processed_at,
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic",
        width=1920,
        height=1080,
        image=image,
        source_reference="synthetic",
    )

    assert _observe(noisy)[1].state is SelectionRowConfirmationState.CONFIRMED


def test_wrong_resolution_or_viewport_or_non_selection_is_unresolved() -> None:
    wrong = _frame(width=1280, height=720)
    assert {item.state for item in _observe(wrong)} == {SelectionRowConfirmationState.UNRESOLVED}

    full = _frame()
    wrong_viewport = ContentViewport(
        frame_id=full.frame_id,
        frame_width=full.width,
        frame_height=full.height,
        pixel_roi=PixelRoi(x=0, y=0, width=1919, height=1080),
    )
    result = observe_jp_mumu_selection_row_confirmations(
        full, wrong_viewport, SelectionConfirmationRenderContext.SELECTION_GRID
    )
    assert {item.state for item in result} == {SelectionRowConfirmationState.UNRESOLVED}
    assert all(item.cyan_pixel_count is None for item in result)

    non_selection = _frame(selection=False)
    assert {item.state for item in _observe(non_selection)} == {
        SelectionRowConfirmationState.UNRESOLVED
    }


def test_tracker_requires_two_consecutive_positives_and_is_sticky() -> None:
    positive = _observe(
        _with_marker(_frame(), SelectionConfirmationRenderContext.SELECTION_GRID, 1)
    )
    negative = _observe(_frame())
    unresolved_frame = _frame(selection=False)
    unresolved = _observe(unresolved_frame)

    tracker = SelectionRowConfirmationTracker().apply(positive)
    assert not tracker.is_confirmed(1)
    assert tracker.pending_positive_counts[0] == 1

    assert not tracker.apply(negative).apply(positive).is_confirmed(1)
    assert not tracker.apply(unresolved).apply(positive).is_confirmed(1)

    locked = tracker.apply(positive)
    assert locked.is_confirmed(1)
    assert locked.apply(negative).is_confirmed(1)
    assert locked.apply(unresolved).is_confirmed(1)


def test_tracker_debounces_rows_independently_and_can_lock_all_rows() -> None:
    frame = _frame()
    for row in range(1, 5):
        frame = _with_marker(frame, SelectionConfirmationRenderContext.SELECTION_GRID, row)
    observations = _observe(frame)

    once = SelectionRowConfirmationTracker().apply(observations)
    assert not once.locked_confirmed_rows
    assert once.pending_positive_counts == (1, 1, 1, 1)

    locked = once.apply(observations)
    assert locked.locked_confirmed_rows == frozenset({1, 2, 3, 4})


def test_tracker_does_not_lock_from_repeated_animation_contamination() -> None:
    frame = _frame()
    image = np.array(frame.image, copy=True)
    roi = selection_confirmation_roi(SelectionConfirmationRenderContext.SELECTION_GRID, 3)
    image[roi.y : roi.y + 32, roi.x : roi.right] = (255, 255, 0)
    animation = Frame(
        frame_id="synthetic:active-row-animation",
        frame_index=0,
        processed_at=frame.processed_at,
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic",
        width=1920,
        height=1080,
        image=image,
        source_reference="synthetic",
    )

    tracker = SelectionRowConfirmationTracker().apply(_observe(animation))
    tracker = tracker.apply(_observe(animation))

    assert not tracker.is_confirmed(3)
