"""Explicit private-template loader for the bounded INFO recovery page observers."""

from __future__ import annotations

from pathlib import Path

from sentry_copilot.image_io import load_bgr_image
from sentry_copilot.vision.info_recovery_pages import (
    INFO_2_2_PHASE_LABEL_ROI,
    RETURNED_INFO_HEADER_ROI,
    InfoRecoveryPageReferencePack,
    crop_info_recovery_page_reference,
)


def load_default_private_info_recovery_page_references() -> InfoRecoveryPageReferencePack:
    """Load only declared calibration frames; this loader never discovers files."""

    root = Path("data/private/live_validation/intel_recovery_source_correction")
    return InfoRecoveryPageReferencePack(
        phase_2_2_label=crop_info_recovery_page_reference(
            load_bgr_image(root / "standard_solo/00-00-14-000_t14.png"),
            INFO_2_2_PHASE_LABEL_ROI,
        ),
        returned_info_header=crop_info_recovery_page_reference(
            load_bgr_image(root / "deadland_coop2_returned_info/00-00-19-000_returned_a.png"),
            RETURNED_INFO_HEADER_ROI,
        ),
    )
