"""Conservative JP MuMu selection-stage and terminal observations.

This module is intentionally limited to screen-stage evidence. It neither
recognizes players or strategies nor mutates domain session state. The fixed
geometry is calibrated only for a full 1920x1080 JP MuMu content viewport.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import cv2
import numpy as np

from sentry_copilot.capture.frame_source import Frame
from sentry_copilot.vision.outside_run_pages import (
    OutsideRunPageObservation,
    is_definite_old_run_terminal_or_outside,
)
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi


class SelectionScreenState(StrEnum):
    """Whether a frame is a reliably recognized selection screen."""

    SELECTION = "selection"
    NOT_SELECTION = "not_selection"
    UNRESOLVED = "unresolved"


class OperationTerminalState(StrEnum):
    """Whether a generic OPERATION stage-entry screen is present."""

    PRESENT = "present"
    ABSENT = "absent"
    UNRESOLVED = "unresolved"


class SelectionLifecycleState(StrEnum):
    """The watcher state for automatic selection-session boundaries."""

    OUTSIDE = "outside"
    ACTIVE = "active"
    ENDED = "ended"


@dataclass(frozen=True)
class SelectionScreenObservation:
    """A fixed-layout selection-screen observation with its measured cue."""

    state: SelectionScreenState
    frame_id: str
    header_cyan_pixel_count: int | None

    def __post_init__(self) -> None:
        if not self.frame_id.strip():
            raise ValueError("selection screen observation frame_id must not be blank")
        if self.header_cyan_pixel_count is not None and self.header_cyan_pixel_count < 0:
            raise ValueError("selection header cyan pixel count must be non-negative")


@dataclass(frozen=True)
class SelectionTerminalObservation:
    """A fixed-layout generic OPERATION terminal observation with its cues."""

    state: OperationTerminalState
    frame_id: str
    title_bright_pixel_count: int | None
    background_dark_pixel_fraction: float | None

    def __post_init__(self) -> None:
        if not self.frame_id.strip():
            raise ValueError("selection terminal observation frame_id must not be blank")
        if self.title_bright_pixel_count is not None and self.title_bright_pixel_count < 0:
            raise ValueError("operation title bright pixel count must be non-negative")
        if self.background_dark_pixel_fraction is not None and not (
            0.0 <= self.background_dark_pixel_fraction <= 1.0
        ):
            raise ValueError("operation background dark pixel fraction must be between 0 and 1")


@dataclass(frozen=True)
class SelectionLifecycleWatcher:
    """Immutable chronological debounce for selection-session boundaries.

    Ordinary screen changes, black frames, and unresolved observations preserve
    an active session. Repeated generic OPERATION or semantic outside-run
    observations end it without inferring an outcome cause.
    """

    state: SelectionLifecycleState = SelectionLifecycleState.OUTSIDE
    session_count: int = 0
    pending_selection_count: int = 0
    pending_terminal_count: int = 0
    confirmation_count: int = 2
    pending_outside_count: int = 0

    def __post_init__(self) -> None:
        if self.confirmation_count < 2:
            raise ValueError("selection lifecycle confirmation_count must be at least 2")
        if self.session_count < 0:
            raise ValueError("selection lifecycle session_count must be non-negative")
        if (
            self.pending_selection_count < 0
            or self.pending_terminal_count < 0
            or self.pending_outside_count < 0
        ):
            raise ValueError("selection lifecycle pending counts must be non-negative")

    def apply(
        self,
        screen: SelectionScreenObservation,
        terminal: SelectionTerminalObservation,
        outside_run_pages: tuple[OutsideRunPageObservation, ...] = (),
    ) -> SelectionLifecycleWatcher:
        """Return the next watcher state without mutating this watcher."""

        if self.state is SelectionLifecycleState.ACTIVE:
            terminal_count = (
                self.pending_terminal_count + 1
                if terminal.state is OperationTerminalState.PRESENT
                else 0
            )
            outside_count = (
                self.pending_outside_count + 1
                if has_definite_outside_run_evidence(outside_run_pages)
                else 0
            )
            if (
                terminal_count >= self.confirmation_count
                or outside_count >= self.confirmation_count
            ):
                return SelectionLifecycleWatcher(
                    state=SelectionLifecycleState.ENDED,
                    session_count=self.session_count,
                    confirmation_count=self.confirmation_count,
                )
            return SelectionLifecycleWatcher(
                state=SelectionLifecycleState.ACTIVE,
                session_count=self.session_count,
                pending_terminal_count=terminal_count,
                pending_outside_count=outside_count,
                confirmation_count=self.confirmation_count,
            )

        selection_count = (
            self.pending_selection_count + 1
            if screen.state is SelectionScreenState.SELECTION
            else 0
        )
        if selection_count >= self.confirmation_count:
            return SelectionLifecycleWatcher(
                state=SelectionLifecycleState.ACTIVE,
                session_count=self.session_count + 1,
                confirmation_count=self.confirmation_count,
            )
        return SelectionLifecycleWatcher(
            state=self.state,
            session_count=self.session_count,
            pending_selection_count=selection_count,
            confirmation_count=self.confirmation_count,
        )


def has_definite_outside_run_evidence(
    observations: tuple[OutsideRunPageObservation, ...],
) -> bool:
    """Return whether any independent page observation is a definite outside cue.

    Page kind is intentionally discarded here: consecutive different outside
    pages count toward the same semantic lifecycle debounce.
    """

    return any(is_definite_old_run_terminal_or_outside(item) for item in observations)


JP_MUMU_SELECTION_LIFECYCLE_PROFILE_ID = "jp_mumu_fullscreen_1920x1080.lifecycle.v1"
"""Calibration profile for the explicitly supplied full-frame JP MuMu layout."""

_JP_MUMU_VIEWPORT = PixelRoi(x=0, y=0, width=1920, height=1080)
_SELECTION_HEADER_ROI = PixelRoi(x=540, y=35, width=280, height=80)
_OPERATION_TITLE_ROI = PixelRoi(x=720, y=500, width=480, height=140)
_OPERATION_BACKGROUND_ROI = PixelRoi(x=100, y=100, width=1720, height=850)
_SELECTION_HEADER_CYAN_THRESHOLD = 250
_OPERATION_TITLE_BRIGHT_THRESHOLD = 1_000
_OPERATION_BACKGROUND_DARK_FRACTION_THRESHOLD = 0.82


def observe_jp_mumu_selection_screen(
    frame: Frame,
    viewport: ContentViewport,
) -> SelectionScreenObservation:
    """Observe the fixed cyan selection-header cue, or return unresolved layout."""

    if not _has_known_jp_mumu_layout(frame, viewport):
        return SelectionScreenObservation(
            state=SelectionScreenState.UNRESOLVED,
            frame_id=frame.frame_id,
            header_cyan_pixel_count=None,
        )
    header = _crop(frame, _SELECTION_HEADER_ROI)
    hsv = cv2.cvtColor(header, cv2.COLOR_BGR2HSV)
    count = int(
        np.count_nonzero(
            (hsv[:, :, 0] >= 70)
            & (hsv[:, :, 0] <= 100)
            & (hsv[:, :, 1] >= 90)
            & (hsv[:, :, 2] >= 100)
        )
    )
    return SelectionScreenObservation(
        state=(
            SelectionScreenState.SELECTION
            if count >= _SELECTION_HEADER_CYAN_THRESHOLD
            else SelectionScreenState.NOT_SELECTION
        ),
        frame_id=frame.frame_id,
        header_cyan_pixel_count=count,
    )


def observe_jp_mumu_operation_terminal(
    frame: Frame,
    viewport: ContentViewport,
) -> SelectionTerminalObservation:
    """Observe the generic OPERATION title composition, or return unresolved layout."""

    if not _has_known_jp_mumu_layout(frame, viewport):
        return SelectionTerminalObservation(
            state=OperationTerminalState.UNRESOLVED,
            frame_id=frame.frame_id,
            title_bright_pixel_count=None,
            background_dark_pixel_fraction=None,
        )
    title = _crop(frame, _OPERATION_TITLE_ROI)
    background = _crop(frame, _OPERATION_BACKGROUND_ROI)
    grayscale = cv2.cvtColor(title, cv2.COLOR_BGR2GRAY)
    background_grayscale = cv2.cvtColor(background, cv2.COLOR_BGR2GRAY)
    title_count = int(np.count_nonzero(grayscale >= 210))
    dark_fraction = float(np.mean(background_grayscale <= 40))
    return SelectionTerminalObservation(
        state=(
            OperationTerminalState.PRESENT
            if (
                title_count >= _OPERATION_TITLE_BRIGHT_THRESHOLD
                and dark_fraction >= _OPERATION_BACKGROUND_DARK_FRACTION_THRESHOLD
            )
            else OperationTerminalState.ABSENT
        ),
        frame_id=frame.frame_id,
        title_bright_pixel_count=title_count,
        background_dark_pixel_fraction=dark_fraction,
    )


def _has_known_jp_mumu_layout(frame: Frame, viewport: ContentViewport) -> bool:
    return (
        (frame.width, frame.height) == (_JP_MUMU_VIEWPORT.width, _JP_MUMU_VIEWPORT.height)
        and viewport.pixel_roi == _JP_MUMU_VIEWPORT
    )


def _crop(frame: Frame, roi: PixelRoi) -> np.ndarray:
    return frame.image[roi.y : roi.bottom, roi.x : roi.right]
