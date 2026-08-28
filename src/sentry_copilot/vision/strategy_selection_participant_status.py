"""Fixed-layout participant status and completion presentation evidence.

The module is deliberately visual-only.  It recognizes the bounded JP MuMu
selection-row presentation, never a participant identity, strategy identity,
or an exit cause.  The caller supplies current render-context evidence from
the same frame.
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
from sentry_copilot.vision.strategy_selection_render_context import (
    SelectionRenderContextObservation,
    SelectionRenderContextState,
)
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi

JP_MUMU_SELECTION_PARTICIPANT_STATUS_PROFILE_ID = (
    "jp_mumu_fullscreen_1920x1080.participant_status.v1"
)
"""Calibration profile for the explicitly supported full-screen JP MuMu layout."""

_ROWS = (1, 2, 3, 4)
_ROW_FIRST_Y = 324
_ROW_STEP_Y = 154
_STATUS_WIDTH = 62
_STATUS_HEIGHT = 70
_GRID_STATUS_X = 164
_DETAIL_STATUS_X = 66
_WHITE_MAX_SATURATION = 70
_WHITE_MIN_GRAYSCALE = 100
_DARK_MAX_GRAYSCALE = 80
_STATUS_MIN_DARK_FRACTION = 0.30
_STATUS_MIN_WHITE_FRACTION = 0.15
_STATUS_MAX_WHITE_FRACTION = 0.35
_NETWORK_MAX_BOTTOM_RIGHT_WHITE_OCCUPANCY = 0.282949
_EXIT_MIN_BOTTOM_RIGHT_WHITE_OCCUPANCY = 0.329032

_GRID_COMPLETION_X = 617
_DETAIL_COMPLETION_X = 320
_COMPLETION_ROW_FIRST_Y = 338
_COMPLETION_WIDTH = 110
_COMPLETION_HEIGHT = 70
_ELLIPSIS_GRAY_MIN = 140
_ELLIPSIS_GRAY_MAX = 190
_ELLIPSIS_MIN_AREA = 60
_ELLIPSIS_MAX_AREA = 82
_ELLIPSIS_MIN_WIDTH = 8
_ELLIPSIS_MAX_WIDTH = 11
_ELLIPSIS_MIN_HEIGHT = 8
_ELLIPSIS_MAX_HEIGHT = 12
_ELLIPSIS_MIN_FILL_RATIO = 0.65
_ELLIPSIS_MAX_FILL_RATIO = 0.92
_ELLIPSIS_MIN_X_SPACING = 18.0
_ELLIPSIS_MAX_X_SPACING = 22.0
_ELLIPSIS_MAX_CENTER_Y_SPREAD = 1.0
_ELLIPSIS_MAX_WIDTH_SPREAD = 2
_ELLIPSIS_MAX_HEIGHT_SPREAD = 3
_ELLIPSIS_MAX_AREA_SPREAD = 15
_ELLIPSIS_MIN_GROUP_X = 28
_ELLIPSIS_MAX_GROUP_X = 46
_ELLIPSIS_MIN_GROUP_Y = 20
_ELLIPSIS_MAX_GROUP_Y = 28
_ELLIPSIS_MIN_GROUP_WIDTH = 45
_ELLIPSIS_MAX_GROUP_WIDTH = 58
_ELLIPSIS_MIN_GROUP_HEIGHT = 8
_ELLIPSIS_MAX_GROUP_HEIGHT = 13
_PORTRAIT_MIN_GRAYSCALE_STANDARD_DEVIATION = 25.0
_PORTRAIT_MIN_SATURATED_PIXEL_FRACTION = 0.70


class SelectionParticipantStatusState(StrEnum):
    """One row's current visual participant-status presentation."""

    NO_STATUS_OVERLAY = "no_status_overlay"
    NETWORK_WARNING = "network_warning"
    EXIT = "exit"
    UNRESOLVED = "unresolved"


class SelectionCompletionPresentationState(StrEnum):
    """Explicit final-row completion presentation, independent from matching."""

    STRATEGY_PORTRAIT_PRESENT = "strategy_portrait_present"
    ELLIPSIS_PLACEHOLDER = "ellipsis_placeholder"
    UNRESOLVED = "unresolved"


class SelectionExitCompletionState(StrEnum):
    """Sticky visual completion result once a row has reliably exited."""

    NOT_EXITED = "not_exited"
    EXIT_COMPLETION_UNRESOLVED = "exit_completion_unresolved"
    EXITED_UNCONFIRMED = "exited_unconfirmed"
    CONFIRMED_THEN_EXITED = "confirmed_then_exited"


@dataclass(frozen=True)
class _EllipsisComponent:
    """One narrow grayscale foreground component inside an audited row box."""

    x: int
    y: int
    width: int
    height: int
    area: int
    centroid_x: float
    centroid_y: float

    @property
    def fill_ratio(self) -> float:
        return self.area / (self.width * self.height)


@dataclass(frozen=True)
class SelectionParticipantStatusObservation:
    """Immutable fixed-layout row-status evidence with copied frame provenance."""

    selection_row: int
    state: SelectionParticipantStatusState
    pixel_bounds: PixelRoi
    render_context: SelectionRenderContextState
    dark_fraction: float | None
    low_saturation_white_fraction: float | None
    bottom_right_white_occupancy: float | None
    frame_id: str
    frame_index: int
    processed_at: datetime
    source_timestamp: timedelta | None
    source_type: FrameSourceType
    source_id: str
    source_reference: str

    def __post_init__(self) -> None:
        _validate_provenance(
            self.frame_id,
            self.frame_index,
            self.processed_at,
            self.source_timestamp,
            self.source_id,
            self.source_reference,
        )
        if self.selection_row not in _ROWS:
            raise ValueError("selection participant status row must be between 1 and 4")
        values = (
            self.dark_fraction,
            self.low_saturation_white_fraction,
            self.bottom_right_white_occupancy,
        )
        if self.state is SelectionParticipantStatusState.UNRESOLVED:
            if any(value is not None for value in values):
                raise ValueError("unresolved participant status must not report metrics")
        elif any(value is None or not 0.0 <= value <= 1.0 for value in values):
            raise ValueError("resolved participant status requires bounded metrics")


@dataclass(frozen=True)
class SelectionCompletionPresentationObservation:
    """Explicit strategy-slot presentation evidence for one row and frame."""

    selection_row: int
    state: SelectionCompletionPresentationState
    pixel_bounds: PixelRoi
    grayscale_standard_deviation: float | None
    ellipsis_component_count: int | None
    frame_id: str
    frame_index: int
    processed_at: datetime
    source_timestamp: timedelta | None
    source_type: FrameSourceType
    source_id: str
    source_reference: str

    def __post_init__(self) -> None:
        _validate_provenance(
            self.frame_id,
            self.frame_index,
            self.processed_at,
            self.source_timestamp,
            self.source_id,
            self.source_reference,
        )
        if self.selection_row not in _ROWS:
            raise ValueError("selection completion row must be between 1 and 4")
        if self.state is SelectionCompletionPresentationState.UNRESOLVED:
            if (
                self.grayscale_standard_deviation is not None
                or self.ellipsis_component_count is not None
            ):
                raise ValueError("unresolved completion presentation must not report metrics")
        elif (
            self.grayscale_standard_deviation is None
            or self.grayscale_standard_deviation < 0.0
            or self.ellipsis_component_count is None
            or self.ellipsis_component_count < 0
        ):
            raise ValueError("resolved completion presentation requires non-negative metrics")


@dataclass(frozen=True)
class SelectionRowExitTracker:
    """Immutable two-observation, sticky EXIT tracker for one selection session."""

    confirmation_count: int = 2
    pending_exit_counts: tuple[int, int, int, int] = (0, 0, 0, 0)
    locked_exit_rows: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        if self.confirmation_count < 2:
            raise ValueError("selection EXIT confirmation_count must be at least 2")
        if any(value < 0 for value in self.pending_exit_counts):
            raise ValueError("selection EXIT pending counts must be non-negative")
        if not self.locked_exit_rows.issubset(_ROWS):
            raise ValueError("locked selection EXIT rows must be between 1 and 4")

    def apply(
        self,
        observations: tuple[SelectionParticipantStatusObservation, ...],
    ) -> SelectionRowExitTracker:
        """Apply one complete frame without allowing non-EXIT states to restore a lock."""

        _validate_complete_rows(observations, "selection EXIT tracker")
        pending = list(self.pending_exit_counts)
        locked = set(self.locked_exit_rows)
        for observation in observations:
            index = observation.selection_row - 1
            if observation.selection_row in locked:
                pending[index] = 0
            elif observation.state is SelectionParticipantStatusState.EXIT:
                pending[index] += 1
                if pending[index] >= self.confirmation_count:
                    locked.add(observation.selection_row)
                    pending[index] = 0
            else:
                pending[index] = 0
        return SelectionRowExitTracker(
            confirmation_count=self.confirmation_count,
            pending_exit_counts=(pending[0], pending[1], pending[2], pending[3]),
            locked_exit_rows=frozenset(locked),
        )

    def is_exited(self, selection_row: int) -> bool:
        if selection_row not in _ROWS:
            raise ValueError("selection EXIT row must be between 1 and 4")
        return selection_row in self.locked_exit_rows


@dataclass(frozen=True)
class SelectionExitCompletionTracker:
    """Sticky completion semantics after EXIT, without creating strategy identity evidence."""

    states: tuple[SelectionExitCompletionState, ...] = (
        SelectionExitCompletionState.NOT_EXITED,
        SelectionExitCompletionState.NOT_EXITED,
        SelectionExitCompletionState.NOT_EXITED,
        SelectionExitCompletionState.NOT_EXITED,
    )

    def __post_init__(self) -> None:
        if len(self.states) != len(_ROWS):
            raise ValueError("selection exit completion tracker requires four row states")

    def apply(
        self,
        exit_tracker: SelectionRowExitTracker,
        completion_observations: tuple[SelectionCompletionPresentationObservation, ...],
        confirmation_rows: frozenset[int],
    ) -> SelectionExitCompletionTracker:
        """Derive sticky completion facts only from same-frame explicit presentation/history."""

        _validate_complete_rows(completion_observations, "selection completion tracker")
        if not confirmation_rows.issubset(_ROWS):
            raise ValueError("selection completion confirmation rows must be between 1 and 4")
        by_row = {item.selection_row: item for item in completion_observations}
        updated = list(self.states)
        for row in _ROWS:
            prior = self.states[row - 1]
            if prior in {
                SelectionExitCompletionState.EXITED_UNCONFIRMED,
                SelectionExitCompletionState.CONFIRMED_THEN_EXITED,
            }:
                continue
            if not exit_tracker.is_exited(row):
                continue
            completion = by_row[row].state
            if row in confirmation_rows:
                updated[row - 1] = SelectionExitCompletionState.CONFIRMED_THEN_EXITED
            elif completion is SelectionCompletionPresentationState.ELLIPSIS_PLACEHOLDER:
                updated[row - 1] = SelectionExitCompletionState.EXITED_UNCONFIRMED
            elif completion is SelectionCompletionPresentationState.STRATEGY_PORTRAIT_PRESENT:
                # A retained strategy portrait is direct post-exit evidence of completion;
                # a same-frame cyan check can strengthen it but is not required.
                updated[row - 1] = SelectionExitCompletionState.CONFIRMED_THEN_EXITED
            else:
                updated[row - 1] = SelectionExitCompletionState.EXIT_COMPLETION_UNRESOLVED
        return SelectionExitCompletionTracker(states=tuple(updated))

    def state_for(self, selection_row: int) -> SelectionExitCompletionState:
        if selection_row not in _ROWS:
            raise ValueError("selection completion row must be between 1 and 4")
        return self.states[selection_row - 1]

    @property
    def exited_unconfirmed_rows(self) -> frozenset[int]:
        return frozenset(
            row
            for row in _ROWS
            if self.state_for(row) is SelectionExitCompletionState.EXITED_UNCONFIRMED
        )


def selection_participant_status_roi(
    render_context: SelectionRenderContextState,
    selection_row: int,
) -> PixelRoi:
    """Return the audited tight status-pictogram ROI for one supported row/context."""

    if selection_row not in _ROWS:
        raise ValueError("selection participant status row must be between 1 and 4")
    if render_context is SelectionRenderContextState.UNRESOLVED:
        raise ValueError("unresolved render context has no participant-status ROI")
    return PixelRoi(
        x=(
            _GRID_STATUS_X
            if render_context is SelectionRenderContextState.SELECTION_GRID
            else _DETAIL_STATUS_X
        ),
        y=_ROW_FIRST_Y + _ROW_STEP_Y * (selection_row - 1),
        width=_STATUS_WIDTH,
        height=_STATUS_HEIGHT,
    )


def selection_completion_presentation_roi(
    render_context: SelectionRenderContextState,
    selection_row: int,
) -> PixelRoi:
    """Return the audited row-local completion box for one reliable render context."""

    if selection_row not in _ROWS:
        raise ValueError("selection completion row must be between 1 and 4")
    if render_context is SelectionRenderContextState.UNRESOLVED:
        raise ValueError("unresolved render context has no completion-presentation ROI")
    return PixelRoi(
        x=(
            _GRID_COMPLETION_X
            if render_context is SelectionRenderContextState.SELECTION_GRID
            else _DETAIL_COMPLETION_X
        ),
        y=_COMPLETION_ROW_FIRST_Y + _ROW_STEP_Y * (selection_row - 1),
        width=_COMPLETION_WIDTH,
        height=_COMPLETION_HEIGHT,
    )


def observe_jp_mumu_selection_participant_statuses(
    frame: Frame,
    viewport: ContentViewport,
    render_context: SelectionRenderContextObservation,
) -> tuple[SelectionParticipantStatusObservation, ...]:
    """Observe four status presentations only when same-frame selection context is reliable."""

    if not _matches_frame(render_context, frame):
        raise ValueError("selection render-context observation must belong to the supplied frame")
    screen = observe_jp_mumu_selection_screen(frame, viewport)
    if (
        screen.state is not SelectionScreenState.SELECTION
        or render_context.state is SelectionRenderContextState.UNRESOLVED
    ):
        return tuple(_unresolved_status(frame, render_context.state, row) for row in _ROWS)
    return tuple(_observe_status(frame, render_context.state, row) for row in _ROWS)


def observe_jp_mumu_selection_completion_presentations(
    frame: Frame,
    viewport: ContentViewport,
    render_context: SelectionRenderContextObservation,
) -> tuple[SelectionCompletionPresentationObservation, ...]:
    """Observe explicit ellipsis versus retained strategy-image presentation for four rows."""

    if not _matches_frame(render_context, frame):
        raise ValueError("selection render-context observation must belong to the supplied frame")
    screen = observe_jp_mumu_selection_screen(frame, viewport)
    if (
        screen.state is not SelectionScreenState.SELECTION
        or render_context.state is SelectionRenderContextState.UNRESOLVED
    ):
        return tuple(_unresolved_completion(frame, row) for row in _ROWS)
    return tuple(_observe_completion(frame, render_context.state, row) for row in _ROWS)


def _observe_status(
    frame: Frame,
    render_context: SelectionRenderContextState,
    selection_row: int,
) -> SelectionParticipantStatusObservation:
    roi = selection_participant_status_roi(render_context, selection_row)
    image = frame.image[roi.y : roi.bottom, roi.x : roi.right]
    grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    white_mask = (hsv[:, :, 1] <= _WHITE_MAX_SATURATION) & (grayscale >= _WHITE_MIN_GRAYSCALE)
    dark_fraction = float(np.mean(grayscale < _DARK_MAX_GRAYSCALE))
    white_fraction = float(np.mean(white_mask))
    bottom_right_mask = white_mask[
        white_mask.shape[0] // 2 :, white_mask.shape[1] // 2 :
    ]
    bottom_right = float(np.mean(bottom_right_mask))
    if not (
        dark_fraction >= _STATUS_MIN_DARK_FRACTION
        and _STATUS_MIN_WHITE_FRACTION <= white_fraction <= _STATUS_MAX_WHITE_FRACTION
    ):
        state = SelectionParticipantStatusState.NO_STATUS_OVERLAY
    elif bottom_right <= _NETWORK_MAX_BOTTOM_RIGHT_WHITE_OCCUPANCY:
        state = SelectionParticipantStatusState.NETWORK_WARNING
    elif bottom_right >= _EXIT_MIN_BOTTOM_RIGHT_WHITE_OCCUPANCY:
        state = SelectionParticipantStatusState.EXIT
    else:
        state = SelectionParticipantStatusState.UNRESOLVED
    return SelectionParticipantStatusObservation(
        selection_row=selection_row,
        state=state,
        pixel_bounds=roi,
        render_context=render_context,
        dark_fraction=(
            dark_fraction if state is not SelectionParticipantStatusState.UNRESOLVED else None
        ),
        low_saturation_white_fraction=(
            white_fraction if state is not SelectionParticipantStatusState.UNRESOLVED else None
        ),
        bottom_right_white_occupancy=(
            bottom_right if state is not SelectionParticipantStatusState.UNRESOLVED else None
        ),
        frame_id=frame.frame_id,
        frame_index=frame.frame_index,
        processed_at=frame.processed_at,
        source_timestamp=frame.source_timestamp,
        source_type=frame.source_type,
        source_id=frame.source_id,
        source_reference=frame.source_reference,
    )


def _observe_completion(
    frame: Frame,
    render_context: SelectionRenderContextState,
    selection_row: int,
) -> SelectionCompletionPresentationObservation:
    roi = selection_completion_presentation_roi(render_context, selection_row)
    image = frame.image[roi.y : roi.bottom, roi.x : roi.right]
    grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    components = _ellipsis_component_count(grayscale)
    standard_deviation = float(np.std(grayscale))
    if components == 3:
        state = SelectionCompletionPresentationState.ELLIPSIS_PLACEHOLDER
    elif _has_retained_strategy_portrait(image, standard_deviation):
        state = SelectionCompletionPresentationState.STRATEGY_PORTRAIT_PRESENT
    else:
        state = SelectionCompletionPresentationState.UNRESOLVED
    return SelectionCompletionPresentationObservation(
        selection_row=selection_row,
        state=state,
        pixel_bounds=roi,
        grayscale_standard_deviation=(
            standard_deviation
            if state is not SelectionCompletionPresentationState.UNRESOLVED
            else None
        ),
        ellipsis_component_count=(
            components if state is not SelectionCompletionPresentationState.UNRESOLVED else None
        ),
        frame_id=frame.frame_id,
        frame_index=frame.frame_index,
        processed_at=frame.processed_at,
        source_timestamp=frame.source_timestamp,
        source_type=frame.source_type,
        source_id=frame.source_id,
        source_reference=frame.source_reference,
    )


def _has_retained_strategy_portrait(image: np.ndarray, standard_deviation: float) -> bool:
    """Require the audited textured and color-rich cue for a retained strategy image."""

    if standard_deviation < _PORTRAIT_MIN_GRAYSCALE_STANDARD_DEVIATION:
        return False
    saturation = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)[:, :, 1]
    return float(np.mean(saturation >= 40)) >= _PORTRAIT_MIN_SATURATED_PIXEL_FRACTION


def _ellipsis_component_count(grayscale: np.ndarray) -> int:
    """Return three only for one complete, audited three-dot foreground group."""

    components = _ellipsis_components(grayscale)
    return 3 if _is_strict_ellipsis_group(components) else 0


def _ellipsis_components(grayscale: np.ndarray) -> tuple[_EllipsisComponent, ...]:
    mask = ((grayscale >= _ELLIPSIS_GRAY_MIN) & (grayscale <= _ELLIPSIS_GRAY_MAX)).astype(np.uint8)
    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    components: list[_EllipsisComponent] = []
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if not (
            _ELLIPSIS_MIN_AREA <= area <= _ELLIPSIS_MAX_AREA
            and _ELLIPSIS_MIN_WIDTH <= width <= _ELLIPSIS_MAX_WIDTH
            and _ELLIPSIS_MIN_HEIGHT <= height <= _ELLIPSIS_MAX_HEIGHT
        ):
            continue
        centroid_x, centroid_y = centroids[index]
        component = _EllipsisComponent(
            x=int(x),
            y=int(y),
            width=int(width),
            height=int(height),
            area=int(area),
            centroid_x=float(centroid_x),
            centroid_y=float(centroid_y),
        )
        if _ELLIPSIS_MIN_FILL_RATIO <= component.fill_ratio <= _ELLIPSIS_MAX_FILL_RATIO:
            components.append(component)
    return tuple(components)


def _is_strict_ellipsis_group(components: tuple[_EllipsisComponent, ...]) -> bool:
    if len(components) != 3:
        return False
    dots = tuple(sorted(components, key=lambda item: item.centroid_x))
    x_spacings = (
        dots[1].centroid_x - dots[0].centroid_x,
        dots[2].centroid_x - dots[1].centroid_x,
    )
    y_values = tuple(item.centroid_y for item in dots)
    widths = tuple(item.width for item in dots)
    heights = tuple(item.height for item in dots)
    areas = tuple(item.area for item in dots)
    group_left = min(item.x for item in dots)
    group_top = min(item.y for item in dots)
    group_right = max(item.x + item.width for item in dots)
    group_bottom = max(item.y + item.height for item in dots)
    return (
        all(_ELLIPSIS_MIN_X_SPACING <= item <= _ELLIPSIS_MAX_X_SPACING for item in x_spacings)
        and max(y_values) - min(y_values) <= _ELLIPSIS_MAX_CENTER_Y_SPREAD
        and max(widths) - min(widths) <= _ELLIPSIS_MAX_WIDTH_SPREAD
        and max(heights) - min(heights) <= _ELLIPSIS_MAX_HEIGHT_SPREAD
        and max(areas) - min(areas) <= _ELLIPSIS_MAX_AREA_SPREAD
        and _ELLIPSIS_MIN_GROUP_X <= group_left <= _ELLIPSIS_MAX_GROUP_X
        and _ELLIPSIS_MIN_GROUP_Y <= group_top <= _ELLIPSIS_MAX_GROUP_Y
        and _ELLIPSIS_MIN_GROUP_WIDTH <= group_right - group_left <= _ELLIPSIS_MAX_GROUP_WIDTH
        and _ELLIPSIS_MIN_GROUP_HEIGHT <= group_bottom - group_top <= _ELLIPSIS_MAX_GROUP_HEIGHT
    )


def _unresolved_status(
    frame: Frame,
    render_context: SelectionRenderContextState,
    selection_row: int,
) -> SelectionParticipantStatusObservation:
    bounds = (
        selection_participant_status_roi(render_context, selection_row)
        if render_context is not SelectionRenderContextState.UNRESOLVED
        else PixelRoi(x=0, y=0, width=_STATUS_WIDTH, height=_STATUS_HEIGHT)
    )
    return SelectionParticipantStatusObservation(
        selection_row=selection_row,
        state=SelectionParticipantStatusState.UNRESOLVED,
        pixel_bounds=bounds,
        render_context=render_context,
        dark_fraction=None,
        low_saturation_white_fraction=None,
        bottom_right_white_occupancy=None,
        frame_id=frame.frame_id,
        frame_index=frame.frame_index,
        processed_at=frame.processed_at,
        source_timestamp=frame.source_timestamp,
        source_type=frame.source_type,
        source_id=frame.source_id,
        source_reference=frame.source_reference,
    )


def _unresolved_completion(
    frame: Frame,
    selection_row: int,
) -> SelectionCompletionPresentationObservation:
    return SelectionCompletionPresentationObservation(
        selection_row=selection_row,
        state=SelectionCompletionPresentationState.UNRESOLVED,
        pixel_bounds=PixelRoi(x=0, y=0, width=_COMPLETION_WIDTH, height=_COMPLETION_HEIGHT),
        grayscale_standard_deviation=None,
        ellipsis_component_count=None,
        frame_id=frame.frame_id,
        frame_index=frame.frame_index,
        processed_at=frame.processed_at,
        source_timestamp=frame.source_timestamp,
        source_type=frame.source_type,
        source_id=frame.source_id,
        source_reference=frame.source_reference,
    )


def _matches_frame(observation: SelectionRenderContextObservation, frame: Frame) -> bool:
    return (
        observation.frame_id == frame.frame_id
        and observation.frame_index == frame.frame_index
        and observation.source_id == frame.source_id
        and observation.source_reference == frame.source_reference
    )


def _validate_complete_rows(
    observations: tuple[SelectionParticipantStatusObservation, ...]
    | tuple[SelectionCompletionPresentationObservation, ...],
    owner: str,
) -> None:
    rows = tuple(item.selection_row for item in observations)
    if len(observations) != len(_ROWS) or set(rows) != set(_ROWS):
        raise ValueError(f"{owner} requires exactly one observation for rows 1..4")


def _validate_provenance(
    frame_id: str,
    frame_index: int,
    processed_at: datetime,
    source_timestamp: timedelta | None,
    source_id: str,
    source_reference: str,
) -> None:
    if not (frame_id.strip() and source_id.strip() and source_reference.strip()):
        raise ValueError(
            "selection participant presentation provenance text fields must not be blank"
        )
    if frame_index < 0:
        raise ValueError("selection participant presentation frame index must be non-negative")
    if processed_at.tzinfo is None or processed_at.utcoffset() is None:
        raise ValueError(
            "selection participant presentation processing time must be timezone-aware"
        )
    if source_timestamp is not None and source_timestamp.total_seconds() < 0:
        raise ValueError("selection participant presentation source timestamp must be non-negative")
