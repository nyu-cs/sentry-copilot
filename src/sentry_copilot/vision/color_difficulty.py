"""Frozen circular-HSV Difficulty identity ranking for authorized INFO surfaces."""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np

from sentry_copilot.capture.frame_source import ImageArray

if TYPE_CHECKING:
    from sentry_copilot.vision.info_1_2 import RankedVisualCandidate, VisualReference

COLOR_DIFFICULTY_SUB_ROI = (0, 0, 178, 70)
COLOR_DIFFICULTY_SIZE = (128, 64)
COLOR_DIFFICULTY_SATURATION_MINIMUM = 80
COLOR_DIFFICULTY_VALUE_MINIMUM = 100


def rank_frozen_color_difficulty(
    query: ImageArray, references: tuple[VisualReference, ...]
) -> tuple[RankedVisualCandidate, ...]:
    """Rank logical IDs by max-over-template frozen circular-HSV spatial ZNCC.

    This is identity evidence only. Page/lifecycle authorization and temporal
    confirmation remain the caller's responsibility; no local acceptance gate
    is intentionally applied here.
    """

    from sentry_copilot.vision.info_1_2 import RankedVisualCandidate

    query_representation, _ = frozen_color_difficulty_representation(_sub_roi(query))
    scores = {
        identity_id: max(
            frozen_color_zncc(
                query_representation,
                frozen_color_difficulty_representation(_sub_roi(item.image))[0],
            )
            for item in references
            if item.identity_id == identity_id
        )
        for identity_id in dict.fromkeys(item.identity_id for item in references)
    }
    return tuple(
        RankedVisualCandidate(identity_id, score)
        for identity_id, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
    )


def frozen_color_difficulty_representation(image: ImageArray) -> tuple[np.ndarray, float]:
    """Encode circular hue before area-resizing the continuous representation."""

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
    hue = hsv[:, :, 0] * (2.0 * np.pi / 180.0)
    saturation = hsv[:, :, 1] / 255.0
    value = hsv[:, :, 2] / 255.0
    foreground = (
        (saturation >= COLOR_DIFFICULTY_SATURATION_MINIMUM / 255.0)
        & (value >= COLOR_DIFFICULTY_VALUE_MINIMUM / 255.0)
    ).astype(np.float32)
    representation = np.dstack(
        (np.sin(hue) * foreground, np.cos(hue) * foreground, saturation * foreground)
    )
    return (
        cv2.resize(representation, COLOR_DIFFICULTY_SIZE, interpolation=cv2.INTER_AREA),
        float(foreground.mean()),
    )


def frozen_color_zncc(left: np.ndarray, right: np.ndarray) -> float:
    """Spatial ZNCC with the frozen zero-denominator behavior."""

    first = left.reshape(-1).astype(np.float32)
    second = right.reshape(-1).astype(np.float32)
    first -= first.mean()
    second -= second.mean()
    denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
    return 0.0 if denominator == 0.0 else float(np.dot(first, second) / denominator)


def _sub_roi(image: ImageArray) -> ImageArray:
    x, y, width, height = COLOR_DIFFICULTY_SUB_ROI
    return image[y : y + height, x : x + width]
