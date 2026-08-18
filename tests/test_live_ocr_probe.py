from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

from sentry_copilot.capture.frame_source import (
    Frame,
    FrameSource,
    FrameSourceMetadata,
    FrameSourceType,
    ImageArray,
)
from sentry_copilot.vision.live_ocr_probe import (
    LiveOcrProbeConfig,
    LiveOcrProbeOutcome,
    run_live_ocr_probe,
)
from sentry_copilot.vision.ocr import OcrBackendReading, OcrBackendUnavailableError
from sentry_copilot.vision.viewport import NormalizedRoi, PixelRoi


class _StaticFrameSource(FrameSource):
    def __init__(self, frame: Frame) -> None:
        self.frame = frame
        self.closed = False

    @property
    def metadata(self) -> FrameSourceMetadata:
        return FrameSourceMetadata(
            source_id="synthetic-live",
            source_type=FrameSourceType.WINDOWS_DISPLAY,
            source_reference="synthetic-display",
        )

    def frames(self) -> Iterator[Frame]:
        try:
            yield self.frame
        finally:
            self.closed = True


class _ReadingBackend:
    def __init__(self) -> None:
        self.images: list[ImageArray] = []
        self.languages: list[str] = []

    async def recognize(self, image: ImageArray, *, language_tag: str) -> OcrBackendReading:
        self.images.append(image)
        self.languages.append(language_tag)
        return OcrBackendReading(" synthetic 0038 ", confidence=0.8)


class _UnavailableBackend:
    async def recognize(self, image: ImageArray, *, language_tag: str) -> OcrBackendReading:
        del image
        raise OcrBackendUnavailableError(f"missing language capability: {language_tag}")


def _frame() -> Frame:
    image = np.zeros((10, 16, 3), dtype=np.uint8)
    image[2:6, 4:12] = (12, 34, 56)
    return Frame(
        frame_id="synthetic-live:000000",
        frame_index=0,
        processed_at=datetime(2026, 8, 18, tzinfo=UTC),
        source_timestamp=timedelta(seconds=1.5),
        source_type=FrameSourceType.WINDOWS_DISPLAY,
        source_id="synthetic-live",
        width=16,
        height=10,
        image=image,
        source_reference="synthetic-monitor",
    )


def test_live_probe_dumps_one_explicit_crop_and_result_without_mutating_frame(
    tmp_path: Path,
) -> None:
    frame = _frame()
    original = np.array(frame.image, copy=True)
    source = _StaticFrameSource(frame)
    backend = _ReadingBackend()
    delays: list[float] = []

    result = run_live_ocr_probe(
        source,
        LiveOcrProbeConfig(
            output_directory=tmp_path / "probe",
            roi=NormalizedRoi(0.25, 0.2, 0.5, 0.4),
            language_tag="ja-JP",
            start_delay_seconds=2.0,
        ),
        backend=backend,
        sleeper=delays.append,
    )

    payload = json.loads(result.result_path.read_text(encoding="utf-8"))
    assert result.outcome is LiveOcrProbeOutcome.COMPLETED
    assert result.frame_path.is_file()
    assert result.roi_path.is_file()
    assert payload["outcome"] == "completed"
    assert payload["language_tag"] == "ja-JP"
    assert payload["requested_roi_kind"] == "normalized"
    assert payload["pixel_roi"] == {"x": 4, "y": 2, "width": 8, "height": 5}
    assert payload["ocr"] == {
        "confidence": 0.8,
        "normalized_text": "synthetic 0038",
        "raw_text": " synthetic 0038 ",
        "status": "recognized",
    }
    assert backend.languages == ["ja-JP"]
    assert backend.images[0].shape == (5, 8, 3)
    assert not backend.images[0].flags.writeable
    assert cv2.imread(str(result.roi_path), cv2.IMREAD_COLOR).shape == (5, 8, 3)
    assert delays == [2.0]
    assert source.closed
    assert np.array_equal(frame.image, original)


def test_live_probe_persists_a_typed_unavailable_result_after_capture(tmp_path: Path) -> None:
    frame = _frame()
    source = _StaticFrameSource(frame)

    result = run_live_ocr_probe(
        source,
        LiveOcrProbeConfig(
            output_directory=tmp_path / "probe",
            roi=PixelRoi(x=4, y=2, width=8, height=4),
            language_tag="ja-JP",
        ),
        backend=_UnavailableBackend(),
    )

    payload = json.loads(result.result_path.read_text(encoding="utf-8"))
    assert result.outcome is LiveOcrProbeOutcome.OCR_UNAVAILABLE
    assert result.ocr_result is None
    assert result.unavailable_reason == "missing language capability: ja-JP"
    assert result.frame_path.is_file()
    assert result.roi_path.is_file()
    assert payload["ocr"] == {
        "confidence": None,
        "normalized_text": None,
        "raw_text": None,
        "reason": "missing language capability: ja-JP",
        "status": "unavailable",
    }
    assert payload["requested_roi_kind"] == "pixel"
    assert source.closed
