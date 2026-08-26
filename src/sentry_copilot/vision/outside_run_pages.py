"""Fixed-layout JP MuMu observations for pages that are outside an active run.

This module intentionally provides visual evidence only.  It does not alter a
selection lifecycle, infer why a run ended, identify players, or inspect any
dynamic player/card content.  The cues are calibrated only for a full 1920x1080
JP MuMu content viewport.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

import cv2
import numpy as np

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi


class OutsideRunPageKind(StrEnum):
    """Fixed-layout pages that positively place the user outside an old run."""

    MAIN_LOBBY = "main_lobby"
    PARTY_ROOM = "party_room"
    PARTY_ROOM_MATCHING_OVERLAY = "party_room_matching_overlay"
    SOLO_MATCHMAKING_PAGE = "solo_matchmaking_page"
    SUCCESS_RESULT = "success_result"
    POST_CLEAR_REMATCH = "post_clear_rematch"
    MATCH_SUCCESS_TRANSITION = "match_success_transition"


class OutsideRunPageState(StrEnum):
    """Conservative visual presence state for one independently observed page."""

    PRESENT = "present"
    ABSENT = "absent"
    UNRESOLVED = "unresolved"


class OutsideRunPageObservationMethod(StrEnum):
    """How an outside-run page observation was produced."""

    FIXED_LAYOUT_PIXEL_CUES = "fixed_layout_pixel_cues"
    UNRESOLVED_LAYOUT = "unresolved_layout"


@dataclass(frozen=True)
class OutsideRunPageMetric:
    """One named non-identity pixel count retained for calibration/debugging."""

    name: str
    value: int

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("outside-run page metric name must not be blank")
        if self.value < 0:
            raise ValueError("outside-run page metric value must be non-negative")


@dataclass(frozen=True)
class OutsideRunPageObservation:
    """Immutable source-neutral visual evidence for one page kind."""

    page_kind: OutsideRunPageKind
    state: OutsideRunPageState
    method: OutsideRunPageObservationMethod
    frame_id: str
    frame_index: int
    processed_at: datetime
    source_timestamp: timedelta | None
    source_type: FrameSourceType
    source_id: str
    source_reference: str
    metrics: tuple[OutsideRunPageMetric, ...]

    def __post_init__(self) -> None:
        if (
            not self.frame_id.strip()
            or not self.source_id.strip()
            or not self.source_reference.strip()
        ):
            raise ValueError("outside-run page observation provenance must not be blank")
        if self.frame_index < 0:
            raise ValueError("outside-run page frame index must be non-negative")
        if self.processed_at.tzinfo is None or self.processed_at.utcoffset() is None:
            raise ValueError("outside-run page processing time must be timezone-aware")
        if self.source_timestamp is not None and self.source_timestamp.total_seconds() < 0:
            raise ValueError("outside-run page source timestamp must be non-negative")
        if self.state is OutsideRunPageState.UNRESOLVED:
            if self.method is not OutsideRunPageObservationMethod.UNRESOLVED_LAYOUT:
                raise ValueError("unresolved outside-run page requires unresolved-layout method")
            if self.metrics:
                raise ValueError("unresolved outside-run page must not report layout metrics")
        elif self.method is not OutsideRunPageObservationMethod.FIXED_LAYOUT_PIXEL_CUES:
            raise ValueError("resolved outside-run page requires fixed-layout pixel cues")


JP_MUMU_OUTSIDE_RUN_PAGES_PROFILE_ID = "jp_mumu_fullscreen_1920x1080.outside_run_pages.v1"
"""Calibration profile for the explicit full-frame JP MuMu baseline only."""

_JP_MUMU_VIEWPORT = PixelRoi(x=0, y=0, width=1920, height=1080)

_MAIN_LOBBY_ACTIONS_ROI = PixelRoi(x=1450, y=400, width=440, height=400)
_PARTY_ROOM_COPY_BUTTON_ROI = PixelRoi(x=1700, y=35, width=180, height=55)
_PARTY_ROOM_HEADER_CHROME_ROI = PixelRoi(x=140, y=145, width=800, height=45)
_MATCHING_WIREFRAME_ROI = PixelRoi(x=100, y=170, width=1050, height=710)
_MATCHING_FACE_ROI = PixelRoi(x=1370, y=480, width=330, height=260)
_MATCHING_TEXT_ROI = PixelRoi(x=1230, y=250, width=600, height=130)
_SUCCESS_TITLE_ROI = PixelRoi(x=190, y=280, width=280, height=140)
_POST_CLEAR_HEADER_CHROME_ROI = PixelRoi(x=0, y=90, width=1920, height=70)
_POST_CLEAR_SUCCESS_ROI = PixelRoi(x=20, y=930, width=480, height=150)

_MAIN_LOBBY_BRIGHT_THRESHOLD = 40_000
# The matching overlay dims the copy-code control to zero bright pixels.  Keep
# this metric in the conjunction/provenance, but let the stable room header be
# the discriminating cue while that overlay is visible.
_PARTY_ROOM_COPY_BRIGHT_THRESHOLD = 0
_PARTY_ROOM_HEADER_CYAN_THRESHOLD = 12_000
_PARTY_OVERLAY_WIREFRAME_CYAN_THRESHOLD = 50_000
_PARTY_OVERLAY_WIREFRAME_RED_MAXIMUM = 10_000
_PARTY_OVERLAY_FACE_CYAN_THRESHOLD = 6_000
_SOLO_WIREFRAME_RED_THRESHOLD = 100_000
_MATCH_SUCCESS_FACE_CYAN_THRESHOLD = 10_000
_MATCH_SUCCESS_TEXT_CYAN_THRESHOLD = 10_000
_SUCCESS_TITLE_CYAN_THRESHOLD = 7_000
_SUCCESS_TITLE_GREEN_THRESHOLD = 7_000
_POST_CLEAR_HEADER_CYAN_THRESHOLD = 50_000
_POST_CLEAR_SUCCESS_CYAN_THRESHOLD = 10_000


def observe_jp_mumu_outside_run_pages(
    frame: Frame,
    viewport: ContentViewport,
) -> tuple[OutsideRunPageObservation, ...]:
    """Observe independent outside-run page kinds without mutating ``frame``.

    A wrong resolution or non-full viewport makes every result unresolved.  On
    the known layout, page cues are intentionally independent: callers can
    retain several observations during a transition instead of forcing a
    top-one page label.  In particular, the party-room base and its matching
    overlay may both be present in the same frame.
    """

    if not _has_known_jp_mumu_layout(frame, viewport):
        return tuple(_unresolved_observation(frame, kind) for kind in OutsideRunPageKind)

    metrics = _measure_metrics(frame)
    return (
        _observation(
            frame,
            OutsideRunPageKind.MAIN_LOBBY,
            metrics,
            metrics["main_lobby_actions_bright"] >= _MAIN_LOBBY_BRIGHT_THRESHOLD,
            "main_lobby_actions_bright",
        ),
        _observation(
            frame,
            OutsideRunPageKind.PARTY_ROOM,
            metrics,
            (
                metrics["party_room_copy_bright"] >= _PARTY_ROOM_COPY_BRIGHT_THRESHOLD
                and metrics["party_room_header_cyan"] >= _PARTY_ROOM_HEADER_CYAN_THRESHOLD
            ),
            "party_room_copy_bright",
            "party_room_header_cyan",
        ),
        _observation(
            frame,
            OutsideRunPageKind.PARTY_ROOM_MATCHING_OVERLAY,
            metrics,
            (
                metrics["matching_wireframe_cyan"] >= _PARTY_OVERLAY_WIREFRAME_CYAN_THRESHOLD
                and metrics["matching_wireframe_red"] <= _PARTY_OVERLAY_WIREFRAME_RED_MAXIMUM
                and metrics["matching_face_cyan"] >= _PARTY_OVERLAY_FACE_CYAN_THRESHOLD
            ),
            "matching_wireframe_cyan",
            "matching_wireframe_red",
            "matching_face_cyan",
        ),
        _observation(
            frame,
            OutsideRunPageKind.SOLO_MATCHMAKING_PAGE,
            metrics,
            (
                metrics["matching_wireframe_red"] >= _SOLO_WIREFRAME_RED_THRESHOLD
                and metrics["matching_face_cyan"] < _MATCH_SUCCESS_FACE_CYAN_THRESHOLD
            ),
            "matching_wireframe_red",
            "matching_face_cyan",
        ),
        _observation(
            frame,
            OutsideRunPageKind.SUCCESS_RESULT,
            metrics,
            (
                metrics["success_title_cyan"] >= _SUCCESS_TITLE_CYAN_THRESHOLD
                and metrics["success_title_green"] >= _SUCCESS_TITLE_GREEN_THRESHOLD
            ),
            "success_title_cyan",
            "success_title_green",
        ),
        _observation(
            frame,
            OutsideRunPageKind.POST_CLEAR_REMATCH,
            metrics,
            (
                metrics["post_clear_header_cyan"] >= _POST_CLEAR_HEADER_CYAN_THRESHOLD
                and metrics["post_clear_success_cyan"] >= _POST_CLEAR_SUCCESS_CYAN_THRESHOLD
            ),
            "post_clear_header_cyan",
            "post_clear_success_cyan",
        ),
        _observation(
            frame,
            OutsideRunPageKind.MATCH_SUCCESS_TRANSITION,
            metrics,
            (
                metrics["matching_face_cyan"] >= _MATCH_SUCCESS_FACE_CYAN_THRESHOLD
                and metrics["matching_text_cyan"] >= _MATCH_SUCCESS_TEXT_CYAN_THRESHOLD
            ),
            "matching_face_cyan",
            "matching_text_cyan",
        ),
    )


def is_definite_old_run_terminal_or_outside(observation: OutsideRunPageObservation) -> bool:
    """Return whether a resolved observation is a strong old-run/outside cue.

    This helper deliberately says nothing about the reason the previous run
    ended.  Lifecycle orchestration consumes only this semantic predicate, not
    a specific page kind.
    """

    return observation.state is OutsideRunPageState.PRESENT and observation.page_kind in {
        OutsideRunPageKind.MAIN_LOBBY,
        OutsideRunPageKind.PARTY_ROOM,
        OutsideRunPageKind.PARTY_ROOM_MATCHING_OVERLAY,
        OutsideRunPageKind.SOLO_MATCHMAKING_PAGE,
        OutsideRunPageKind.SUCCESS_RESULT,
        OutsideRunPageKind.POST_CLEAR_REMATCH,
        OutsideRunPageKind.MATCH_SUCCESS_TRANSITION,
    }


def _measure_metrics(frame: Frame) -> dict[str, int]:
    return {
        "main_lobby_actions_bright": _bright_pixel_count(frame, _MAIN_LOBBY_ACTIONS_ROI),
        "party_room_copy_bright": _bright_pixel_count(frame, _PARTY_ROOM_COPY_BUTTON_ROI),
        "party_room_header_cyan": _cyan_pixel_count(frame, _PARTY_ROOM_HEADER_CHROME_ROI),
        "matching_wireframe_cyan": _cyan_pixel_count(frame, _MATCHING_WIREFRAME_ROI),
        "matching_wireframe_red": _red_pixel_count(frame, _MATCHING_WIREFRAME_ROI),
        "matching_face_cyan": _cyan_pixel_count(frame, _MATCHING_FACE_ROI),
        "matching_text_cyan": _cyan_pixel_count(frame, _MATCHING_TEXT_ROI),
        "success_title_cyan": _cyan_pixel_count(frame, _SUCCESS_TITLE_ROI),
        "success_title_green": _green_pixel_count(frame, _SUCCESS_TITLE_ROI),
        "post_clear_header_cyan": _cyan_pixel_count(frame, _POST_CLEAR_HEADER_CHROME_ROI),
        "post_clear_success_cyan": _cyan_pixel_count(frame, _POST_CLEAR_SUCCESS_ROI),
    }


def _observation(
    frame: Frame,
    page_kind: OutsideRunPageKind,
    all_metrics: dict[str, int],
    present: bool,
    *metric_names: str,
) -> OutsideRunPageObservation:
    return OutsideRunPageObservation(
        page_kind=page_kind,
        state=OutsideRunPageState.PRESENT if present else OutsideRunPageState.ABSENT,
        method=OutsideRunPageObservationMethod.FIXED_LAYOUT_PIXEL_CUES,
        frame_id=frame.frame_id,
        frame_index=frame.frame_index,
        processed_at=frame.processed_at,
        source_timestamp=frame.source_timestamp,
        source_type=frame.source_type,
        source_id=frame.source_id,
        source_reference=frame.source_reference,
        metrics=tuple(OutsideRunPageMetric(name, all_metrics[name]) for name in metric_names),
    )


def _unresolved_observation(
    frame: Frame,
    page_kind: OutsideRunPageKind,
) -> OutsideRunPageObservation:
    return OutsideRunPageObservation(
        page_kind=page_kind,
        state=OutsideRunPageState.UNRESOLVED,
        method=OutsideRunPageObservationMethod.UNRESOLVED_LAYOUT,
        frame_id=frame.frame_id,
        frame_index=frame.frame_index,
        processed_at=frame.processed_at,
        source_timestamp=frame.source_timestamp,
        source_type=frame.source_type,
        source_id=frame.source_id,
        source_reference=frame.source_reference,
        metrics=(),
    )


def _has_known_jp_mumu_layout(frame: Frame, viewport: ContentViewport) -> bool:
    return (
        (frame.width, frame.height) == (_JP_MUMU_VIEWPORT.width, _JP_MUMU_VIEWPORT.height)
        and viewport.pixel_roi == _JP_MUMU_VIEWPORT
    )


def _bright_pixel_count(frame: Frame, roi: PixelRoi) -> int:
    grayscale = cv2.cvtColor(_crop(frame, roi), cv2.COLOR_BGR2GRAY)
    return int(np.count_nonzero(grayscale >= 180))


def _cyan_pixel_count(frame: Frame, roi: PixelRoi) -> int:
    hsv = cv2.cvtColor(_crop(frame, roi), cv2.COLOR_BGR2HSV)
    return int(
        np.count_nonzero(
            (hsv[:, :, 0] >= 70)
            & (hsv[:, :, 0] <= 100)
            & (hsv[:, :, 1] >= 90)
            & (hsv[:, :, 2] >= 100)
        )
    )


def _green_pixel_count(frame: Frame, roi: PixelRoi) -> int:
    hsv = cv2.cvtColor(_crop(frame, roi), cv2.COLOR_BGR2HSV)
    return int(
        np.count_nonzero(
            (hsv[:, :, 0] >= 40)
            & (hsv[:, :, 0] <= 80)
            & (hsv[:, :, 1] >= 90)
            & (hsv[:, :, 2] >= 100)
        )
    )


def _red_pixel_count(frame: Frame, roi: PixelRoi) -> int:
    hsv = cv2.cvtColor(_crop(frame, roi), cv2.COLOR_BGR2HSV)
    return int(
        np.count_nonzero(
            ((hsv[:, :, 0] <= 10) | (hsv[:, :, 0] >= 170))
            & (hsv[:, :, 1] >= 100)
            & (hsv[:, :, 2] >= 60)
        )
    )


def _crop(frame: Frame, roi: PixelRoi) -> np.ndarray:
    return frame.image[roi.y : roi.bottom, roi.x : roi.right]
