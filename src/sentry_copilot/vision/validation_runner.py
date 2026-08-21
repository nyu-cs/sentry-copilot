"""Small, explicit offline frame validation runner.

The runner only coordinates existing frame input and geometry primitives. It performs no visual
recognition and never discovers input files outside the path supplied by the caller.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from sentry_copilot.capture.frame_source import (
    Frame,
    FrameSource,
    ImageSequenceFrameSource,
    LocalVideoFrameSource,
)
from sentry_copilot.image_io import ImageEncodeError, write_bgr_png
from sentry_copilot.vision.viewport import (
    ContentViewport,
    NormalizedRoi,
    PixelRoi,
    crop_normalized_roi,
)


@dataclass(frozen=True)
class NamedNormalizedRoi:
    """A caller-named normalized ROI used only for offline debug output."""

    name: str
    roi: NormalizedRoi

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("ROI name must not be blank")


@dataclass(frozen=True)
class OfflineValidationConfig:
    """Explicit input/output and geometry choices for one offline validation run."""

    source_path: Path
    output_directory: Path
    full_frame: bool = False
    viewport_pixel_roi: PixelRoi | None = None
    rois: tuple[NamedNormalizedRoi, ...] = ()
    sample_every_n: int = 1
    source_id: str = "offline-validation"

    def __post_init__(self) -> None:
        if not str(self.source_path).strip():
            raise ValueError("source_path must not be blank")
        if self.full_frame == (self.viewport_pixel_roi is not None):
            raise ValueError("choose exactly one of full_frame or viewport_pixel_roi")
        if self.sample_every_n <= 0:
            raise ValueError("sample_every_n must be positive")
        names = [item.name for item in self.rois]
        if len(names) != len(set(names)):
            raise ValueError("ROI names must be unique")


@dataclass(frozen=True)
class OfflineValidationResult:
    output_directory: Path
    manifest_path: Path
    selected_frame_count: int
    manifest_record_count: int


def run_offline_validation(config: OfflineValidationConfig) -> OfflineValidationResult:
    """Run explicitly selected frames, write debug images, and emit a JSONL manifest."""

    source = frame_source_from_path(config.source_path, source_id=config.source_id)
    config.output_directory.mkdir(parents=True, exist_ok=True)
    frame_directory = config.output_directory / "frames"
    roi_directory = config.output_directory / "rois"
    frame_directory.mkdir(parents=True, exist_ok=True)
    roi_directory.mkdir(parents=True, exist_ok=True)
    manifest_path = config.output_directory / "manifest.jsonl"

    selected_frame_count = 0
    manifest_record_count = 0
    with manifest_path.open("w", encoding="utf-8", newline="\n") as manifest:
        for frame in source.frames():
            if frame.frame_index % config.sample_every_n != 0:
                continue
            viewport = _viewport_for_frame(frame, config)
            frame_path = frame_directory / f"frame_{frame.frame_index:06d}.png"
            _write_frame_debug(frame, viewport, config.rois, frame_path)
            selected_frame_count += 1

            if config.rois:
                for named_roi in config.rois:
                    crop = crop_normalized_roi(frame, viewport, named_roi.roi)
                    roi_path = roi_directory / (
                        f"frame_{frame.frame_index:06d}_{_safe_name(named_roi.name)}.png"
                    )
                    try:
                        write_bgr_png(roi_path, crop.image)
                    except ImageEncodeError as error:
                        raise OSError(f"cannot write ROI image: {roi_path}") from error
                    manifest.write(
                        _manifest_line(
                            frame,
                            viewport,
                            named_roi.name,
                            crop.pixel_roi,
                            frame_path,
                            roi_path,
                        )
                    )
                    manifest_record_count += 1
            else:
                manifest.write(_manifest_line(frame, viewport, None, None, frame_path, frame_path))
                manifest_record_count += 1

    return OfflineValidationResult(
        output_directory=config.output_directory,
        manifest_path=manifest_path,
        selected_frame_count=selected_frame_count,
        manifest_record_count=manifest_record_count,
    )


def frame_source_from_path(path: Path, *, source_id: str) -> FrameSource:
    """Create a source from exactly one caller-supplied file or directory path."""

    if path.is_dir():
        return ImageSequenceFrameSource.from_directory(path, source_id=source_id)
    if path.is_file():
        return LocalVideoFrameSource(path, source_id=source_id)
    raise FileNotFoundError(f"offline validation source does not exist: {path}")


def parse_named_roi(value: str) -> NamedNormalizedRoi:
    """Parse ``name=x,y,width,height`` for the CLI."""

    try:
        name, coordinates = value.split("=", maxsplit=1)
        values = tuple(float(part) for part in coordinates.split(","))
        if len(values) != 4:
            raise ValueError
        return NamedNormalizedRoi(name=name, roi=NormalizedRoi(*values))
    except (TypeError, ValueError) as error:
        raise ValueError("ROI must use name=x,y,width,height") from error


def _viewport_for_frame(frame: Frame, config: OfflineValidationConfig) -> ContentViewport:
    if config.full_frame:
        return ContentViewport.full_frame(frame)
    assert config.viewport_pixel_roi is not None
    return ContentViewport(
        frame_id=frame.frame_id,
        frame_width=frame.width,
        frame_height=frame.height,
        pixel_roi=config.viewport_pixel_roi,
    )


def _write_frame_debug(
    frame: Frame,
    viewport: ContentViewport,
    rois: Iterable[NamedNormalizedRoi],
    output_path: Path,
) -> None:
    image = np.array(frame.image, dtype=np.uint8, copy=True)
    _draw_rectangle(image, viewport.pixel_roi, (0, 200, 0))
    for named_roi in rois:
        _draw_rectangle(image, named_roi.roi.resolve(viewport), (255, 0, 255))
    try:
        write_bgr_png(output_path, image)
    except ImageEncodeError as error:
        raise OSError(f"cannot write frame debug image: {output_path}") from error


def _draw_rectangle(image: np.ndarray, roi: PixelRoi, color: tuple[int, int, int]) -> None:
    cv2.rectangle(image, (roi.x, roi.y), (roi.right - 1, roi.bottom - 1), color, 1)


def _manifest_line(
    frame: Frame,
    viewport: ContentViewport,
    roi_name: str | None,
    pixel_roi: PixelRoi | None,
    frame_output_path: Path,
    output_path: Path,
) -> str:
    record = {
        "frame_id": frame.frame_id,
        "frame_index": frame.frame_index,
        "source_timestamp_seconds": frame.timestamp_seconds,
        "frame_size": {"width": frame.width, "height": frame.height},
        "viewport": _roi_json(viewport.pixel_roi),
        "roi_name": roi_name,
        "roi_pixel_bounds": _roi_json(pixel_roi) if pixel_roi is not None else None,
        "frame_output_path": str(frame_output_path),
        "output_path": str(output_path),
    }
    return json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"


def _roi_json(roi: PixelRoi) -> dict[str, int]:
    return {"x": roi.x, "y": roi.y, "width": roi.width, "height": roi.height}


def _safe_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
    return safe or "roi"
