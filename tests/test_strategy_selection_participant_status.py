from __future__ import annotations

from datetime import UTC, datetime

import cv2
import numpy as np
import pytest

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.vision.strategy_selection_participant_status import (
    SelectionCompletionPresentationObservation,
    SelectionCompletionPresentationState,
    SelectionExitCompletionState,
    SelectionExitCompletionTracker,
    SelectionParticipantStatusObservation,
    SelectionParticipantStatusState,
    SelectionRowExitTracker,
    observe_jp_mumu_selection_completion_presentations,
    observe_jp_mumu_selection_participant_statuses,
    selection_completion_presentation_roi,
    selection_participant_status_roi,
)
from sentry_copilot.vision.strategy_selection_render_context import (
    SelectionRenderContextObservation,
    SelectionRenderContextState,
)
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi


def _frame(index: int = 0, *, selection: bool = True) -> Frame:
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    if selection:
        image[35:115, 540:820] = (255, 255, 0)
    return Frame(
        frame_id=f"synthetic:{index}",
        frame_index=index,
        processed_at=datetime(2026, 8, 28, tzinfo=UTC),
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic",
        width=1920,
        height=1080,
        image=image,
        source_reference=f"synthetic:{index}",
    )


def _context(frame: Frame, state: SelectionRenderContextState) -> SelectionRenderContextObservation:
    return SelectionRenderContextObservation(
        state=state,
        bright_pixel_fraction=0.0 if state is not SelectionRenderContextState.UNRESOLVED else None,
        pixel_bounds=PixelRoi(x=1550, y=550, width=120, height=180),
        frame_id=frame.frame_id,
        frame_index=frame.frame_index,
        processed_at=frame.processed_at,
        source_timestamp=frame.source_timestamp,
        source_type=frame.source_type,
        source_id=frame.source_id,
        source_reference=frame.source_reference,
    )


def _with_status(
    frame: Frame,
    row: int,
    *,
    kind: str,
    context: SelectionRenderContextState = SelectionRenderContextState.SELECTION_GRID,
) -> Frame:
    image = np.array(frame.image, copy=True)
    roi = selection_participant_status_roi(context, row)
    image[roi.y : roi.bottom, roi.x : roi.right] = (50, 50, 50)
    if kind == "network":
        image[roi.y + 10 : roi.y + 45, roi.x + 2 : roi.x + 22] = (180, 180, 180)
    elif kind == "exit":
        image[roi.y + 25 : roi.y + 60, roi.x + 35 : roi.x + 60] = (180, 180, 180)
    elif kind == "gap":
        image[roi.y + 35 : roi.y + 53, roi.x + 31 : roi.x + 50] = (180, 180, 180)
        image[roi.y + 5 : roi.y + 22, roi.x + 5 : roi.x + 25] = (180, 180, 180)
    return Frame(
        frame_id=frame.frame_id,
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


def _with_ellipsis(
    frame: Frame,
    *,
    context: SelectionRenderContextState = SelectionRenderContextState.SELECTION_GRID,
    row: int = 1,
    centers: tuple[tuple[int, int], ...] | None = None,
    axes: tuple[int, int] = (4, 5),
) -> Frame:
    """Draw an audited-shape synthetic ellipsis inside one completion row box."""

    image = np.array(frame.image, copy=True)
    roi = selection_completion_presentation_roi(context, row)
    if centers is None:
        first_center_x = 38 if context is SelectionRenderContextState.SELECTION_GRID else 39
        centers = tuple((first_center_x + 20 * index, 28) for index in range(3))
    for center_x, center_y in centers:
        cv2.ellipse(
            image,
            (roi.x + center_x, roi.y + center_y),
            axes,
            0,
            0,
            360,
            (160, 160, 160),
            -1,
        )
    return Frame(
        frame_id=frame.frame_id,
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


def _with_retained_strategy_portrait(
    frame: Frame,
    *,
    context: SelectionRenderContextState = SelectionRenderContextState.SELECTION_GRID,
    row: int = 1,
) -> Frame:
    """Draw a synthetic retained strategy image with the established texture cue."""

    image = np.array(frame.image, copy=True)
    roi = selection_completion_presentation_roi(context, row)
    texture = np.indices((roi.height, roi.width))[0][:, :, None] * np.array(
        [1, 2, 3], dtype=np.uint8
    )
    image[roi.y : roi.bottom, roi.x : roi.right] = texture
    return Frame(
        frame_id=frame.frame_id,
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


def _observations(
    frame: Frame,
    context: SelectionRenderContextState = SelectionRenderContextState.SELECTION_GRID,
) -> tuple[SelectionParticipantStatusObservation, ...]:
    return observe_jp_mumu_selection_participant_statuses(
        frame, ContentViewport.full_frame(frame), _context(frame, context)
    )


def test_status_observer_rejects_bright_and_dark_ordinary_avatars() -> None:
    bright = _frame()
    dark = _with_status(_frame(), 1, kind="ordinary")

    assert _observations(bright)[0].state is SelectionParticipantStatusState.NO_STATUS_OVERLAY
    assert _observations(dark)[0].state is SelectionParticipantStatusState.NO_STATUS_OVERLAY


def test_status_observer_classifies_network_exit_and_conservative_gap() -> None:
    network = _with_status(_frame(), 1, kind="network")
    exit_frame = _with_status(_frame(), 1, kind="exit")
    gap = _with_status(_frame(), 1, kind="gap")

    assert _observations(network)[0].state is SelectionParticipantStatusState.NETWORK_WARNING
    assert _observations(exit_frame)[0].state is SelectionParticipantStatusState.EXIT
    assert _observations(gap)[0].state is SelectionParticipantStatusState.UNRESOLVED


def test_status_observer_requires_same_frame_supported_context_and_viewport() -> None:
    frame = _with_status(_frame(), 2, kind="exit")
    stale = _context(_frame(1), SelectionRenderContextState.SELECTION_GRID)
    with pytest.raises(ValueError, match="belong to the supplied frame"):
        observe_jp_mumu_selection_participant_statuses(
            frame, ContentViewport.full_frame(frame), stale
        )

    wrong_viewport = ContentViewport(
        frame_id=frame.frame_id,
        frame_width=frame.width,
        frame_height=frame.height,
        pixel_roi=PixelRoi(x=1, y=0, width=1919, height=1080),
    )
    unresolved = observe_jp_mumu_selection_participant_statuses(
        frame, wrong_viewport, _context(frame, SelectionRenderContextState.SELECTION_GRID)
    )
    assert {item.state for item in unresolved} == {SelectionParticipantStatusState.UNRESOLVED}


def test_exit_tracker_requires_two_observations_then_remains_sticky() -> None:
    exit_frame = _with_status(_frame(), 1, kind="exit")
    network_frame = _with_status(_frame(), 1, kind="network")
    normal_frame = _frame()
    tracker = SelectionRowExitTracker().apply(_observations(exit_frame))
    assert not tracker.is_exited(1)

    locked = tracker.apply(_observations(exit_frame))
    assert locked.is_exited(1)
    assert locked.apply(_observations(network_frame)).is_exited(1)
    assert locked.apply(_observations(normal_frame)).is_exited(1)
    unresolved = _observations(_frame(selection=False))
    assert locked.apply(unresolved).is_exited(1)


def test_completion_observer_detects_audited_grid_and_detail_ellipses() -> None:
    decorated = _with_ellipsis(_frame())
    observations = observe_jp_mumu_selection_completion_presentations(
        decorated,
        ContentViewport.full_frame(decorated),
        _context(decorated, SelectionRenderContextState.SELECTION_GRID),
    )
    assert observations[0].state is SelectionCompletionPresentationState.ELLIPSIS_PLACEHOLDER

    detail = _with_ellipsis(
        _frame(), context=SelectionRenderContextState.STRATEGY_DETAIL, row=4
    )
    detail_observations = observe_jp_mumu_selection_completion_presentations(
        detail,
        ContentViewport.full_frame(detail),
        _context(detail, SelectionRenderContextState.STRATEGY_DETAIL),
    )
    assert detail_observations[3].state is SelectionCompletionPresentationState.ELLIPSIS_PLACEHOLDER


@pytest.mark.parametrize(
    ("centers", "axes"),
    [
        (((38, 28), (58, 32), (78, 28)), (4, 5)),
        (((38, 28), (58, 28), (90, 28)), (4, 5)),
        (((38, 28), (58, 28), (78, 28)), (6, 6)),
        (((38, 28), (58, 28)), (4, 5)),
        (((38, 28), (58, 28), (78, 28), (98, 28)), (4, 5)),
    ],
)
def test_completion_observer_rejects_non_ellipsis_geometry(
    centers: tuple[tuple[int, int], ...], axes: tuple[int, int]
) -> None:
    frame = _with_ellipsis(_frame(), centers=centers, axes=axes)
    observations = observe_jp_mumu_selection_completion_presentations(
        frame,
        ContentViewport.full_frame(frame),
        _context(frame, SelectionRenderContextState.SELECTION_GRID),
    )
    assert observations[0].state is SelectionCompletionPresentationState.UNRESOLVED


@pytest.mark.parametrize("kind", ["selecting", "ambiguous"])
def test_completion_observer_does_not_infer_portrait_from_non_ellipsis(
    kind: str,
) -> None:
    frame = _frame()
    image = np.array(frame.image, copy=True)
    roi = selection_completion_presentation_roi(SelectionRenderContextState.SELECTION_GRID, 1)
    shade = 220 if kind == "selecting" else 160
    image[roi.y : roi.bottom, roi.x : roi.right] = (shade, shade, shade)
    decorated = Frame(
        frame_id=frame.frame_id,
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
    observation = observe_jp_mumu_selection_completion_presentations(
        decorated,
        ContentViewport.full_frame(decorated),
        _context(decorated, SelectionRenderContextState.SELECTION_GRID),
    )[0]
    assert observation.state is SelectionCompletionPresentationState.UNRESOLVED


def test_observer_retained_portrait_with_locked_exit_becomes_confirmed_then_exited() -> None:
    exit_frame = _with_retained_strategy_portrait(_with_status(_frame(), 1, kind="exit"))
    context = _context(exit_frame, SelectionRenderContextState.SELECTION_GRID)
    exits = _observations(exit_frame)
    locked_exit = SelectionRowExitTracker().apply(exits).apply(exits)
    completion = observe_jp_mumu_selection_completion_presentations(
        exit_frame,
        ContentViewport.full_frame(exit_frame),
        context,
    )

    assert completion[0].state is SelectionCompletionPresentationState.STRATEGY_PORTRAIT_PRESENT
    tracker = SelectionExitCompletionTracker().apply(locked_exit, completion, frozenset())
    assert tracker.state_for(1) is SelectionExitCompletionState.CONFIRMED_THEN_EXITED


def test_completion_presentation_roi_is_render_context_aware_and_retains_full_grid_glyph() -> None:
    grid = selection_completion_presentation_roi(SelectionRenderContextState.SELECTION_GRID, 1)
    detail = selection_completion_presentation_roi(SelectionRenderContextState.STRATEGY_DETAIL, 1)

    assert grid == PixelRoi(x=617, y=338, width=110, height=70)
    assert detail == PixelRoi(x=320, y=338, width=110, height=70)
    assert (
        selection_completion_presentation_roi(SelectionRenderContextState.SELECTION_GRID, 2).y
        == 492
    )
    assert grid.right >= 708


def test_exit_completion_tracker_is_conservative_and_sticky() -> None:
    exit_frame = _with_status(_frame(), 1, kind="exit")
    exits = _observations(exit_frame)
    locked_exit = SelectionRowExitTracker().apply(exits).apply(exits)
    completion = observe_jp_mumu_selection_completion_presentations(
        exit_frame,
        ContentViewport.full_frame(exit_frame),
        _context(exit_frame, SelectionRenderContextState.SELECTION_GRID),
    )
    tracker = SelectionExitCompletionTracker().apply(locked_exit, completion, frozenset())
    assert tracker.state_for(1) is SelectionExitCompletionState.EXIT_COMPLETION_UNRESOLVED

    ellipsis = list(completion)
    first = ellipsis[0]
    ellipsis[0] = SelectionCompletionPresentationObservation(
        selection_row=1,
        state=SelectionCompletionPresentationState.ELLIPSIS_PLACEHOLDER,
        pixel_bounds=first.pixel_bounds,
        grayscale_standard_deviation=1.0,
        ellipsis_component_count=3,
        frame_id=first.frame_id,
        frame_index=first.frame_index,
        processed_at=first.processed_at,
        source_timestamp=first.source_timestamp,
        source_type=first.source_type,
        source_id=first.source_id,
        source_reference=first.source_reference,
    )
    exited_unconfirmed = tracker.apply(locked_exit, tuple(ellipsis), frozenset())
    assert exited_unconfirmed.state_for(1) is SelectionExitCompletionState.EXITED_UNCONFIRMED
    assert exited_unconfirmed.apply(locked_exit, completion, frozenset({1})).state_for(1) is (
        SelectionExitCompletionState.EXITED_UNCONFIRMED
    )


def test_same_frame_portrait_preserves_confirmed_then_exited_without_matcher_identity() -> None:
    exit_frame = _with_status(_frame(), 1, kind="exit")
    exits = _observations(exit_frame)
    locked_exit = SelectionRowExitTracker().apply(exits).apply(exits)
    completion = list(
        observe_jp_mumu_selection_completion_presentations(
            exit_frame,
            ContentViewport.full_frame(exit_frame),
            _context(exit_frame, SelectionRenderContextState.SELECTION_GRID),
        )
    )
    first = completion[0]
    completion[0] = SelectionCompletionPresentationObservation(
        selection_row=1,
        state=SelectionCompletionPresentationState.STRATEGY_PORTRAIT_PRESENT,
        pixel_bounds=first.pixel_bounds,
        grayscale_standard_deviation=30.0,
        ellipsis_component_count=0,
        frame_id=first.frame_id,
        frame_index=first.frame_index,
        processed_at=first.processed_at,
        source_timestamp=first.source_timestamp,
        source_type=first.source_type,
        source_id=first.source_id,
        source_reference=first.source_reference,
    )
    state = SelectionExitCompletionTracker().apply(locked_exit, tuple(completion), frozenset())
    assert state.state_for(1) is SelectionExitCompletionState.CONFIRMED_THEN_EXITED
