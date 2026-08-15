"""Vision-side geometry and provider interfaces with no domain-state mutation."""

from .ocr import (
    OcrBackend,
    OcrBackendError,
    OcrBackendReading,
    OcrBackendUnavailableError,
    OcrResult,
    OcrStatus,
    WindowsOcrBackend,
    WindowsOcrRuntime,
    WinRtWindowsOcrRuntime,
    recognize_text,
)
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
    "OcrBackend",
    "OcrBackendError",
    "OcrBackendReading",
    "OcrBackendUnavailableError",
    "OcrResult",
    "OcrStatus",
    "WinRtWindowsOcrRuntime",
    "WindowsOcrBackend",
    "WindowsOcrRuntime",
    "recognize_text",
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
