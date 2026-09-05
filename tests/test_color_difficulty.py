from __future__ import annotations

import cv2
import numpy as np
import pytest

from sentry_copilot.vision.color_difficulty import (
    COLOR_DIFFICULTY_SATURATION_MINIMUM,
    COLOR_DIFFICULTY_SIZE,
    COLOR_DIFFICULTY_VALUE_MINIMUM,
    frozen_color_difficulty_representation,
    frozen_color_zncc,
)
from sentry_copilot.vision.info_1_2 import VisualReference, _rank_frozen_color_difficulty


def _bgr_for_hsv(hue: int, saturation: int = 255, value: int = 255) -> np.ndarray:
    hsv = np.full((70, 220, 3), (hue, saturation, value), dtype=np.uint8)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


def test_feature_uses_inclusive_original_resolution_hsv_foreground_mask() -> None:
    at_boundary = _bgr_for_hsv(
        10, COLOR_DIFFICULTY_SATURATION_MINIMUM, COLOR_DIFFICULTY_VALUE_MINIMUM
    )
    below_saturation = _bgr_for_hsv(10, COLOR_DIFFICULTY_SATURATION_MINIMUM - 20, 255)
    below_value = _bgr_for_hsv(10, 255, COLOR_DIFFICULTY_VALUE_MINIMUM - 20)

    representation, foreground = frozen_color_difficulty_representation(at_boundary[:, :178])

    assert representation.shape == (COLOR_DIFFICULTY_SIZE[1], COLOR_DIFFICULTY_SIZE[0], 3)
    assert foreground == pytest.approx(1.0)
    assert frozen_color_difficulty_representation(below_saturation[:, :178])[1] == 0.0
    assert frozen_color_difficulty_representation(below_value[:, :178])[1] == 0.0


def test_feature_converts_hue_to_circular_planes_before_interpolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = _bgr_for_hsv(179)
    observed: list[np.ndarray] = []
    original_resize = cv2.resize

    def capture_resize(
        source: np.ndarray, size: tuple[int, int], *, interpolation: int
    ) -> np.ndarray:
        observed.append(np.array(source, copy=True))
        return original_resize(source, size, interpolation=interpolation)

    monkeypatch.setattr(cv2, "resize", capture_resize)

    frozen_color_difficulty_representation(image[:, :178])

    assert len(observed) == 1
    assert observed[0].shape == (70, 178, 3)
    assert observed[0].dtype == np.float32
    assert observed[0][:, :, 0].mean() < 0.0  # sin(near 2π), not interpolated raw hue.


def test_zncc_returns_zero_for_zero_denominator() -> None:
    constant = np.ones((64, 128, 3), dtype=np.float32)

    assert frozen_color_zncc(constant, constant) == 0.0


def test_ranking_collapses_duplicate_physical_templates_by_logical_max() -> None:
    standard = _bgr_for_hsv(10)
    alternate_standard = _bgr_for_hsv(20)
    adversity = _bgr_for_hsv(50)
    deadland = _bgr_for_hsv(90)
    ultimate = _bgr_for_hsv(140)
    references = (
        VisualReference("difficulty.covenant_latter.standard", standard),
        VisualReference("difficulty.covenant_latter.standard", alternate_standard),
        VisualReference("difficulty.covenant_latter.adversity", adversity),
        VisualReference("difficulty.covenant_latter.deadland", deadland),
        VisualReference("difficulty.covenant_latter.ultimate", ultimate),
    )

    ranking = _rank_frozen_color_difficulty(alternate_standard, references)

    assert len(ranking) == 4
    assert ranking[0].identity_id == "difficulty.covenant_latter.standard"
    assert ranking[0].score == pytest.approx(1.0)
