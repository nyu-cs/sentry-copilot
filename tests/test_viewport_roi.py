from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.vision.viewport import (
    ContentViewport,
    NormalizedRoi,
    PixelRoi,
    crop_normalized_roi,
    save_roi_debug_image,
)


def _frame(*, frame_id: str = "synthetic:000000") -> Frame:
    image = np.zeros((10, 16, 3), dtype=np.uint8)
    for row in range(image.shape[0]):
        for column in range(image.shape[1]):
            image[row, column] = (row, column, row + column)
    return Frame(
        frame_id=frame_id,
        frame_index=0,
        processed_at=datetime(2026, 8, 15, tzinfo=UTC),
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic",
        width=16,
        height=10,
        image=image,
        source_reference="synthetic.png",
    )


def test_full_frame_viewport_is_explicit_and_resolution_independent() -> None:
    frame = _frame()

    viewport = ContentViewport.full_frame(frame)

    assert viewport.pixel_roi == PixelRoi(x=0, y=0, width=16, height=10)
    assert viewport.frame_id == frame.frame_id


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ((-1, 0, 1, 1), "origin"),
        ((0, 0, 0, 1), "width"),
    ],
)
def test_pixel_roi_rejects_invalid_geometry(
    arguments: tuple[int, int, int, int], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        PixelRoi(*arguments)


def test_content_viewport_rejects_out_of_frame_bounds() -> None:
    with pytest.raises(ValueError, match="within frame bounds"):
        ContentViewport(
            frame_id="synthetic:000000",
            frame_width=16,
            frame_height=10,
            pixel_roi=PixelRoi(x=8, y=1, width=9, height=8),
        )


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ((-0.1, 0.0, 0.5, 0.5), "origin"),
        ((0.0, 0.0, 0.0, 0.5), "width"),
        ((0.75, 0.0, 0.5, 0.5), "within"),
    ],
)
def test_normalized_roi_rejects_out_of_bounds_or_empty_geometry(
    arguments: tuple[float, float, float, float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        NormalizedRoi(*arguments)


def test_normalized_roi_resolves_relative_to_content_not_raw_frame() -> None:
    frame = _frame()
    viewport = ContentViewport(
        frame_id=frame.frame_id,
        frame_width=frame.width,
        frame_height=frame.height,
        pixel_roi=PixelRoi(x=2, y=1, width=10, height=8),
    )

    pixel_roi = NormalizedRoi(x=0.1, y=0.25, width=0.5, height=0.5).resolve(viewport)

    assert pixel_roi == PixelRoi(x=3, y=3, width=5, height=4)


def test_crop_is_a_safe_copy_and_preserves_original_frame() -> None:
    frame = _frame()
    original = np.array(frame.image, copy=True)
    viewport = ContentViewport.full_frame(frame)

    crop = crop_normalized_roi(frame, viewport, NormalizedRoi(0.25, 0.2, 0.5, 0.4))

    assert crop.pixel_roi == PixelRoi(x=4, y=2, width=8, height=5)
    assert np.array_equal(crop.image, original[2:7, 4:12])
    assert not crop.image.flags.writeable
    assert np.array_equal(frame.image, original)
    with pytest.raises(ValueError):
        crop.image[0, 0, 0] = 99


def test_crop_rejects_viewport_from_another_frame() -> None:
    frame = _frame()
    other = _frame(frame_id="synthetic:000001")

    with pytest.raises(ValueError, match="different frame"):
        crop_normalized_roi(other, ContentViewport.full_frame(frame), NormalizedRoi(0, 0, 1, 1))


def test_debug_image_is_caller_directed_and_does_not_mutate_frame(tmp_path: Path) -> None:
    frame = _frame()
    original = np.array(frame.image, copy=True)
    viewport = ContentViewport(
        frame_id=frame.frame_id,
        frame_width=frame.width,
        frame_height=frame.height,
        pixel_roi=PixelRoi(x=2, y=1, width=10, height=8),
    )
    crop = crop_normalized_roi(frame, viewport, NormalizedRoi(0.2, 0.25, 0.5, 0.5))
    output = tmp_path / "debug" / "roi.png"

    result = save_roi_debug_image(frame, crop, output)

    assert result == output
    assert result.is_file()
    assert cv2.imread(str(result), cv2.IMREAD_COLOR) is not None
    assert np.array_equal(frame.image, original)
