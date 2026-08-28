"""Fixed-layout, row-local confirmation-marker observations for JP MuMu selection.

This module observes only the persistent cyan confirmation marker.  It does not
recognize a strategy, infer a player identity, mutate session state, or decide
which render context is active.  The caller supplies that context explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

import cv2
import numpy as np

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.vision.selection_session_lifecycle import (
    SelectionScreenState,
    observe_jp_mumu_selection_screen,
)
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi

JP_MUMU_SELECTION_CONFIRMATION_PROFILE_ID = "jp_mumu_fullscreen_1920x1080.confirmation.v1"
"""Calibration profile for the explicit JP MuMu fullscreen baseline."""

JP_MUMU_SELECTION_CONFIRMATION_THRESHOLD = 1_000
"""Minimum HSV cyan-pixel count for one visual confirmation observation."""

_ROWS = (1, 2, 3, 4)
_ROW_FIRST_Y = 330
_ROW_STEP_Y = 154
_CUE_WIDTH = 85
_CUE_HEIGHT = 75
_GRID_X = 735
_DETAIL_X = 410
_MARKER_MIN_SIZE = 45
_MARKER_MAX_SIZE = 60
_MARKER_MIN_FILL_RATIO = 0.2
_MARKER_MAX_FILL_RATIO = 0.5


class SelectionConfirmationRenderContext(StrEnum):
    """Explicit selection-screen render context; it is never auto-detected here."""

    SELECTION_GRID = "selection_grid"
    STRATEGY_DETAIL = "strategy_detail"


class SelectionRowConfirmationState(StrEnum):
    """One row's visual confirmation evidence, separate from strategy identity."""

    CONFIRMED = "confirmed"
    NOT_CONFIRMED = "not_confirmed"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class SelectionRowConfirmationObservation:
    """Immutable marker evidence for a selection row with copied frame provenance."""

    selection_row: int
    state: SelectionRowConfirmationState
    cyan_pixel_count: int | None
    pixel_bounds: PixelRoi
    render_context: SelectionConfirmationRenderContext
    frame_id: str
    frame_index: int
    processed_at: datetime
    source_timestamp: timedelta | None
    source_type: FrameSourceType
    source_id: str
    source_reference: str

    def __post_init__(self) -> None:
        if self.selection_row not in _ROWS:
            raise ValueError("selection confirmation row must be between 1 and 4")
        if not (
            self.frame_id.strip()
            and self.source_id.strip()
            and self.source_reference.strip()
        ):
            raise ValueError("selection confirmation provenance text fields must not be blank")
        if self.frame_index < 0:
            raise ValueError("selection confirmation frame index must be non-negative")
        if self.processed_at.tzinfo is None or self.processed_at.utcoffset() is None:
            raise ValueError("selection confirmation processing time must be timezone-aware")
        if self.source_timestamp is not None and self.source_timestamp.total_seconds() < 0:
            raise ValueError("selection confirmation source timestamp must be non-negative")
        if self.state is SelectionRowConfirmationState.UNRESOLVED:
            if self.cyan_pixel_count is not None:
                raise ValueError("unresolved selection confirmation must not report a cyan count")
        elif self.cyan_pixel_count is None or self.cyan_pixel_count < 0:
            raise ValueError("resolved selection confirmation requires a non-negative cyan count")


@dataclass(frozen=True)
class SelectionRowConfirmationTracker:
    """Caller-owned sticky per-selection debounce for four visual row markers."""

    confirmation_count: int = 2
    pending_positive_counts: tuple[int, int, int, int] = (0, 0, 0, 0)
    locked_confirmed_rows: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        if self.confirmation_count < 2:
            raise ValueError("selection confirmation count must be at least 2")
        if any(value < 0 for value in self.pending_positive_counts):
            raise ValueError("selection confirmation pending counts must be non-negative")
        if not self.locked_confirmed_rows.issubset(_ROWS):
            raise ValueError("locked selection confirmation rows must be between 1 and 4")

    def apply(
        self,
        observations: tuple[SelectionRowConfirmationObservation, ...],
        *,
        terminal_rows: frozenset[int] = frozenset(),
    ) -> SelectionRowConfirmationTracker:
        """Return the debounced tracker state without mutating this instance.

        A row locks after consecutive positive visual observations.  Once locked,
        later unresolved or negative observations cannot imply an in-game unconfirm.
        """

        _validate_complete_rows(observations)
        if not terminal_rows.issubset(_ROWS):
            raise ValueError("terminal selection confirmation rows must be between 1 and 4")
        pending = list(self.pending_positive_counts)
        locked = set(self.locked_confirmed_rows)
        for observation in observations:
            index = observation.selection_row - 1
            if observation.selection_row in locked or observation.selection_row in terminal_rows:
                pending[index] = 0
                continue
            if observation.state is SelectionRowConfirmationState.CONFIRMED:
                pending[index] += 1
                if pending[index] >= self.confirmation_count:
                    locked.add(observation.selection_row)
                    pending[index] = 0
            else:
                pending[index] = 0
        return SelectionRowConfirmationTracker(
            confirmation_count=self.confirmation_count,
            pending_positive_counts=(pending[0], pending[1], pending[2], pending[3]),
            locked_confirmed_rows=frozenset(locked),
        )

    def is_confirmed(self, selection_row: int) -> bool:
        """Return the sticky visual confirmation result for one selection row."""

        if selection_row not in _ROWS:
            raise ValueError("selection confirmation row must be between 1 and 4")
        return selection_row in self.locked_confirmed_rows


def selection_confirmation_roi(
    render_context: SelectionConfirmationRenderContext,
    selection_row: int,
) -> PixelRoi:
    """Return one context-specific confirmation ROI for a row in the known layout."""

    if selection_row not in _ROWS:
        raise ValueError("selection confirmation row must be between 1 and 4")
    x = (
        _GRID_X
        if render_context is SelectionConfirmationRenderContext.SELECTION_GRID
        else _DETAIL_X
    )
    return PixelRoi(
        x=x,
        y=_ROW_FIRST_Y + _ROW_STEP_Y * (selection_row - 1),
        width=_CUE_WIDTH,
        height=_CUE_HEIGHT,
    )


def observe_jp_mumu_selection_row_confirmations(
    frame: Frame,
    viewport: ContentViewport,
    render_context: SelectionConfirmationRenderContext,
) -> tuple[SelectionRowConfirmationObservation, ...]:
    """Observe all four row-local markers under one explicit render context.

    Frames outside the existing reliable selection-screen boundary, or outside
    the full JP MuMu baseline, yield four ``UNRESOLVED`` observations.
    """

    screen = observe_jp_mumu_selection_screen(frame, viewport)
    if screen.state is not SelectionScreenState.SELECTION:
        return tuple(
            _unresolved_observation(frame, render_context, selection_row)
            for selection_row in _ROWS
        )
    return tuple(
        _observe_row(frame, render_context, selection_row) for selection_row in _ROWS
    )


def _observe_row(
    frame: Frame,
    render_context: SelectionConfirmationRenderContext,
    selection_row: int,
) -> SelectionRowConfirmationObservation:
    roi = selection_confirmation_roi(render_context, selection_row)
    crop = frame.image[roi.y : roi.bottom, roi.x : roi.right]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    cyan_mask = (
        (hsv[:, :, 0] >= 70)
        & (hsv[:, :, 0] <= 100)
        & (hsv[:, :, 1] >= 90)
        & (hsv[:, :, 2] >= 100)
    ).astype(np.uint8)
    cyan_count = int(np.count_nonzero(cyan_mask))
    return SelectionRowConfirmationObservation(
        selection_row=selection_row,
        state=(
            SelectionRowConfirmationState.CONFIRMED
            if (
                cyan_count >= JP_MUMU_SELECTION_CONFIRMATION_THRESHOLD
                and _has_check_like_marker(cyan_mask)
            )
            else SelectionRowConfirmationState.NOT_CONFIRMED
        ),
        cyan_pixel_count=cyan_count,
        pixel_bounds=roi,
        render_context=render_context,
        frame_id=frame.frame_id,
        frame_index=frame.frame_index,
        processed_at=frame.processed_at,
        source_timestamp=frame.source_timestamp,
        source_type=frame.source_type,
        source_id=frame.source_id,
        source_reference=frame.source_reference,
    )


def _has_check_like_marker(cyan_mask: np.ndarray) -> bool:
    """Return whether one compact, interior cyan component looks like a check frame.

    The quantity gate alone also accepts the large, edge-spanning cyan band
    used by the active-row selection animation. A real marker has a compact
    square outer component with substantial dark interior; its relative shape
    is shared by the grid and detail confirmation ROIs.
    """

    component_count, _, stats, _ = cv2.connectedComponentsWithStats(
        cyan_mask,
        connectivity=8,
    )
    height, width = cyan_mask.shape
    for index in range(1, component_count):
        x, y, component_width, component_height, area = stats[index]
        if (
            x == 0
            or y == 0
            or x + component_width == width
            or y + component_height == height
        ):
            continue
        if not (
            _MARKER_MIN_SIZE <= component_width <= _MARKER_MAX_SIZE
            and _MARKER_MIN_SIZE <= component_height <= _MARKER_MAX_SIZE
        ):
            continue
        fill_ratio = area / (component_width * component_height)
        if _MARKER_MIN_FILL_RATIO <= fill_ratio <= _MARKER_MAX_FILL_RATIO:
            return True
    return False


def _unresolved_observation(
    frame: Frame,
    render_context: SelectionConfirmationRenderContext,
    selection_row: int,
) -> SelectionRowConfirmationObservation:
    return SelectionRowConfirmationObservation(
        selection_row=selection_row,
        state=SelectionRowConfirmationState.UNRESOLVED,
        cyan_pixel_count=None,
        pixel_bounds=selection_confirmation_roi(render_context, selection_row),
        render_context=render_context,
        frame_id=frame.frame_id,
        frame_index=frame.frame_index,
        processed_at=frame.processed_at,
        source_timestamp=frame.source_timestamp,
        source_type=frame.source_type,
        source_id=frame.source_id,
        source_reference=frame.source_reference,
    )


def _validate_complete_rows(
    observations: tuple[SelectionRowConfirmationObservation, ...],
) -> None:
    rows = tuple(item.selection_row for item in observations)
    if len(observations) != len(_ROWS) or set(rows) != set(_ROWS):
        raise ValueError(
            "selection confirmation tracker requires exactly one observation for rows 1..4"
        )
