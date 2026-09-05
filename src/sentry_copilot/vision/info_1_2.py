"""Fixed-layout visual observations for the JP MuMu initial ``情報確認 1/2`` page."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import cv2
import numpy as np

from sentry_copilot.capture.frame_source import Frame, ImageArray
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi

JP_MUMU_INFO_1_2_PROFILE_ID = "jp_mumu_fullscreen_1920x1080.info_1_2.v1"
INFO_1_2_ANCHOR_ROI = PixelRoi(370, 35, 420, 80)
INFO_DIFFICULTY_ROI = PixelRoi(145, 35, 220, 70)
BOSS_ROI = PixelRoi(116, 324, 232, 232)
ENEMY_SLOT_ROIS = (
    PixelRoi(1130, 360, 132, 132),
    PixelRoi(1365, 360, 132, 132),
    PixelRoi(1588, 360, 132, 132),
)
INFO_1_2_ANCHOR_THRESHOLD = 0.80
BOSS_SCORE_THRESHOLD = 0.30
BOSS_MARGIN_THRESHOLD = 0.035
ENEMY_SCORE_THRESHOLD = 0.70
ENEMY_MARGIN_THRESHOLD = 0.20
TWO_SLOT_RATIO_MAX = 0.01
THREE_SLOT_RATIO_MIN = 0.10
KNOWN_DIFFICULTY_IDS = (
    "difficulty.covenant_latter.standard",
    "difficulty.covenant_latter.adversity",
    "difficulty.covenant_latter.deadland",
    "difficulty.covenant_latter.ultimate",
)
CALIBRATED_INFO_DIFFICULTY_IDS = KNOWN_DIFFICULTY_IDS
INFO_DIFFICULTY_IDS = KNOWN_DIFFICULTY_IDS


class Info12State(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNRESOLVED = "unresolved"


class EnemySlotLayout(StrEnum):
    TWO_SLOT = "two_slot"
    THREE_SLOT = "three_slot"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class VisualReference:
    identity_id: str
    image: ImageArray

    def __post_init__(self) -> None:
        if not self.identity_id.strip():
            raise ValueError("visual reference identity must not be blank")
        if self.image.dtype != np.uint8 or self.image.ndim != 3 or self.image.shape[2] != 3:
            raise ValueError("visual reference image must be uint8 BGR")
        image = np.array(self.image, copy=True)
        image.setflags(write=False)
        object.__setattr__(self, "image", image)


@dataclass(frozen=True)
class EnemyVisualReference:
    """An enemy category reference whose source alpha is part of the calibrated contract."""

    identity_id: str
    image: np.ndarray

    def __post_init__(self) -> None:
        if not self.identity_id.strip():
            raise ValueError("enemy visual reference identity must not be blank")
        if self.image.dtype != np.uint8 or self.image.ndim != 3 or self.image.shape[2] != 4:
            raise ValueError("enemy visual reference image must be uint8 BGRA")
        image = np.array(self.image, copy=True)
        image.setflags(write=False)
        object.__setattr__(self, "image", image)


@dataclass(frozen=True)
class Info12ReferencePack:
    anchor: ImageArray
    bosses: tuple[VisualReference, ...]
    enemy_categories: tuple[EnemyVisualReference, ...]
    difficulties: tuple[VisualReference, ...] = ()

    def __post_init__(self) -> None:
        if len(self.bosses) != 7 or len(self.enemy_categories) != 7:
            raise ValueError(
                "INFO 1/2 reference pack requires exactly seven Boss and enemy references"
            )
        if (
            len({item.identity_id for item in self.bosses}) != 7
            or len({item.identity_id for item in self.enemy_categories}) != 7
        ):
            raise ValueError("INFO 1/2 reference IDs must be unique")
        if self.difficulties and {
            item.identity_id for item in self.difficulties
        } != set(INFO_DIFFICULTY_IDS):
            raise ValueError("INFO difficulty references must cover all four supported identities")


@dataclass(frozen=True)
class RankedVisualCandidate:
    identity_id: str
    score: float


@dataclass(frozen=True)
class Info12Observation:
    state: Info12State
    frame_id: str
    anchor_score: float | None
    boss_ranking: tuple[RankedVisualCandidate, ...] = ()
    enemy_rankings: tuple[tuple[RankedVisualCandidate, ...], ...] = ()
    enemy_slot_layout: EnemySlotLayout = EnemySlotLayout.UNRESOLVED
    difficulty_ranking: tuple[RankedVisualCandidate, ...] = ()
    third_slot_foreground_ratio: float | None = None

    @property
    def reliable_boss_id(self) -> str | None:
        return _reliable(self.boss_ranking, BOSS_SCORE_THRESHOLD, BOSS_MARGIN_THRESHOLD)

    @property
    def reliable_enemy_ids(self) -> tuple[str | None, ...]:
        if self.enemy_slot_layout is EnemySlotLayout.UNRESOLVED:
            return ()
        values = tuple(
            _reliable(item, ENEMY_SCORE_THRESHOLD, ENEMY_MARGIN_THRESHOLD)
            for item in self.enemy_rankings
        )
        expected = 2 if self.enemy_slot_layout is EnemySlotLayout.TWO_SLOT else 3
        return values[:expected] if len(values) >= expected else ()

    @property
    def reliable_difficulty_id(self) -> str | None:
        """Compatibility projection; callers must apply semantic authorization."""

        return self.difficulty_candidate_id

    @property
    def difficulty_candidate_id(self) -> str | None:
        """Frozen color identity candidate without a local score/margin gate."""

        return self.difficulty_ranking[0].identity_id if self.difficulty_ranking else None


def observe_jp_mumu_info_1_2(
    frame: Frame, viewport: ContentViewport, pack: Info12ReferencePack | None
) -> Info12Observation:
    if (
        pack is None
        or (frame.width, frame.height) != (1920, 1080)
        or viewport.pixel_roi != PixelRoi(0, 0, 1920, 1080)
    ):
        return Info12Observation(Info12State.UNRESOLVED, frame.frame_id, None)
    anchor_score = _ncc(_crop(frame, INFO_1_2_ANCHOR_ROI), pack.anchor)
    if anchor_score < INFO_1_2_ANCHOR_THRESHOLD:
        return Info12Observation(Info12State.ABSENT, frame.frame_id, anchor_score)
    slot_three_ratio = float(
        np.mean(cv2.cvtColor(_crop(frame, ENEMY_SLOT_ROIS[2]), cv2.COLOR_BGR2GRAY) >= 165)
    )
    layout = classify_enemy_slot_layout(slot_three_ratio)
    slots = (
        ENEMY_SLOT_ROIS[:2]
        if layout is EnemySlotLayout.TWO_SLOT
        else ENEMY_SLOT_ROIS
        if layout is EnemySlotLayout.THREE_SLOT
        else ()
    )
    return Info12Observation(
        Info12State.PRESENT,
        frame.frame_id,
        anchor_score,
        _rank_ncc(_crop(frame, BOSS_ROI), pack.bosses),
        tuple(_rank_shape(_crop(frame, roi), pack.enemy_categories) for roi in slots),
        layout,
        _rank_frozen_color_difficulty(_crop(frame, INFO_DIFFICULTY_ROI), pack.difficulties)
        if pack.difficulties
        else (),
        slot_three_ratio,
    )


def classify_enemy_slot_layout(third_slot_foreground_ratio: float) -> EnemySlotLayout:
    """Classify only the calibrated visual third-slot presence ratio."""

    if third_slot_foreground_ratio <= TWO_SLOT_RATIO_MAX:
        return EnemySlotLayout.TWO_SLOT
    if third_slot_foreground_ratio >= THREE_SLOT_RATIO_MIN:
        return EnemySlotLayout.THREE_SLOT
    return EnemySlotLayout.UNRESOLVED


def _reliable(
    ranking: tuple[RankedVisualCandidate, ...], score: float, margin: float
) -> str | None:
    if len(ranking) < 2 or ranking[0].score < score or ranking[0].score - ranking[1].score < margin:
        return None
    return ranking[0].identity_id


def _ncc(query: ImageArray, reference: ImageArray) -> float:
    left = cv2.resize(cv2.cvtColor(query, cv2.COLOR_BGR2GRAY), (128, 128))
    right = cv2.resize(cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY), (128, 128))
    return float(cv2.matchTemplate(left, right, cv2.TM_CCOEFF_NORMED)[0, 0])


def _rank_ncc(
    query: ImageArray, references: tuple[VisualReference, ...]
) -> tuple[RankedVisualCandidate, ...]:
    """Rank logical identities by their strongest declared visual template."""

    return tuple(
        sorted(
            (
                RankedVisualCandidate(
                    identity_id,
                    max(
                        _ncc(query, item.image)
                        for item in references
                        if item.identity_id == identity_id
                    ),
                )
                for identity_id in dict.fromkeys(item.identity_id for item in references)
            ),
            key=lambda item: item.score,
            reverse=True,
        )
    )


def _rank_frozen_color_difficulty(
    query: ImageArray, references: tuple[VisualReference, ...]
) -> tuple[RankedVisualCandidate, ...]:
    """Use the frozen four-way identity feature; no local acceptance threshold."""

    from sentry_copilot.vision.color_difficulty import rank_frozen_color_difficulty

    return rank_frozen_color_difficulty(query, references)


def _query_mask(image: ImageArray) -> np.ndarray:
    return (cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) >= 165).astype(np.uint8)


def _reference_mask(image: np.ndarray) -> np.ndarray:
    return ((image[:, :, 3] > 32) & (cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY) >= 150)).astype(
        np.uint8
    )


def _rank_shape(
    query: ImageArray, references: tuple[EnemyVisualReference, ...]
) -> tuple[RankedVisualCandidate, ...]:
    source = _shape(_query_mask(query))
    result: list[RankedVisualCandidate] = []
    for item in references:
        target = _shape(_reference_mask(item.image))
        result.append(
            RankedVisualCandidate(
                item.identity_id,
                _cosine_similarity(source, target),
            )
        )
    return tuple(sorted(result, key=lambda item: item.score, reverse=True))


def _cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    left_float = left.astype(np.float32).reshape(-1)
    right_float = right.astype(np.float32).reshape(-1)
    denominator = float(np.linalg.norm(left_float) * np.linalg.norm(right_float))
    return float(np.dot(left_float, right_float) / denominator) if denominator else 0.0


def _shape(mask: np.ndarray) -> np.ndarray:
    points = cv2.findNonZero(mask)
    if points is None:
        return np.zeros((128, 128), dtype=np.uint8)
    x, y, width, height = cv2.boundingRect(points)
    return cv2.resize(
        mask[y : y + height, x : x + width], (128, 128), interpolation=cv2.INTER_NEAREST
    )


def _crop(frame: Frame, roi: PixelRoi) -> ImageArray:
    return frame.image[roi.y : roi.bottom, roi.x : roi.right]


def crop_info_difficulty_reference(image: ImageArray) -> ImageArray:
    """Extract the calibrated INFO difficulty ROI from one full-frame reference."""

    if image.shape[0] < INFO_DIFFICULTY_ROI.bottom or image.shape[1] < INFO_DIFFICULTY_ROI.right:
        raise ValueError("INFO difficulty reference image is smaller than the calibrated ROI")
    return np.array(
        image[
            INFO_DIFFICULTY_ROI.y : INFO_DIFFICULTY_ROI.bottom,
            INFO_DIFFICULTY_ROI.x : INFO_DIFFICULTY_ROI.right,
        ],
        copy=True,
    )
