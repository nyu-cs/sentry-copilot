from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import cv2
import numpy as np
import pytest

from sentry_copilot.capture.frame_source import Frame, FrameSourceType, ImageArray
from sentry_copilot.vision.ocr import (
    OcrBackendReading,
    OcrBackendUnavailableError,
    OcrStatus,
    WindowsOcrBackend,
    recognize_text,
)
from sentry_copilot.vision.viewport import ContentViewport, NormalizedRoi, PixelRoi


def _frame() -> Frame:
    image = np.full((80, 160, 3), 255, dtype=np.uint8)
    cv2.putText(image, "ID 0038", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    return Frame(
        frame_id="synthetic:000009",
        frame_index=9,
        processed_at=datetime(2026, 8, 15, tzinfo=UTC),
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic-source",
        width=160,
        height=80,
        image=image,
        source_reference="synthetic-text.png",
    )


class _ReadingBackend:
    def __init__(self, reading: OcrBackendReading) -> None:
        self.reading = reading
        self.images: list[ImageArray] = []

    async def recognize(self, image: ImageArray, *, language_tag: str) -> OcrBackendReading:
        self.images.append(image)
        return self.reading


def test_ocr_uses_only_normalized_crop_and_records_full_provenance() -> None:
    frame = _frame()
    original = np.array(frame.image, copy=True)
    backend = _ReadingBackend(
        OcrBackendReading(" \u30c6\u30b9\u30c8\u3000#\uff10\uff10\uff13\uff18 ", confidence=0.75)
    )

    result = asyncio.run(
        recognize_text(
            frame,
            ContentViewport.full_frame(frame),
            NormalizedRoi(0.125, 0.25, 0.5, 0.5),
            backend,
            language_tag="ja-JP",
        )
    )

    assert result.raw_text == " \u30c6\u30b9\u30c8\u3000#\uff10\uff10\uff13\uff18 "
    assert result.normalized_text == "\u30c6\u30b9\u30c8 #0038"
    assert result.status is OcrStatus.RECOGNIZED
    assert result.confidence == 0.75
    assert result.pixel_bounds == PixelRoi(x=20, y=20, width=80, height=40)
    assert result.frame_id == frame.frame_id
    assert result.frame_index == frame.frame_index
    assert result.processed_at == frame.processed_at
    assert result.source_timestamp == frame.source_timestamp
    assert result.source_type is frame.source_type
    assert result.source_id == frame.source_id
    assert result.source_reference == frame.source_reference
    assert backend.images[0].shape == (40, 80, 3)
    assert not backend.images[0].flags.writeable
    assert np.array_equal(frame.image, original)
    with pytest.raises(AttributeError):
        result.normalized_text = "changed"


@pytest.mark.parametrize(
    ("raw_text", "expected_status", "expected_normalized"),
    [
        (None, OcrStatus.UNKNOWN, None),
        ("  \n\t ", OcrStatus.EMPTY, ""),
    ],
)
def test_ocr_preserves_unknown_and_empty_results_safely(
    raw_text: str | None,
    expected_status: OcrStatus,
    expected_normalized: str | None,
) -> None:
    frame = _frame()
    backend = _ReadingBackend(OcrBackendReading(raw_text))

    result = asyncio.run(
        recognize_text(
            frame,
            ContentViewport.full_frame(frame),
            PixelRoi(x=0, y=0, width=80, height=40),
            backend,
        )
    )

    assert result.status is expected_status
    assert result.normalized_text == expected_normalized


def test_ocr_rejects_pixel_roi_outside_the_content_viewport() -> None:
    frame = _frame()
    backend = _ReadingBackend(OcrBackendReading("synthetic"))
    viewport = ContentViewport(
        frame_id=frame.frame_id,
        frame_width=frame.width,
        frame_height=frame.height,
        pixel_roi=PixelRoi(x=20, y=10, width=120, height=60),
    )

    with pytest.raises(ValueError, match="within the content viewport"):
        asyncio.run(
            recognize_text(frame, viewport, PixelRoi(x=0, y=0, width=80, height=40), backend)
        )


def test_windows_backend_delegates_to_an_injected_runtime_without_system_ocr() -> None:
    class _Runtime:
        async def recognize(self, image: ImageArray, language_tag: str) -> OcrBackendReading:
            assert language_tag == "ja-JP"
            assert image.shape == (8, 10, 3)
            return OcrBackendReading("\u5408\u6210", confidence=1.0)

    backend = WindowsOcrBackend(runtime=_Runtime())

    result = asyncio.run(
        backend.recognize(np.zeros((8, 10, 3), dtype=np.uint8), language_tag="ja-JP")
    )

    assert result == OcrBackendReading("\u5408\u6210", confidence=1.0)


def test_windows_backend_reports_missing_japanese_language_capability() -> None:
    class _UnavailableRuntime:
        async def recognize(self, image: ImageArray, language_tag: str) -> OcrBackendReading:
            raise OcrBackendUnavailableError(f"missing language: {language_tag}")

    backend = WindowsOcrBackend(runtime=_UnavailableRuntime())

    with pytest.raises(OcrBackendUnavailableError, match="ja-JP"):
        asyncio.run(backend.recognize(np.zeros((8, 10, 3), dtype=np.uint8), language_tag="ja-JP"))


def test_backend_reading_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError, match="between"):
        OcrBackendReading("synthetic", confidence=1.1)
