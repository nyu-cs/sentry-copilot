"""Source-neutral OpenCV template matching over explicitly supplied frame regions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from sentry_copilot.capture.frame_source import Frame, ImageArray
from sentry_copilot.vision.viewport import ContentViewport, NormalizedRoi, PixelRoi

type SearchRoi = NormalizedRoi | PixelRoi


@dataclass(frozen=True)
class TemplateImage:
    """A caller-supplied immutable BGR template with opaque caller-defined provenance."""

    template_id: str
    image: ImageArray

    def __post_init__(self) -> None:
        if not self.template_id.strip():
            raise ValueError("template_id must not be blank")
        if self.image.dtype != np.uint8 or self.image.ndim != 3 or self.image.shape[2] != 3:
            raise ValueError("template image must be a uint8 BGR image")
        if self.image.shape[0] <= 0 or self.image.shape[1] <= 0:
            raise ValueError("template image must not be empty")
        image = np.array(self.image, dtype=np.uint8, copy=True)
        image.setflags(write=False)
        object.__setattr__(self, "image", image)


@dataclass(frozen=True)
class TemplateMatchResult:
    """Immutable evidence-free result of one template search against one frame region."""

    frame_id: str
    frame_index: int
    source_id: str
    source_reference: str
    template_id: str
    search_bounds: PixelRoi
    threshold: float
    score: float
    matched: bool
    match_bounds: PixelRoi | None
    debug_output_path: Path | None = None


def match_template(
    frame: Frame,
    viewport: ContentViewport,
    roi: SearchRoi,
    template: TemplateImage,
    *,
    threshold: float = 0.9,
    debug_output_path: str | Path | None = None,
) -> TemplateMatchResult:
    """Match a caller-provided BGR template in an explicit content-relative search region."""

    if not -1.0 <= threshold <= 1.0:
        raise ValueError("threshold must be between -1.0 and 1.0")
    viewport.validate_frame(frame)
    search_bounds = _resolve_search_bounds(viewport, roi)
    search_image = frame.image[
        search_bounds.y : search_bounds.bottom, search_bounds.x : search_bounds.right
    ]
    template_height, template_width = template.image.shape[:2]
    if template_width > search_bounds.width or template_height > search_bounds.height:
        raise ValueError("template dimensions must fit inside the search ROI")

    scores = cv2.matchTemplate(search_image, template.image, cv2.TM_CCOEFF_NORMED)
    _, score, _, location = cv2.minMaxLoc(scores)
    match_bounds = PixelRoi(
        x=search_bounds.x + location[0],
        y=search_bounds.y + location[1],
        width=template_width,
        height=template_height,
    )
    result = TemplateMatchResult(
        frame_id=frame.frame_id,
        frame_index=frame.frame_index,
        source_id=frame.source_id,
        source_reference=frame.source_reference,
        template_id=template.template_id,
        search_bounds=search_bounds,
        threshold=threshold,
        score=float(score),
        matched=score >= threshold,
        match_bounds=match_bounds,
        debug_output_path=Path(debug_output_path) if debug_output_path is not None else None,
    )
    if result.debug_output_path is not None:
        save_template_match_debug(frame, viewport, result, result.debug_output_path)
    return result


def save_template_match_debug(
    frame: Frame,
    viewport: ContentViewport,
    result: TemplateMatchResult,
    output_path: str | Path,
) -> Path:
    """Write a caller-requested annotated copy; never alter the source frame payload."""

    viewport.validate_frame(frame)
    if result.frame_id != frame.frame_id:
        raise ValueError("template match result belongs to a different frame")
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image = np.array(frame.image, dtype=np.uint8, copy=True)
    _draw_rectangle(image, viewport.pixel_roi, color=(0, 200, 0))
    _draw_rectangle(image, result.search_bounds, color=(255, 200, 0))
    if result.match_bounds is not None:
        color = (0, 255, 0) if result.matched else (0, 0, 255)
        _draw_rectangle(image, result.match_bounds, color=color)
    if not cv2.imwrite(str(destination), image):
        raise OSError(f"cannot write template-match debug image: {destination}")
    return destination


def _resolve_search_bounds(viewport: ContentViewport, roi: SearchRoi) -> PixelRoi:
    if isinstance(roi, NormalizedRoi):
        return roi.resolve(viewport)
    content = viewport.pixel_roi
    if (
        roi.x < content.x
        or roi.y < content.y
        or roi.right > content.right
        or roi.bottom > content.bottom
    ):
        raise ValueError("pixel search ROI must stay within the content viewport")
    return roi


def _draw_rectangle(
    image: ImageArray,
    roi: PixelRoi,
    *,
    color: tuple[int, int, int],
) -> None:
    cv2.rectangle(image, (roi.x, roi.y), (roi.right - 1, roi.bottom - 1), color, thickness=1)
