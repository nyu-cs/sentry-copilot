"""Bounded Boss evidence from the JP MuMu returned-INFO core-only page."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import cv2
import numpy as np

from sentry_copilot.capture.frame_source import Frame, ImageArray
from sentry_copilot.vision.info_1_2 import (
    ENEMY_MARGIN_THRESHOLD,
    ENEMY_SCORE_THRESHOLD,
    EnemySlotLayout,
    Info12ReferencePack,
    RankedVisualCandidate,
    _rank_ncc,
    _rank_shape,
    _reliable,
)
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi

JP_MUMU_RETURNED_INFO_RECOVERY_PROFILE_ID = "jp_mumu_fullscreen_1920x1080.returned_info.v1"
RETURNED_INFO_BOSS_ROI = PixelRoi(116, 252, 232, 232)
RETURNED_INFO_BOSS_SCORE_THRESHOLD = 0.44
RETURNED_INFO_BOSS_MARGIN_THRESHOLD = 0.25
RETURNED_INFO_BOSS_CONFIRMATION_COUNT = 2
RETURNED_INFO_ENEMY_SLOT_ROIS = (
    PixelRoi(1119, 284, 160, 137),
    PixelRoi(1348, 280, 157, 147),
    PixelRoi(1584, 288, 138, 139),
)
RETURNED_INFO_ENEMY_TWO_SLOT_RATIO_MAX = 0.01
RETURNED_INFO_ENEMY_THREE_SLOT_RATIO_MIN = 0.10
RETURNED_INFO_ENEMY_CONFIRMATION_COUNT = 2


class ReturnedInfoBossState(StrEnum):
    RELIABLE = "reliable"
    UNRESOLVED = "unresolved"


class ReturnedInfoEnemyState(StrEnum):
    """Whether the returned-info Enemy cards form one complete reliable set."""

    RELIABLE = "reliable"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class ReturnedInfoBossObservation:
    """One returned-page Boss ranking, without page or encounter lifecycle authority."""

    state: ReturnedInfoBossState
    frame_id: str
    ranking: tuple[RankedVisualCandidate, ...] = ()

    @property
    def reliable_id(self) -> str | None:
        return self.ranking[0].identity_id if self.state is ReturnedInfoBossState.RELIABLE else None


@dataclass(frozen=True)
class ReturnedInfoEnemyObservation:
    """One immutable returned-page Enemy layout/ranking observation without session authority."""

    state: ReturnedInfoEnemyState
    frame_id: str
    slot_layout: EnemySlotLayout = EnemySlotLayout.UNRESOLVED
    third_slot_foreground_ratio: float | None = None
    slot_rankings: tuple[tuple[RankedVisualCandidate, ...], ...] = ()
    complete_candidate: tuple[str, ...] | None = None

    @property
    def reliable_ids(self) -> tuple[str, ...]:
        return self.complete_candidate or ()


def observe_jp_mumu_returned_info_boss(
    frame: Frame,
    viewport: ContentViewport,
    references: Info12ReferencePack | None,
) -> ReturnedInfoBossObservation:
    """Rank only the calibrated returned-page Boss card against existing logical references."""

    if (
        references is None
        or (frame.width, frame.height) != (1920, 1080)
        or viewport.pixel_roi != PixelRoi(0, 0, 1920, 1080)
    ):
        return ReturnedInfoBossObservation(ReturnedInfoBossState.UNRESOLVED, frame.frame_id)
    ranking = _rank_ncc(_crop(frame, RETURNED_INFO_BOSS_ROI), references.bosses)
    reliable = (
        len(ranking) >= 2
        and ranking[0].score >= RETURNED_INFO_BOSS_SCORE_THRESHOLD
        and ranking[0].score - ranking[1].score >= RETURNED_INFO_BOSS_MARGIN_THRESHOLD
    )
    return ReturnedInfoBossObservation(
        ReturnedInfoBossState.RELIABLE if reliable else ReturnedInfoBossState.UNRESOLVED,
        frame.frame_id,
        ranking,
    )


def observe_jp_mumu_returned_info_enemy(
    frame: Frame,
    viewport: ContentViewport,
    references: Info12ReferencePack | None,
    known_enemy_ids: frozenset[str],
) -> ReturnedInfoEnemyObservation:
    """Resolve a complete returned-page Enemy set under the approved fixed common geometry."""

    if (
        references is None
        or (frame.width, frame.height) != (1920, 1080)
        or viewport.pixel_roi != PixelRoi(0, 0, 1920, 1080)
    ):
        return ReturnedInfoEnemyObservation(ReturnedInfoEnemyState.UNRESOLVED, frame.frame_id)
    third_slot = _crop(frame, RETURNED_INFO_ENEMY_SLOT_ROIS[2])
    third_slot_gray = cv2.cvtColor(third_slot, cv2.COLOR_BGR2GRAY)
    third_slot_foreground_ratio = float(np.mean(third_slot_gray >= 165))
    layout = classify_returned_info_enemy_slot_layout(third_slot_foreground_ratio)
    slot_rois = (
        RETURNED_INFO_ENEMY_SLOT_ROIS[:2]
        if layout is EnemySlotLayout.TWO_SLOT
        else RETURNED_INFO_ENEMY_SLOT_ROIS
        if layout is EnemySlotLayout.THREE_SLOT
        else ()
    )
    rankings = tuple(
        _rank_shape(_crop(frame, roi), references.enemy_categories) for roi in slot_rois
    )
    candidate = _complete_enemy_candidate(layout, rankings, known_enemy_ids)
    return ReturnedInfoEnemyObservation(
        ReturnedInfoEnemyState.RELIABLE
        if candidate is not None
        else ReturnedInfoEnemyState.UNRESOLVED,
        frame.frame_id,
        layout,
        third_slot_foreground_ratio,
        rankings,
        candidate,
    )


def classify_returned_info_enemy_slot_layout(
    third_slot_foreground_ratio: float,
) -> EnemySlotLayout:
    """Classify only the calibrated returned-page third-slot foreground ratio."""

    if third_slot_foreground_ratio <= RETURNED_INFO_ENEMY_TWO_SLOT_RATIO_MAX:
        return EnemySlotLayout.TWO_SLOT
    if third_slot_foreground_ratio >= RETURNED_INFO_ENEMY_THREE_SLOT_RATIO_MIN:
        return EnemySlotLayout.THREE_SLOT
    return EnemySlotLayout.UNRESOLVED


def _complete_enemy_candidate(
    layout: EnemySlotLayout,
    rankings: tuple[tuple[RankedVisualCandidate, ...], ...],
    known_enemy_ids: frozenset[str],
) -> tuple[str, ...] | None:
    expected_count = 2 if layout is EnemySlotLayout.TWO_SLOT else 3
    if layout is EnemySlotLayout.UNRESOLVED or len(rankings) != expected_count:
        return None
    values = tuple(
        _reliable(ranking, ENEMY_SCORE_THRESHOLD, ENEMY_MARGIN_THRESHOLD) for ranking in rankings
    )
    if any(item is None for item in values):
        return None
    candidate = tuple(item for item in values if item is not None)
    if len(set(candidate)) != expected_count or not set(candidate) <= known_enemy_ids:
        return None
    return candidate


def _crop(frame: Frame, roi: PixelRoi) -> ImageArray:
    return frame.image[roi.y : roi.bottom, roi.x : roi.right]
