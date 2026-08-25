from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from typing import cast

import numpy as np
import pytest

from sentry_copilot.capture.frame_source import Frame, FrameSourceType, ImageArray
from sentry_copilot.domain.runtime_association_core import (
    PreviousConfirmedRuntimeAssociation,
    RuntimeAssociationInput,
    RuntimeAssociationParticipationState,
    RuntimeAssociationResolutionStatus,
    RuntimeSlotAssociationObservation,
    SelectionParticipantAssociationFact,
    derive_runtime_associations,
)
from sentry_copilot.domain.strategy_selection import SelectionOutcome
from sentry_copilot.vision.ocr import OcrBackendReading, OcrStatus
from sentry_copilot.vision.runtime_preparation_checkpoint import (
    CheckpointFrameProvenance,
    OcrEvidence,
    PreparationCheckpoint,
    PreparationPhaseStatus,
    PreparationRecognition,
    PreparationRecognitionMethod,
    RoundNumberMethod,
    RoundNumberObservation,
    RuntimeHpObservation,
    RuntimeHpStatus,
    RuntimeInitialHpEvidence,
    RuntimePreparationCheckpointRequest,
    RuntimeSelfMarkerAggregate,
    RuntimeSelfMarkerAggregateStatus,
    RuntimeSelfMarkerObservation,
    RuntimeSelfMarkerStatus,
    RuntimeSlotVisualPosition,
    aggregate_runtime_self_markers,
    derive_runtime_initial_hp_evidence,
    observe_jp_mumu_preparation_checkpoint,
    project_unique_self_marker_to_association_core,
)
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi


class _QueuedBackend:
    def __init__(self, values: list[str | None]) -> None:
        self._values = deque(values)
        self.images: list[ImageArray] = []

    async def recognize(self, image: ImageArray, *, language_tag: str) -> OcrBackendReading:
        self.images.append(image)
        return OcrBackendReading(self._values.popleft())


def _frame(*, self_slots: tuple[int, ...] = ()) -> Frame:
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    for slot in self_slots:
        y = 211 + 145 * (slot - 1)
        image[y : y + 36, 34:70] = (120, 200, 100)
    return Frame(
        frame_id="synthetic:checkpoint:000001",
        frame_index=1,
        processed_at=datetime(2026, 8, 25, tzinfo=UTC),
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic-checkpoint",
        width=1920,
        height=1080,
        image=image,
        source_reference="synthetic-checkpoint.png",
    )


def _request(*slot_ids: str) -> RuntimePreparationCheckpointRequest:
    return RuntimePreparationCheckpointRequest(
        session_id="session.synthetic",
        runtime_slots=tuple(
            RuntimeSlotVisualPosition(runtime_slot_id=slot_id, visual_index=index)
            for index, slot_id in enumerate(slot_ids, start=1)
        ),
    )


def _ocr_evidence() -> OcrEvidence:
    return OcrEvidence(
        pixel_bounds=PixelRoi(x=0, y=0, width=1, height=1),
        raw_text="synthetic",
        normalized_text="synthetic",
        confidence=1.0,
        status=OcrStatus.RECOGNIZED,
    )


def _checkpoint(
    *,
    round_number: int | None,
    hp_by_slot: dict[str, int | None],
) -> PreparationCheckpoint:
    frame = _frame()
    slots = tuple(hp_by_slot)
    marker_observations = tuple(
        RuntimeSelfMarkerObservation(
            runtime_slot_id=slot,
            status=RuntimeSelfMarkerStatus.SELF_MARKER_ABSENT,
            pixel_bounds=PixelRoi(x=0, y=0, width=1, height=1),
            teal_pixel_count=0,
            threshold_pixel_count=300,
        )
        for slot in slots
    )
    return PreparationCheckpoint(
        session_id="session.synthetic",
        frame=CheckpointFrameProvenance.from_frame(frame),
        viewport=ContentViewport.full_frame(frame),
        preparation=PreparationRecognition(
            status=PreparationPhaseStatus.PREPARATION,
            method=PreparationRecognitionMethod.PREPARATION_LABEL_OCR,
            primary_evidence=_ocr_evidence(),
        ),
        round_number=RoundNumberObservation(
            round_number=round_number,
            method=(
                RoundNumberMethod.OCR
                if round_number is not None
                else RoundNumberMethod.UNRESOLVED
            ),
            evidence=_ocr_evidence() if round_number is not None else None,
        ),
        self_marker=RuntimeSelfMarkerAggregate(
            status=RuntimeSelfMarkerAggregateStatus.UNRESOLVED,
            self_runtime_slot_id=None,
            present_runtime_slot_ids=(),
        ),
        slot_self_markers=marker_observations,
        slot_hp=tuple(
            RuntimeHpObservation(
                runtime_slot_id=slot,
                status=RuntimeHpStatus.OBSERVED if hp is not None else RuntimeHpStatus.UNRESOLVED,
                observed_current_hp=hp,
                evidence=(_ocr_evidence(),) if hp is not None else (),
            )
            for slot, hp in hp_by_slot.items()
        ),
    )


def test_round_one_preparation_establishes_initial_hp_and_later_checkpoint_preserves_it() -> None:
    baseline = _checkpoint(round_number=1, hp_by_slot={"slot.1": 26})
    later = _checkpoint(round_number=2, hp_by_slot={"slot.1": 23})

    evidence = derive_runtime_initial_hp_evidence((baseline, later))

    assert evidence == (
        RuntimeInitialHpEvidence(
            runtime_slot_id="slot.1",
            known_initial_hp=26,
            current_hp=23,
            hp_loss_observed=True,
        ),
    )


def test_later_checkpoint_without_round_one_baseline_does_not_backfill_initial_hp() -> None:
    later = _checkpoint(round_number=2, hp_by_slot={"slot.1": 23})

    evidence = derive_runtime_initial_hp_evidence((later,))

    assert evidence[0].known_initial_hp is None
    assert evidence[0].current_hp == 23
    assert not evidence[0].hp_loss_observed


def test_unresolved_later_hp_preserves_baseline_without_presenting_stale_current_value() -> None:
    baseline = _checkpoint(round_number=1, hp_by_slot={"slot.1": 26})
    unresolved = _checkpoint(round_number=2, hp_by_slot={"slot.1": None})

    evidence = derive_runtime_initial_hp_evidence((baseline, unresolved))

    assert evidence[0].known_initial_hp == 26
    assert evidence[0].current_hp is None
    assert not evidence[0].hp_loss_observed


def test_invalid_later_hp_preserves_baseline_without_presenting_stale_current_value() -> None:
    baseline = _checkpoint(round_number=1, hp_by_slot={"slot.1": 26})
    invalid = _checkpoint(round_number=2, hp_by_slot={"slot.1": None})
    invalid = replace(
        invalid,
        slot_hp=(
            RuntimeHpObservation(
                runtime_slot_id="slot.1",
                status=RuntimeHpStatus.INVALID,
                observed_current_hp=None,
                evidence=(_ocr_evidence(),),
            ),
        ),
    )

    evidence = derive_runtime_initial_hp_evidence((baseline, invalid))

    assert evidence[0].known_initial_hp == 26
    assert evidence[0].current_hp is None
    assert not evidence[0].hp_loss_observed


def test_observer_uses_primary_label_without_shop_or_exclamation_requirements() -> None:
    frame = _frame(self_slots=())
    # Preparation label, unresolved round, then four matching HP ensemble readings.
    backend = _QueuedBackend(["休憩タイム", None, *("26" for _ in range(6))])

    checkpoint = asyncio.run(
        observe_jp_mumu_preparation_checkpoint(
            frame,
            ContentViewport.full_frame(frame),
            _request("slot.1"),
            backend,
        )
    )

    assert checkpoint.preparation.status is PreparationPhaseStatus.PREPARATION
    assert checkpoint.round_number.round_number is None
    assert checkpoint.slot_self_markers[0].status is RuntimeSelfMarkerStatus.SELF_MARKER_ABSENT
    assert checkpoint.slot_hp[0].observed_current_hp == 26
    assert not frame.image.any()


@pytest.mark.parametrize(
    ("hp_readings", "expected_status", "expected_hp"),
    (
        (["5", "5", None, None, None, None], RuntimeHpStatus.OBSERVED, 5),
        (["5", None, None, None, None, None], RuntimeHpStatus.UNRESOLVED, None),
        (["0", None, None, None, None, None], RuntimeHpStatus.OBSERVED, 0),
        (["5", "5", "26", "26", None, None], RuntimeHpStatus.INVALID, None),
        (["1000", "26", "26", None, None, None], RuntimeHpStatus.INVALID, None),
    ),
)
def test_runtime_hp_ensemble_handles_one_digit_and_out_of_range_evidence_conservatively(
    hp_readings: list[str | None],
    expected_status: RuntimeHpStatus,
    expected_hp: int | None,
) -> None:
    backend = _QueuedBackend(["休憩タイム", None, *hp_readings])
    frame = _frame()

    checkpoint = asyncio.run(
        observe_jp_mumu_preparation_checkpoint(
            frame,
            ContentViewport.full_frame(frame),
            _request("slot.1"),
            backend,
        )
    )

    hp = checkpoint.slot_hp[0]
    assert hp.status is expected_status
    assert hp.observed_current_hp == expected_hp


def test_battle_enemy_count_is_explicit_not_preparation_evidence() -> None:
    frame = _frame()
    backend = _QueuedBackend(["37 / 37"])

    checkpoint = asyncio.run(
        observe_jp_mumu_preparation_checkpoint(
            frame,
            ContentViewport.full_frame(frame),
            _request("slot.1"),
            backend,
        )
    )

    assert checkpoint.preparation.status is PreparationPhaseStatus.NOT_PREPARATION
    assert checkpoint.round_number.round_number is None
    assert checkpoint.slot_hp[0].status is RuntimeHpStatus.UNRESOLVED


def test_missing_primary_label_is_unresolved_even_without_exclamation_markers() -> None:
    frame = _frame()
    backend = _QueuedBackend([None])

    checkpoint = asyncio.run(
        observe_jp_mumu_preparation_checkpoint(
            frame,
            ContentViewport.full_frame(frame),
            _request("slot.1"),
            backend,
        )
    )

    assert checkpoint.preparation.status is PreparationPhaseStatus.UNRESOLVED
    assert checkpoint.round_number.round_number is None


def test_exact_ocr_round_number_is_preserved_without_a_phase_state_machine() -> None:
    frame = _frame()
    backend = _QueuedBackend(["休憩タイム", "12", *("26" for _ in range(6))])

    checkpoint = asyncio.run(
        observe_jp_mumu_preparation_checkpoint(
            frame,
            ContentViewport.full_frame(frame),
            _request("slot.1"),
            backend,
        )
    )

    assert checkpoint.round_number.round_number == 12
    assert checkpoint.round_number.method is RoundNumberMethod.OCR


def test_unique_self_marker_projects_to_core_without_persisting_identity() -> None:
    frame = _frame(self_slots=(2,))
    backend = _QueuedBackend(["休憩タイム", "1", *("27" for _ in range(12))])
    checkpoint = asyncio.run(
        observe_jp_mumu_preparation_checkpoint(
            frame,
            ContentViewport.full_frame(frame),
            _request("slot.1", "slot.2"),
            backend,
        )
    )
    projected = project_unique_self_marker_to_association_core(
        RuntimeSlotAssociationObservation(
            runtime_slot_id="slot.2",
            participation_state=RuntimeAssociationParticipationState.ACTIVE,
        ),
        checkpoint.self_marker,
    )

    assert checkpoint.self_marker.status is RuntimeSelfMarkerAggregateStatus.UNIQUE
    assert checkpoint.self_marker.self_runtime_slot_id == "slot.2"
    assert projected.self_marker is True


def test_multiple_self_markers_are_explicit_conflict_without_highest_score_winner() -> None:
    observations = tuple(
        RuntimeSelfMarkerObservation(
            runtime_slot_id=slot,
            status=RuntimeSelfMarkerStatus.SELF_MARKER_PRESENT,
            pixel_bounds=PixelRoi(x=0, y=0, width=1, height=1),
            teal_pixel_count=400,
            threshold_pixel_count=300,
        )
        for slot in ("slot.1", "slot.2")
    )

    aggregate = aggregate_runtime_self_markers(observations)

    assert aggregate.status is RuntimeSelfMarkerAggregateStatus.CONFLICT
    assert aggregate.self_runtime_slot_id is None


def test_unique_self_marker_resolves_a_self_slot_with_duplicate_avatar_candidates() -> None:
    aggregate = RuntimeSelfMarkerAggregate(
        status=RuntimeSelfMarkerAggregateStatus.UNIQUE,
        self_runtime_slot_id="slot.1",
        present_runtime_slot_ids=("slot.1",),
    )
    slot = project_unique_self_marker_to_association_core(
        RuntimeSlotAssociationObservation(
            runtime_slot_id="slot.1",
            participation_state=RuntimeAssociationParticipationState.ACTIVE,
            avatar_candidate_participant_ids=frozenset({"participant.self", "participant.other"}),
        ),
        aggregate,
    )
    result = derive_runtime_associations(
        RuntimeAssociationInput(
            session_id="session.synthetic",
            participants=(
                SelectionParticipantAssociationFact(
                    session_player_id="participant.self",
                    player_tag="0001",
                    is_self=True,
                    selection_outcome=SelectionOutcome.ENTERED_BATTLE,
                ),
                SelectionParticipantAssociationFact(
                    session_player_id="participant.other",
                    player_tag="0002",
                    selection_outcome=SelectionOutcome.ENTERED_BATTLE,
                ),
            ),
            runtime_slots=(slot,),
        )
    )

    resolution = result.for_slot("slot.1")
    assert resolution is not None
    assert resolution.status is RuntimeAssociationResolutionStatus.CONFIRMED
    assert resolution.session_player_id == "participant.self"


def test_initial_hp_can_resolve_duplicate_avatar_candidates_but_missing_baseline_cannot() -> None:
    participants = (
        SelectionParticipantAssociationFact(
            session_player_id="participant.a",
            player_tag="0001",
            expected_initial_hp=26,
            selection_outcome=SelectionOutcome.ENTERED_BATTLE,
        ),
        SelectionParticipantAssociationFact(
            session_player_id="participant.b",
            player_tag="0002",
            expected_initial_hp=23,
            selection_outcome=SelectionOutcome.ENTERED_BATTLE,
        ),
    )
    slots = (
        RuntimeSlotAssociationObservation(
            runtime_slot_id="slot.1",
            participation_state=RuntimeAssociationParticipationState.ACTIVE,
            avatar_candidate_participant_ids=frozenset({"participant.a", "participant.b"}),
            current_hp=26,
            hp_is_known_initial=True,
        ),
        RuntimeSlotAssociationObservation(
            runtime_slot_id="slot.2",
            participation_state=RuntimeAssociationParticipationState.ACTIVE,
            avatar_candidate_participant_ids=frozenset({"participant.a", "participant.b"}),
            current_hp=23,
            hp_is_known_initial=True,
        ),
    )
    resolved = derive_runtime_associations(
        RuntimeAssociationInput(
            session_id="session.synthetic",
            participants=participants,
            runtime_slots=slots,
        )
    )
    unknown_hp = derive_runtime_associations(
        RuntimeAssociationInput(
            session_id="session.synthetic",
            participants=participants,
            runtime_slots=tuple(
                slot.model_copy(update={"current_hp": None, "hp_is_known_initial": False})
                for slot in slots
            ),
        )
    )

    assert [item.status for item in resolved.resolutions] == [
        RuntimeAssociationResolutionStatus.CONFIRMED,
        RuntimeAssociationResolutionStatus.CONFIRMED,
    ]
    assert all(
        item.status is RuntimeAssociationResolutionStatus.UNRESOLVED
        for item in unknown_hp.resolutions
    )


def test_later_current_hp_does_not_remap_a_sticky_association() -> None:
    historical = RuntimeInitialHpEvidence(
        runtime_slot_id="slot.1",
        known_initial_hp=26,
        current_hp=23,
        hp_loss_observed=True,
    )
    core_slot = historical.project_to_association_core(
        RuntimeSlotAssociationObservation(
            runtime_slot_id="slot.1",
            participation_state=RuntimeAssociationParticipationState.ACTIVE,
            current_hp=23,
        )
    )
    result = derive_runtime_associations(
        RuntimeAssociationInput(
            session_id="session.synthetic",
            participants=(
                SelectionParticipantAssociationFact(
                    session_player_id="participant.a",
                    player_tag="0001",
                    expected_initial_hp=26,
                    selection_outcome=SelectionOutcome.ENTERED_BATTLE,
                ),
                SelectionParticipantAssociationFact(
                    session_player_id="participant.b",
                    player_tag="0002",
                    expected_initial_hp=23,
                    selection_outcome=SelectionOutcome.ENTERED_BATTLE,
                ),
            ),
            runtime_slots=(core_slot,),
            previous_confirmed_associations=(
                PreviousConfirmedRuntimeAssociation(
                    runtime_slot_id="slot.1", session_player_id="participant.a"
                ),
            ),
        )
    )

    resolution = result.for_slot("slot.1")
    assert resolution is not None
    assert resolution.status is RuntimeAssociationResolutionStatus.CONFIRMED
    assert resolution.session_player_id == "participant.a"
    assert core_slot.current_hp == 26
    assert core_slot.hp_is_known_initial


def test_checkpoint_models_are_immutable() -> None:
    checkpoint = _checkpoint(round_number=1, hp_by_slot={"slot.1": 26})

    with pytest.raises(FrozenInstanceError):
        setattr(cast(object, checkpoint), "_".join(("session", "id")), "changed")


def test_runtime_hp_model_rejects_an_out_of_range_value() -> None:
    with pytest.raises(ValueError, match="between zero and 999"):
        RuntimeHpObservation(
            runtime_slot_id="slot.1",
            status=RuntimeHpStatus.OBSERVED,
            observed_current_hp=1000,
            evidence=(_ocr_evidence(),),
        )
