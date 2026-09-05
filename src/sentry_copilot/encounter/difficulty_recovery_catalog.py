"""Declared private template loader for bounded non-primary Difficulty recovery."""

from __future__ import annotations

from pathlib import Path

from sentry_copilot.image_io import load_bgr_image
from sentry_copilot.vision.difficulty_recovery import (
    POST_START_DIFFICULTY_ROI,
    DifficultyRecoveryReferencePack,
)
from sentry_copilot.vision.info_1_2 import VisualReference


def load_default_private_difficulty_recovery_references() -> DifficultyRecoveryReferencePack:
    """Load only the explicit private calibration templates; never discover assets."""

    return DifficultyRecoveryReferencePack(
        post_start_templates=(
            _post_start_reference(
                "difficulty.covenant_latter.standard",
                Path("data/private/live_validation/intel_recovery_source_correction/standard_solo/00-00-13-000_t13.png"),
            ),
            _post_start_reference(
                "difficulty.covenant_latter.standard",
                Path("data/private/live_validation/intel_recovery_source_correction/standard_coop4/00-00-40-000_t40.png"),
            ),
            _post_start_reference(
                "difficulty.covenant_latter.adversity",
                Path("data/private/live_validation/intel_recovery_source_correction/adversity_solo/00-00-15-000_t15.png"),
            ),
            _post_start_reference(
                "difficulty.covenant_latter.deadland",
                Path("data/private/live_validation/intel_recovery_source_correction/deadland_solo/00-00-19-000_t19.png"),
            ),
            _post_start_reference(
                "difficulty.covenant_latter.ultimate",
                Path(
                    "data/private/live_validation/ac4_ultimate_calibration/"
                    "ac4_ultimate_solo_001_2026-09-04_16-12-33/frames/info_2_2/"
                    "00-00-15-000_phase_15_0.png"
                ),
            ),
        ),
        operation_splash_templates=(
            _reference(
                "difficulty.covenant_latter.standard",
                Path("data/private/live_validation/post_start_difficulty_calibration/references/operation_splash/standard_1.png"),
            ),
            _reference(
                "difficulty.covenant_latter.standard",
                Path("data/private/live_validation/post_start_difficulty_calibration/references/operation_splash/standard_2.png"),
            ),
            _reference(
                "difficulty.covenant_latter.adversity",
                Path("data/private/live_validation/post_start_difficulty_calibration/references/operation_splash/adversity_1.png"),
            ),
            _reference(
                "difficulty.covenant_latter.adversity",
                Path("data/private/live_validation/post_start_difficulty_calibration/references/operation_splash/adversity_2.png"),
            ),
            _reference(
                "difficulty.covenant_latter.deadland",
                Path("data/private/live_validation/post_start_difficulty_calibration/references/operation_splash/deadland_1.png"),
            ),
            _reference(
                "difficulty.covenant_latter.deadland",
                Path("data/private/live_validation/post_start_difficulty_calibration/references/operation_splash/deadland_2.png"),
            ),
            _reference(
                "difficulty.covenant_latter.ultimate",
                Path("data/private/live_validation/post_start_difficulty_calibration/references/operation_splash/ultimate_1.png"),
            ),
        ),
    )


def _reference(identity_id: str, path: Path) -> VisualReference:
    return VisualReference(identity_id, load_bgr_image(path))


def _post_start_reference(identity_id: str, path: Path) -> VisualReference:
    """Crop each frozen full-frame post-start physical reference to its INFO ROI."""

    image = load_bgr_image(path)
    roi = POST_START_DIFFICULTY_ROI
    return VisualReference(identity_id, image[roi.y : roi.bottom, roi.x : roi.right])
