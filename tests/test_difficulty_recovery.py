from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.vision.difficulty_recovery import (
    OPERATION_SPLASH_DIFFICULTY_ROI,
    POST_START_DIFFICULTY_ROI,
    DifficultyRecoveryReferencePack,
    DifficultyRecoveryState,
    observe_jp_mumu_operation_splash_difficulty,
    observe_jp_mumu_post_start_difficulty,
)
from sentry_copilot.vision.info_1_2 import INFO_DIFFICULTY_IDS, VisualReference
from sentry_copilot.vision.viewport import ContentViewport


def _image(index: int, *, size: tuple[int, int]) -> np.ndarray:
    height, width = size[1], size[0]
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :: index + 2] = 40 + index * 55
    image[10 + index * 5 : 50 + index * 7, 20 + index * 11 : 90 + index * 13] = (
        255,
        255 - index * 40,
        80 + index * 40,
    )
    return image


def _frame(index: int, image: np.ndarray | None = None) -> Frame:
    payload = np.zeros((1080, 1920, 3), dtype=np.uint8) if image is None else image
    return Frame(
        frame_id=f"difficulty-recovery:{index}",
        frame_index=index,
        processed_at=datetime(2026, 8, 30, tzinfo=UTC),
        source_timestamp=None,
        source_type=FrameSourceType.WINDOWS_DISPLAY,
        source_id="synthetic",
        source_reference="synthetic",
        width=1920,
        height=1080,
        image=payload,
    )


def _pack() -> DifficultyRecoveryReferencePack:
    post = tuple(
        VisualReference(
            identity_id,
            _image(
                index,
                size=(POST_START_DIFFICULTY_ROI.width, POST_START_DIFFICULTY_ROI.height),
            ),
        )
        for index, identity_id in enumerate(INFO_DIFFICULTY_IDS)
    )
    operation = tuple(
        VisualReference(
            identity_id,
            _image(
                index,
                size=(
                    OPERATION_SPLASH_DIFFICULTY_ROI.width,
                    OPERATION_SPLASH_DIFFICULTY_ROI.height,
                ),
            ),
        )
        for index, identity_id in enumerate(INFO_DIFFICULTY_IDS)
    )
    return DifficultyRecoveryReferencePack(post, operation)


def test_post_start_reference_pack_requires_all_four_logical_identities() -> None:
    valid = _pack()

    assert len(valid.post_start_templates) == 4
    assert {item.identity_id for item in valid.post_start_templates} == set(INFO_DIFFICULTY_IDS)

    with pytest.raises(ValueError, match="all four supported identities"):
        DifficultyRecoveryReferencePack(
            valid.post_start_templates[:-1], valid.operation_splash_templates
        )


def test_post_start_reference_pack_allows_duplicate_physical_variants() -> None:
    valid = _pack()

    pack = DifficultyRecoveryReferencePack(
        (valid.post_start_templates[0],) + valid.post_start_templates,
        valid.operation_splash_templates,
    )

    assert len(pack.post_start_templates) == 5
    assert {item.identity_id for item in pack.post_start_templates} == set(INFO_DIFFICULTY_IDS)


def test_operation_reference_pack_keeps_its_existing_independent_contract() -> None:
    valid = _pack()

    DifficultyRecoveryReferencePack(
        valid.post_start_templates, valid.operation_splash_templates[:2]
    )


def _with_roi(frame: Frame, roi_x: int, roi_y: int, image: np.ndarray) -> Frame:
    payload = np.array(frame.image, copy=True)
    height, width = image.shape[:2]
    payload[roi_y : roi_y + height, roi_x : roi_x + width] = image
    return frame.model_copy(update={"image": payload}) if hasattr(frame, "model_copy") else Frame(
        frame_id=frame.frame_id,
        frame_index=frame.frame_index,
        processed_at=frame.processed_at,
        source_timestamp=frame.source_timestamp,
        source_type=frame.source_type,
        source_id=frame.source_id,
        source_reference=frame.source_reference,
        width=frame.width,
        height=frame.height,
        image=payload,
    )


def test_post_start_ranks_a_visible_top_bar_as_a_candidate_without_a_local_gate() -> None:
    pack = _pack()
    frame = _with_roi(
        _frame(1),
        POST_START_DIFFICULTY_ROI.x,
        POST_START_DIFFICULTY_ROI.y,
        pack.post_start_templates[1].image,
    )

    present = observe_jp_mumu_post_start_difficulty(frame, ContentViewport.full_frame(frame), pack)
    absent_frame = _frame(2)
    absent = observe_jp_mumu_post_start_difficulty(
        absent_frame, ContentViewport.full_frame(absent_frame), pack
    )

    assert present.state is DifficultyRecoveryState.CANDIDATE
    assert present.candidate_id == INFO_DIFFICULTY_IDS[1]
    assert absent.state is DifficultyRecoveryState.CANDIDATE
    assert absent.candidate_id is not None


def test_operation_splash_ranks_the_central_panel() -> None:
    pack = _pack()
    frame = _with_roi(
        _frame(3),
        OPERATION_SPLASH_DIFFICULTY_ROI.x,
        OPERATION_SPLASH_DIFFICULTY_ROI.y,
        pack.operation_splash_templates[2].image,
    )

    observation = observe_jp_mumu_operation_splash_difficulty(
        frame, ContentViewport.full_frame(frame), pack
    )

    assert observation.state is DifficultyRecoveryState.RELIABLE
    assert observation.reliable_id == INFO_DIFFICULTY_IDS[2]


def test_operation_splash_can_add_a_calibrated_identity_without_post_start_support() -> None:
    base = _pack()
    ultimate_id = "difficulty.covenant_latter.ultimate"
    ultimate = VisualReference(
        ultimate_id,
        _image(
            3,
            size=(
                OPERATION_SPLASH_DIFFICULTY_ROI.width,
                OPERATION_SPLASH_DIFFICULTY_ROI.height,
            ),
        ),
    )
    pack = DifficultyRecoveryReferencePack(
        base.post_start_templates,
        base.operation_splash_templates + (ultimate,),
    )
    frame = _with_roi(
        _frame(4),
        OPERATION_SPLASH_DIFFICULTY_ROI.x,
        OPERATION_SPLASH_DIFFICULTY_ROI.y,
        ultimate.image,
    )

    observation = observe_jp_mumu_operation_splash_difficulty(
        frame, ContentViewport.full_frame(frame), pack
    )

    assert observation.state is DifficultyRecoveryState.RELIABLE
    assert observation.reliable_id == ultimate_id
