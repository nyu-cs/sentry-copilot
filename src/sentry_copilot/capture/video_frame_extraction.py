"""Explicit timestamp-based full-resolution video frame extraction with OpenCV only."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import cast

import cv2

from sentry_copilot.capture.frame_source import ImageArray
from sentry_copilot.image_io import ImageEncodeError, write_bgr_png

_TIMESTAMP = re.compile(
    r"(?P<hours>\d{2}):(?P<minutes>\d{2}):(?P<seconds>\d{2})(?:\.(?P<milliseconds>\d{3}))?\Z"
)
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")


class VideoFrameExtractionStatus(StrEnum):
    """Whether one explicit request produced an output image."""

    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True)
class VideoFrameRequest:
    """One timestamp and safe caller-defined output label."""

    timestamp_text: str
    label: str

    def __post_init__(self) -> None:
        parse_video_timestamp(self.timestamp_text)
        if not _LABEL.fullmatch(self.label):
            raise ValueError(
                "frame label must use letters, digits, '_' or '-' and start with alphanumeric"
            )

    @property
    def timestamp(self) -> timedelta:
        """Requested non-negative source-relative timestamp."""

        return parse_video_timestamp(self.timestamp_text)

    @property
    def output_filename(self) -> str:
        """Stable, path-safe PNG filename derived only from this explicit request."""

        return f"{_timestamp_filename(self.timestamp_text)}_{self.label}.png"


@dataclass(frozen=True)
class VideoFrameExtractionConfig:
    """Caller-owned video, output directory, and explicit timestamp requests."""

    video_path: Path
    output_directory: Path
    requests: tuple[VideoFrameRequest, ...]

    def __post_init__(self) -> None:
        if not str(self.video_path).strip():
            raise ValueError("video_path must not be blank")
        if not self.requests:
            raise ValueError("at least one timestamp request is required")
        filenames = tuple(request.output_filename for request in self.requests)
        if len(filenames) != len(set(filenames)):
            raise ValueError("timestamp requests must produce unique output filenames")


@dataclass(frozen=True)
class VideoFrameExtractionRecord:
    """Immutable outcome and seek provenance for one timestamp request."""

    request: VideoFrameRequest
    status: VideoFrameExtractionStatus
    output_path: Path | None
    actual_frame_index: int | None
    actual_timestamp_seconds: float | None
    width: int | None
    height: int | None
    failure_type: str | None = None
    failure_message: str | None = None

    def __post_init__(self) -> None:
        if self.status is VideoFrameExtractionStatus.SUCCESS:
            if (
                self.output_path is None
                or self.actual_frame_index is None
                or self.actual_timestamp_seconds is None
                or self.width is None
                or self.height is None
                or self.failure_type is not None
                or self.failure_message is not None
            ):
                raise ValueError("successful frame extraction must have complete frame provenance")
            if self.actual_frame_index < 0 or self.actual_timestamp_seconds < 0:
                raise ValueError("successful frame provenance must be non-negative")
            if self.width <= 0 or self.height <= 0:
                raise ValueError("successful frame dimensions must be positive")
        elif not self.failure_type or not self.failure_message:
            raise ValueError("failed frame extraction must contain typed failure details")


@dataclass(frozen=True)
class VideoFrameExtractionResult:
    """Caller-owned output manifest and all requested extraction outcomes."""

    output_directory: Path
    manifest_path: Path
    video_path: Path
    frame_rate: float | None
    records: tuple[VideoFrameExtractionRecord, ...]


def parse_video_timestamp(value: str) -> timedelta:
    """Parse strict ``HH:MM:SS`` or ``HH:MM:SS.mmm`` source-relative timestamps."""

    match = _TIMESTAMP.fullmatch(value)
    if match is None:
        raise ValueError("timestamp must use HH:MM:SS or HH:MM:SS.mmm")
    minutes = int(match["minutes"])
    seconds = int(match["seconds"])
    if minutes >= 60 or seconds >= 60:
        raise ValueError("timestamp minutes and seconds must be less than 60")
    milliseconds = int(match["milliseconds"] or 0)
    return timedelta(
        hours=int(match["hours"]),
        minutes=minutes,
        seconds=seconds,
        milliseconds=milliseconds,
    )


def extract_video_frames(config: VideoFrameExtractionConfig) -> VideoFrameExtractionResult:
    """Extract requested full-resolution frames from exactly one caller-provided video path."""

    config.output_directory.mkdir(parents=True, exist_ok=True)
    manifest_path = config.output_directory / "video-frame-extraction.json"
    capture = cv2.VideoCapture(str(config.video_path))
    if not capture.isOpened():
        records = tuple(
            _failed_record(request, "VideoOpenError", f"cannot open video: {config.video_path}")
            for request in config.requests
        )
        result = VideoFrameExtractionResult(
            output_directory=config.output_directory,
            manifest_path=manifest_path,
            video_path=config.video_path,
            frame_rate=None,
            records=records,
        )
        _write_manifest(result)
        return result

    frame_rate = _read_frame_rate(capture)
    try:
        records = tuple(
            _extract_one(capture, request, config.output_directory, frame_rate)
            for request in config.requests
        )
    finally:
        capture.release()
    result = VideoFrameExtractionResult(
        output_directory=config.output_directory,
        manifest_path=manifest_path,
        video_path=config.video_path,
        frame_rate=frame_rate,
        records=records,
    )
    _write_manifest(result)
    return result


def _extract_one(
    capture: cv2.VideoCapture,
    request: VideoFrameRequest,
    output_directory: Path,
    frame_rate: float,
) -> VideoFrameExtractionRecord:
    requested_frame_index = round(request.timestamp.total_seconds() * frame_rate)
    if not capture.set(cv2.CAP_PROP_POS_FRAMES, requested_frame_index):
        return _failed_record(
            request, "VideoSeekError", "OpenCV could not seek to the requested frame"
        )
    ok, image = capture.read()
    if not ok or image is None:
        return _failed_record(
            request, "FrameDecodeError", "OpenCV could not decode the requested frame"
        )
    frame_index = max(0, round(capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1)
    decoded_timestamp = _decoded_timestamp_seconds(capture, frame_index, frame_rate)
    payload = cast(ImageArray, image)
    output_path = output_directory / request.output_filename
    try:
        write_bgr_png(output_path, payload)
    except ImageEncodeError:
        return _failed_record(request, "FrameWriteError", f"cannot write PNG: {output_path}")
    height, width = payload.shape[:2]
    return VideoFrameExtractionRecord(
        request=request,
        status=VideoFrameExtractionStatus.SUCCESS,
        output_path=output_path,
        actual_frame_index=frame_index,
        actual_timestamp_seconds=decoded_timestamp,
        width=width,
        height=height,
    )


def _read_frame_rate(capture: cv2.VideoCapture) -> float:
    frame_rate = float(capture.get(cv2.CAP_PROP_FPS))
    if frame_rate <= 0:
        raise ValueError("video reports no positive frame rate")
    return frame_rate


def _decoded_timestamp_seconds(
    capture: cv2.VideoCapture, frame_index: int, frame_rate: float
) -> float:
    decoded_milliseconds = float(capture.get(cv2.CAP_PROP_POS_MSEC))
    if decoded_milliseconds >= 0:
        return decoded_milliseconds / 1000.0
    return frame_index / frame_rate


def _failed_record(
    request: VideoFrameRequest,
    failure_type: str,
    failure_message: str,
) -> VideoFrameExtractionRecord:
    return VideoFrameExtractionRecord(
        request=request,
        status=VideoFrameExtractionStatus.FAILED,
        output_path=None,
        actual_frame_index=None,
        actual_timestamp_seconds=None,
        width=None,
        height=None,
        failure_type=failure_type,
        failure_message=failure_message,
    )


def _write_manifest(result: VideoFrameExtractionResult) -> None:
    payload = {
        "schema_version": 1,
        "source_video_path": str(result.video_path),
        "source_video_reference": str(result.video_path),
        "frame_rate": result.frame_rate,
        "requests": [_record_json(record) for record in result.records],
    }
    result.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _record_json(record: VideoFrameExtractionRecord) -> dict[str, object]:
    return {
        "requested_timestamp": record.request.timestamp_text,
        "requested_timestamp_seconds": record.request.timestamp.total_seconds(),
        "label": record.request.label,
        "status": record.status.value,
        "actual_decoded_frame_index": record.actual_frame_index,
        "actual_decoded_timestamp_seconds": record.actual_timestamp_seconds,
        "width": record.width,
        "height": record.height,
        "output_filename": record.output_path.name if record.output_path is not None else None,
        "failure": (
            {"type": record.failure_type, "message": record.failure_message}
            if record.failure_type is not None
            else None
        ),
    }


def _timestamp_filename(timestamp_text: str) -> str:
    return timestamp_text.replace(":", "-").replace(".", "-")
