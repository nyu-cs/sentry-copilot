"""Vision-side geometry and provider interfaces with no domain-state mutation."""

from .viewport import (
    ContentViewport,
    NormalizedRoi,
    PixelRoi,
    ResolvedRoiCrop,
    crop_normalized_roi,
    save_roi_debug_image,
)

__all__ = [
    "ContentViewport",
    "NormalizedRoi",
    "PixelRoi",
    "ResolvedRoiCrop",
    "crop_normalized_roi",
    "save_roi_debug_image",
]
