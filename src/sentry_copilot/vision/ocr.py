"""Source-neutral OCR over explicitly supplied frame regions.

This foundation deliberately recognizes only caller-selected pixels.  It provides no game text
parsing, screen semantics, or domain-state mutation.
"""

from __future__ import annotations

import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

import numpy as np

from sentry_copilot.capture.frame_source import Frame, FrameSourceType, ImageArray
from sentry_copilot.vision.viewport import ContentViewport, NormalizedRoi, PixelRoi

type OcrRoi = NormalizedRoi | PixelRoi


class OcrStatus(StrEnum):
    """Whether a backend recognized text, explicitly found none, or could not determine it."""

    RECOGNIZED = "recognized"
    EMPTY = "empty"
    UNKNOWN = "unknown"


class WindowsOcrCapabilityStatus(StrEnum):
    """Availability of a requested Windows OCR language capability."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class OcrBackendError(RuntimeError):
    """A typed failure from an explicitly selected OCR backend."""


class OcrBackendUnavailableError(OcrBackendError):
    """The selected backend or requested language is unavailable on this machine."""


@dataclass(frozen=True)
class WindowsOcrLanguageCapability:
    """Immutable local capability check without installing or changing Windows features."""

    language_tag: str
    status: WindowsOcrCapabilityStatus
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.language_tag.strip():
            raise ValueError("language_tag must not be blank")
        if self.status is WindowsOcrCapabilityStatus.AVAILABLE and self.reason is not None:
            raise ValueError("available Windows OCR capability must not contain a reason")
        if self.status is WindowsOcrCapabilityStatus.UNAVAILABLE and not self.reason:
            raise ValueError("unavailable Windows OCR capability must contain a reason")

    @property
    def available(self) -> bool:
        """Whether the requested system OCR capability is ready for use."""

        return self.status is WindowsOcrCapabilityStatus.AVAILABLE


def check_windows_ocr_language(language_tag: str) -> WindowsOcrLanguageCapability:
    """Check one local Windows OCR language without installing any language capability."""

    if not language_tag.strip():
        raise ValueError("language_tag must not be blank")
    if sys.platform != "win32":
        return WindowsOcrLanguageCapability(
            language_tag=language_tag,
            status=WindowsOcrCapabilityStatus.UNAVAILABLE,
            reason="Windows OCR is available only on Windows",
        )
    try:
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
    except ModuleNotFoundError:
        return WindowsOcrLanguageCapability(
            language_tag=language_tag,
            status=WindowsOcrCapabilityStatus.UNAVAILABLE,
            reason="Windows OCR Python/WinRT bindings are not installed",
        )

    if OcrEngine.is_language_supported(Language(language_tag)):
        return WindowsOcrLanguageCapability(
            language_tag=language_tag,
            status=WindowsOcrCapabilityStatus.AVAILABLE,
        )
    return WindowsOcrLanguageCapability(
        language_tag=language_tag,
        status=WindowsOcrCapabilityStatus.UNAVAILABLE,
        reason=(
            f"Windows OCR language is unavailable: {language_tag}. "
            "Install the matching Windows OCR language capability."
        ),
    )


@dataclass(frozen=True)
class OcrBackendReading:
    """Backend text before common normalization; ``None`` means unknown, not an empty result."""

    raw_text: str | None
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("OCR confidence must be between 0.0 and 1.0")


class OcrBackend(Protocol):
    """Minimal async adapter for an OCR engine over one immutable BGR crop."""

    async def recognize(self, image: ImageArray, *, language_tag: str) -> OcrBackendReading:
        """Recognize only the supplied immutable BGR crop."""


@dataclass(frozen=True)
class OcrResult:
    """Immutable OCR output and complete source/geometry provenance for one crop."""

    frame_id: str
    frame_index: int
    processed_at: datetime
    source_timestamp: timedelta | None
    source_type: FrameSourceType
    source_id: str
    source_reference: str
    language_tag: str
    pixel_bounds: PixelRoi
    raw_text: str | None
    normalized_text: str | None
    confidence: float | None
    status: OcrStatus

    def __post_init__(self) -> None:
        if not (
            self.frame_id.strip()
            and self.source_id.strip()
            and self.source_reference.strip()
        ):
            raise ValueError("OCR provenance text fields must not be blank")
        if self.frame_index < 0:
            raise ValueError("frame_index must be non-negative")
        if self.processed_at.tzinfo is None or self.processed_at.utcoffset() is None:
            raise ValueError("processed_at must be timezone-aware")
        if self.source_timestamp is not None and self.source_timestamp.total_seconds() < 0:
            raise ValueError("source_timestamp must be non-negative")
        if not self.language_tag.strip():
            raise ValueError("language_tag must not be blank")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("OCR confidence must be between 0.0 and 1.0")
        if self.status is OcrStatus.UNKNOWN:
            if self.raw_text is not None or self.normalized_text is not None:
                raise ValueError("unknown OCR result must not contain text")
        elif self.status is OcrStatus.EMPTY:
            if self.raw_text is None or self.normalized_text != "":
                raise ValueError("empty OCR result must contain only empty normalized text")
        elif self.raw_text is None or not self.normalized_text:
            raise ValueError("recognized OCR result must contain normalized text")


async def recognize_text(
    frame: Frame,
    viewport: ContentViewport,
    roi: OcrRoi,
    backend: OcrBackend,
    *,
    language_tag: str = "ja-JP",
) -> OcrResult:
    """Recognize text only inside a caller-supplied content-relative ROI."""

    if not language_tag.strip():
        raise ValueError("language_tag must not be blank")
    viewport.validate_frame(frame)
    pixel_bounds = _resolve_roi(viewport, roi)
    crop = np.array(
        frame.image[pixel_bounds.y : pixel_bounds.bottom, pixel_bounds.x : pixel_bounds.right],
        dtype=np.uint8,
        copy=True,
    )
    crop.setflags(write=False)
    reading = await backend.recognize(crop, language_tag=language_tag)
    normalized_text = _normalize_text(reading.raw_text)
    status = _status_for(reading.raw_text, normalized_text)
    return OcrResult(
        frame_id=frame.frame_id,
        frame_index=frame.frame_index,
        processed_at=frame.processed_at,
        source_timestamp=frame.source_timestamp,
        source_type=frame.source_type,
        source_id=frame.source_id,
        source_reference=frame.source_reference,
        language_tag=language_tag,
        pixel_bounds=pixel_bounds,
        raw_text=reading.raw_text,
        normalized_text=normalized_text,
        confidence=reading.confidence,
        status=status,
    )


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


def _normalize_text(raw_text: str | None) -> str | None:
    if raw_text is None:
        return None
    return " ".join(unicodedata.normalize("NFKC", raw_text).split())


def _status_for(raw_text: str | None, normalized_text: str | None) -> OcrStatus:
    if raw_text is None:
        return OcrStatus.UNKNOWN
    if normalized_text == "":
        return OcrStatus.EMPTY
    return OcrStatus.RECOGNIZED


class WindowsOcrRuntime(Protocol):
    """Narrow seam that lets tests avoid relying on Windows OCR language packs."""

    async def recognize(self, image: ImageArray, language_tag: str) -> OcrBackendReading:
        """Recognize one BGR image using the requested BCP-47 language tag."""


@dataclass(frozen=True)
class WindowsOcrBackend:
    """Windows built-in OCR adapter; requested language support is checked for every call."""

    runtime: WindowsOcrRuntime = field(default_factory=lambda: WinRtWindowsOcrRuntime())

    async def recognize(self, image: ImageArray, *, language_tag: str) -> OcrBackendReading:
        if not language_tag.strip():
            raise ValueError("language_tag must not be blank")
        return await self.runtime.recognize(image, language_tag)


@dataclass(frozen=True)
class WinRtWindowsOcrRuntime:
    """Thin Python/WinRT bridge to the Windows OCR component, without external executables."""

    async def recognize(self, image: ImageArray, language_tag: str) -> OcrBackendReading:
        if sys.platform != "win32":
            raise OcrBackendUnavailableError("Windows OCR is available only on Windows")
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("Windows OCR requires a uint8 BGR image")
        if image.shape[0] <= 0 or image.shape[1] <= 0:
            raise ValueError("Windows OCR image must not be empty")
        try:
            from winrt.windows.globalization import Language
            from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
            from winrt.windows.media.ocr import OcrEngine
            from winrt.windows.storage.streams import DataWriter
        except ModuleNotFoundError as error:
            raise OcrBackendUnavailableError(
                "Windows OCR Python/WinRT bindings are not installed"
            ) from error

        capability = check_windows_ocr_language(language_tag)
        if not capability.available:
            assert capability.reason is not None
            raise OcrBackendUnavailableError(capability.reason)
        language = Language(language_tag)
        engine = OcrEngine.try_create_from_language(language)
        if engine is None:
            raise OcrBackendUnavailableError(f"Windows OCR engine is unavailable: {language_tag}")

        height, width = image.shape[:2]
        bgra = np.empty((height, width, 4), dtype=np.uint8)
        bgra[:, :, :3] = image
        bgra[:, :, 3] = 255
        writer = DataWriter()
        writer.write_bytes(bgra.tobytes())
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            writer.detach_buffer(),
            BitmapPixelFormat.BGRA8,
            width,
            height,
        )
        try:
            result = await engine.recognize_async(bitmap)
        except Exception as error:
            raise OcrBackendError("Windows OCR recognition failed") from error
        finally:
            bitmap.close()
        return OcrBackendReading(raw_text=result.text or None)
