"""Immutable content-viewport and normalized ROI primitives.

This module is deliberately geometry-only. A caller supplies the content viewport after manual
calibration or a future detector; no screen, page, player, or strategy interpretation happens
here.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor
from pathlib import Path

import cv2
import numpy as np

from sentry_copilot.capture.frame_source import Frame, ImageArray
from sentry_copilot.image_io import ImageEncodeError, write_bgr_png


@dataclass(frozen=True)
class PixelRoi:
    """A non-empty rectangle in raw-frame pixel coordinates."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.x < 0 or self.y < 0:
            raise ValueError("pixel ROI origin must be non-negative")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("pixel ROI width and height must be positive")

    @property
    def right(self) -> int:
        """Exclusive right pixel coordinate."""

        return self.x + self.width

    @property
    def bottom(self) -> int:
        """Exclusive bottom pixel coordinate."""

        return self.y + self.height


@dataclass(frozen=True)
class ContentViewport:
    """A caller-calibrated game-content rectangle bound to one immutable frame."""

    frame_id: str
    frame_width: int
    frame_height: int
    pixel_roi: PixelRoi

    def __post_init__(self) -> None:
        if not self.frame_id.strip():
            raise ValueError("frame_id must not be blank")
        if self.frame_width <= 0 or self.frame_height <= 0:
            raise ValueError("frame dimensions must be positive")
        if self.pixel_roi.right > self.frame_width or self.pixel_roi.bottom > self.frame_height:
            raise ValueError("content viewport must stay within frame bounds")

    @classmethod
    def full_frame(cls, frame: Frame) -> ContentViewport:
        """Explicitly treat all of ``frame`` as game content."""

        return cls(
            frame_id=frame.frame_id,
            frame_width=frame.width,
            frame_height=frame.height,
            pixel_roi=PixelRoi(x=0, y=0, width=frame.width, height=frame.height),
        )

    def validate_frame(self, frame: Frame) -> None:
        """Reject a viewport accidentally reused with another frame or resolution."""

        if frame.frame_id != self.frame_id:
            raise ValueError("content viewport belongs to a different frame")
        if (frame.width, frame.height) != (self.frame_width, self.frame_height):
            raise ValueError("content viewport frame dimensions do not match")


@dataclass(frozen=True)
class NormalizedRoi:
    """A non-empty rectangle normalized to a content viewport, not to the desktop."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        values = (self.x, self.y, self.width, self.height)
        if not all(np.isfinite(value) for value in values):
            raise ValueError("normalized ROI values must be finite")
        if self.x < 0 or self.y < 0:
            raise ValueError("normalized ROI origin must be non-negative")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("normalized ROI width and height must be positive")
        if self.right > 1 or self.bottom > 1:
            raise ValueError("normalized ROI must stay within the content viewport")

    @property
    def right(self) -> float:
        """Exclusive normalized right coordinate."""

        return self.x + self.width

    @property
    def bottom(self) -> float:
        """Exclusive normalized bottom coordinate."""

        return self.y + self.height

    def resolve(self, viewport: ContentViewport) -> PixelRoi:
        """Project this ROI into raw-frame pixels, preserving every touched pixel."""

        content = viewport.pixel_roi
        left = content.x + floor(self.x * content.width)
        top = content.y + floor(self.y * content.height)
        right = content.x + ceil(self.right * content.width)
        bottom = content.y + ceil(self.bottom * content.height)
        return PixelRoi(x=left, y=top, width=right - left, height=bottom - top)


@dataclass(frozen=True)
class ResolvedRoiCrop:
    """An immutable image crop with its complete geometry provenance."""

    frame_id: str
    viewport: ContentViewport
    normalized_roi: NormalizedRoi
    pixel_roi: PixelRoi
    image: ImageArray

    def __post_init__(self) -> None:
        if self.frame_id != self.viewport.frame_id:
            raise ValueError("resolved crop frame_id must match its viewport")
        if self.image.dtype != np.uint8 or self.image.ndim != 3 or self.image.shape[2] != 3:
            raise ValueError("resolved crop image must be a uint8 BGR image")
        if self.image.shape[:2] != (self.pixel_roi.height, self.pixel_roi.width):
            raise ValueError("resolved crop dimensions must match its pixel ROI")
        payload = np.array(self.image, dtype=np.uint8, copy=True)
        payload.setflags(write=False)
        object.__setattr__(self, "image", payload)


def crop_normalized_roi(
    frame: Frame,
    viewport: ContentViewport,
    normalized_roi: NormalizedRoi,
) -> ResolvedRoiCrop:
    """Copy a normalized content ROI without mutating or sharing the source frame payload."""

    viewport.validate_frame(frame)
    pixel_roi = normalized_roi.resolve(viewport)
    image = np.array(
        frame.image[pixel_roi.y : pixel_roi.bottom, pixel_roi.x : pixel_roi.right],
        dtype=np.uint8,
        copy=True,
    )
    return ResolvedRoiCrop(
        frame_id=frame.frame_id,
        viewport=viewport,
        normalized_roi=normalized_roi,
        pixel_roi=pixel_roi,
        image=image,
    )


def save_roi_debug_image(
    frame: Frame,
    crop: ResolvedRoiCrop,
    output_path: str | Path,
) -> Path:
    """Write a caller-directed BGR debug image with content and crop rectangles drawn on a copy."""

    crop.viewport.validate_frame(frame)
    if crop.frame_id != frame.frame_id:
        raise ValueError("resolved crop belongs to a different frame")
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    debug_image = np.array(frame.image, dtype=np.uint8, copy=True)
    _draw_rectangle(debug_image, crop.viewport.pixel_roi, color=(0, 200, 0))
    _draw_rectangle(debug_image, crop.pixel_roi, color=(255, 0, 255))
    try:
        write_bgr_png(destination, debug_image)
    except ImageEncodeError as error:
        raise OSError(f"cannot write ROI debug image: {destination}") from error
    return destination


def _draw_rectangle(
    image: ImageArray,
    roi: PixelRoi,
    *,
    color: tuple[int, int, int],
) -> None:
    cv2.rectangle(image, (roi.x, roi.y), (roi.right - 1, roi.bottom - 1), color, thickness=1)
