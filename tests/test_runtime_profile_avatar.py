from __future__ import annotations

import cv2
import numpy as np

from sentry_copilot.domain.runtime_association_core import (
    RuntimeAssociationParticipationState,
    RuntimeSlotAssociationObservation,
)
from sentry_copilot.vision.runtime_profile_avatar import (
    JP_MUMU_RUNTIME_CARD_BOTTOM_OVERLAY_EXCLUSION,
    RuntimeAvatarCompatibilityRequest,
    RuntimeAvatarCompatibilityStatus,
    RuntimeProfileAvatarObservation,
    SessionProfileAvatarReference,
    derive_runtime_avatar_compatibility,
)
from sentry_copilot.vision.viewport import PixelRoi


def _profile(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    image = rng.integers(0, 30, size=(92, 92, 3), dtype=np.uint8)
    for _ in range(12):
        center = tuple(int(value) for value in rng.integers(8, 84, size=2))
        radius = int(rng.integers(3, 10))
        color = tuple(int(value) for value in rng.integers(90, 256, size=3))
        cv2.circle(image, center, radius, color, 2, cv2.LINE_AA)
    for _ in range(6):
        start = tuple(int(value) for value in rng.integers(0, 92, size=2))
        end = tuple(int(value) for value in rng.integers(0, 92, size=2))
        color = tuple(int(value) for value in rng.integers(90, 256, size=3))
        cv2.line(image, start, end, color, 2, cv2.LINE_AA)
    cv2.putText(image, f"P{seed}", (6, 86), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
    return image


def _selection(identifier: str, image: np.ndarray) -> SessionProfileAvatarReference:
    return SessionProfileAvatarReference(
        session_player_id=identifier,
        frame_id="selection:000001",
        source_reference="synthetic-selection.png",
        pixel_bounds=PixelRoi(x=155, y=316, width=92, height=92),
        image=image,
    )


def _runtime(image: np.ndarray, *, slot: str = "runtime.slot.3") -> RuntimeProfileAvatarObservation:
    card = np.zeros((119, 121, 3), dtype=np.uint8)
    card[:100, :100] = cv2.resize(image, (100, 100), interpolation=cv2.INTER_CUBIC)
    card[100:, :] = (30, 210, 50)
    return RuntimeProfileAvatarObservation(
        runtime_slot_id=slot,
        frame_id="runtime:000021",
        source_reference="synthetic-runtime.png",
        pixel_bounds=PixelRoi(x=34, y=501, width=121, height=119),
        image=card,
        feature_exclusions=(JP_MUMU_RUNTIME_CARD_BOTTOM_OVERLAY_EXCLUSION,),
    )


def _request(
    selections: tuple[SessionProfileAvatarReference, ...],
    runtime: RuntimeProfileAvatarObservation,
) -> RuntimeAvatarCompatibilityRequest:
    return RuntimeAvatarCompatibilityRequest(
        session_id="session.synthetic",
        selection_references=selections,
        runtime_observation=runtime,
    )


def test_unique_avatar_returns_one_session_local_candidate_with_different_dimensions() -> None:
    first = _selection("participant.first", _profile(1))
    second = _selection("participant.second", _profile(2))

    result = derive_runtime_avatar_compatibility(_request((second, first), _runtime(_profile(1))))

    assert result.status is RuntimeAvatarCompatibilityStatus.UNIQUE
    assert result.candidate_session_player_ids == ("participant.first",)
    assert result.avatar_candidate_participant_ids == frozenset({"participant.first"})
    assert result.runtime_slot_id == "runtime.slot.3"
    assert result.runtime_pixel_bounds == PixelRoi(x=34, y=501, width=121, height=119)
    core_observation = RuntimeSlotAssociationObservation(
        runtime_slot_id=result.runtime_slot_id,
        participation_state=RuntimeAssociationParticipationState.ACTIVE,
        avatar_candidate_participant_ids=result.avatar_candidate_participant_ids,
    )
    assert core_observation.avatar_candidate_participant_ids == frozenset({"participant.first"})


def test_masked_runtime_overlay_does_not_prevent_matching() -> None:
    profile = _profile(3)
    observation = _runtime(profile)
    assert observation.image.shape == (119, 121, 3)

    result = derive_runtime_avatar_compatibility(
        _request((_selection("participant.overlay", profile),), observation)
    )

    assert result.status is RuntimeAvatarCompatibilityStatus.UNIQUE
    assert result.candidate_session_player_ids == ("participant.overlay",)


def test_duplicate_selection_avatars_remain_ambiguous_without_winner() -> None:
    profile = _profile(4)

    result = derive_runtime_avatar_compatibility(
        _request(
            (
                _selection("participant.alpha", profile),
                _selection("participant.beta", profile),
            ),
            _runtime(profile),
        )
    )

    assert result.status is RuntimeAvatarCompatibilityStatus.AMBIGUOUS
    assert result.candidate_session_player_ids == ("participant.alpha", "participant.beta")
    assert len([item for item in result.candidate_evidence if item.compatible]) == 2


def test_unrelated_avatar_is_unresolved_with_no_candidate() -> None:
    result = derive_runtime_avatar_compatibility(
        _request((_selection("participant.first", _profile(5)),), _runtime(_profile(99)))
    )

    assert result.status is RuntimeAvatarCompatibilityStatus.UNRESOLVED
    assert result.candidate_session_player_ids == ()
    assert result.avatar_candidate_participant_ids == frozenset()


def test_reference_payloads_are_immutable_and_selection_order_has_no_slot_meaning() -> None:
    target = _profile(7)
    selection = _selection("participant.target", target)
    result = derive_runtime_avatar_compatibility(
        _request(
            (
                _selection("participant.other", _profile(8)),
                selection,
            ),
            _runtime(target, slot="runtime.slot.1"),
        )
    )

    assert not selection.image.flags.writeable
    assert result.status is RuntimeAvatarCompatibilityStatus.UNIQUE
    assert result.runtime_slot_id == "runtime.slot.1"
    assert result.candidate_session_player_ids == ("participant.target",)
