from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import numpy as np

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.vision.info_recovery_pages import (
    INFO_2_2_PHASE_LABEL_ROI,
    RETURNED_INFO_HEADER_ROI,
    InfoRecoveryPageReferencePack,
    InfoRecoveryPageState,
    observe_jp_mumu_info_2_2_phase,
    observe_jp_mumu_returned_info_page,
)
from sentry_copilot.vision.viewport import ContentViewport


def _frame(index: int = 0) -> Frame:
    return Frame(
        frame_id=f"recovery-pages:{index}",
        frame_index=index,
        processed_at=datetime(2026, 8, 30, tzinfo=UTC),
        source_timestamp=None,
        source_type=FrameSourceType.WINDOWS_DISPLAY,
        source_id="synthetic-display",
        source_reference="synthetic-display",
        width=1920,
        height=1080,
        image=np.zeros((1080, 1920, 3), dtype=np.uint8),
    )


def _references() -> InfoRecoveryPageReferencePack:
    phase = np.zeros(
        (INFO_2_2_PHASE_LABEL_ROI.height, INFO_2_2_PHASE_LABEL_ROI.width, 3), dtype=np.uint8
    )
    phase[:, ::3] = (180, 90, 40)
    returned = np.zeros(
        (RETURNED_INFO_HEADER_ROI.height, RETURNED_INFO_HEADER_ROI.width, 3), dtype=np.uint8
    )
    returned[::3, :] = (40, 180, 90)
    return InfoRecoveryPageReferencePack(phase, returned)


def _with_roi(frame: Frame, roi_image: np.ndarray, *, returned: bool = False) -> Frame:
    roi = RETURNED_INFO_HEADER_ROI if returned else INFO_2_2_PHASE_LABEL_ROI
    image = frame.image.copy()
    image[roi.y : roi.bottom, roi.x : roi.right] = roi_image
    return replace(frame, image=image)


def test_2_2_phase_observer_accepts_normal_grid_and_strategy_detail_presentations() -> None:
    references = _references()
    normal = _with_roi(_frame(1), references.phase_2_2_label)
    detail = _with_roi(_frame(2), references.phase_2_2_label)

    assert (
        observe_jp_mumu_info_2_2_phase(normal, ContentViewport.full_frame(normal), references).state
        is InfoRecoveryPageState.PRESENT
    )
    assert (
        observe_jp_mumu_info_2_2_phase(detail, ContentViewport.full_frame(detail), references).state
        is InfoRecoveryPageState.PRESENT
    )


def test_2_2_phase_observer_rejects_info_returned_info_and_operation_like_frames() -> None:
    references = _references()
    initial_info = _frame(3)
    returned_info = _with_roi(_frame(4), references.returned_info_header, returned=True)
    operation = _frame(5)

    for frame in (initial_info, returned_info, operation):
        observation = observe_jp_mumu_info_2_2_phase(
            frame, ContentViewport.full_frame(frame), references
        )
        assert observation.state is InfoRecoveryPageState.ABSENT


def test_returned_info_observer_is_high_precision_page_evidence_only() -> None:
    references = _references()
    returned = _with_roi(_frame(6), references.returned_info_header, returned=True)
    absent = _frame(7)

    assert (
        observe_jp_mumu_returned_info_page(
            returned, ContentViewport.full_frame(returned), references
        ).state
        is InfoRecoveryPageState.PRESENT
    )
    assert (
        observe_jp_mumu_returned_info_page(
            absent, ContentViewport.full_frame(absent), references
        ).state
        is InfoRecoveryPageState.ABSENT
    )
