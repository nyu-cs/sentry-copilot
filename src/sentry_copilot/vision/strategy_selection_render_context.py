"""Fixed-layout render-context evidence for JP MuMu strategy selection.

This recognizer is deliberately independent from confirmation-marker geometry,
strategy identity, and session lifecycle state.  It only distinguishes the
known full-screen selection grid from its right-side strategy-detail render.
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

JP_MUMU_SELECTION_RENDER_CONTEXT_PROFILE_ID = "jp_mumu_fullscreen_1920x1080.render_context.v1"
"""Calibration profile for the explicit JP MuMu 1920x1080 fullscreen layout."""

JP_MUMU_SELECTION_DETAIL_BRIGHT_FRACTION_CUTOFF = 0.05
"""Verified diagnostic cutoff for the fixed right-side detail-layout cue."""

_DETAIL_CUE_ROI = PixelRoi(x=1550, y=550, width=120, height=180)
_BRIGHT_GRAY_THRESHOLD = 180


class SelectionRenderContextState(StrEnum):
    """Visible selection render context, without lifecycle interpretation."""

    SELECTION_GRID = "selection_grid"
    STRATEGY_DETAIL = "strategy_detail"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class SelectionRenderContextObservation:
    """Immutable context evidence with copied frame/source provenance."""

    state: SelectionRenderContextState
    bright_pixel_fraction: float | None
    pixel_bounds: PixelRoi
    frame_id: str
    frame_index: int
    processed_at: datetime
    source_timestamp: timedelta | None
    source_type: FrameSourceType
    source_id: str
    source_reference: str

    def __post_init__(self) -> None:
        if not (
            self.frame_id.strip()
            and self.source_id.strip()
            and self.source_reference.strip()
        ):
            raise ValueError("selection render-context provenance text fields must not be blank")
        if self.frame_index < 0:
            raise ValueError("selection render-context frame index must be non-negative")
        if self.processed_at.tzinfo is None or self.processed_at.utcoffset() is None:
            raise ValueError("selection render-context processing time must be timezone-aware")
        if self.source_timestamp is not None and self.source_timestamp.total_seconds() < 0:
            raise ValueError("selection render-context source timestamp must be non-negative")
        if self.state is SelectionRenderContextState.UNRESOLVED:
            if self.bright_pixel_fraction is not None:
                raise ValueError(
                    "unresolved selection render context must not report a bright fraction"
                )
        elif (
            self.bright_pixel_fraction is None
            or not 0.0 <= self.bright_pixel_fraction <= 1.0
        ):
            raise ValueError(
                "resolved selection render context requires a bright fraction from zero to one"
            )


def selection_render_context_roi() -> PixelRoi:
    """Return the one fixed detail-layout cue ROI for the verified baseline."""

    return _DETAIL_CUE_ROI


def observe_jp_mumu_selection_render_context(
    frame: Frame,
    viewport: ContentViewport,
) -> SelectionRenderContextObservation:
    """Classify one known selection frame, otherwise return ``UNRESOLVED``.

    The existing selection-screen observer is the mandatory boundary: any
    wrong layout, viewport, information page, or other non-selection frame is
    deliberately not interpreted as either render context.
    """

    screen = observe_jp_mumu_selection_screen(frame, viewport)
    if screen.state is not SelectionScreenState.SELECTION:
        return _unresolved(frame)

    crop = frame.image[
        _DETAIL_CUE_ROI.y : _DETAIL_CUE_ROI.bottom,
        _DETAIL_CUE_ROI.x : _DETAIL_CUE_ROI.right,
    ]
    grayscale = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    fraction = float(np.mean(grayscale >= _BRIGHT_GRAY_THRESHOLD))
    return SelectionRenderContextObservation(
        state=(
            SelectionRenderContextState.STRATEGY_DETAIL
            if fraction >= JP_MUMU_SELECTION_DETAIL_BRIGHT_FRACTION_CUTOFF
            else SelectionRenderContextState.SELECTION_GRID
        ),
        bright_pixel_fraction=fraction,
        pixel_bounds=_DETAIL_CUE_ROI,
        frame_id=frame.frame_id,
        frame_index=frame.frame_index,
        processed_at=frame.processed_at,
        source_timestamp=frame.source_timestamp,
        source_type=frame.source_type,
        source_id=frame.source_id,
        source_reference=frame.source_reference,
    )


def _unresolved(frame: Frame) -> SelectionRenderContextObservation:
    return SelectionRenderContextObservation(
        state=SelectionRenderContextState.UNRESOLVED,
        bright_pixel_fraction=None,
        pixel_bounds=_DETAIL_CUE_ROI,
        frame_id=frame.frame_id,
        frame_index=frame.frame_index,
        processed_at=frame.processed_at,
        source_timestamp=frame.source_timestamp,
        source_type=frame.source_type,
        source_id=frame.source_id,
        source_reference=frame.source_reference,
    )
