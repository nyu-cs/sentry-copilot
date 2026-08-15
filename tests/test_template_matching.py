from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.vision.template_matching import (
    TemplateImage,
    match_template,
    save_template_match_debug,
)
from sentry_copilot.vision.viewport import ContentViewport, NormalizedRoi, PixelRoi


def _frame() -> Frame:
    image = np.zeros((20, 30, 3), dtype=np.uint8)
    image[7:11, 12:17] = np.array(
        [
            [[10, 20, 30], [20, 30, 40], [30, 40, 50], [40, 50, 60], [50, 60, 70]],
            [[20, 40, 60], [30, 50, 70], [40, 60, 80], [50, 70, 90], [60, 80, 100]],
            [[30, 60, 90], [40, 70, 100], [50, 80, 110], [60, 90, 120], [70, 100, 130]],
            [[40, 80, 120], [50, 90, 130], [60, 100, 140], [70, 110, 150], [80, 120, 160]],
        ],
        dtype=np.uint8,
    )
    return Frame(
        frame_id="synthetic:000007",
        frame_index=7,
        processed_at=datetime(2026, 8, 15, tzinfo=UTC),
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic-source",
        width=30,
        height=20,
        image=image,
        source_reference="synthetic.png",
    )


def _template(frame: Frame) -> TemplateImage:
    return TemplateImage("template.synthetic.marker", frame.image[7:11, 12:17])


def test_normalized_roi_match_returns_source_provenance_and_pixel_bounds() -> None:
    frame = _frame()
    result = match_template(
        frame,
        ContentViewport.full_frame(frame),
        NormalizedRoi(0.25, 0.2, 0.5, 0.6),
        _template(frame),
        threshold=0.99,
    )

    assert result.matched
    assert result.score == pytest.approx(1.0)
    assert result.match_bounds == PixelRoi(x=12, y=7, width=5, height=4)
    assert result.frame_id == frame.frame_id
    assert result.frame_index == frame.frame_index
    assert result.source_id == frame.source_id
    assert result.source_reference == frame.source_reference
    assert result.debug_output_path is None


def test_pixel_roi_is_supported_and_cannot_escape_content_viewport() -> None:
    frame = _frame()
    viewport = ContentViewport(
        frame_id=frame.frame_id,
        frame_width=frame.width,
        frame_height=frame.height,
        pixel_roi=PixelRoi(x=5, y=3, width=20, height=14),
    )

    result = match_template(
        frame,
        viewport,
        PixelRoi(x=10, y=5, width=10, height=8),
        _template(frame),
    )

    assert result.matched
    with pytest.raises(ValueError, match="within the content viewport"):
        match_template(frame, viewport, PixelRoi(x=0, y=0, width=10, height=8), _template(frame))


def test_matcher_rejects_templates_larger_than_the_search_region() -> None:
    frame = _frame()

    with pytest.raises(ValueError, match="fit inside"):
        match_template(
            frame,
            ContentViewport.full_frame(frame),
            PixelRoi(x=0, y=0, width=4, height=3),
            _template(frame),
        )


def test_template_and_frame_are_immutable_and_debug_output_is_explicit(tmp_path: Path) -> None:
    frame = _frame()
    original = np.array(frame.image, copy=True)
    template = _template(frame)
    output = tmp_path / "debug" / "match.png"

    result = match_template(
        frame,
        ContentViewport.full_frame(frame),
        NormalizedRoi(0, 0, 1, 1),
        template,
        debug_output_path=output,
    )

    assert result.debug_output_path == output
    assert output.is_file()
    assert cv2.imread(str(output), cv2.IMREAD_COLOR) is not None
    assert np.array_equal(frame.image, original)
    assert not template.image.flags.writeable
    with pytest.raises(ValueError):
        template.image[0, 0, 0] = 0


def test_debug_writer_rejects_result_from_another_frame(tmp_path: Path) -> None:
    frame = _frame()
    result = match_template(
        frame,
        ContentViewport.full_frame(frame),
        NormalizedRoi(0, 0, 1, 1),
        _template(frame),
    )
    other = Frame(
        frame_id="synthetic:000008",
        frame_index=8,
        processed_at=datetime(2026, 8, 15, tzinfo=UTC),
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic-source",
        width=30,
        height=20,
        image=np.zeros((20, 30, 3), dtype=np.uint8),
        source_reference="synthetic-other.png",
    )

    with pytest.raises(ValueError, match="different frame"):
        save_template_match_debug(
            other,
            ContentViewport.full_frame(other),
            result,
            tmp_path / "x.png",
        )
