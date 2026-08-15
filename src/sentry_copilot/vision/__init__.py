"""Vision-side geometry and provider interfaces with no domain-state mutation."""

from .template_matching import (
    TemplateImage,
    TemplateMatchResult,
    match_template,
    save_template_match_debug,
)
from .validation_runner import (
    NamedNormalizedRoi,
    OfflineValidationConfig,
    OfflineValidationResult,
    frame_source_from_path,
    parse_named_roi,
    run_offline_validation,
)
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
    "NamedNormalizedRoi",
    "OfflineValidationConfig",
    "OfflineValidationResult",
    "frame_source_from_path",
    "parse_named_roi",
    "run_offline_validation",
    "TemplateImage",
    "TemplateMatchResult",
    "match_template",
    "save_template_match_debug",
]
