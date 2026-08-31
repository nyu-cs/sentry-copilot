from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

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


def test_post_start_ranks_a_visible_top_bar_and_rejects_an_absent_region() -> None:
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

    assert present.state is DifficultyRecoveryState.RELIABLE
    assert present.reliable_id == INFO_DIFFICULTY_IDS[1]
    assert absent.state is DifficultyRecoveryState.UNRESOLVED
    assert absent.reliable_id is None


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
