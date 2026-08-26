from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.vision.strategy_selection_render_context import (
    JP_MUMU_SELECTION_DETAIL_BRIGHT_FRACTION_CUTOFF,
    SelectionRenderContextState,
    observe_jp_mumu_selection_render_context,
    selection_render_context_roi,
)
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi


def _frame(*, selection: bool = True, width: int = 1920, height: int = 1080) -> Frame:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    if selection and width >= 820 and height >= 115:
        image[35:115, 540:820] = (255, 255, 0)
    return Frame(
        frame_id=f"synthetic:{width}x{height}",
        frame_index=7,
        processed_at=datetime.now(UTC),
        source_timestamp=timedelta(seconds=12),
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic-source",
        width=width,
        height=height,
        image=image,
        source_reference="synthetic-reference",
    )


def _with_detail_fraction(frame: Frame, fraction: float) -> Frame:
    roi = selection_render_context_roi()
    count = round(roi.width * roi.height * fraction)
    image = np.array(frame.image, copy=True)
    for index in range(count):
        y, x = divmod(index, roi.width)
        image[roi.y + y, roi.x + x] = (200, 200, 200)
    return Frame(
        frame_id=f"{frame.frame_id}:detail",
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


def _observe(frame: Frame):
    return observe_jp_mumu_selection_render_context(frame, ContentViewport.full_frame(frame))


def test_dark_known_selection_frame_is_grid_and_preserves_provenance() -> None:
    frame = _frame()
    original = np.array(frame.image, copy=True)

    observation = _observe(frame)

    assert observation.state is SelectionRenderContextState.SELECTION_GRID
    assert observation.bright_pixel_fraction == 0.0
    assert observation.pixel_bounds == PixelRoi(x=1550, y=550, width=120, height=180)
    assert observation.frame_id == frame.frame_id
    assert observation.frame_index == frame.frame_index
    assert observation.source_timestamp == timedelta(seconds=12)
    assert np.array_equal(frame.image, original)


def test_bright_known_selection_frame_is_strategy_detail() -> None:
    observation = _observe(_with_detail_fraction(_frame(), 0.10))

    assert observation.state is SelectionRenderContextState.STRATEGY_DETAIL
    assert observation.bright_pixel_fraction == pytest.approx(0.10, abs=1 / (120 * 180))


@pytest.mark.parametrize(
    ("fraction", "expected"),
    [
        (
            JP_MUMU_SELECTION_DETAIL_BRIGHT_FRACTION_CUTOFF - 1 / (120 * 180),
            SelectionRenderContextState.SELECTION_GRID,
        ),
        (
            JP_MUMU_SELECTION_DETAIL_BRIGHT_FRACTION_CUTOFF,
            SelectionRenderContextState.STRATEGY_DETAIL,
        ),
    ],
)
def test_detail_cutoff_is_inclusive(fraction: float, expected: SelectionRenderContextState) -> None:
    assert _observe(_with_detail_fraction(_frame(), fraction)).state is expected


def test_wrong_resolution_or_viewport_is_unresolved() -> None:
    wrong = _frame(width=1280, height=720)
    assert _observe(wrong).state is SelectionRenderContextState.UNRESOLVED

    frame = _frame()
    wrong_viewport = ContentViewport(
        frame_id=frame.frame_id,
        frame_width=frame.width,
        frame_height=frame.height,
        pixel_roi=PixelRoi(x=0, y=0, width=1919, height=1080),
    )
    assert (
        observe_jp_mumu_selection_render_context(frame, wrong_viewport).state
        is SelectionRenderContextState.UNRESOLVED
    )


def test_non_selection_and_information_page_like_frames_are_unresolved() -> None:
    assert _observe(_frame(selection=False)).state is SelectionRenderContextState.UNRESOLVED

    info_page = _with_detail_fraction(_frame(selection=False), 0.90)
    assert _observe(info_page).state is SelectionRenderContextState.UNRESOLVED
