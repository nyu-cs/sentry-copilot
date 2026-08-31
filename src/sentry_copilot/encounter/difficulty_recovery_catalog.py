"""Declared private template loader for bounded non-primary Difficulty recovery."""

from __future__ import annotations

from pathlib import Path

from sentry_copilot.image_io import load_bgr_image
from sentry_copilot.vision.difficulty_recovery import DifficultyRecoveryReferencePack
from sentry_copilot.vision.info_1_2 import VisualReference


def load_default_private_difficulty_recovery_references() -> DifficultyRecoveryReferencePack:
    """Load only the explicit private calibration templates; never discover assets."""

    root = Path("data/private/live_validation/post_start_difficulty_calibration/references")
    return DifficultyRecoveryReferencePack(
        post_start_templates=(
            _reference(
                "difficulty.covenant_latter.standard",
                root / "post_start_top_bar/standard_1.png",
            ),
            _reference(
                "difficulty.covenant_latter.standard",
                root / "post_start_top_bar/standard_2.png",
            ),
            _reference(
                "difficulty.covenant_latter.adversity",
                root / "post_start_top_bar/adversity.png",
            ),
            _reference(
                "difficulty.covenant_latter.deadland",
                root / "post_start_top_bar/deadland.png",
            ),
        ),
        operation_splash_templates=(
            _reference(
                "difficulty.covenant_latter.standard",
                root / "operation_splash/standard_1.png",
            ),
            _reference(
                "difficulty.covenant_latter.standard",
                root / "operation_splash/standard_2.png",
            ),
            _reference(
                "difficulty.covenant_latter.adversity",
                root / "operation_splash/adversity_1.png",
            ),
            _reference(
                "difficulty.covenant_latter.adversity",
                root / "operation_splash/adversity_2.png",
            ),
            _reference(
                "difficulty.covenant_latter.deadland",
                root / "operation_splash/deadland_1.png",
            ),
            _reference(
                "difficulty.covenant_latter.deadland",
                root / "operation_splash/deadland_2.png",
            ),
        ),
    )


def _reference(identity_id: str, path: Path) -> VisualReference:
    return VisualReference(identity_id, load_bgr_image(path))
