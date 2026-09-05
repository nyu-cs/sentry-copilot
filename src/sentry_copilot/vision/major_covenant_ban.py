"""Cached, Major/Core-only glyph observations for JP MuMu INFO pages.

Separate nominal positions locate the eight visual discs on initial and returned INFO pages so
that each can be locally recentered. They are deliberately never an identity mapping: every
Covenant ID comes from glyph matching.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import cast

import cv2
import numpy as np
import numpy.typing as npt

from sentry_copilot.capture.frame_source import Frame, ImageArray
from sentry_copilot.encounter.models import MAJOR_COVENANT_IDS, CovenantBanState
from sentry_copilot.vision.info_1_2 import Info12State, RankedVisualCandidate
from sentry_copilot.vision.info_recovery_pages import InfoRecoveryPageState
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi

JP_MUMU_MAJOR_COVENANT_BAN_PROFILE_ID = "jp_mumu_fullscreen_1920x1080.major_ban.v1"
JP_MUMU_RETURNED_INFO_MAJOR_PROFILE_ID = "jp_mumu_fullscreen_1920x1080.returned_info_major.v1"
MAJOR_NOMINAL_CENTERS = (
    (265, 832),
    (434, 832),
    (604, 833),
    (775, 833),
    (943, 833),
    (1113, 832),
    (1283, 832),
    (1451, 832),
)
# These nominal windows are only the fixed default returned-INFO Major row locator. They do not
# encode Major identity and must not be generalized to Additional Covenant scrolling layouts.
RETURNED_INFO_MAJOR_NOMINAL_CENTERS = (
    (265, 775),
    (434, 775),
    (604, 776),
    (775, 776),
    (943, 776),
    (1113, 775),
    (1283, 775),
    (1451, 775),
)
MAJOR_LOCAL_SEARCH_HALF_SIZE = 76
MAJOR_RECENTERED_CROP_SIZE = 112
MAJOR_INNER_DISC_RADIUS = 40
MAJOR_STATE_SATURATION_THRESHOLD = 150.0
MAJOR_IDENTITY_MIN_RANSAC_INLIERS = 10.0
MAJOR_IDENTITY_MIN_MARGIN = 10.0
_INITIAL_SUPPORTED_DIFFICULTY_IDS = frozenset(
    {
        "difficulty.covenant_latter.adversity",
        "difficulty.covenant_latter.deadland",
    }
)
_RETURNED_SUPPORTED_DIFFICULTY_IDS = _INITIAL_SUPPORTED_DIFFICULTY_IDS | frozenset(
    {"difficulty.covenant_latter.ultimate"}
)


def supports_initial_major_covenant_ban(difficulty_id: str | None) -> bool:
    """Return whether initial-INFO Major/Core visual recognition supports Difficulty."""

    return difficulty_id in _INITIAL_SUPPORTED_DIFFICULTY_IDS


def supports_returned_major_covenant_ban(difficulty_id: str | None) -> bool:
    """Return whether returned-INFO Major/Core visual recovery supports Difficulty."""

    return difficulty_id in _RETURNED_SUPPORTED_DIFFICULTY_IDS


class MajorCovenantBanObservationState(StrEnum):
    OBSERVED = "observed"
    UNSUPPORTED = "unsupported"
    ROW_ABSENT = "row_absent"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class MajorCovenantVisualReference:
    """One retained, declared Major glyph exemplar and its independently reviewed Ban state."""

    covenant_id: str
    state: CovenantBanState
    image: ImageArray

    def __post_init__(self) -> None:
        if self.covenant_id not in MAJOR_COVENANT_IDS:
            raise ValueError("Major visual reference must use a supported Major/Core Covenant ID")
        if self.state is CovenantBanState.UNRESOLVED:
            raise ValueError("Major visual reference state must be resolved")
        if (
            self.image.dtype != np.uint8
            or self.image.ndim != 3
            or self.image.shape != (MAJOR_RECENTERED_CROP_SIZE, MAJOR_RECENTERED_CROP_SIZE, 3)
        ):
            raise ValueError("Major visual reference must be a 112x112 uint8 BGR crop")
        image = np.array(self.image, copy=True)
        image.setflags(write=False)
        object.__setattr__(self, "image", image)


@dataclass(frozen=True)
class MajorCovenantReferencePack:
    """Explicit initial and optional returned Major/Core exemplars; never Additional assets."""

    references: tuple[MajorCovenantVisualReference, ...]
    returned_info_references: tuple[MajorCovenantVisualReference, ...] = ()

    def __post_init__(self) -> None:
        ids = {item.covenant_id for item in self.references}
        if ids != MAJOR_COVENANT_IDS:
            raise ValueError(
                "Major reference pack must include every supported Major/Core Covenant"
            )
        returned_ids = {item.covenant_id for item in self.returned_info_references}
        if self.returned_info_references and returned_ids != MAJOR_COVENANT_IDS:
            raise ValueError(
                "Returned Major reference pack must include every supported Major/Core Covenant"
            )


@dataclass(frozen=True)
class MajorCovenantIdentityObservation:
    """One locally recentered disc's glyph evidence, retaining extraction index only for audit."""

    candidate_index_for_extraction_only: int
    refined_center: tuple[int, int]
    radius: int
    state: CovenantBanState
    state_saturation_median: float
    ranking: tuple[RankedVisualCandidate, ...]

    @property
    def covenant_id(self) -> str | None:
        if not _ranking_reliable(self.ranking):
            return None
        return self.ranking[0].identity_id

    @property
    def top_1_score(self) -> float | None:
        return self.ranking[0].score if self.ranking else None

    @property
    def margin(self) -> float | None:
        return self.ranking[0].score - self.ranking[1].score if len(self.ranking) >= 2 else None


@dataclass(frozen=True)
class MajorCovenantBanObservation:
    """One frame-local Major/Core Ban observation with no session mutation."""

    state: MajorCovenantBanObservationState
    frame_id: str
    supported: bool
    row_visible: bool
    candidate_count: int
    identity_observations: tuple[MajorCovenantIdentityObservation, ...] = ()
    disabled_major_covenant_ids: tuple[str, ...] = ()
    structural_valid: bool = False
    reason: str | None = None

    @property
    def complete_reliable(self) -> bool:
        identities = tuple(item.covenant_id for item in self.identity_observations)
        states = tuple(item.state for item in self.identity_observations)
        resolved_disabled_ids = tuple(
            sorted(
                identity_id
                for identity_id, state in zip(identities, states, strict=True)
                if identity_id is not None and state is CovenantBanState.DISABLED
            )
        )
        return (
            self.state is MajorCovenantBanObservationState.OBSERVED
            and self.structural_valid
            and self.candidate_count == 8
            and len(identities) == 8
            and all(identity_id is not None for identity_id in identities)
            and set(identities) == MAJOR_COVENANT_IDS
            and sum(state is CovenantBanState.UNRESTRICTED for state in states) == 5
            and sum(state is CovenantBanState.DISABLED for state in states) == 3
            and len(self.disabled_major_covenant_ids) == 3
            and self.disabled_major_covenant_ids == resolved_disabled_ids
        )


@dataclass(frozen=True)
class _CachedMajorReference:
    covenant_id: str
    state: CovenantBanState
    keypoints: tuple[cv2.KeyPoint, ...]
    descriptors: np.ndarray | None


@dataclass(frozen=True)
class _QueryFeatures:
    keypoints: tuple[cv2.KeyPoint, ...]
    descriptors: np.ndarray | None


class MajorCovenantBanObserver:
    """Cache references and observe one fixed Major row without position-based identity."""

    def __init__(self, references: MajorCovenantReferencePack) -> None:
        self._references = references
        self._sift = cv2.SIFT_create(  # type: ignore[attr-defined]
            nfeatures=50,
            contrastThreshold=0.01,
            edgeThreshold=5,
        )
        self._matcher = cv2.BFMatcher()
        self._reference_cache = self._cache_references(references.references)
        self._returned_info_reference_cache = self._cache_references(
            references.returned_info_references or references.references
        )

    def _cache_references(
        self, references: tuple[MajorCovenantVisualReference, ...]
    ) -> tuple[_CachedMajorReference, ...]:
        return tuple(
            _CachedMajorReference(
                covenant_id=item.covenant_id,
                state=item.state,
                keypoints=features.keypoints,
                descriptors=features.descriptors,
            )
            for item in references
            for features in (self._compute_features(item.image, item.state),)
        )

    def observe(
        self,
        frame: Frame,
        viewport: ContentViewport,
        *,
        info_state: Info12State,
        difficulty_id: str | None,
    ) -> MajorCovenantBanObservation:
        """Observe supported initial-INFO Major discs, otherwise return explicit no-fact state."""

        if (
            (frame.width, frame.height) != (1920, 1080)
            or viewport.pixel_roi != PixelRoi(0, 0, 1920, 1080)
            or info_state is not Info12State.PRESENT
        ):
            return MajorCovenantBanObservation(
                MajorCovenantBanObservationState.UNRESOLVED,
                frame.frame_id,
                False,
                False,
                0,
                reason="requires_genuine_initial_info",
            )
        if not supports_initial_major_covenant_ban(difficulty_id):
            return MajorCovenantBanObservation(
                MajorCovenantBanObservationState.UNSUPPORTED,
                frame.frame_id,
                False,
                False,
                0,
                reason="difficulty_not_supported_for_major_ban",
            )

        return self._observe_fixed_major_row(
            frame,
            MAJOR_NOMINAL_CENTERS,
            absent_reason="canonical_major_row_not_fully_visible",
            reference_cache=self._reference_cache,
        )

    def observe_returned_info(
        self,
        frame: Frame,
        viewport: ContentViewport,
        *,
        returned_info_state: InfoRecoveryPageState,
        difficulty_id: str | None,
    ) -> MajorCovenantBanObservation:
        """Observe the fixed default returned-INFO Major row with the shared glyph matcher."""

        if (
            (frame.width, frame.height) != (1920, 1080)
            or viewport.pixel_roi != PixelRoi(0, 0, 1920, 1080)
            or returned_info_state is not InfoRecoveryPageState.PRESENT
        ):
            return MajorCovenantBanObservation(
                MajorCovenantBanObservationState.UNRESOLVED,
                frame.frame_id,
                False,
                False,
                0,
                reason="requires_returned_info_page",
            )
        if not supports_returned_major_covenant_ban(difficulty_id):
            return MajorCovenantBanObservation(
                MajorCovenantBanObservationState.UNSUPPORTED,
                frame.frame_id,
                False,
                False,
                0,
                reason="difficulty_not_supported_for_major_ban",
            )
        return self._observe_fixed_major_row(
            frame,
            RETURNED_INFO_MAJOR_NOMINAL_CENTERS,
            absent_reason="returned_major_row_not_fully_visible",
            reference_cache=self._returned_info_reference_cache,
        )

    def _observe_fixed_major_row(
        self,
        frame: Frame,
        nominal_centers: tuple[tuple[int, int], ...],
        *,
        absent_reason: str,
        reference_cache: tuple[_CachedMajorReference, ...],
    ) -> MajorCovenantBanObservation:
        """Extract locally recentered candidates, then share the state and glyph pipeline."""

        candidates = tuple(
            candidate
            for index, nominal_center in enumerate(nominal_centers, start=1)
            for candidate in (_extract_candidate(frame.image, index, nominal_center),)
            if candidate is not None
        )
        if len(candidates) != len(nominal_centers):
            return MajorCovenantBanObservation(
                MajorCovenantBanObservationState.ROW_ABSENT,
                frame.frame_id,
                True,
                False,
                len(candidates),
                reason=absent_reason,
            )

        observations = tuple(
            self._observe_candidate(candidate, reference_cache=reference_cache)
            for candidate in candidates
        )
        resolved_ids = tuple(item.covenant_id for item in observations)
        states = tuple(item.state for item in observations)
        reliable = all(identity_id is not None for identity_id in resolved_ids)
        ids = tuple(identity_id for identity_id in resolved_ids if identity_id is not None)
        disabled = (
            tuple(
                sorted(
                    identity_id
                    for identity_id, state in zip(ids, states, strict=True)
                    if state is CovenantBanState.DISABLED
                )
            )
            if reliable
            else ()
        )
        structural_valid = (
            reliable
            and len(ids) == 8
            and set(ids) == MAJOR_COVENANT_IDS
            and len(set(ids)) == 8
            and sum(state is CovenantBanState.UNRESTRICTED for state in states) == 5
            and sum(state is CovenantBanState.DISABLED for state in states) == 3
        )
        return MajorCovenantBanObservation(
            (
                MajorCovenantBanObservationState.OBSERVED
                if structural_valid
                else MajorCovenantBanObservationState.UNRESOLVED
            ),
            frame.frame_id,
            True,
            True,
            len(candidates),
            observations,
            disabled if structural_valid else (),
            structural_valid,
            None if structural_valid else "major_identity_or_state_structure_unresolved",
        )

    def _observe_candidate(
        self,
        candidate: tuple[int, tuple[int, int], int, ImageArray],
        *,
        reference_cache: tuple[_CachedMajorReference, ...] | None = None,
    ) -> MajorCovenantIdentityObservation:
        index, center, radius, crop = candidate
        saturation = _state_saturation_median(crop)
        state = (
            CovenantBanState.UNRESTRICTED
            if saturation >= MAJOR_STATE_SATURATION_THRESHOLD
            else CovenantBanState.DISABLED
        )
        query = self._compute_features(crop, state)
        ranking = self._rank(query, reference_cache=reference_cache)
        return MajorCovenantIdentityObservation(index, center, radius, state, saturation, ranking)

    def _compute_features(self, crop: ImageArray, state: CovenantBanState) -> _QueryFeatures:
        image = _normalized_sift_image(crop, state)
        keypoints, descriptors = self._sift.detectAndCompute(image, None)
        copied = None if descriptors is None else np.array(descriptors, copy=True)
        if copied is not None:
            copied.setflags(write=False)
        return _QueryFeatures(tuple(keypoints), copied)

    def _rank(
        self,
        query: _QueryFeatures,
        *,
        reference_cache: tuple[_CachedMajorReference, ...] | None = None,
    ) -> tuple[RankedVisualCandidate, ...]:
        cache = self._reference_cache if reference_cache is None else reference_cache
        scores: list[tuple[str, int, int]] = []
        for covenant_id in MAJOR_COVENANT_IDS:
            pairs = (
                self._pair_evidence(query, reference)
                for reference in cache
                if reference.covenant_id == covenant_id
            )
            inliers, matches = max(pairs, key=lambda item: (item[0], item[1]))
            scores.append((covenant_id, inliers, matches))
        return tuple(
            RankedVisualCandidate(covenant_id, float(inliers))
            for covenant_id, inliers, _ in sorted(
                scores,
                key=lambda item: (item[1], item[2], item[0]),
                reverse=True,
            )
        )

    def _pair_evidence(
        self, query: _QueryFeatures, reference: _CachedMajorReference
    ) -> tuple[int, int]:
        if query.descriptors is None or reference.descriptors is None:
            return 0, 0
        pairs = self._matcher.knnMatch(query.descriptors, reference.descriptors, k=2)
        good = tuple(
            pair[0]
            for pair in pairs
            if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance
        )
        if len(good) < 4:
            return 0, len(good)
        query_xy = np.array([query.keypoints[item.queryIdx].pt for item in good], dtype=np.float32)
        reference_xy = np.array(
            [reference.keypoints[item.trainIdx].pt for item in good], dtype=np.float32
        )
        _, inlier_mask = cv2.findHomography(query_xy, reference_xy, cv2.RANSAC, 3.0)
        return (int(inlier_mask.sum()) if inlier_mask is not None else 0), len(good)


def _extract_candidate(
    image: ImageArray, index: int, nominal_center: tuple[int, int]
) -> tuple[int, tuple[int, int], int, ImageArray] | None:
    x, y = nominal_center
    half = MAJOR_LOCAL_SEARCH_HALF_SIZE
    window = image[y - half : y + half, x - half : x + half]
    if window.shape[:2] != (half * 2, half * 2):
        return None
    gray = cv2.cvtColor(window, cv2.COLOR_BGR2GRAY)
    circles = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        1.0,
        90,
        param1=100,
        param2=22,
        minRadius=42,
        maxRadius=70,
    )
    if circles is None:
        return None
    circle = cast(
        npt.NDArray[np.float32],
        min(
            circles[0],
            key=lambda circle: (circle[0] - half) ** 2 + (circle[1] - half) ** 2,
        ),
    )
    center = (round(x - half + float(circle[0])), round(y - half + float(circle[1])))
    crop = cast(
        ImageArray,
        cv2.getRectSubPix(
            image,
            (MAJOR_RECENTERED_CROP_SIZE, MAJOR_RECENTERED_CROP_SIZE),
            center,
        ),
    )
    return index, center, round(float(circle[2])), crop


def _inner_disc_mask() -> npt.NDArray[np.bool_]:
    yy, xx = np.indices((MAJOR_RECENTERED_CROP_SIZE, MAJOR_RECENTERED_CROP_SIZE))
    return np.asarray(
        (xx - MAJOR_RECENTERED_CROP_SIZE // 2) ** 2 + (yy - MAJOR_RECENTERED_CROP_SIZE // 2) ** 2
        <= MAJOR_INNER_DISC_RADIUS**2,
        dtype=np.bool_,
    )


def _state_saturation_median(crop: ImageArray) -> float:
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    return float(np.median(hsv[:, :, 1][_inner_disc_mask()]))


def _normalized_sift_image(crop: ImageArray, state: CovenantBanState) -> np.ndarray:
    """Use the validated polarity normalization and remove the outer ring/state marker."""

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    if state is CovenantBanState.UNRESTRICTED:
        gray = 255 - gray
    result = np.array(gray, copy=True)
    result[~_inner_disc_mask()] = 0
    return result


def _ranking_reliable(ranking: tuple[RankedVisualCandidate, ...]) -> bool:
    return (
        len(ranking) >= 2
        and ranking[0].score >= MAJOR_IDENTITY_MIN_RANSAC_INLIERS
        and ranking[0].score - ranking[1].score >= MAJOR_IDENTITY_MIN_MARGIN
    )
