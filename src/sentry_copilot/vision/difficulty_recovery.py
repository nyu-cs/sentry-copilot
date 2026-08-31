"""Bounded template-based Difficulty recovery outside the initial INFO 1/2 page."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import cv2

from sentry_copilot.capture.frame_source import Frame, ImageArray
from sentry_copilot.vision.info_1_2 import (
    INFO_DIFFICULTY_IDS,
    RankedVisualCandidate,
    VisualReference,
)
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi

JP_MUMU_DIFFICULTY_RECOVERY_PROFILE_ID = "jp_mumu_fullscreen_1920x1080.difficulty_recovery.v1"
POST_START_DIFFICULTY_ROI = PixelRoi(145, 35, 220, 70)
OPERATION_SPLASH_DIFFICULTY_ROI = PixelRoi(720, 470, 480, 300)
POST_START_SCORE_THRESHOLD = 0.90
POST_START_MARGIN_THRESHOLD = 0.15
OPERATION_SPLASH_SCORE_THRESHOLD = 0.90
OPERATION_SPLASH_MARGIN_THRESHOLD = 0.15


class DifficultyRecoverySource(StrEnum):
    POST_START_VISUAL = "post_start_visual"
    OPERATION_SPLASH_VISUAL = "operation_splash_visual"


class DifficultyRecoveryState(StrEnum):
    RELIABLE = "reliable"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class DifficultyRecoveryReferencePack:
    """Explicit private templates; duplicate IDs represent calibrated render variants."""

    post_start_templates: tuple[VisualReference, ...]
    operation_splash_templates: tuple[VisualReference, ...]

    def __post_init__(self) -> None:
        for templates, label in (
            (self.post_start_templates, "post-start"),
            (self.operation_splash_templates, "OPERATION splash"),
        ):
            template_ids = {item.identity_id for item in templates}
            if not templates or template_ids != set(INFO_DIFFICULTY_IDS):
                raise ValueError(
                    f"{label} Difficulty templates must cover exactly the supported IDs"
                )


@dataclass(frozen=True)
class DifficultyRecoveryObservation:
    """Immutable, source-truthful visual evidence from one non-primary frame."""

    source: DifficultyRecoverySource
    state: DifficultyRecoveryState
    frame_id: str
    ranking: tuple[RankedVisualCandidate, ...] = ()

    @property
    def reliable_id(self) -> str | None:
        if self.state is not DifficultyRecoveryState.RELIABLE:
            return None
        return self.ranking[0].identity_id if self.ranking else None


def observe_jp_mumu_post_start_difficulty(
    frame: Frame,
    viewport: ContentViewport,
    references: DifficultyRecoveryReferencePack | None,
) -> DifficultyRecoveryObservation:
    """Observe the visible top-left Difficulty only; no generic 2/2 page detector exists."""

    return _observe(
        frame,
        viewport,
        references,
        DifficultyRecoverySource.POST_START_VISUAL,
        POST_START_DIFFICULTY_ROI,
        POST_START_SCORE_THRESHOLD,
        POST_START_MARGIN_THRESHOLD,
        () if references is None else references.post_start_templates,
    )


def observe_jp_mumu_operation_splash_difficulty(
    frame: Frame,
    viewport: ContentViewport,
    references: DifficultyRecoveryReferencePack | None,
) -> DifficultyRecoveryObservation:
    """Observe the central OPERATION splash panel through calibrated clean/loading templates."""

    return _observe(
        frame,
        viewport,
        references,
        DifficultyRecoverySource.OPERATION_SPLASH_VISUAL,
        OPERATION_SPLASH_DIFFICULTY_ROI,
        OPERATION_SPLASH_SCORE_THRESHOLD,
        OPERATION_SPLASH_MARGIN_THRESHOLD,
        () if references is None else references.operation_splash_templates,
    )


def _observe(
    frame: Frame,
    viewport: ContentViewport,
    references: DifficultyRecoveryReferencePack | None,
    source: DifficultyRecoverySource,
    roi: PixelRoi,
    score_threshold: float,
    margin_threshold: float,
    templates: tuple[VisualReference, ...],
) -> DifficultyRecoveryObservation:
    if (
        references is None
        or (frame.width, frame.height) != (1920, 1080)
        or viewport.pixel_roi != PixelRoi(0, 0, 1920, 1080)
    ):
        return DifficultyRecoveryObservation(
            source, DifficultyRecoveryState.UNRESOLVED, frame.frame_id
        )
    ranking = _rank_variants(_crop(frame, roi), templates)
    reliable = (
        len(ranking) >= 2
        and ranking[0].score >= score_threshold
        and ranking[0].score - ranking[1].score >= margin_threshold
    )
    return DifficultyRecoveryObservation(
        source,
        DifficultyRecoveryState.RELIABLE if reliable else DifficultyRecoveryState.UNRESOLVED,
        frame.frame_id,
        ranking,
    )


def _rank_variants(
    query: ImageArray, templates: tuple[VisualReference, ...]
) -> tuple[RankedVisualCandidate, ...]:
    scores = {
        identity_id: max(
            _ncc(query, item.image)
            for item in templates
            if item.identity_id == identity_id
        )
        for identity_id in INFO_DIFFICULTY_IDS
    }
    return tuple(
        RankedVisualCandidate(identity_id, score)
        for identity_id, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
    )


def _ncc(query: ImageArray, reference: ImageArray) -> float:
    left = cv2.resize(cv2.cvtColor(query, cv2.COLOR_BGR2GRAY), (128, 128))
    right = cv2.resize(cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY), (128, 128))
    return float(cv2.matchTemplate(left, right, cv2.TM_CCOEFF_NORMED)[0, 0])


def _crop(frame: Frame, roi: PixelRoi) -> ImageArray:
    return frame.image[roi.y : roi.bottom, roi.x : roi.right]
