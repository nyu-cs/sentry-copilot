from __future__ import annotations

from datetime import UTC, datetime

import cv2
import numpy as np
import pytest

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.vision.info_1_2 import (
    EnemyVisualReference,
    Info12ReferencePack,
    VisualReference,
)
from sentry_copilot.vision.returned_info_recovery import (
    RETURNED_INFO_BOSS_ROI,
    RETURNED_INFO_ENEMY_SLOT_ROIS,
    ReturnedInfoBossState,
    ReturnedInfoEnemyState,
    classify_returned_info_enemy_slot_layout,
    observe_jp_mumu_returned_info_boss,
    observe_jp_mumu_returned_info_enemy,
)
from sentry_copilot.vision.viewport import ContentViewport


def _image(index: int) -> np.ndarray:
    image = np.zeros(
        (RETURNED_INFO_BOSS_ROI.height, RETURNED_INFO_BOSS_ROI.width, 3), dtype=np.uint8
    )
    image[:, :: index + 2] = 35 + index * 25
    image[10 + index * 8 : 90 + index * 8, 18 + index * 12 : 120 + index * 12] = (
        230,
        200 - index * 20,
        50 + index * 20,
    )
    return image


def _references() -> Info12ReferencePack:
    boss = tuple(VisualReference(f"boss.{index}", _image(index)) for index in range(7))
    enemy = np.full((132, 132, 4), 255, dtype=np.uint8)
    return Info12ReferencePack(
        np.zeros((16, 16, 3), dtype=np.uint8),
        boss,
        tuple(EnemyVisualReference(f"enemy.{index}", enemy) for index in range(7)),
    )


def _frame(*, with_boss: bool) -> Frame:
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    if with_boss:
        image[
            RETURNED_INFO_BOSS_ROI.y : RETURNED_INFO_BOSS_ROI.bottom,
            RETURNED_INFO_BOSS_ROI.x : RETURNED_INFO_BOSS_ROI.right,
        ] = _references().bosses[0].image
    return Frame(
        frame_id="returned-info:000001",
        frame_index=1,
        processed_at=datetime(2026, 8, 30, tzinfo=UTC),
        source_timestamp=None,
        source_type=FrameSourceType.WINDOWS_DISPLAY,
        source_id="synthetic-display",
        width=1920,
        height=1080,
        image=image,
        source_reference="synthetic-display",
    )


def test_returned_info_boss_uses_existing_logical_references_with_returned_specific_gate() -> None:
    frame = _frame(with_boss=True)

    observation = observe_jp_mumu_returned_info_boss(
        frame, ContentViewport.full_frame(frame), _references()
    )

    assert observation.state is ReturnedInfoBossState.RELIABLE
    assert observation.reliable_id == "boss.0"
    assert observation.ranking[0].score == pytest.approx(1.0)


def test_returned_info_boss_does_not_treat_a_blank_crop_as_reliable() -> None:
    frame = _frame(with_boss=False)

    observation = observe_jp_mumu_returned_info_boss(
        frame, ContentViewport.full_frame(frame), _references()
    )

    assert observation.state is ReturnedInfoBossState.UNRESOLVED
    assert observation.reliable_id is None


def _enemy_image(index: int) -> np.ndarray:
    image = np.zeros((132, 132, 4), dtype=np.uint8)
    pattern = np.random.default_rng(index).integers(0, 2, (16, 16), dtype=np.uint8) * 255
    pattern[0, 0] = 255
    image[20:116, 18:114, :3] = cv2.resize(pattern, (96, 96), interpolation=cv2.INTER_NEAREST)[
        :, :, None
    ]
    image[20:116, 18:114, 3] = cv2.resize(pattern, (96, 96), interpolation=cv2.INTER_NEAREST)
    return image


def _enemy_references() -> Info12ReferencePack:
    return Info12ReferencePack(
        np.zeros((16, 16, 3), dtype=np.uint8),
        _references().bosses,
        tuple(EnemyVisualReference(f"enemy.{index}", _enemy_image(index)) for index in range(7)),
    )


def _enemy_frame(indices: tuple[int, ...], *, third_ratio: float | None = None) -> Frame:
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    references = _enemy_references()
    for index, roi in zip(indices, RETURNED_INFO_ENEMY_SLOT_ROIS[: len(indices)], strict=True):
        image[roi.y : roi.bottom, roi.x : roi.right] = cv2.resize(
            references.enemy_categories[index].image[:, :, :3],
            (roi.width, roi.height),
            interpolation=cv2.INTER_NEAREST,
        )
    if third_ratio is not None:
        roi = RETURNED_INFO_ENEMY_SLOT_ROIS[2]
        pixels = int(roi.width * roi.height * third_ratio)
        image[roi.y : roi.y + max(1, pixels // roi.width), roi.x : roi.right] = 255
    return Frame(
        frame_id="returned-info:enemy",
        frame_index=2,
        processed_at=datetime(2026, 8, 30, tzinfo=UTC),
        source_timestamp=None,
        source_type=FrameSourceType.WINDOWS_DISPLAY,
        source_id="synthetic",
        width=1920,
        height=1080,
        image=image,
        source_reference="synthetic",
    )


def test_returned_enemy_observer_resolves_two_and_three_slot_sets() -> None:
    references = _enemy_references()
    two = _enemy_frame((0, 1))
    three = _enemy_frame((0, 1, 2))
    known = frozenset(f"enemy.{index}" for index in range(7))

    two_observation = observe_jp_mumu_returned_info_enemy(
        two, ContentViewport.full_frame(two), references, known
    )
    three_observation = observe_jp_mumu_returned_info_enemy(
        three, ContentViewport.full_frame(three), references, known
    )

    assert two_observation.state is ReturnedInfoEnemyState.RELIABLE
    assert two_observation.slot_layout.value == "two_slot"
    assert two_observation.complete_candidate == ("enemy.0", "enemy.1")
    assert three_observation.state is ReturnedInfoEnemyState.RELIABLE
    assert three_observation.slot_layout.value == "three_slot"
    assert three_observation.complete_candidate == ("enemy.0", "enemy.1", "enemy.2")


def test_returned_enemy_observer_rejects_uncertain_duplicate_and_unknown_candidates() -> None:
    references = _enemy_references()
    uncertain = _enemy_frame((0, 1), third_ratio=0.05)
    duplicate = _enemy_frame((0, 0))
    known = frozenset({"enemy.0"})

    assert classify_returned_info_enemy_slot_layout(0.01).value == "two_slot"
    assert classify_returned_info_enemy_slot_layout(0.05).value == "unresolved"
    assert classify_returned_info_enemy_slot_layout(0.10).value == "three_slot"
    assert observe_jp_mumu_returned_info_enemy(
        uncertain,
        ContentViewport.full_frame(uncertain),
        references,
        frozenset({"enemy.0", "enemy.1"}),
    ).complete_candidate is None
    assert observe_jp_mumu_returned_info_enemy(
        duplicate,
        ContentViewport.full_frame(duplicate),
        references,
        frozenset({"enemy.0", "enemy.1"}),
    ).complete_candidate is None
    assert observe_jp_mumu_returned_info_enemy(
        _enemy_frame((0, 1)), ContentViewport.full_frame(_enemy_frame((0, 1))), references, known
    ).complete_candidate is None
