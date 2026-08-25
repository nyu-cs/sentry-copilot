from __future__ import annotations

from datetime import UTC, datetime

import cv2
import numpy as np
import pytest

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.vision.selection_session_lifecycle import (
    OperationTerminalState,
    SelectionLifecycleState,
    SelectionLifecycleWatcher,
    SelectionScreenObservation,
    SelectionScreenState,
    SelectionTerminalObservation,
    observe_jp_mumu_operation_terminal,
    observe_jp_mumu_selection_screen,
)
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi


def _screen(state: SelectionScreenState) -> SelectionScreenObservation:
    return SelectionScreenObservation(
        state=state,
        frame_id=f"screen-{state}",
        header_cyan_pixel_count=0,
    )


def _terminal(state: OperationTerminalState) -> SelectionTerminalObservation:
    return SelectionTerminalObservation(
        state=state,
        frame_id=f"terminal-{state}",
        title_bright_pixel_count=0,
    )


def _frame(*, width: int = 1920, height: int = 1080) -> Frame:
    return Frame(
        frame_id="synthetic:000000",
        frame_index=0,
        processed_at=datetime.now(UTC),
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic",
        width=width,
        height=height,
        image=np.zeros((height, width, 3), dtype=np.uint8),
        source_reference="synthetic",
    )


def _advance(
    watcher: SelectionLifecycleWatcher,
    screen: SelectionScreenState,
    terminal: OperationTerminalState = OperationTerminalState.ABSENT,
) -> SelectionLifecycleWatcher:
    return watcher.apply(_screen(screen), _terminal(terminal))


def test_confirmation_count_must_be_at_least_two() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        SelectionLifecycleWatcher(confirmation_count=1)


def test_two_selection_observations_start_one_session() -> None:
    watcher = _advance(SelectionLifecycleWatcher(), SelectionScreenState.SELECTION)
    assert watcher.state is SelectionLifecycleState.OUTSIDE
    assert watcher.session_count == 0

    watcher = _advance(watcher, SelectionScreenState.SELECTION)
    assert watcher.state is SelectionLifecycleState.ACTIVE
    assert watcher.session_count == 1


def test_active_session_survives_non_selection_unresolved_and_black_like_observations() -> None:
    watcher = SelectionLifecycleWatcher()
    watcher = _advance(watcher, SelectionScreenState.SELECTION)
    watcher = _advance(watcher, SelectionScreenState.SELECTION)
    for state in (
        SelectionScreenState.SELECTION,
        SelectionScreenState.SELECTION,
        SelectionScreenState.SELECTION,
        SelectionScreenState.NOT_SELECTION,
        SelectionScreenState.UNRESOLVED,
        SelectionScreenState.NOT_SELECTION,
    ):
        watcher = _advance(watcher, state)
        assert watcher.state is SelectionLifecycleState.ACTIVE
        assert watcher.session_count == 1


def test_two_operation_observations_end_active_session() -> None:
    watcher = SelectionLifecycleWatcher()
    watcher = _advance(watcher, SelectionScreenState.SELECTION)
    watcher = _advance(watcher, SelectionScreenState.SELECTION)
    watcher = _advance(
        watcher,
        SelectionScreenState.NOT_SELECTION,
        OperationTerminalState.PRESENT,
    )
    assert watcher.state is SelectionLifecycleState.ACTIVE

    watcher = _advance(
        watcher,
        SelectionScreenState.NOT_SELECTION,
        OperationTerminalState.PRESENT,
    )
    assert watcher.state is SelectionLifecycleState.ENDED
    assert watcher.session_count == 1


def test_terminal_absence_does_not_end_and_later_selection_starts_second_session() -> None:
    watcher = SelectionLifecycleWatcher()
    watcher = _advance(watcher, SelectionScreenState.SELECTION)
    watcher = _advance(watcher, SelectionScreenState.SELECTION)
    watcher = _advance(watcher, SelectionScreenState.NOT_SELECTION)
    assert watcher.state is SelectionLifecycleState.ACTIVE

    watcher = _advance(
        watcher,
        SelectionScreenState.NOT_SELECTION,
        OperationTerminalState.PRESENT,
    )
    watcher = _advance(
        watcher,
        SelectionScreenState.NOT_SELECTION,
        OperationTerminalState.PRESENT,
    )
    assert watcher.state is SelectionLifecycleState.ENDED

    watcher = _advance(watcher, SelectionScreenState.SELECTION)
    watcher = _advance(watcher, SelectionScreenState.SELECTION)
    assert watcher.state is SelectionLifecycleState.ACTIVE
    assert watcher.session_count == 2


def test_fixed_layout_cues_produce_observations_without_mutating_frame() -> None:
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    header_hsv = np.full((80, 280, 3), (85, 200, 200), dtype=np.uint8)
    image[35:115, 540:820] = cv2.cvtColor(header_hsv, cv2.COLOR_HSV2BGR)
    image[500:640, 720:1200] = (220, 220, 220)
    frame = Frame(
        frame_id="synthetic:cue",
        frame_index=0,
        processed_at=datetime.now(UTC),
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic",
        width=1920,
        height=1080,
        image=image,
        source_reference="synthetic",
    )
    original = frame.image.copy()
    viewport = ContentViewport.full_frame(frame)

    assert observe_jp_mumu_selection_screen(frame, viewport).state is SelectionScreenState.SELECTION
    assert (
        observe_jp_mumu_operation_terminal(frame, viewport).state
        is OperationTerminalState.PRESENT
    )
    assert np.array_equal(frame.image, original)


def test_wrong_frame_or_viewport_is_unresolved() -> None:
    frame = _frame(width=1280, height=720)
    viewport = ContentViewport.full_frame(frame)
    assert (
        observe_jp_mumu_selection_screen(frame, viewport).state
        is SelectionScreenState.UNRESOLVED
    )
    assert (
        observe_jp_mumu_operation_terminal(frame, viewport).state
        is OperationTerminalState.UNRESOLVED
    )

    full_frame = _frame()
    wrong_viewport = ContentViewport(
        frame_id=full_frame.frame_id,
        frame_width=full_frame.width,
        frame_height=full_frame.height,
        pixel_roi=PixelRoi(x=0, y=0, width=1919, height=1080),
    )
    assert (
        observe_jp_mumu_selection_screen(full_frame, wrong_viewport).state
        is SelectionScreenState.UNRESOLVED
    )
