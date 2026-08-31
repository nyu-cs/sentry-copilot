"""Fixed-layout page-presence evidence for bounded INFO recovery reminders."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import cv2

from sentry_copilot.capture.frame_source import Frame, ImageArray
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi

JP_MUMU_INFO_RECOVERY_PAGES_PROFILE_ID = "jp_mumu_fullscreen_1920x1080.info_recovery_pages.v1"
INFO_2_2_PHASE_LABEL_ROI = PixelRoi(535, 28, 355, 90)
INFO_2_2_PHASE_THRESHOLD = 0.995
RETURNED_INFO_HEADER_ROI = PixelRoi(50, 110, 850, 70)
RETURNED_INFO_HEADER_THRESHOLD = 0.80


class InfoRecoveryPageState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class InfoRecoveryPageReferencePack:
    """Explicit, caller-loaded templates for the bounded JP MuMu recovery pages."""

    phase_2_2_label: ImageArray
    returned_info_header: ImageArray

    def __post_init__(self) -> None:
        _validate_reference(self.phase_2_2_label, INFO_2_2_PHASE_LABEL_ROI, "2/2 phase label")
        _validate_reference(
            self.returned_info_header,
            RETURNED_INFO_HEADER_ROI,
            "returned-info header",
        )


@dataclass(frozen=True)
class InfoRecoveryPageObservation:
    """Immutable page-presence evidence; it never owns encounter lifecycle or facts."""

    state: InfoRecoveryPageState
    frame_id: str
    score: float | None


def observe_jp_mumu_info_2_2_phase(
    frame: Frame,
    viewport: ContentViewport,
    references: InfoRecoveryPageReferencePack | None,
) -> InfoRecoveryPageObservation:
    """Observe the complete ``2/2 戦術選択`` phase label only."""

    return _observe(
        frame,
        viewport,
        references,
        INFO_2_2_PHASE_LABEL_ROI,
        INFO_2_2_PHASE_THRESHOLD,
        None if references is None else references.phase_2_2_label,
    )


def observe_jp_mumu_returned_info_page(
    frame: Frame,
    viewport: ContentViewport,
    references: InfoRecoveryPageReferencePack | None,
) -> InfoRecoveryPageObservation:
    """Observe the returned INFO core-only page for reminder suppression only."""

    return _observe(
        frame,
        viewport,
        references,
        RETURNED_INFO_HEADER_ROI,
        RETURNED_INFO_HEADER_THRESHOLD,
        None if references is None else references.returned_info_header,
    )


def crop_info_recovery_page_reference(image: ImageArray, roi: PixelRoi) -> ImageArray:
    """Copy one calibrated full-frame ROI into its explicit observer reference geometry."""

    if image.shape[0] < roi.bottom or image.shape[1] < roi.right:
        raise ValueError("INFO recovery page reference image is smaller than the calibrated ROI")
    return image[roi.y : roi.bottom, roi.x : roi.right].copy()


def _observe(
    frame: Frame,
    viewport: ContentViewport,
    references: InfoRecoveryPageReferencePack | None,
    roi: PixelRoi,
    threshold: float,
    reference: ImageArray | None,
) -> InfoRecoveryPageObservation:
    if (
        references is None
        or reference is None
        or (frame.width, frame.height) != (1920, 1080)
        or viewport.pixel_roi != PixelRoi(0, 0, 1920, 1080)
    ):
        return InfoRecoveryPageObservation(InfoRecoveryPageState.UNRESOLVED, frame.frame_id, None)
    score = _ncc(_crop(frame, roi), reference)
    return InfoRecoveryPageObservation(
        InfoRecoveryPageState.PRESENT if score >= threshold else InfoRecoveryPageState.ABSENT,
        frame.frame_id,
        score,
    )


def _validate_reference(image: ImageArray, roi: PixelRoi, label: str) -> None:
    if image.shape != (roi.height, roi.width, 3):
        raise ValueError(f"{label} reference must be a BGR crop matching its calibrated ROI")


def _ncc(query: ImageArray, reference: ImageArray) -> float:
    left = cv2.resize(cv2.cvtColor(query, cv2.COLOR_BGR2GRAY), (128, 128))
    right = cv2.resize(cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY), (128, 128))
    return float(cv2.matchTemplate(left, right, cv2.TM_CCOEFF_NORMED)[0, 0])


def _crop(frame: Frame, roi: PixelRoi) -> ImageArray:
    return frame.image[roi.y : roi.bottom, roi.x : roi.right]
