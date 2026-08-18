"""Caller-directed one-frame Windows OCR probing with no game-specific interpretation."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC
from enum import StrEnum
from pathlib import Path
from time import sleep

import cv2
import numpy as np

from sentry_copilot.capture.frame_source import Frame, FrameSource, ImageArray
from sentry_copilot.capture.windows_display import WindowsDisplayFrameSource
from sentry_copilot.vision.ocr import (
    OcrBackend,
    OcrBackendUnavailableError,
    OcrResult,
    OcrRoi,
    WindowsOcrBackend,
    recognize_text,
)
from sentry_copilot.vision.viewport import ContentViewport, NormalizedRoi, PixelRoi

type Sleeper = Callable[[float], None]


class LiveOcrProbeOutcome(StrEnum):
    """Terminal outcome of a single caller-requested live OCR probe."""

    COMPLETED = "completed"
    OCR_UNAVAILABLE = "ocr_unavailable"


@dataclass(frozen=True)
class LiveOcrProbeConfig:
    """Explicit local-only settings for one captured frame and one OCR region."""

    output_directory: Path
    roi: OcrRoi
    language_tag: str
    start_delay_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not self.language_tag.strip():
            raise ValueError("language_tag must not be blank")
        if self.start_delay_seconds < 0:
            raise ValueError("start_delay_seconds must be non-negative")


@dataclass(frozen=True)
class LiveOcrProbeResult:
    """Immutable paths and OCR outcome from one local display frame."""

    outcome: LiveOcrProbeOutcome
    frame_path: Path
    roi_path: Path
    result_path: Path
    frame: Frame
    pixel_roi: PixelRoi
    ocr_result: OcrResult | None
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if self.outcome is LiveOcrProbeOutcome.COMPLETED:
            if self.ocr_result is None or self.unavailable_reason is not None:
                raise ValueError(
                    "completed OCR probe must contain one result and no unavailable reason"
                )
        elif self.ocr_result is not None or not self.unavailable_reason:
            raise ValueError("unavailable OCR probe must contain a reason and no OCR result")


def run_live_ocr_probe(
    source: FrameSource,
    config: LiveOcrProbeConfig,
    *,
    backend: OcrBackend | None = None,
    sleeper: Sleeper = sleep,
) -> LiveOcrProbeResult:
    """Capture exactly one caller-selected frame, OCR one caller-selected ROI, and dump it."""

    if config.start_delay_seconds:
        sleeper(config.start_delay_seconds)
    frame = _capture_one_frame(source)
    viewport = ContentViewport.full_frame(frame)
    pixel_roi = _resolve_roi(viewport, config.roi)
    crop = _copy_crop(frame, pixel_roi)

    config.output_directory.mkdir(parents=True, exist_ok=True)
    frame_path = config.output_directory / "captured-frame.png"
    roi_path = config.output_directory / "roi-crop.png"
    result_path = config.output_directory / "ocr-result.json"
    _write_png(frame_path, frame.image, "captured frame")
    _write_png(roi_path, crop, "OCR ROI crop")

    selected_backend = backend or WindowsOcrBackend()
    try:
        ocr_result = asyncio.run(
            recognize_text(
                frame,
                viewport,
                config.roi,
                selected_backend,
                language_tag=config.language_tag,
            )
        )
    except OcrBackendUnavailableError as error:
        result = LiveOcrProbeResult(
            outcome=LiveOcrProbeOutcome.OCR_UNAVAILABLE,
            frame_path=frame_path,
            roi_path=roi_path,
            result_path=result_path,
            frame=frame,
            pixel_roi=pixel_roi,
            ocr_result=None,
            unavailable_reason=str(error),
        )
    else:
        result = LiveOcrProbeResult(
            outcome=LiveOcrProbeOutcome.COMPLETED,
            frame_path=frame_path,
            roi_path=roi_path,
            result_path=result_path,
            frame=frame,
            pixel_roi=pixel_roi,
            ocr_result=ocr_result,
        )
    result_path.write_text(
        json.dumps(_result_json(result, config), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return result


def _capture_one_frame(source: FrameSource) -> Frame:
    frames = source.frames()
    try:
        return next(frames)
    finally:
        if isinstance(source, WindowsDisplayFrameSource):
            source.stop()
        _close_iterator(frames)


def _close_iterator(frames: Iterator[Frame]) -> None:
    close = getattr(frames, "close", None)
    if callable(close):
        close()


def _resolve_roi(viewport: ContentViewport, roi: OcrRoi) -> PixelRoi:
    if isinstance(roi, NormalizedRoi):
        return roi.resolve(viewport)
    content = viewport.pixel_roi
    if (
        roi.x < content.x
        or roi.y < content.y
        or roi.right > content.right
        or roi.bottom > content.bottom
    ):
        raise ValueError("pixel OCR ROI must stay within the content viewport")
    return roi


def _copy_crop(frame: Frame, pixel_roi: PixelRoi) -> ImageArray:
    crop = np.array(
        frame.image[pixel_roi.y : pixel_roi.bottom, pixel_roi.x : pixel_roi.right],
        dtype=np.uint8,
        copy=True,
    )
    crop.setflags(write=False)
    return crop


def _write_png(path: Path, image: ImageArray, description: str) -> None:
    if not cv2.imwrite(str(path), image):
        raise OSError(f"cannot write {description}: {path}")


def _result_json(
    result: LiveOcrProbeResult,
    config: LiveOcrProbeConfig,
) -> dict[str, object]:
    frame = result.frame
    payload: dict[str, object] = {
        "schema_version": 1,
        "outcome": result.outcome.value,
        "language_tag": config.language_tag,
        "requested_roi_kind": "normalized" if isinstance(config.roi, NormalizedRoi) else "pixel",
        "pixel_roi": _roi_json(result.pixel_roi),
        "frame": {
            "frame_id": frame.frame_id,
            "frame_index": frame.frame_index,
            "processed_at": frame.processed_at.astimezone(UTC).isoformat(),
            "source_timestamp_seconds": frame.timestamp_seconds,
            "source_type": frame.source_type.value,
            "source_id": frame.source_id,
            "source_reference": frame.source_reference,
            "width": frame.width,
            "height": frame.height,
        },
        "outputs": {
            "captured_frame": str(result.frame_path),
            "roi_crop": str(result.roi_path),
        },
    }
    if result.ocr_result is None:
        payload["ocr"] = {
            "status": "unavailable",
            "raw_text": None,
            "normalized_text": None,
            "confidence": None,
            "reason": result.unavailable_reason,
        }
    else:
        payload["ocr"] = {
            "status": result.ocr_result.status.value,
            "raw_text": result.ocr_result.raw_text,
            "normalized_text": result.ocr_result.normalized_text,
            "confidence": result.ocr_result.confidence,
        }
    return payload


def _roi_json(roi: PixelRoi) -> dict[str, int]:
    return {"x": roi.x, "y": roi.y, "width": roi.width, "height": roi.height}
