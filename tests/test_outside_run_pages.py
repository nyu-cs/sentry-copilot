from __future__ import annotations

from datetime import UTC, datetime

import cv2
import numpy as np
import pytest

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.vision.outside_run_pages import (
    OutsideRunPageKind,
    OutsideRunPageState,
    is_definite_old_run_terminal_or_outside,
    observe_jp_mumu_outside_run_pages,
)
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi


def _frame(*, width: int = 1920, height: int = 1080) -> Frame:
    return Frame(
        frame_id="synthetic:outside-pages",
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


def _with_hsv_rect(frame: Frame, roi: PixelRoi, hsv: tuple[int, int, int]) -> Frame:
    image = frame.image.copy()
    patch = np.full((roi.height, roi.width, 3), hsv, dtype=np.uint8)
    image[roi.y : roi.bottom, roi.x : roi.right] = cv2.cvtColor(patch, cv2.COLOR_HSV2BGR)
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


def _with_bgr_rect(frame: Frame, roi: PixelRoi, bgr: tuple[int, int, int]) -> Frame:
    image = frame.image.copy()
    image[roi.y : roi.bottom, roi.x : roi.right] = bgr
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


def _state(frame: Frame, page: OutsideRunPageKind) -> OutsideRunPageState:
    observations = observe_jp_mumu_outside_run_pages(frame, ContentViewport.full_frame(frame))
    return next(item.state for item in observations if item.page_kind is page)


@pytest.mark.parametrize(
    ("page", "build"),
    [
        (
            OutsideRunPageKind.MAIN_LOBBY,
            lambda frame: _with_bgr_rect(frame, PixelRoi(1450, 400, 440, 400), (220, 220, 220)),
        ),
        (
            OutsideRunPageKind.PARTY_ROOM,
            lambda frame: _with_hsv_rect(
                _with_bgr_rect(frame, PixelRoi(1700, 35, 180, 55), (220, 220, 220)),
                PixelRoi(140, 145, 800, 45),
                (85, 200, 200),
            ),
        ),
        (
            OutsideRunPageKind.PARTY_ROOM_MATCHING_OVERLAY,
            lambda frame: _with_hsv_rect(
                _with_hsv_rect(frame, PixelRoi(100, 170, 1050, 710), (85, 200, 200)),
                PixelRoi(1370, 480, 330, 260),
                (85, 200, 200),
            ),
        ),
        (
            OutsideRunPageKind.SOLO_MATCHMAKING_PAGE,
            lambda frame: _with_hsv_rect(frame, PixelRoi(100, 170, 1050, 710), (0, 200, 200)),
        ),
        (
            OutsideRunPageKind.SUCCESS_RESULT,
            lambda frame: _with_hsv_rect(frame, PixelRoi(190, 280, 280, 140), (75, 200, 200)),
        ),
        (
            OutsideRunPageKind.POST_CLEAR_REMATCH,
            lambda frame: _with_hsv_rect(
                _with_hsv_rect(frame, PixelRoi(0, 90, 1920, 70), (85, 200, 200)),
                PixelRoi(20, 930, 480, 150),
                (85, 200, 200),
            ),
        ),
        (
            OutsideRunPageKind.MATCH_SUCCESS_TRANSITION,
            lambda frame: _with_hsv_rect(
                _with_hsv_rect(frame, PixelRoi(1370, 480, 330, 260), (85, 200, 200)),
                PixelRoi(1230, 250, 600, 130),
                (85, 200, 200),
            ),
        ),
    ],
)
def test_each_page_kind_has_a_positive_synthetic_cue(
    page: OutsideRunPageKind,
    build: object,
) -> None:
    assert callable(build)
    frame = build(_frame())
    observations = observe_jp_mumu_outside_run_pages(frame, ContentViewport.full_frame(frame))
    states = {item.page_kind: item.state for item in observations}
    assert states[page] is OutsideRunPageState.PRESENT
    assert all(
        state is OutsideRunPageState.ABSENT
        for kind, state in states.items()
        if kind is not page
    )


def test_cross_page_cues_do_not_force_an_unrelated_page_present() -> None:
    frame = _with_hsv_rect(_frame(), PixelRoi(190, 280, 280, 140), (75, 200, 200))
    observations = observe_jp_mumu_outside_run_pages(frame, ContentViewport.full_frame(frame))
    states = {item.page_kind: item.state for item in observations}
    assert states[OutsideRunPageKind.SUCCESS_RESULT] is OutsideRunPageState.PRESENT
    assert states[OutsideRunPageKind.MAIN_LOBBY] is OutsideRunPageState.ABSENT
    assert states[OutsideRunPageKind.PARTY_ROOM] is OutsideRunPageState.ABSENT
    assert states[OutsideRunPageKind.SOLO_MATCHMAKING_PAGE] is OutsideRunPageState.ABSENT
    assert states[OutsideRunPageKind.POST_CLEAR_REMATCH] is OutsideRunPageState.ABSENT
    assert states[OutsideRunPageKind.MATCH_SUCCESS_TRANSITION] is OutsideRunPageState.ABSENT


def test_wrong_frame_or_viewport_is_unresolved() -> None:
    frame = _frame(width=1280, height=720)
    assert {
        item.state
        for item in observe_jp_mumu_outside_run_pages(frame, ContentViewport.full_frame(frame))
    } == {OutsideRunPageState.UNRESOLVED}

    full = _frame()
    wrong_viewport = ContentViewport(
        frame_id=full.frame_id,
        frame_width=full.width,
        frame_height=full.height,
        pixel_roi=PixelRoi(0, 0, 1919, 1080),
    )
    assert {
        item.state for item in observe_jp_mumu_outside_run_pages(full, wrong_viewport)
    } == {OutsideRunPageState.UNRESOLVED}


def test_observations_do_not_mutate_the_frame() -> None:
    frame = _with_hsv_rect(_frame(), PixelRoi(190, 280, 280, 140), (75, 200, 200))
    original = frame.image.copy()
    observe_jp_mumu_outside_run_pages(frame, ContentViewport.full_frame(frame))
    assert np.array_equal(frame.image, original)


def test_semantic_grouping_requires_a_present_observation() -> None:
    frame = _with_hsv_rect(_frame(), PixelRoi(190, 280, 280, 140), (75, 200, 200))
    observations = observe_jp_mumu_outside_run_pages(frame, ContentViewport.full_frame(frame))
    assert is_definite_old_run_terminal_or_outside(
        next(item for item in observations if item.page_kind is OutsideRunPageKind.SUCCESS_RESULT)
    )
    assert not is_definite_old_run_terminal_or_outside(
        next(item for item in observations if item.page_kind is OutsideRunPageKind.MAIN_LOBBY)
    )
