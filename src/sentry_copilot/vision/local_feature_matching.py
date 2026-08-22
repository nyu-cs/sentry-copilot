"""Catalog-backed local-feature matching for cross-layout visual identity evidence."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt

from sentry_copilot.capture.frame_source import ImageArray
from sentry_copilot.image_io import ImageDecodeError, load_bgr_image
from sentry_copilot.vision.visual_references import (
    StrategyVisualReference,
    VisualCatalogKind,
    VisualMatchStatus,
    VisualReference,
    VisualReferenceAsset,
    VisualReferenceCatalog,
    VisualReferenceKind,
)

FloatArray = npt.NDArray[np.float32]


@dataclass(frozen=True)
class FeatureExclusionRegion:
    """One pixel-space rectangle excluded from feature extraction, never image pixels."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        values = (self.x, self.y, self.width, self.height)
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise TypeError("feature exclusion geometry must use integer pixels")
        if self.x < 0 or self.y < 0:
            raise ValueError("feature exclusion origin must be non-negative")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("feature exclusion dimensions must be positive")

    def validate_for_image(self, *, width: int, height: int) -> None:
        """Reject an exclusion that does not fit exactly within one image."""

        if self.x + self.width > width or self.y + self.height > height:
            raise ValueError(
                "feature exclusion region exceeds image bounds: "
                f"{self.x},{self.y},{self.width},{self.height} for {width}x{height}"
            )


@dataclass(frozen=True)
class FeatureExclusionPolicy:
    """Presentation-only exclusions shared by one declared render context."""

    render_context: VisualReferenceKind
    regions: tuple[FeatureExclusionRegion, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.render_context, VisualReferenceKind):
            raise TypeError("feature exclusion policy render_context must be a VisualReferenceKind")
        if not isinstance(self.regions, tuple):
            raise TypeError("feature exclusion policy regions must be an immutable tuple")
        if not self.regions:
            raise ValueError("feature exclusion policy requires at least one region")
        if any(not isinstance(region, FeatureExclusionRegion) for region in self.regions):
            raise TypeError(
                "feature exclusion policy regions must be FeatureExclusionRegion values"
            )


SELECTION_GRID_RENDER_BADGE_EXCLUSION = FeatureExclusionRegion(
    x=124,
    y=0,
    width=28,
    height=28,
)
"""Validated top-right completion-badge exclusion for a 152x128 selection-grid crop."""


SELECTION_GRID_RENDER_FEATURE_EXCLUSION_POLICY = FeatureExclusionPolicy(
    render_context=VisualReferenceKind.SELECTION_GRID_RENDER,
    regions=(SELECTION_GRID_RENDER_BADGE_EXCLUSION,),
)
"""Opt-in policy for the validated selection-grid render context."""


class LocalFeatureCandidateStatus(StrEnum):
    """Whether one reference produced accepted geometric identity evidence."""

    VALID = "valid"
    REJECTED = "rejected"


class LocalFeatureRejectionReason(StrEnum):
    """Typed reason why one query/reference comparison was not accepted."""

    QUERY_NO_DESCRIPTORS = "query_no_descriptors"
    REFERENCE_NO_DESCRIPTORS = "reference_no_descriptors"
    INSUFFICIENT_RATIO_MATCHES = "insufficient_ratio_matches"
    TRANSFORM_ESTIMATION_FAILED = "transform_estimation_failed"
    SCALE_OUT_OF_RANGE = "scale_out_of_range"
    ROTATION_OUT_OF_RANGE = "rotation_out_of_range"
    INSUFFICIENT_INLIERS = "insufficient_inliers"


class LocalFeatureMatchError(ValueError):
    """A caller-supplied query cannot be decoded or matched."""


@dataclass(frozen=True)
class LocalFeatureMatcherConfig:
    """Shared matcher policy; defaults reproduce the seven-anchor feasibility experiment."""

    sift_nfeatures: int = 300
    sift_contrast_threshold: float = 0.02
    sift_edge_threshold: float = 10.0
    lowe_ratio: float = 0.75
    ransac_reprojection_threshold: float = 3.0
    minimum_scale: float = 0.80
    maximum_scale: float = 1.60
    maximum_abs_rotation_degrees: float = 5.0
    minimum_inliers: int = 3
    minimum_inlier_ratio: float = 0.0
    ambiguity_margin: float = 0.0
    feature_exclusion_policies: tuple[FeatureExclusionPolicy, ...] = ()

    def __post_init__(self) -> None:
        if self.sift_nfeatures <= 0:
            raise ValueError("sift_nfeatures must be positive")
        if self.sift_contrast_threshold <= 0 or self.sift_edge_threshold <= 0:
            raise ValueError("SIFT thresholds must be positive")
        if not 0 < self.lowe_ratio < 1:
            raise ValueError("lowe_ratio must be between 0 and 1")
        if self.ransac_reprojection_threshold <= 0:
            raise ValueError("ransac_reprojection_threshold must be positive")
        if self.minimum_scale <= 0 or self.maximum_scale < self.minimum_scale:
            raise ValueError("scale range must be positive and ordered")
        if self.maximum_abs_rotation_degrees < 0:
            raise ValueError("maximum_abs_rotation_degrees must be non-negative")
        if self.minimum_inliers < 3:
            raise ValueError("minimum_inliers must be at least 3")
        if not 0 <= self.minimum_inlier_ratio <= 1:
            raise ValueError("minimum_inlier_ratio must be between 0 and 1")
        if self.ambiguity_margin < 0:
            raise ValueError("ambiguity_margin must be non-negative")
        if not isinstance(self.feature_exclusion_policies, tuple):
            raise TypeError("feature exclusion policies must be an immutable tuple")
        if any(
            not isinstance(policy, FeatureExclusionPolicy)
            for policy in self.feature_exclusion_policies
        ):
            raise TypeError("feature exclusion policies must contain FeatureExclusionPolicy values")
        contexts = tuple(policy.render_context for policy in self.feature_exclusion_policies)
        if len(contexts) != len(set(contexts)):
            raise ValueError("feature exclusion policies must not repeat a render context")


@dataclass(frozen=True)
class LocalFeatureReferenceCandidate:
    """Raw local-feature evidence for one catalog reference asset.

    Transform values always map query pixel coordinates into reference pixel coordinates.
    Translation is measured in reference-image pixels.
    """

    identity_id: str
    asset_id: str
    asset_sha256: str
    asset_provenance: str | None
    reference_kind: VisualReferenceKind
    catalog_schema_version: int
    catalog_fingerprint: str
    query_keypoint_count: int
    reference_keypoint_count: int
    raw_descriptor_match_count: int
    lowe_ratio_match_count: int
    ransac_inlier_count: int
    inlier_ratio: float
    scale: float | None
    rotation_degrees: float | None
    x_translation: float | None
    y_translation: float | None
    geometry_valid: bool
    status: LocalFeatureCandidateStatus
    rejection_reason: LocalFeatureRejectionReason | None


@dataclass(frozen=True)
class LocalFeatureIdentityCandidate:
    """Strongest deterministic reference evidence aggregated for one visual identity."""

    identity_id: str
    score: float
    valid_reference_count: int
    best_reference: LocalFeatureReferenceCandidate


@dataclass(frozen=True)
class LocalFeatureVisualMatchResult:
    """Immutable identity-level local-feature result with complete reference evidence."""

    kind: VisualCatalogKind
    catalog_path: Path
    catalog_schema_version: int
    catalog_fingerprint: str
    query_reference: str
    query_sha256: str
    query_width: int
    query_height: int
    query_feature_exclusions: tuple[FeatureExclusionRegion, ...]
    config: LocalFeatureMatcherConfig
    status: VisualMatchStatus
    identity_candidates: tuple[LocalFeatureIdentityCandidate, ...]
    reference_candidates: tuple[LocalFeatureReferenceCandidate, ...]
    selected_identity: LocalFeatureIdentityCandidate | None


@dataclass(frozen=True)
class _FeatureSet:
    points: FloatArray
    descriptors: FloatArray | None

    @property
    def keypoint_count(self) -> int:
        return int(self.points.shape[0])


@dataclass(frozen=True)
class _PreparedReference:
    reference: VisualReference
    asset: VisualReferenceAsset
    features: _FeatureSet


@dataclass(frozen=True)
class _CandidateValues:
    identity_id: str
    asset_id: str
    asset_sha256: str
    asset_provenance: str | None
    reference_kind: VisualReferenceKind
    catalog_schema_version: int
    catalog_fingerprint: str
    query_keypoint_count: int
    reference_keypoint_count: int
    raw_descriptor_match_count: int = 0
    lowe_ratio_match_count: int = 0
    ransac_inlier_count: int = 0
    inlier_ratio: float = 0.0
    scale: float | None = None
    rotation_degrees: float | None = None
    x_translation: float | None = None
    y_translation: float | None = None


class LocalFeatureVisualMatcher:
    """Precompute catalog SIFT descriptors and match explicit BGR query images safely."""

    def __init__(
        self,
        catalog: VisualReferenceCatalog,
        config: LocalFeatureMatcherConfig | None = None,
    ) -> None:
        self.catalog = catalog
        self.config = config or LocalFeatureMatcherConfig()
        sift_create = cv2.__dict__.get("SIFT_create")
        if not callable(sift_create):
            raise LocalFeatureMatchError("OpenCV SIFT support is unavailable")
        try:
            self._sift = sift_create(
                nfeatures=self.config.sift_nfeatures,
                contrastThreshold=self.config.sift_contrast_threshold,
                edgeThreshold=self.config.sift_edge_threshold,
            )
        except cv2.error as error:
            raise LocalFeatureMatchError("OpenCV SIFT support is unavailable") from error
        self._descriptor_matcher = cv2.BFMatcher(cv2.NORM_L2)
        self._policies = {
            policy.render_context: policy.regions
            for policy in self.config.feature_exclusion_policies
        }
        cache = {
            (reference.asset_id, reference.reference_kind): self._detect(
                catalog.asset(reference.asset_id).image,
                self._exclusions_for_context(reference.reference_kind),
            )
            for reference in catalog.references
        }
        self._prepared_references = tuple(
            _PreparedReference(
                reference=reference,
                asset=catalog.asset(reference.asset_id),
                features=cache[(reference.asset_id, reference.reference_kind)],
            )
            for reference in catalog.references
        )
        self._cached_reference_asset_ids = tuple(sorted({asset_id for asset_id, _ in cache}))
        self._cached_reference_feature_keys = tuple(
            sorted((asset_id, context.value) for asset_id, context in cache)
        )

    @property
    def cached_reference_asset_ids(self) -> tuple[str, ...]:
        """Expose stable cache coverage without leaking mutable OpenCV descriptor arrays."""

        return self._cached_reference_asset_ids

    @property
    def cached_reference_feature_keys(self) -> tuple[tuple[str, str], ...]:
        """Expose context-sensitive in-memory descriptor cache keys for diagnostics."""

        return self._cached_reference_feature_keys

    def match_path(
        self,
        path: str | Path,
        *,
        query_render_context: VisualReferenceKind | None = None,
        query_feature_exclusions: tuple[FeatureExclusionRegion, ...] = (),
    ) -> LocalFeatureVisualMatchResult:
        """Load one explicit query with optional context or caller-supplied exclusions."""

        query_path = Path(path)
        try:
            image = load_bgr_image(query_path)
            digest = _file_sha256(query_path)
        except (ImageDecodeError, OSError) as error:
            raise LocalFeatureMatchError(
                f"cannot load local-feature query: {query_path}"
            ) from error
        return self.match(
            image,
            query_reference=str(query_path),
            query_sha256=digest,
            query_render_context=query_render_context,
            query_feature_exclusions=query_feature_exclusions,
        )

    def match(
        self,
        query_image: ImageArray,
        *,
        query_reference: str,
        query_sha256: str | None = None,
        query_render_context: VisualReferenceKind | None = None,
        query_feature_exclusions: tuple[FeatureExclusionRegion, ...] = (),
    ) -> LocalFeatureVisualMatchResult:
        """Match one explicit BGR crop without resizing or mutating its payload."""

        _validate_bgr(query_image)
        if not query_reference.strip():
            raise ValueError("query_reference must not be blank")
        payload = np.array(query_image, dtype=np.uint8, copy=True)
        digest = query_sha256 or hashlib.sha256(payload.tobytes()).hexdigest()
        query_exclusions = (
            self._exclusions_for_context(query_render_context) + query_feature_exclusions
        )
        query_features = self._detect(payload, query_exclusions)
        reference_candidates = tuple(
            self._compare(query_features, prepared)
            for prepared in self._prepared_references
        )
        identity_candidates = _aggregate_identity_candidates(reference_candidates)
        status, selected = _resolve_identity_match(identity_candidates, self.config)
        height, width = payload.shape[:2]
        return LocalFeatureVisualMatchResult(
            kind=self.catalog.kind,
            catalog_path=self.catalog.catalog_path,
            catalog_schema_version=self.catalog.schema_version,
            catalog_fingerprint=self.catalog.fingerprint,
            query_reference=query_reference,
            query_sha256=digest,
            query_width=width,
            query_height=height,
            query_feature_exclusions=query_exclusions,
            config=self.config,
            status=status,
            identity_candidates=identity_candidates,
            reference_candidates=reference_candidates,
            selected_identity=selected,
        )

    def _exclusions_for_context(
        self, context: VisualReferenceKind | None
    ) -> tuple[FeatureExclusionRegion, ...]:
        if context is None:
            return ()
        return self._policies.get(context, ())

    def _detect(
        self,
        image: ImageArray,
        exclusions: tuple[FeatureExclusionRegion, ...] = (),
    ) -> _FeatureSet:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        mask = _feature_mask(gray.shape[1], gray.shape[0], exclusions)
        keypoints, descriptors = self._sift.detectAndCompute(gray, mask)
        points = np.asarray(
            [keypoint.pt for keypoint in keypoints], dtype=np.float32
        ).reshape(-1, 2)
        points.setflags(write=False)
        if descriptors is None:
            return _FeatureSet(points=points, descriptors=None)
        descriptor_array = np.asarray(descriptors, dtype=np.float32)
        descriptor_array.setflags(write=False)
        return _FeatureSet(points=points, descriptors=descriptor_array)

    def _compare(
        self,
        query: _FeatureSet,
        prepared: _PreparedReference,
    ) -> LocalFeatureReferenceCandidate:
        reference = prepared.features
        base = _candidate_base(self.catalog, prepared, query, reference)
        if query.descriptors is None:
            return _rejected(base, LocalFeatureRejectionReason.QUERY_NO_DESCRIPTORS)
        if reference.descriptors is None:
            return _rejected(base, LocalFeatureRejectionReason.REFERENCE_NO_DESCRIPTORS)
        raw_matches = self._descriptor_matcher.knnMatch(
            query.descriptors,
            reference.descriptors,
            k=2,
        )
        accepted = tuple(
            pair[0]
            for pair in raw_matches
            if len(pair) == 2 and pair[0].distance < self.config.lowe_ratio * pair[1].distance
        )
        base = replace(
            base,
            raw_descriptor_match_count=len(raw_matches),
            lowe_ratio_match_count=len(accepted),
        )
        if len(accepted) < self.config.minimum_inliers:
            return _rejected(base, LocalFeatureRejectionReason.INSUFFICIENT_RATIO_MATCHES)
        source_points = np.asarray(
            [query.points[item.queryIdx] for item in accepted],
            dtype=np.float32,
        ).reshape(-1, 1, 2)
        target_points = np.asarray(
            [reference.points[item.trainIdx] for item in accepted],
            dtype=np.float32,
        ).reshape(-1, 1, 2)
        transform, inlier_mask = cv2.estimateAffinePartial2D(
            source_points,
            target_points,
            method=cv2.RANSAC,
            ransacReprojThreshold=self.config.ransac_reprojection_threshold,
            maxIters=2000,
            confidence=0.99,
            refineIters=10,
        )
        if transform is None or inlier_mask is None:
            return _rejected(base, LocalFeatureRejectionReason.TRANSFORM_ESTIMATION_FAILED)
        scale = float(math.hypot(transform[0, 0], transform[1, 0]))
        rotation = float(math.degrees(math.atan2(transform[1, 0], transform[0, 0])))
        inliers = int(np.asarray(inlier_mask).reshape(-1).sum())
        base = replace(
            base,
            ransac_inlier_count=inliers,
            inlier_ratio=inliers / max(1, query.keypoint_count),
            scale=scale,
            rotation_degrees=rotation,
            x_translation=float(transform[0, 2]),
            y_translation=float(transform[1, 2]),
        )
        if not self.config.minimum_scale <= scale <= self.config.maximum_scale:
            return _rejected(base, LocalFeatureRejectionReason.SCALE_OUT_OF_RANGE)
        if abs(rotation) > self.config.maximum_abs_rotation_degrees:
            return _rejected(base, LocalFeatureRejectionReason.ROTATION_OUT_OF_RANGE)
        if inliers < self.config.minimum_inliers:
            return _rejected(base, LocalFeatureRejectionReason.INSUFFICIENT_INLIERS)
        return _candidate_result(
            base,
            geometry_valid=True,
            status=LocalFeatureCandidateStatus.VALID,
            rejection_reason=None,
        )


def write_local_feature_match_report(
    result: LocalFeatureVisualMatchResult,
    output_directory: str | Path,
) -> Path:
    """Write one caller-owned JSON report with raw feature and transform evidence."""

    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    output_path = destination / "visual-local-feature-match.json"
    output_path.write_text(
        json.dumps(_result_json(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def _feature_mask(
    width: int,
    height: int,
    exclusions: tuple[FeatureExclusionRegion, ...],
) -> npt.NDArray[np.uint8] | None:
    """Return a SIFT-accepted uint8 mask without changing the supplied image."""

    if not exclusions:
        return None
    mask = np.full((height, width), 255, dtype=np.uint8)
    for region in exclusions:
        region.validate_for_image(width=width, height=height)
        mask[region.y : region.y + region.height, region.x : region.x + region.width] = 0
    return mask


def _candidate_base(
    catalog: VisualReferenceCatalog,
    prepared: _PreparedReference,
    query: _FeatureSet,
    reference: _FeatureSet,
) -> _CandidateValues:
    return _CandidateValues(
        identity_id=_identity_id(prepared.reference),
        asset_id=prepared.asset.asset_id,
        asset_sha256=prepared.asset.sha256,
        asset_provenance=prepared.asset.provenance,
        reference_kind=prepared.reference.reference_kind,
        catalog_schema_version=catalog.schema_version,
        catalog_fingerprint=catalog.fingerprint,
        query_keypoint_count=query.keypoint_count,
        reference_keypoint_count=reference.keypoint_count,
    )


def _candidate_result(
    values: _CandidateValues,
    *,
    geometry_valid: bool,
    status: LocalFeatureCandidateStatus,
    rejection_reason: LocalFeatureRejectionReason | None,
) -> LocalFeatureReferenceCandidate:
    return LocalFeatureReferenceCandidate(
        identity_id=values.identity_id,
        asset_id=values.asset_id,
        asset_sha256=values.asset_sha256,
        asset_provenance=values.asset_provenance,
        reference_kind=values.reference_kind,
        catalog_schema_version=values.catalog_schema_version,
        catalog_fingerprint=values.catalog_fingerprint,
        query_keypoint_count=values.query_keypoint_count,
        reference_keypoint_count=values.reference_keypoint_count,
        raw_descriptor_match_count=values.raw_descriptor_match_count,
        lowe_ratio_match_count=values.lowe_ratio_match_count,
        ransac_inlier_count=values.ransac_inlier_count,
        inlier_ratio=values.inlier_ratio,
        scale=values.scale,
        rotation_degrees=values.rotation_degrees,
        x_translation=values.x_translation,
        y_translation=values.y_translation,
        geometry_valid=geometry_valid,
        status=status,
        rejection_reason=rejection_reason,
    )


def _rejected(
    values: _CandidateValues,
    reason: LocalFeatureRejectionReason,
) -> LocalFeatureReferenceCandidate:
    return _candidate_result(
        values,
        geometry_valid=False,
        status=LocalFeatureCandidateStatus.REJECTED,
        rejection_reason=reason,
    )

def _aggregate_identity_candidates(
    candidates: tuple[LocalFeatureReferenceCandidate, ...],
) -> tuple[LocalFeatureIdentityCandidate, ...]:
    grouped: dict[str, list[LocalFeatureReferenceCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.identity_id, []).append(candidate)
    identities: list[LocalFeatureIdentityCandidate] = []
    for identity_id, references in grouped.items():
        ranked = sorted(
            references,
            key=lambda item: (
                -int(item.geometry_valid),
                -item.inlier_ratio,
                -item.ransac_inlier_count,
                -item.lowe_ratio_match_count,
                item.asset_id,
            ),
        )
        best = ranked[0]
        identities.append(
            LocalFeatureIdentityCandidate(
                identity_id=identity_id,
                score=best.inlier_ratio if best.geometry_valid else 0.0,
                valid_reference_count=sum(item.geometry_valid for item in references),
                best_reference=best,
            )
        )
    return tuple(
        sorted(
            identities,
            key=lambda item: (
                -int(item.best_reference.geometry_valid),
                -item.score,
                item.identity_id,
            ),
        )
    )


def _resolve_identity_match(
    candidates: tuple[LocalFeatureIdentityCandidate, ...],
    config: LocalFeatureMatcherConfig,
) -> tuple[VisualMatchStatus, LocalFeatureIdentityCandidate | None]:
    eligible = tuple(
        candidate
        for candidate in candidates
        if candidate.best_reference.geometry_valid
        and candidate.score >= config.minimum_inlier_ratio
    )
    if not eligible:
        return VisualMatchStatus.UNRESOLVED, None
    top = eligible[0]
    if len(eligible) > 1 and top.score - eligible[1].score <= config.ambiguity_margin:
        return VisualMatchStatus.AMBIGUOUS, None
    return VisualMatchStatus.MATCHED, top


def _identity_id(reference: VisualReference) -> str:
    return (
        reference.strategy_id
        if isinstance(reference, StrategyVisualReference)
        else reference.avatar_id
    )


def _validate_bgr(image: ImageArray) -> None:
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("query image must be a uint8 BGR image")
    if image.shape[0] <= 0 or image.shape[1] <= 0:
        raise ValueError("query image must not be empty")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _result_json(result: LocalFeatureVisualMatchResult) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": result.kind.value,
        "catalog_path": str(result.catalog_path),
        "catalog_schema_version": result.catalog_schema_version,
        "catalog_fingerprint": result.catalog_fingerprint,
        "query": {
            "path": result.query_reference,
            "sha256": result.query_sha256,
            "width": result.query_width,
            "height": result.query_height,
            "feature_exclusions": [
                _region_json(region) for region in result.query_feature_exclusions
            ],
        },
        "matcher": {
            "type": "sift_similarity_ransac",
            "transform_direction": "query_to_reference",
            "configuration": _config_json(result.config),
            "score_semantics": "ransac_inliers_divided_by_query_keypoints",
        },
        "status": result.status.value,
        "selected_identity": _identity_candidate_json(result.selected_identity),
        "identity_candidates": [
            _identity_candidate_json(candidate) for candidate in result.identity_candidates
        ],
        "reference_candidates": [
            _reference_candidate_json(candidate) for candidate in result.reference_candidates
        ],
    }


def _region_json(region: FeatureExclusionRegion) -> dict[str, int]:
    return {"x": region.x, "y": region.y, "width": region.width, "height": region.height}


def _config_json(config: LocalFeatureMatcherConfig) -> dict[str, object]:
    values = asdict(config)
    values["feature_exclusion_policies"] = [
        {
            "render_context": policy.render_context.value,
            "regions": [_region_json(region) for region in policy.regions],
        }
        for policy in config.feature_exclusion_policies
    ]
    return values


def _identity_candidate_json(
    candidate: LocalFeatureIdentityCandidate | None,
) -> dict[str, object] | None:
    if candidate is None:
        return None
    return {
        "identity_id": candidate.identity_id,
        "score": candidate.score,
        "valid_reference_count": candidate.valid_reference_count,
        "best_reference_asset_id": candidate.best_reference.asset_id,
    }


def _reference_candidate_json(
    candidate: LocalFeatureReferenceCandidate,
) -> dict[str, object]:
    return {
        "identity_id": candidate.identity_id,
        "asset_id": candidate.asset_id,
        "asset_sha256": candidate.asset_sha256,
        "asset_provenance": candidate.asset_provenance,
        "reference_kind": candidate.reference_kind.value,
        "catalog_schema_version": candidate.catalog_schema_version,
        "catalog_fingerprint": candidate.catalog_fingerprint,
        "query_keypoint_count": candidate.query_keypoint_count,
        "reference_keypoint_count": candidate.reference_keypoint_count,
        "raw_descriptor_match_count": candidate.raw_descriptor_match_count,
        "lowe_ratio_match_count": candidate.lowe_ratio_match_count,
        "ransac_inlier_count": candidate.ransac_inlier_count,
        "inlier_ratio": candidate.inlier_ratio,
        "transform": {
            "direction": "query_to_reference",
            "scale": candidate.scale,
            "rotation_degrees": candidate.rotation_degrees,
            "x_translation_reference_pixels": candidate.x_translation,
            "y_translation_reference_pixels": candidate.y_translation,
        },
        "geometry_valid": candidate.geometry_valid,
        "status": candidate.status.value,
        "rejection_reason": candidate.rejection_reason.value
        if candidate.rejection_reason is not None
        else None,
    }
