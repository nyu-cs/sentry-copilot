"""Conservative scroll-aware Additional Covenant Ban observations for JP MuMu."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from itertools import combinations
from typing import cast

import cv2
import numpy as np

from sentry_copilot.capture.frame_source import Frame, ImageArray
from sentry_copilot.encounter.models import ADDITIONAL_COVENANT_IDS, CovenantBanState
from sentry_copilot.vision.info_1_2 import Info12State, RankedVisualCandidate
from sentry_copilot.vision.info_recovery_pages import InfoRecoveryPageState
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi

JP_MUMU_ADDITIONAL_COVENANT_BAN_PROFILE_ID = "jp_mumu_fullscreen_1920x1080.additional_ban.v1"
_SUPPORTED = frozenset(
    {
        "difficulty.covenant_latter.adversity",
        "difficulty.covenant_latter.deadland",
        "difficulty.covenant_latter.ultimate",
    }
)
_SEARCH = (120, 470, 1660, 520)
_LOWER_ROW_RECOVERY_SEARCH = (120, 760, 1160, 320)
_SIZE, _RADIUS = 112, 40
_SECOND_ROW_NOMINAL_X_CENTERS = (263, 435, 607, 779, 951, 1123)
_SECOND_ROW_GEOMETRY_TOLERANCE = 18


def supports_additional_covenant_ban(difficulty_id: str | None) -> bool:
    return difficulty_id in _SUPPORTED


class AdditionalCovenantBanObservationState(StrEnum):
    OBSERVED = "observed"
    UNSUPPORTED = "unsupported"
    SURFACE_ABSENT = "surface_absent"
    PARTIAL = "partial"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class AdditionalCovenantVisualReference:
    covenant_id: str
    state: CovenantBanState
    image: ImageArray

    def __post_init__(self) -> None:
        if (
            self.covenant_id not in ADDITIONAL_COVENANT_IDS
            or self.state is CovenantBanState.UNRESOLVED
        ):
            raise ValueError(
                "Additional visual reference must be a resolved known Additional Covenant"
            )
        if self.image.dtype != np.uint8 or self.image.shape != (_SIZE, _SIZE, 3):
            raise ValueError("Additional visual reference must be a 112x112 uint8 BGR crop")
        image = np.array(self.image, copy=True)
        image.setflags(write=False)
        object.__setattr__(self, "image", image)


@dataclass(frozen=True)
class AdditionalCovenantReferencePack:
    references: tuple[AdditionalCovenantVisualReference, ...]

    def __post_init__(self) -> None:
        if (
            len(self.references) != 15
            or {item.covenant_id for item in self.references} != ADDITIONAL_COVENANT_IDS
        ):
            raise ValueError(
                "Additional reference pack must contain exactly every Additional Covenant once"
            )


@dataclass(frozen=True)
class AdditionalCovenantIdentityObservation:
    x_order_for_structure_only: int
    center: tuple[int, int]
    state_saturation_median: float
    ranking: tuple[RankedVisualCandidate, ...]

    @property
    def covenant_id(self) -> str | None:
        if len(self.ranking) < 2 or self.ranking[0].score <= self.ranking[1].score:
            return None
        return self.ranking[0].identity_id


@dataclass(frozen=True)
class AdditionalLogicalRowCandidateDiagnostic:
    """Privacy-safe evidence for one six-slot lattice hypothesis."""

    source_row_index: int
    detected_centers: tuple[tuple[int, int, int], ...]
    completed_centers: tuple[tuple[int, int, int], ...]
    matched_slot_count: int
    maximum_x_residual: float
    inferred_missing_slot_index: int | None
    ignored_detection_count: int
    detection_source: str = "primary"
    rejection_reason: str | None = None
    identity_rankings: tuple[tuple[RankedVisualCandidate, ...], ...] = ()


@dataclass(frozen=True)
class AdditionalCovenantBanObservation:
    state: AdditionalCovenantBanObservationState
    frame_id: str
    row_sizes: tuple[int, ...]
    second_row_visible: bool
    target_observations: tuple[AdditionalCovenantIdentityObservation, ...] = ()
    candidate_disabled_covenant_ids: tuple[str, ...] = ()
    surface_mode: str = "absent"
    selected_row_sizes: tuple[int, ...] = ()
    ignored_row_sizes: tuple[int, ...] = ()
    reason: str | None = None
    grouped_circle_centers: tuple[tuple[tuple[int, int, int], ...], ...] = ()
    logical_row_candidates: tuple[AdditionalLogicalRowCandidateDiagnostic, ...] = ()
    selected_logical_row_centers: tuple[tuple[int, int, int], ...] = ()
    selected_row_observations: tuple[AdditionalCovenantIdentityObservation, ...] = ()
    extra_detections_ignored: bool = False
    lower_row_recovery_attempted: bool = False
    lower_row_recovery_grouped_circle_centers: tuple[
        tuple[tuple[int, int, int], ...], ...
    ] = ()
    selected_logical_row_source: str | None = None

    @property
    def complete_reliable(self) -> bool:
        return (
            self.state is AdditionalCovenantBanObservationState.OBSERVED
            and len(self.candidate_disabled_covenant_ids) == 4
        )


@dataclass(frozen=True)
class _Features:
    points: tuple[cv2.KeyPoint, ...]
    descriptors: np.ndarray | None


class AdditionalCovenantBanObserver:
    """Observe either one unambiguous 9+6 surface or one authorized six-icon second row."""

    def __init__(self, references: AdditionalCovenantReferencePack) -> None:
        self._sift = cv2.SIFT_create(  # type: ignore[attr-defined]
            nfeatures=50,
            contrastThreshold=0.01,
            edgeThreshold=5,
        )
        self._matcher = cv2.BFMatcher()
        self._references = tuple(
            (item.covenant_id, item.state, self._features(item.image, item.state))
            for item in references.references
        )

    def observe(
        self,
        frame: Frame,
        viewport: ContentViewport,
        *,
        info_state: Info12State,
        difficulty_id: str | None,
    ) -> AdditionalCovenantBanObservation:
        if (
            (frame.width, frame.height) != (1920, 1080)
            or viewport.pixel_roi != PixelRoi(0, 0, 1920, 1080)
            or info_state is not Info12State.PRESENT
        ):
            return AdditionalCovenantBanObservation(
                AdditionalCovenantBanObservationState.SURFACE_ABSENT,
                frame.frame_id,
                (),
                False,
                reason="requires_info_context",
            )
        if not supports_additional_covenant_ban(difficulty_id):
            return AdditionalCovenantBanObservation(
                AdditionalCovenantBanObservationState.UNSUPPORTED,
                frame.frame_id,
                (),
                False,
                reason="difficulty_not_supported_for_additional_ban",
            )
        return self._observe_surface(frame)

    def observe_returned_info(
        self,
        frame: Frame,
        viewport: ContentViewport,
        *,
        returned_info_state: InfoRecoveryPageState,
        returned_info_scan_active: bool = False,
        difficulty_id: str | None,
    ) -> AdditionalCovenantBanObservation:
        """Observe the same scroll surface after independently confirmed returned INFO."""

        if (
            (frame.width, frame.height) != (1920, 1080)
            or viewport.pixel_roi != PixelRoi(0, 0, 1920, 1080)
            or (
                returned_info_state is not InfoRecoveryPageState.PRESENT
                and not returned_info_scan_active
            )
        ):
            return AdditionalCovenantBanObservation(
                AdditionalCovenantBanObservationState.SURFACE_ABSENT,
                frame.frame_id,
                (),
                False,
                reason="requires_returned_info_context",
            )
        if not supports_additional_covenant_ban(difficulty_id):
            return AdditionalCovenantBanObservation(
                AdditionalCovenantBanObservationState.UNSUPPORTED,
                frame.frame_id,
                (),
                False,
                reason="difficulty_not_supported_for_additional_ban",
            )
        return self._observe_surface(frame)

    def _observe_surface(self, frame: Frame) -> AdditionalCovenantBanObservation:
        rows = _rows(_circles(frame.image))
        sizes = tuple(len(row) for row in rows)
        grouped_centers = tuple(tuple(row) for row in rows)
        selected = _select_surface_layout(rows)
        if selected is None:
            primary_result: AdditionalCovenantBanObservation | None = None
            logical_rows = _logical_second_row_candidates(rows)
            if logical_rows:
                primary_result = self._observe_logical_second_rows(
                    frame,
                    rows,
                    sizes,
                    grouped_centers,
                    logical_rows,
                )
                if primary_result.state is AdditionalCovenantBanObservationState.OBSERVED:
                    return primary_result
            return self._observe_lower_row_recovery(
                frame,
                rows,
                sizes,
                grouped_centers,
                primary_result,
            )
        mode, selected_indices = selected
        selected_rows = tuple(rows[index] for index in selected_indices)
        selected_sizes = tuple(len(row) for row in selected_rows)
        ignored_sizes = tuple(
            len(row) for index, row in enumerate(rows) if index not in selected_indices
        )
        second_row = selected_rows[-1]
        observed_indices = range(1, 7) if mode == "second_row_only" else range(3, 7)
        observations: list[AdditionalCovenantIdentityObservation] = []
        for index in observed_indices:
            candidate = second_row[index - 1]
            if not _candidate_has_safe_frame_crop(candidate, frame.image):
                return AdditionalCovenantBanObservation(
                    AdditionalCovenantBanObservationState.UNRESOLVED,
                    frame.frame_id,
                    sizes,
                    True,
                    surface_mode=mode,
                    selected_row_sizes=selected_sizes,
                    ignored_row_sizes=ignored_sizes,
                    reason="target_icon_incomplete",
                    grouped_circle_centers=grouped_centers,
                )
            x, y, _ = candidate
            crop = cast(ImageArray, cv2.getRectSubPix(frame.image, (_SIZE, _SIZE), (x, y)))
            state = CovenantBanState.UNRESTRICTED if index <= 2 else CovenantBanState.DISABLED
            observations.append(
                AdditionalCovenantIdentityObservation(
                    index,
                    (x, y),
                    _saturation(crop),
                    self._rank(self._features(crop, state)),
                )
            )
        if mode == "second_row_only" and not _second_row_appearance_is_plausible(observations):
            return AdditionalCovenantBanObservation(
                AdditionalCovenantBanObservationState.UNRESOLVED,
                frame.frame_id,
                sizes,
                True,
                tuple(observations[2:]),
                surface_mode=mode,
                selected_row_sizes=selected_sizes,
                ignored_row_sizes=ignored_sizes,
                reason="second_row_state_polarity_inconsistent",
                grouped_circle_centers=grouped_centers,
                selected_logical_row_centers=tuple(second_row),
                selected_row_observations=tuple(observations),
            )
        targets = tuple(observations[2:]) if mode == "second_row_only" else tuple(observations)
        identities = tuple(item.covenant_id for item in targets)
        all_identities = tuple(item.covenant_id for item in observations)
        if (
            any(item is None for item in all_identities)
            or len(set(all_identities)) != len(observations)
            or any(item is None for item in identities)
            or len(set(identities)) != 4
        ):
            return AdditionalCovenantBanObservation(
                AdditionalCovenantBanObservationState.UNRESOLVED,
                frame.frame_id,
                sizes,
                True,
                targets,
                surface_mode=mode,
                selected_row_sizes=selected_sizes,
                ignored_row_sizes=ignored_sizes,
                reason="target_identity_tied_or_duplicate",
                grouped_circle_centers=grouped_centers,
                selected_logical_row_centers=tuple(second_row),
                selected_row_observations=tuple(observations),
            )
        return AdditionalCovenantBanObservation(
            AdditionalCovenantBanObservationState.OBSERVED,
            frame.frame_id,
            sizes,
            True,
            targets,
            tuple(sorted(item for item in identities if item is not None)),
            surface_mode=mode,
            selected_row_sizes=selected_sizes,
            ignored_row_sizes=ignored_sizes,
            grouped_circle_centers=grouped_centers,
            selected_logical_row_centers=tuple(second_row),
            selected_row_observations=tuple(observations),
            selected_logical_row_source="primary",
        )

    def _observe_lower_row_recovery(
        self,
        frame: Frame,
        primary_rows: list[list[tuple[int, int, int]]],
        primary_sizes: tuple[int, ...],
        primary_grouped_centers: tuple[tuple[tuple[int, int, int], ...], ...],
        primary_result: AdditionalCovenantBanObservation | None,
    ) -> AdditionalCovenantBanObservation:
        """Retry only the low six-slot row with an unclipped bottom search region."""

        recovery_rows = _rows(_lower_row_recovery_circles(frame.image))
        recovery_grouped_centers = tuple(tuple(row) for row in recovery_rows)
        recovery_candidates = _logical_second_row_candidates(
            recovery_rows,
            authorized_search=_LOWER_ROW_RECOVERY_SEARCH,
            detection_source="lower_row_recovery",
        )
        recovery_result = (
            self._observe_logical_second_rows(
                frame,
                recovery_rows,
                tuple(len(row) for row in recovery_rows),
                recovery_grouped_centers,
                recovery_candidates,
            )
            if recovery_candidates
            else None
        )
        result = recovery_result or primary_result
        if result is None:
            state = (
                AdditionalCovenantBanObservationState.PARTIAL
                if primary_rows or recovery_rows
                else AdditionalCovenantBanObservationState.SURFACE_ABSENT
            )
            result = AdditionalCovenantBanObservation(
                state,
                frame.frame_id,
                primary_sizes,
                False,
                surface_mode=(
                    "partial"
                    if state is AdditionalCovenantBanObservationState.PARTIAL
                    else "absent"
                ),
                reason=(
                    "requires_unambiguous_complete_additional_surface"
                    if state is AdditionalCovenantBanObservationState.PARTIAL
                    else None
                ),
            )
        primary_diagnostics = (
            primary_result.logical_row_candidates if primary_result is not None else ()
        )
        recovery_diagnostics = (
            recovery_result.logical_row_candidates if recovery_result is not None else ()
        )
        return replace(
            result,
            row_sizes=primary_sizes,
            grouped_circle_centers=primary_grouped_centers,
            logical_row_candidates=primary_diagnostics + recovery_diagnostics,
            extra_detections_ignored=(
                result.extra_detections_ignored
                or bool(primary_rows)
                or any(
                    item.ignored_detection_count > 0
                    for item in (*primary_diagnostics, *recovery_diagnostics)
                )
            ),
            lower_row_recovery_attempted=True,
            lower_row_recovery_grouped_circle_centers=recovery_grouped_centers,
        )

    def _observe_logical_second_rows(
        self,
        frame: Frame,
        rows: list[list[tuple[int, int, int]]],
        sizes: tuple[int, ...],
        grouped_centers: tuple[tuple[tuple[int, int, int], ...], ...],
        logical_rows: tuple[AdditionalLogicalRowCandidateDiagnostic, ...],
    ) -> AdditionalCovenantBanObservation:
        """Accept one logical six-slot row only after all glyphs independently agree."""

        evaluated: list[
            tuple[AdditionalCovenantBanObservation, AdditionalLogicalRowCandidateDiagnostic]
        ] = []
        for logical_row in logical_rows:
            selected_sizes = (len(rows[logical_row.source_row_index]),)
            ignored_sizes = tuple(
                len(row)
                for index, row in enumerate(rows)
                if index != logical_row.source_row_index
            )
            observation = self._observe_completed_second_row(
                frame,
                sizes,
                logical_row.completed_centers,
                selected_sizes,
                ignored_sizes,
                surface_mode=(
                    "second_row_reconstructed"
                    if logical_row.inferred_missing_slot_index is not None
                    else (
                        "second_row_only"
                        if len(rows) == 1
                        and len(rows[logical_row.source_row_index]) == 6
                        else "second_row_lattice"
                    )
                ),
            )
            evaluated.append(
                (
                    observation,
                    replace(
                        logical_row,
                        rejection_reason=observation.reason,
                        identity_rankings=tuple(
                            item.ranking for item in observation.selected_row_observations
                        ),
                    ),
                )
            )
        accepted = tuple(
            (observation, diagnostic)
            for observation, diagnostic in evaluated
            if observation.state is AdditionalCovenantBanObservationState.OBSERVED
        )
        diagnostics = tuple(diagnostic for _observation, diagnostic in evaluated)
        if len(accepted) == 1:
            observation, selected_diagnostic = accepted[0]
            return replace(
                observation,
                grouped_circle_centers=grouped_centers,
                logical_row_candidates=diagnostics,
                extra_detections_ignored=any(
                    item.ignored_detection_count > 0 for item in diagnostics
                )
                or len(rows) > 1,
                selected_logical_row_source=selected_diagnostic.detection_source,
            )
        return AdditionalCovenantBanObservation(
            AdditionalCovenantBanObservationState.PARTIAL,
            frame.frame_id,
            sizes,
            True,
            surface_mode="second_row_lattice",
            reason=(
                "logical_second_row_not_uniquely_complete"
                if accepted
                else "logical_second_row_identity_or_state_unresolved"
            ),
            grouped_circle_centers=grouped_centers,
            logical_row_candidates=diagnostics,
            extra_detections_ignored=any(
                item.ignored_detection_count > 0 for item in diagnostics
            )
            or len(rows) > 1,
        )

    def _observe_completed_second_row(
        self,
        frame: Frame,
        sizes: tuple[int, ...],
        candidates: tuple[tuple[int, int, int], ...],
        selected_sizes: tuple[int, ...],
        ignored_sizes: tuple[int, ...],
        *,
        surface_mode: str,
    ) -> AdditionalCovenantBanObservation:
        """Evaluate one fitted row with the normal state-polarity glyph matcher."""

        observations: list[AdditionalCovenantIdentityObservation] = []
        for index, candidate in enumerate(candidates, start=1):
            if not _candidate_has_safe_frame_crop(candidate, frame.image):
                return AdditionalCovenantBanObservation(
                    AdditionalCovenantBanObservationState.UNRESOLVED,
                    frame.frame_id,
                    sizes,
                    True,
                    surface_mode=surface_mode,
                    selected_row_sizes=selected_sizes,
                    ignored_row_sizes=ignored_sizes,
                    reason="inferred_target_icon_incomplete",
                    selected_logical_row_centers=candidates,
                )
            x, y, _ = candidate
            crop = cast(ImageArray, cv2.getRectSubPix(frame.image, (_SIZE, _SIZE), (x, y)))
            # Slot geometry establishes Ban-state polarity only; glyph ranking alone establishes ID.
            state = CovenantBanState.UNRESTRICTED if index <= 2 else CovenantBanState.DISABLED
            observations.append(
                AdditionalCovenantIdentityObservation(
                    index,
                    (x, y),
                    _saturation(crop),
                    self._rank(self._features(crop, state)),
                )
            )
        targets = tuple(observations[2:])
        all_identities = tuple(item.covenant_id for item in observations)
        identities = tuple(item.covenant_id for item in targets)
        if (
            not _second_row_appearance_is_plausible(observations)
            or any(item is None for item in all_identities)
            or len(set(all_identities)) != len(observations)
            or any(item is None for item in identities)
            or len(set(identities)) != 4
        ):
            return AdditionalCovenantBanObservation(
                AdditionalCovenantBanObservationState.UNRESOLVED,
                frame.frame_id,
                sizes,
                True,
                targets,
                surface_mode=surface_mode,
                selected_row_sizes=selected_sizes,
                ignored_row_sizes=ignored_sizes,
                reason="reconstructed_target_identity_or_state_unresolved",
                selected_logical_row_centers=candidates,
                selected_row_observations=tuple(observations),
            )
        return AdditionalCovenantBanObservation(
            AdditionalCovenantBanObservationState.OBSERVED,
            frame.frame_id,
            sizes,
            True,
            targets,
            tuple(sorted(item for item in identities if item is not None)),
            surface_mode=surface_mode,
            selected_row_sizes=selected_sizes,
            ignored_row_sizes=ignored_sizes,
            selected_logical_row_centers=candidates,
            selected_row_observations=tuple(observations),
        )

    def _features(self, crop: ImageArray, state: CovenantBanState) -> _Features:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        if state is CovenantBanState.UNRESTRICTED:
            gray = 255 - gray
        result = np.array(gray, copy=True)
        result[~_mask()] = 0
        points, descriptors = self._sift.detectAndCompute(result, None)
        return _Features(tuple(points), descriptors)

    def _rank(self, query: _Features) -> tuple[RankedVisualCandidate, ...]:
        values: list[tuple[str, int, int]] = []
        for identity, _state, reference in self._references:
            inliers, good = _pair(self._matcher, query, reference)
            values.append((identity, inliers, good))
        return tuple(
            RankedVisualCandidate(identity, float(inliers))
            for identity, inliers, _ in sorted(
                values, key=lambda item: (item[1], item[2], item[0]), reverse=True
            )
        )


def _mask() -> np.ndarray:
    yy, xx = np.indices((_SIZE, _SIZE))
    return (xx - 56) ** 2 + (yy - 56) ** 2 <= _RADIUS**2


def _saturation(crop: ImageArray) -> float:
    return float(np.median(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[:, :, 1][_mask()]))


def _pair(matcher: cv2.BFMatcher, query: _Features, reference: _Features) -> tuple[int, int]:
    if query.descriptors is None or reference.descriptors is None:
        return 0, 0
    good = tuple(
        pair[0]
        for pair in matcher.knnMatch(query.descriptors, reference.descriptors, k=2)
        if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance
    )
    if len(good) < 4:
        return 0, len(good)
    left = np.array([query.points[item.queryIdx].pt for item in good], dtype=np.float32)
    right = np.array([reference.points[item.trainIdx].pt for item in good], dtype=np.float32)
    _, inliers = cv2.findHomography(left, right, cv2.RANSAC, 3.0)
    return (int(inliers.sum()) if inliers is not None else 0), len(good)


def _circles(image: ImageArray) -> list[tuple[int, int, int]]:
    return _circles_in_search(image, _SEARCH)


def _lower_row_recovery_circles(image: ImageArray) -> list[tuple[int, int, int]]:
    return _circles_in_search(image, _LOWER_ROW_RECOVERY_SEARCH)


def _circles_in_search(
    image: ImageArray,
    search: tuple[int, int, int, int],
) -> list[tuple[int, int, int]]:
    x, y, width, height = search
    gray = cv2.GaussianBlur(
        cv2.cvtColor(image[y : y + height, x : x + width], cv2.COLOR_BGR2GRAY),
        (7, 7),
        1.5,
    )
    found = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        1.2,
        120,
        param1=100,
        param2=35,
        minRadius=48,
        maxRadius=82,
    )
    if found is None:
        return []
    return sorted(
        [(round(a + x), round(b + y), round(c)) for a, b, c in found[0]],
        key=lambda item: (item[1], item[0]),
    )


def _rows(candidates: list[tuple[int, int, int]]) -> list[list[tuple[int, int, int]]]:
    bands: list[list[tuple[int, int, int]]] = []
    for item in candidates:
        band = next(
            (
                existing
                for existing in bands
                if abs(item[1] - round(sum(x[1] for x in existing) / len(existing))) < 45
            ),
            None,
        )
        if band is None:
            band = []
            bands.append(band)
        band.append(item)
    return [
        sorted(band) for band in sorted(bands, key=lambda band: sum(x[1] for x in band) / len(band))
    ]


def _candidate_is_detected_in_authorized_surface(
    candidate: tuple[int, int, int],
    *,
    search: tuple[int, int, int, int] = _SEARCH,
) -> bool:
    """Keep detected and inferred structural centers inside the authorized search geometry."""

    x, y, radius = candidate
    search_x, search_y, search_width, search_height = search
    return (
        48 <= radius <= 56
        and search_x <= x < search_x + search_width
        and search_y <= y < search_y + search_height
    )


def _candidate_has_safe_frame_crop(candidate: tuple[int, int, int], image: ImageArray) -> bool:
    """Require the local glyph crop to fit the actual captured frame, not the Hough ROI."""

    x, y, _radius = candidate
    half = _SIZE // 2
    height, width = image.shape[:2]
    return bool(half <= x <= width - half and half <= y <= height - half)


def _plausible_row(row: list[tuple[int, int, int]]) -> bool:
    return all(_candidate_is_detected_in_authorized_surface(item) for item in row) and all(
        120 <= right[0] - left[0] <= 190
        for left, right in zip(row, row[1:], strict=False)
    )


def _select_surface_layout(
    rows: list[list[tuple[int, int, int]]],
) -> tuple[str, tuple[int, ...]] | None:
    """Select one unambiguous full 9+6 surface; logical one-row fitting is separate."""

    full_pairs = tuple(
        (first_index, second_index)
        for first_index, first in enumerate(rows)
        for second_index, second in enumerate(rows)
        if first_index != second_index
        and len(first) == 9
        and len(second) == 6
        and _plausible_row(first)
        and _plausible_row(second)
        and _row_center_y(first) < _row_center_y(second)
    )
    if len(full_pairs) == 1:
        return "full_9x6", full_pairs[0]
    return None


def _reconstructed_second_rows(
    rows: list[list[tuple[int, int, int]]],
) -> tuple[tuple[int, tuple[tuple[int, int, int], ...]], ...]:
    """Compatibility projection for focused five-of-six geometry tests."""

    return tuple(
        (item.source_row_index, item.completed_centers)
        for item in _logical_second_row_candidates(rows)
        if item.inferred_missing_slot_index is not None
    )


def _reconstruct_second_row(
    row: list[tuple[int, int, int]],
) -> tuple[tuple[int, int, int], ...] | None:
    """Infer exactly one missing icon center from the fixed six-icon geometry, never its ID."""

    if len(row) != 5:
        return None
    candidates = _logical_second_row_candidates([row])
    return candidates[0].completed_centers if len(candidates) == 1 else None


def _logical_second_row_candidates(
    rows: list[list[tuple[int, int, int]]],
    *,
    authorized_search: tuple[int, int, int, int] = _SEARCH,
    detection_source: str = "primary",
) -> tuple[AdditionalLogicalRowCandidateDiagnostic, ...]:
    """Fit five or six detections to the six-slot lattice while ignoring neighboring residue."""

    candidates: list[AdditionalLogicalRowCandidateDiagnostic] = []
    for row_index, row in enumerate(rows):
        eligible = tuple(
            item
            for item in row
            if _candidate_is_detected_in_authorized_surface(
                item,
                search=authorized_search,
            )
        )
        if len(eligible) < 5:
            continue
        for matched_count in (6, 5):
            if len(eligible) < matched_count:
                continue
            missing_indices: tuple[int | None, ...] = (
                (None,)
                if matched_count == 6
                else tuple(range(len(_SECOND_ROW_NOMINAL_X_CENTERS)))
            )
            for selected in combinations(eligible, matched_count):
                for missing_index in missing_indices:
                    fitted = _fit_logical_second_row(
                        row_index,
                        tuple(sorted(selected)),
                        len(row),
                        missing_index,
                        authorized_search=authorized_search,
                        detection_source=detection_source,
                    )
                    if fitted is not None:
                        candidates.append(fitted)
    unique = {
        (
            item.source_row_index,
            item.completed_centers,
            item.inferred_missing_slot_index,
        ): item
        for item in candidates
    }
    maximum_matches_by_row = {
        row_index: max(
            item.matched_slot_count
            for item in unique.values()
            if item.source_row_index == row_index
        )
        for row_index in {item.source_row_index for item in unique.values()}
    }
    return tuple(
        sorted(
            (
                item
                for item in unique.values()
                if item.matched_slot_count
                == maximum_matches_by_row[item.source_row_index]
            ),
            key=lambda item: (
                item.source_row_index,
                -item.matched_slot_count,
                item.maximum_x_residual,
                item.inferred_missing_slot_index
                if item.inferred_missing_slot_index is not None
                else -1,
            ),
        )
    )


def _fit_logical_second_row(
    source_row_index: int,
    selected: tuple[tuple[int, int, int], ...],
    source_detection_count: int,
    missing_index: int | None,
    *,
    authorized_search: tuple[int, int, int, int],
    detection_source: str,
) -> AdditionalLogicalRowCandidateDiagnostic | None:
    slot_indices = tuple(
        index
        for index in range(len(_SECOND_ROW_NOMINAL_X_CENTERS))
        if index != missing_index
    )
    if len(selected) != len(slot_indices):
        return None
    if max(item[1] for item in selected) - min(item[1] for item in selected) > 18:
        return None
    offsets = tuple(
        candidate[0] - _SECOND_ROW_NOMINAL_X_CENTERS[index]
        for candidate, index in zip(selected, slot_indices, strict=True)
    )
    offset = round(float(np.median(offsets)))
    residual = max(abs(value - offset) for value in offsets)
    if abs(offset) > _SECOND_ROW_GEOMETRY_TOLERANCE or residual > _SECOND_ROW_GEOMETRY_TOLERANCE:
        return None
    y = round(float(np.median(tuple(item[1] for item in selected))))
    radius = round(float(np.median(tuple(item[2] for item in selected))))
    by_slot = dict(zip(slot_indices, selected, strict=True))
    completed = tuple(
        by_slot.get(index, (_SECOND_ROW_NOMINAL_X_CENTERS[index] + offset, y, radius))
        for index in range(len(_SECOND_ROW_NOMINAL_X_CENTERS))
    )
    if not all(
        _candidate_is_detected_in_authorized_surface(item, search=authorized_search)
        for item in completed
    ):
        return None
    return AdditionalLogicalRowCandidateDiagnostic(
        source_row_index=source_row_index,
        detected_centers=selected,
        completed_centers=completed,
        matched_slot_count=len(selected),
        maximum_x_residual=float(residual),
        inferred_missing_slot_index=missing_index,
        ignored_detection_count=source_detection_count - len(selected),
        detection_source=detection_source,
    )


def _row_center_y(row: list[tuple[int, int, int]]) -> float:
    return sum(item[1] for item in row) / len(row)


def _second_row_appearance_is_plausible(
    observations: list[AdditionalCovenantIdentityObservation],
) -> bool:
    """Require only relative state ordering; identity still comes exclusively from glyph ranking."""

    return min(item.state_saturation_median for item in observations[:2]) > max(
        item.state_saturation_median for item in observations[2:]
    )
