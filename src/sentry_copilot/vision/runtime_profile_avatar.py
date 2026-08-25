"""Session-local profile-avatar compatibility evidence for runtime association.

This module compares caller-supplied player profile-avatar crops only.  It does not recognise
runtime state, identify a player globally, mutate session state, or treat a selection row as a
runtime slot.  Its output is a finite set of compatible *session* participants for M0.6b1a.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy as np

from sentry_copilot.capture.frame_source import ImageArray
from sentry_copilot.domain.identifiers import RuntimeSlotId, SessionId, SessionParticipantId
from sentry_copilot.vision.local_feature_matching import (
    FeatureExclusionRegion,
    LocalFeatureCandidateStatus,
    LocalFeatureMatcherConfig,
    LocalFeatureReferenceCandidate,
    LocalFeatureVisualMatcher,
)
from sentry_copilot.vision.viewport import PixelRoi
from sentry_copilot.vision.visual_references import (
    AvatarVisualReference,
    VisualCatalogKind,
    VisualReferenceAsset,
    VisualReferenceCatalog,
    VisualReferenceKind,
)

JP_MUMU_RUNTIME_CARD_BOTTOM_OVERLAY_EXCLUSION = FeatureExclusionRegion(
    x=0,
    y=100,
    width=121,
    height=19,
)
"""Calibrated exclusion for the bottom HP/presentation area of a 121x119 runtime card.

It is opt-in: callers must explicitly attach it to an observation from this known layout.
"""


class RuntimeAvatarCompatibilityStatus(StrEnum):
    """Whether visual evidence leaves zero, one, or multiple session participants."""

    UNIQUE = "unique"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class SessionProfileAvatarReference:
    """One caller-provided selection-side player profile avatar for this session only."""

    session_player_id: SessionParticipantId
    frame_id: str
    source_reference: str
    pixel_bounds: PixelRoi
    image: ImageArray

    def __post_init__(self) -> None:
        _validate_provenance(self.frame_id, self.source_reference)
        _validate_image(self.image, "selection profile avatar")
        _validate_geometry(self.pixel_bounds, self.image, "selection profile avatar")
        object.__setattr__(self, "image", _immutable_image(self.image))


@dataclass(frozen=True)
class RuntimeProfileAvatarObservation:
    """One caller-provided ACTIVE runtime profile-avatar/card crop and its provenance."""

    runtime_slot_id: RuntimeSlotId
    frame_id: str
    source_reference: str
    pixel_bounds: PixelRoi
    image: ImageArray
    feature_exclusions: tuple[FeatureExclusionRegion, ...] = ()

    def __post_init__(self) -> None:
        _validate_provenance(self.frame_id, self.source_reference)
        _validate_image(self.image, "runtime profile avatar")
        _validate_geometry(self.pixel_bounds, self.image, "runtime profile avatar")
        if not isinstance(self.feature_exclusions, tuple):
            raise TypeError("runtime profile-avatar feature exclusions must be an immutable tuple")
        for exclusion in self.feature_exclusions:
            if not isinstance(exclusion, FeatureExclusionRegion):
                raise TypeError("runtime profile-avatar exclusions must be FeatureExclusionRegion")
            exclusion.validate_for_image(width=self.image.shape[1], height=self.image.shape[0])
        object.__setattr__(self, "image", _immutable_image(self.image))


@dataclass(frozen=True)
class RuntimeAvatarCompatibilityRequest:
    """The complete, bounded session-local reference set for one runtime-slot observation."""

    session_id: SessionId
    selection_references: tuple[SessionProfileAvatarReference, ...]
    runtime_observation: RuntimeProfileAvatarObservation

    def __post_init__(self) -> None:
        if not 1 <= len(self.selection_references) <= 4:
            raise ValueError(
                "session-local avatar matching requires one to four selection references"
            )
        participant_ids = tuple(item.session_player_id for item in self.selection_references)
        if len(participant_ids) != len(set(participant_ids)):
            raise ValueError(
                "selection profile-avatar references must have unique session_player_id"
            )


@dataclass(frozen=True)
class RuntimeAvatarCandidateEvidence:
    """Debuggable local-feature evidence for one session participant, never an identity claim."""

    session_player_id: SessionParticipantId
    compatible: bool
    query_keypoint_count: int
    reference_keypoint_count: int
    lowe_ratio_match_count: int
    ransac_inlier_count: int
    inlier_ratio: float
    scale: float | None
    rotation_degrees: float | None
    rejection_reason: str | None


@dataclass(frozen=True)
class RuntimeAvatarCompatibilityResult:
    """Immutable supporting evidence consumable by the M0.6b1a candidate field."""

    session_id: SessionId
    runtime_slot_id: RuntimeSlotId
    runtime_frame_id: str
    runtime_source_reference: str
    runtime_pixel_bounds: PixelRoi
    status: RuntimeAvatarCompatibilityStatus
    candidate_session_player_ids: tuple[SessionParticipantId, ...]
    candidate_evidence: tuple[RuntimeAvatarCandidateEvidence, ...]
    reference_set_fingerprint: str

    def __post_init__(self) -> None:
        evidence_ids = tuple(item.session_player_id for item in self.candidate_evidence)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("avatar candidate evidence must have unique session participants")
        compatible_ids = tuple(
            item.session_player_id for item in self.candidate_evidence if item.compatible
        )
        if compatible_ids != self.candidate_session_player_ids:
            raise ValueError("avatar candidate IDs must match accepted candidate evidence")
        if self.status is RuntimeAvatarCompatibilityStatus.UNIQUE:
            if len(self.candidate_session_player_ids) != 1:
                raise ValueError("unique avatar compatibility requires exactly one participant")
        elif self.status is RuntimeAvatarCompatibilityStatus.AMBIGUOUS:
            if len(self.candidate_session_player_ids) < 2:
                raise ValueError("ambiguous avatar compatibility requires multiple participants")
        elif self.candidate_session_player_ids:
            raise ValueError("unresolved avatar compatibility cannot name a participant")
        if len(self.candidate_session_player_ids) != len(set(self.candidate_session_player_ids)):
            raise ValueError("avatar compatibility candidates must be unique")

    @property
    def avatar_candidate_participant_ids(self) -> frozenset[SessionParticipantId]:
        """Project to M0.6b1a's avatar-compatible candidate input without asserting identity."""

        return frozenset(self.candidate_session_player_ids)


def calibrated_runtime_avatar_matcher_config() -> LocalFeatureMatcherConfig:
    """Return the M0.6b1b1 calibration policy without changing global matcher defaults."""

    return LocalFeatureMatcherConfig(
        minimum_scale=0.55,
        maximum_scale=1.70,
        maximum_abs_rotation_degrees=8.0,
        minimum_inliers=3,
        minimum_inlier_ratio=0.09,
    )


def derive_runtime_avatar_compatibility(
    request: RuntimeAvatarCompatibilityRequest,
    *,
    matcher_config: LocalFeatureMatcherConfig | None = None,
) -> RuntimeAvatarCompatibilityResult:
    """Return all accepted session-local avatar candidates, never a score-selected winner.

    The local-feature matcher supplies geometric acceptance.  Every accepted participant remains
    a candidate; a second accepted avatar is an explicit ambiguity even if its raw evidence is
    weaker.  The domain association core remains responsible for combining this evidence with
    self-marker, HP, manual, and sticky facts.
    """

    catalog, identity_to_participant = _session_local_catalog(request)
    config = matcher_config or calibrated_runtime_avatar_matcher_config()
    matcher = LocalFeatureVisualMatcher(catalog, config)
    match = matcher.match(
        request.runtime_observation.image,
        query_reference=request.runtime_observation.source_reference,
        query_render_context=None,
        query_feature_exclusions=request.runtime_observation.feature_exclusions,
    )
    evidence = tuple(
        _candidate_evidence(
            candidate.best_reference,
            identity_to_participant[candidate.identity_id],
        )
        for candidate in match.identity_candidates
    )
    candidates = tuple(
        item.session_player_id for item in evidence if item.compatible
    )
    status = (
        RuntimeAvatarCompatibilityStatus.UNIQUE
        if len(candidates) == 1
        else RuntimeAvatarCompatibilityStatus.AMBIGUOUS
        if len(candidates) > 1
        else RuntimeAvatarCompatibilityStatus.UNRESOLVED
    )
    return RuntimeAvatarCompatibilityResult(
        session_id=request.session_id,
        runtime_slot_id=request.runtime_observation.runtime_slot_id,
        runtime_frame_id=request.runtime_observation.frame_id,
        runtime_source_reference=request.runtime_observation.source_reference,
        runtime_pixel_bounds=request.runtime_observation.pixel_bounds,
        status=status,
        candidate_session_player_ids=candidates,
        candidate_evidence=evidence,
        reference_set_fingerprint=catalog.fingerprint,
    )


def _session_local_catalog(
    request: RuntimeAvatarCompatibilityRequest,
) -> tuple[VisualReferenceCatalog, dict[str, SessionParticipantId]]:
    """Build an in-memory, non-persistent catalog whose identities are opaque local handles."""

    assets: list[VisualReferenceAsset] = []
    references: list[AvatarVisualReference] = []
    identity_to_participant: dict[str, SessionParticipantId] = {}
    fingerprint_parts: list[str] = []
    for index, selection in enumerate(request.selection_references):
        identity_id = f"session-avatar-{index}"
        asset_id = f"session-avatar-asset-{index}"
        digest = _image_sha256(selection.image)
        assets.append(
            VisualReferenceAsset(
                asset_id=asset_id,
                asset_reference=selection.source_reference,
                path=Path(f"session://{request.session_id}/avatar/{index}"),
                sha256=digest,
                width=selection.image.shape[1],
                height=selection.image.shape[0],
                provenance=selection.source_reference,
                image=selection.image,
            )
        )
        references.append(
            AvatarVisualReference(
                avatar_id=identity_id,
                asset_id=asset_id,
                reference_kind=VisualReferenceKind.OTHER_EXPLICIT_RENDER_CONTEXT,
            )
        )
        identity_to_participant[identity_id] = selection.session_player_id
        fingerprint_parts.append(f"{selection.session_player_id}:{digest}")
    fingerprint = hashlib.sha256("|".join(fingerprint_parts).encode("utf-8")).hexdigest()
    return (
        VisualReferenceCatalog(
            kind=VisualCatalogKind.AVATAR,
            catalog_path=Path(f"session://{request.session_id}/profile-avatar-references"),
            schema_version=1,
            fingerprint=fingerprint,
            assets=tuple(assets),
            references=tuple(references),
        ),
        identity_to_participant,
    )


def _candidate_evidence(
    candidate: object,
    session_player_id: SessionParticipantId,
) -> RuntimeAvatarCandidateEvidence:
    if not isinstance(candidate, LocalFeatureReferenceCandidate):
        raise TypeError("local-feature avatar candidate has an unexpected type")
    return RuntimeAvatarCandidateEvidence(
        session_player_id=session_player_id,
        compatible=candidate.status is LocalFeatureCandidateStatus.VALID,
        query_keypoint_count=candidate.query_keypoint_count,
        reference_keypoint_count=candidate.reference_keypoint_count,
        lowe_ratio_match_count=candidate.lowe_ratio_match_count,
        ransac_inlier_count=candidate.ransac_inlier_count,
        inlier_ratio=candidate.inlier_ratio,
        scale=candidate.scale,
        rotation_degrees=candidate.rotation_degrees,
        rejection_reason=(candidate.rejection_reason.value if candidate.rejection_reason else None),
    )


def _image_sha256(image: ImageArray) -> str:
    return hashlib.sha256(image.tobytes()).hexdigest()


def _validate_provenance(frame_id: str, source_reference: str) -> None:
    if not frame_id.strip() or not source_reference.strip():
        raise ValueError("profile-avatar frame_id and source_reference must not be blank")


def _validate_image(image: ImageArray, label: str) -> None:
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"{label} image must be a uint8 BGR image")
    if image.shape[0] <= 0 or image.shape[1] <= 0:
        raise ValueError(f"{label} image must be non-empty")


def _validate_geometry(bounds: PixelRoi, image: ImageArray, label: str) -> None:
    if (bounds.width, bounds.height) != (image.shape[1], image.shape[0]):
        raise ValueError(f"{label} pixel_bounds must match image dimensions")


def _immutable_image(image: ImageArray) -> ImageArray:
    payload = np.array(image, dtype=np.uint8, copy=True)
    payload.setflags(write=False)
    return payload
