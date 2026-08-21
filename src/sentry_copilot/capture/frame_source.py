"""Read-only offline frame sources and raw-frame dump utilities.

This module intentionally produces frames only. It does not locate a viewport, inspect pixels,
or emit domain observations, so future window capture can implement the same ``FrameSource``
protocol without changing recognition consumers.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import cast

import cv2
import numpy as np
import numpy.typing as npt

from sentry_copilot.image_io import (
    ImageDecodeError,
    ImageEncodeError,
    load_bgr_image,
    write_bgr_png,
)

ImageArray = npt.NDArray[np.uint8]


class FrameSourceType(StrEnum):
    IMAGE_SEQUENCE = "image_sequence"
    LOCAL_VIDEO = "local_video"
    WINDOWS_DISPLAY = "windows_display"


@dataclass(frozen=True)
class Frame:
    """An immutable input frame with source and processing-time provenance."""

    frame_id: str
    frame_index: int
    processed_at: datetime
    source_timestamp: timedelta | None
    source_type: FrameSourceType
    source_id: str
    width: int
    height: int
    image: ImageArray
    source_reference: str

    def __post_init__(self) -> None:
        if not self.frame_id.strip() or not self.source_id.strip():
            raise ValueError("frame_id and source_id must not be blank")
        if self.frame_index < 0:
            raise ValueError("frame_index must be non-negative")
        if self.processed_at.tzinfo is None or self.processed_at.utcoffset() is None:
            raise ValueError("processed_at must be timezone-aware")
        if self.source_timestamp is not None and self.source_timestamp.total_seconds() < 0:
            raise ValueError("source_timestamp must be non-negative")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("frame dimensions must be positive")
        if self.image.dtype != np.uint8 or self.image.ndim != 3 or self.image.shape[2] != 3:
            raise ValueError("frame image must be a uint8 BGR image")
        if self.image.shape[:2] != (self.height, self.width):
            raise ValueError("frame dimensions must match its image payload")
        if not self.source_reference.strip():
            raise ValueError("source_reference must not be blank")
        payload = np.array(self.image, dtype=np.uint8, copy=True)
        payload.setflags(write=False)
        object.__setattr__(self, "image", payload)

    @property
    def frame(self) -> ImageArray:
        """Compatibility alias for the image payload."""

        return self.image

    @property
    def timestamp_seconds(self) -> float | None:
        """Compatibility projection of a relative source timestamp."""

        return (
            self.source_timestamp.total_seconds()
            if self.source_timestamp is not None
            else None
        )


@dataclass(frozen=True)
class FrameSourceMetadata:
    source_id: str
    source_type: FrameSourceType
    source_reference: str
    frame_rate: float | None = None

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.source_reference.strip():
            raise ValueError("source metadata text fields must not be blank")
        if self.frame_rate is not None and self.frame_rate <= 0:
            raise ValueError("frame_rate must be positive when provided")


class FrameSource(ABC):
    """Stable downstream input contract for replay and future live sources."""

    @property
    @abstractmethod
    def metadata(self) -> FrameSourceMetadata:
        """Describe the source without reading frames."""

    @abstractmethod
    def frames(self) -> Iterator[Frame]:
        """Yield immutable frames in stable increasing source index order."""

    def __iter__(self) -> Iterator[Frame]:
        return self.frames()


class ImageSequenceFrameSource(FrameSource):
    """Read a caller-specified ordered list of local images through OpenCV."""

    def __init__(
        self,
        paths: Sequence[str | Path],
        *,
        source_id: str = "image-sequence",
    ) -> None:
        if not paths:
            raise ValueError("image sequence cannot be empty")
        if not source_id.strip():
            raise ValueError("source_id must not be blank")
        self._paths = tuple(Path(path) for path in paths)
        self._metadata = FrameSourceMetadata(
            source_id=source_id,
            source_type=FrameSourceType.IMAGE_SEQUENCE,
            source_reference="image-sequence",
        )

    @classmethod
    def from_directory(
        cls,
        directory: str | Path,
        *,
        patterns: tuple[str, ...] = ("*.png", "*.jpg", "*.jpeg", "*.bmp"),
        source_id: str = "image-sequence",
    ) -> ImageSequenceFrameSource:
        root = Path(directory)
        paths = tuple(
            sorted(
                path
                for pattern in patterns
                for path in root.glob(pattern)
                if path.is_file()
            )
        )
        return cls(paths, source_id=source_id)

    @property
    def metadata(self) -> FrameSourceMetadata:
        return self._metadata

    def frames(self) -> Iterator[Frame]:
        for index, path in enumerate(self._paths):
            try:
                image = load_bgr_image(path)
            except ImageDecodeError as error:
                raise FileNotFoundError(f"cannot read image frame: {path}") from error
            yield _frame(
                image=image,
                source=self.metadata,
                frame_index=index,
                source_timestamp=None,
                source_reference=str(path),
            )


class LocalVideoFrameSource(FrameSource):
    """Read a local video through OpenCV without performing any visual interpretation."""

    def __init__(
        self,
        path: str | Path,
        *,
        source_id: str = "local-video",
        sample_every_seconds: float | None = None,
    ) -> None:
        if not source_id.strip():
            raise ValueError("source_id must not be blank")
        if sample_every_seconds is not None and sample_every_seconds <= 0:
            raise ValueError("sample_every_seconds must be positive")
        self.path = Path(path)
        self._source_id = source_id
        self.sample_every_seconds = sample_every_seconds

    @property
    def metadata(self) -> FrameSourceMetadata:
        return FrameSourceMetadata(
            source_id=self._source_id,
            source_type=FrameSourceType.LOCAL_VIDEO,
            source_reference=str(self.path),
            frame_rate=self._frame_rate(),
        )

    def frames(self) -> Iterator[Frame]:
        capture = cv2.VideoCapture(str(self.path))
        if not capture.isOpened():
            raise FileNotFoundError(f"cannot open video: {self.path}")
        fps = _frame_rate(capture)
        step = (
            max(1, round(fps * self.sample_every_seconds))
            if self.sample_every_seconds is not None
            else 1
        )
        source = FrameSourceMetadata(
            source_id=self._source_id,
            source_type=FrameSourceType.LOCAL_VIDEO,
            source_reference=str(self.path),
            frame_rate=fps,
        )
        frame_index = 0
        try:
            while True:
                ok, image = capture.read()
                if not ok:
                    break
                if frame_index % step == 0:
                    yield _frame(
                        image=cast(ImageArray, image),
                        source=source,
                        frame_index=frame_index,
                        source_timestamp=timedelta(seconds=frame_index / fps),
                        source_reference=str(self.path),
                    )
                frame_index += 1
        finally:
            capture.release()

    def _frame_rate(self) -> float:
        capture = cv2.VideoCapture(str(self.path))
        if not capture.isOpened():
            raise FileNotFoundError(f"cannot open video: {self.path}")
        try:
            return _frame_rate(capture)
        finally:
            capture.release()


@dataclass(frozen=True)
class RawFrameDump:
    output_directory: Path
    metadata_path: Path
    frame_paths: tuple[Path, ...]


def dump_raw_frames(
    source: FrameSource,
    output_directory: str | Path,
    *,
    session_id: str | None = None,
    processed_at: datetime | None = None,
) -> RawFrameDump:
    """Write raw PNG frames and minimal source/session JSON to a caller-owned directory."""

    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    dumped_at = processed_at or datetime.now(UTC)
    if dumped_at.tzinfo is None or dumped_at.utcoffset() is None:
        raise ValueError("processed_at must be timezone-aware")

    frame_paths: list[Path] = []
    frame_metadata: list[dict[str, object]] = []
    for frame in source.frames():
        frame_path = destination / f"frame_{frame.frame_index:06d}.png"
        try:
            write_bgr_png(frame_path, frame.image)
        except ImageEncodeError as error:
            raise OSError(f"cannot write raw frame dump: {frame_path}") from error
        frame_paths.append(frame_path)
        frame_metadata.append(
            {
                "frame_id": frame.frame_id,
                "frame_index": frame.frame_index,
                "source_timestamp_seconds": frame.timestamp_seconds,
                "width": frame.width,
                "height": frame.height,
                "file": frame_path.name,
            }
        )

    metadata_path = destination / "frames.metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "session_id": session_id,
                "processed_at": dumped_at.astimezone(UTC).isoformat(),
                "source": _metadata_json(source.metadata),
                "frames": frame_metadata,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return RawFrameDump(
        output_directory=destination,
        metadata_path=metadata_path,
        frame_paths=tuple(frame_paths),
    )


def _frame(
    *,
    image: ImageArray,
    source: FrameSourceMetadata,
    frame_index: int,
    source_timestamp: timedelta | None,
    source_reference: str,
) -> Frame:
    payload = np.array(image, dtype=np.uint8, copy=True)
    height, width = payload.shape[:2]
    return Frame(
        frame_id=f"{source.source_id}:{frame_index:06d}",
        frame_index=frame_index,
        processed_at=datetime.now(UTC),
        source_timestamp=source_timestamp,
        source_type=source.source_type,
        source_id=source.source_id,
        width=width,
        height=height,
        image=payload,
        source_reference=source_reference,
    )


def _frame_rate(capture: cv2.VideoCapture) -> float:
    value = float(capture.get(cv2.CAP_PROP_FPS))
    return value if value > 0 else 30.0


def _metadata_json(metadata: FrameSourceMetadata) -> dict[str, object]:
    result = asdict(metadata)
    result["source_type"] = metadata.source_type.value
    return result
