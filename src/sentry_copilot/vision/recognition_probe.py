"""Generic one-frame OCR/template probe harness with caller-owned diagnostics only."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC
from enum import StrEnum
from pathlib import Path
from time import sleep
from typing import cast

import cv2
import numpy as np

from sentry_copilot.capture.frame_source import Frame, FrameSource, ImageArray
from sentry_copilot.capture.windows_display import WindowsDisplayFrameSource
from sentry_copilot.vision.ocr import (
    OcrBackend,
    OcrBackendUnavailableError,
    OcrResult,
    recognize_text,
)
from sentry_copilot.vision.template_matching import (
    TemplateImage,
    TemplateMatchResult,
    match_template,
)
from sentry_copilot.vision.viewport import ContentViewport, NormalizedRoi, PixelRoi

type ProbeRoi = NormalizedRoi | PixelRoi
type Sleeper = Callable[[float], None]

_OPERATION_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")


class RecognitionProbeConfigurationError(ValueError):
    """The caller supplied an invalid generic probe definition."""


class RecognitionProbeOperationType(StrEnum):
    """The small set of source-neutral operations supported by this developer harness."""

    OCR = "ocr"
    TEMPLATE = "template"


class RecognitionProbeStatus(StrEnum):
    """Per-operation result status, distinct from OCR's text status and match boolean."""

    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(frozen=True)
class OcrProbeOperation:
    """One explicit OCR request over one normalized or raw-pixel ROI."""

    name: str
    roi: ProbeRoi
    language_tag: str

    def __post_init__(self) -> None:
        _validate_operation_name(self.name)
        if not self.language_tag.strip():
            raise RecognitionProbeConfigurationError("OCR language_tag must not be blank")

    @property
    def operation_type(self) -> RecognitionProbeOperationType:
        return RecognitionProbeOperationType.OCR


@dataclass(frozen=True)
class TemplateProbeOperation:
    """One caller-owned template match request over one normalized or raw-pixel ROI."""

    name: str
    roi: ProbeRoi
    template: TemplateImage
    template_reference: str
    threshold: float = 0.9

    def __post_init__(self) -> None:
        _validate_operation_name(self.name)
        if not self.template_reference.strip():
            raise RecognitionProbeConfigurationError("template_reference must not be blank")
        if not -1.0 <= self.threshold <= 1.0:
            raise RecognitionProbeConfigurationError(
                "template threshold must be between -1.0 and 1.0"
            )

    @property
    def operation_type(self) -> RecognitionProbeOperationType:
        return RecognitionProbeOperationType.TEMPLATE


type RecognitionProbeOperation = OcrProbeOperation | TemplateProbeOperation


@dataclass(frozen=True)
class RecognitionProbeConfig:
    """Caller-owned output and explicit operations for exactly one input frame."""

    output_directory: Path
    operations: tuple[RecognitionProbeOperation, ...]
    start_delay_seconds: float = 0.0
    write_annotated_diagnostic: bool = False

    def __post_init__(self) -> None:
        if not self.operations:
            raise RecognitionProbeConfigurationError("at least one probe operation is required")
        names = tuple(operation.name for operation in self.operations)
        if len(names) != len(set(names)):
            raise RecognitionProbeConfigurationError("probe operation names must be unique")
        if self.start_delay_seconds < 0:
            raise RecognitionProbeConfigurationError("start_delay_seconds must be non-negative")


@dataclass(frozen=True)
class RecognitionProbeOperationResult:
    """Immutable execution result for one explicit ROI operation."""

    name: str
    operation_type: RecognitionProbeOperationType
    requested_roi: ProbeRoi
    pixel_roi: PixelRoi
    crop_path: Path
    status: RecognitionProbeStatus
    ocr_result: OcrResult | None = None
    template_result: TemplateMatchResult | None = None
    template_reference: str | None = None
    failure_type: str | None = None
    failure_message: str | None = None

    def __post_init__(self) -> None:
        if self.operation_type is RecognitionProbeOperationType.OCR:
            if self.template_result is not None:
                raise ValueError("OCR probe result must not contain a template result")
        elif self.ocr_result is not None:
            raise ValueError("template probe result must not contain an OCR result")
        if self.operation_type is RecognitionProbeOperationType.OCR:
            if self.template_reference is not None:
                raise ValueError("OCR probe result must not contain a template reference")
        elif not self.template_reference:
            raise ValueError("template probe result must contain a template reference")
        if self.status is RecognitionProbeStatus.COMPLETED:
            expected = (
                self.ocr_result
                if self.operation_type is RecognitionProbeOperationType.OCR
                else self.template_result
            )
            if (
                expected is None
                or self.failure_type is not None
                or self.failure_message is not None
            ):
                raise ValueError("completed probe result must contain only its operation result")
        elif self.status is RecognitionProbeStatus.UNAVAILABLE:
            if (
                self.operation_type is not RecognitionProbeOperationType.OCR
                or not self.failure_message
            ):
                raise ValueError("only OCR probe results can be unavailable")
        elif not self.failure_type or not self.failure_message:
            raise ValueError("failed probe result must contain typed failure details")


@dataclass(frozen=True)
class RecognitionProbeResult:
    """Immutable caller-owned artifacts from a one-frame recognition experiment."""

    output_directory: Path
    source_frame_path: Path
    report_path: Path
    diagnostic_path: Path | None
    frame: Frame
    operations: tuple[RecognitionProbeOperationResult, ...]


def load_template_image(path: str | Path, *, template_id: str | None = None) -> TemplateImage:
    """Load one caller-specified BGR template; no template discovery or directory scan occurs."""

    source = Path(path)
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        raise RecognitionProbeConfigurationError(f"cannot read template image: {source}")
    return TemplateImage(template_id or str(source), cast(ImageArray, image))


def run_recognition_probe(
    source: FrameSource,
    config: RecognitionProbeConfig,
    *,
    ocr_backend: OcrBackend | None = None,
    sleeper: Sleeper = sleep,
) -> RecognitionProbeResult:
    """Run explicit generic OCR/template experiments over exactly one captured or local frame."""

    if config.start_delay_seconds:
        sleeper(config.start_delay_seconds)
    frame = _capture_one_frame(source)
    viewport = ContentViewport.full_frame(frame)
    config.output_directory.mkdir(parents=True, exist_ok=True)
    source_frame_path = config.output_directory / "source-frame.png"
    _write_png(source_frame_path, frame.image, "probe source frame")

    selected_ocr_backend = ocr_backend
    operation_results: list[RecognitionProbeOperationResult] = []
    for operation in config.operations:
        pixel_roi = _resolve_roi(viewport, operation.roi)
        crop_path = config.output_directory / f"roi-{operation.name}.png"
        _write_png(crop_path, _copy_crop(frame, pixel_roi), f"probe ROI crop {operation.name}")
        operation_results.append(
            _run_operation(frame, viewport, operation, pixel_roi, crop_path, selected_ocr_backend)
        )

    results = tuple(operation_results)
    diagnostic_path = (
        config.output_directory / "diagnostic.png" if config.write_annotated_diagnostic else None
    )
    if diagnostic_path is not None:
        _write_diagnostic(frame, results, diagnostic_path)
    report_path = config.output_directory / "recognition-probe.json"
    result = RecognitionProbeResult(
        output_directory=config.output_directory,
        source_frame_path=source_frame_path,
        report_path=report_path,
        diagnostic_path=diagnostic_path,
        frame=frame,
        operations=results,
    )
    report_path.write_text(
        json.dumps(_report_json(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _run_operation(
    frame: Frame,
    viewport: ContentViewport,
    operation: RecognitionProbeOperation,
    pixel_roi: PixelRoi,
    crop_path: Path,
    ocr_backend: OcrBackend | None,
) -> RecognitionProbeOperationResult:
    if isinstance(operation, OcrProbeOperation):
        if ocr_backend is None:
            from sentry_copilot.vision.ocr import WindowsOcrBackend

            ocr_backend = WindowsOcrBackend()
        try:
            ocr_result = asyncio.run(
                recognize_text(
                    frame,
                    viewport,
                    operation.roi,
                    ocr_backend,
                    language_tag=operation.language_tag,
                )
            )
        except OcrBackendUnavailableError as error:
            return RecognitionProbeOperationResult(
                name=operation.name,
                operation_type=operation.operation_type,
                requested_roi=operation.roi,
                pixel_roi=pixel_roi,
                crop_path=crop_path,
                status=RecognitionProbeStatus.UNAVAILABLE,
                failure_type=type(error).__name__,
                failure_message=str(error),
            )
        except Exception as error:
            return _failed_operation(operation, pixel_roi, crop_path, error)
        return RecognitionProbeOperationResult(
            name=operation.name,
            operation_type=operation.operation_type,
            requested_roi=operation.roi,
            pixel_roi=pixel_roi,
            crop_path=crop_path,
            status=RecognitionProbeStatus.COMPLETED,
            ocr_result=ocr_result,
        )

    try:
        template_result = match_template(
            frame,
            viewport,
            operation.roi,
            operation.template,
            threshold=operation.threshold,
        )
    except Exception as error:
        return _failed_operation(operation, pixel_roi, crop_path, error)
    return RecognitionProbeOperationResult(
        name=operation.name,
        operation_type=operation.operation_type,
        requested_roi=operation.roi,
        pixel_roi=pixel_roi,
        crop_path=crop_path,
        status=RecognitionProbeStatus.COMPLETED,
        template_result=template_result,
        template_reference=operation.template_reference,
    )


def _failed_operation(
    operation: RecognitionProbeOperation,
    pixel_roi: PixelRoi,
    crop_path: Path,
    error: Exception,
) -> RecognitionProbeOperationResult:
    return RecognitionProbeOperationResult(
        name=operation.name,
        operation_type=operation.operation_type,
        requested_roi=operation.roi,
        pixel_roi=pixel_roi,
        crop_path=crop_path,
        status=RecognitionProbeStatus.FAILED,
        template_reference=(
            operation.template_reference
            if isinstance(operation, TemplateProbeOperation)
            else None
        ),
        failure_type=type(error).__name__,
        failure_message=str(error),
    )


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


def _resolve_roi(viewport: ContentViewport, roi: ProbeRoi) -> PixelRoi:
    if isinstance(roi, NormalizedRoi):
        return roi.resolve(viewport)
    content = viewport.pixel_roi
    if (
        roi.x < content.x
        or roi.y < content.y
        or roi.right > content.right
        or roi.bottom > content.bottom
    ):
        raise RecognitionProbeConfigurationError(
            "pixel probe ROI must stay within the content viewport"
        )
    return roi


def _copy_crop(frame: Frame, roi: PixelRoi) -> ImageArray:
    crop = np.array(
        frame.image[roi.y : roi.bottom, roi.x : roi.right], dtype=np.uint8, copy=True
    )
    crop.setflags(write=False)
    return crop


def _write_png(path: Path, image: ImageArray, description: str) -> None:
    if not cv2.imwrite(str(path), image):
        raise OSError(f"cannot write {description}: {path}")


def _write_diagnostic(
    frame: Frame,
    operations: tuple[RecognitionProbeOperationResult, ...],
    path: Path,
) -> None:
    image = np.array(frame.image, dtype=np.uint8, copy=True)
    for operation in operations:
        color = _diagnostic_color(operation.status)
        _draw_rectangle(image, operation.pixel_roi, color)
        cv2.putText(
            image,
            operation.name,
            (operation.pixel_roi.x, max(12, operation.pixel_roi.y - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            color,
            1,
            lineType=cv2.LINE_AA,
        )
        if (
            operation.template_result is not None
            and operation.template_result.match_bounds is not None
        ):
            _draw_rectangle(image, operation.template_result.match_bounds, color)
    _write_png(path, image, "probe diagnostic")


def _diagnostic_color(status: RecognitionProbeStatus) -> tuple[int, int, int]:
    if status is RecognitionProbeStatus.COMPLETED:
        return (0, 255, 0)
    if status is RecognitionProbeStatus.UNAVAILABLE:
        return (0, 180, 255)
    return (0, 0, 255)


def _draw_rectangle(image: ImageArray, roi: PixelRoi, color: tuple[int, int, int]) -> None:
    cv2.rectangle(image, (roi.x, roi.y), (roi.right - 1, roi.bottom - 1), color, thickness=1)


def _report_json(result: RecognitionProbeResult) -> dict[str, object]:
    frame = result.frame
    return {
        "schema_version": 1,
        "source": {
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
            "source_frame": str(result.source_frame_path),
            "diagnostic": (
                str(result.diagnostic_path) if result.diagnostic_path is not None else None
            ),
        },
        "operations": [_operation_json(operation) for operation in result.operations],
    }


def _operation_json(operation: RecognitionProbeOperationResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": operation.name,
        "operation_type": operation.operation_type.value,
        "status": operation.status.value,
        "requested_roi": _requested_roi_json(operation.requested_roi),
        "pixel_roi": _pixel_roi_json(operation.pixel_roi),
        "crop_path": str(operation.crop_path),
    }
    if operation.ocr_result is not None:
        payload["ocr"] = {
            "language_tag": operation.ocr_result.language_tag,
            "status": operation.ocr_result.status.value,
            "raw_text": operation.ocr_result.raw_text,
            "normalized_text": operation.ocr_result.normalized_text,
            "confidence": operation.ocr_result.confidence,
        }
    if operation.template_result is not None:
        result = operation.template_result
        payload["template"] = {
            "template_id": result.template_id,
            "template_reference": operation.template_reference,
            "threshold": result.threshold,
            "score": result.score,
            "matched": result.matched,
            "match_bounds": (
                _pixel_roi_json(result.match_bounds)
                if result.match_bounds is not None
                else None
            ),
        }
    if operation.failure_type is not None:
        payload["failure"] = {
            "type": operation.failure_type,
            "message": operation.failure_message,
        }
    return payload


def _requested_roi_json(roi: ProbeRoi) -> dict[str, object]:
    if isinstance(roi, NormalizedRoi):
        return {
            "kind": "normalized",
            "x": roi.x,
            "y": roi.y,
            "width": roi.width,
            "height": roi.height,
        }
    return {"kind": "pixel", **_pixel_roi_json(roi)}


def _pixel_roi_json(roi: PixelRoi) -> dict[str, int]:
    return {"x": roi.x, "y": roi.y, "width": roi.width, "height": roi.height}


def _validate_operation_name(name: str) -> None:
    if not _OPERATION_NAME.fullmatch(name):
        raise RecognitionProbeConfigurationError(
            "probe operation name must start with a letter and use only letters, digits, '_' or '-'"
        )
