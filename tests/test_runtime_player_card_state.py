from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime

import numpy as np

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
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
from sentry_copilot.vision.runtime_player_card_state import (
    RuntimePlayerCardVisualState,
    RuntimePlayerCardVisualStateMethod,
    RuntimePlayerCardVisualStateObservation,
    observe_jp_mumu_runtime_player_card_states,
    project_runtime_player_card_state_to_association_core,
    runtime_player_card_state_cue_roi,
)
from sentry_copilot.vision.runtime_preparation_checkpoint import RuntimeSlotVisualPosition
from sentry_copilot.vision.viewport import ContentViewport


def _frame_for_state(state: RuntimePlayerCardVisualState) -> Frame:
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    cue = runtime_player_card_state_cue_roi(3)
    if state is RuntimePlayerCardVisualState.ACTIVE:
        image[cue.y : cue.y + 20, cue.x : cue.x + 20] = 220
    elif state is RuntimePlayerCardVisualState.SPECTATING_OR_DEAD:
        image[cue.y : cue.y + 30, cue.x : cue.x + 38] = 180
    elif state is RuntimePlayerCardVisualState.EXITED:
        image[cue.y : cue.y + 20, cue.x : cue.x + 30] = 155
    return Frame(
        frame_id=f"synthetic:runtime-card-state:{state.value}",
        frame_index=3,
        processed_at=datetime(2026, 8, 25, tzinfo=UTC),
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic-runtime-card-state",
        width=1920,
        height=1080,
        image=image,
        source_reference="synthetic-runtime-card-state.png",
    )


def _observe(state: RuntimePlayerCardVisualState) -> RuntimePlayerCardVisualStateObservation:
    frame = _frame_for_state(state)
    observations = observe_jp_mumu_runtime_player_card_states(
        frame,
        ContentViewport.full_frame(frame),
        (RuntimeSlotVisualPosition(runtime_slot_id="slot.3", visual_index=3),),
    )
    return observations[0]


def _association_input(state: RuntimeAssociationParticipationState) -> RuntimeAssociationInput:
    return RuntimeAssociationInput(
        session_id="session.synthetic",
        participants=(
            SelectionParticipantAssociationFact(
                session_player_id="participant.a",
                player_tag="0001",
                selection_outcome=SelectionOutcome.ENTERED_BATTLE,
            ),
        ),
        runtime_slots=(
            RuntimeSlotAssociationObservation(
                runtime_slot_id="slot.3",
                participation_state=state,
            ),
        ),
        previous_confirmed_associations=(
            PreviousConfirmedRuntimeAssociation(
                runtime_slot_id="slot.3", session_player_id="participant.a"
            ),
        ),
    )


def test_positive_active_state_requires_high_band_card_detail() -> None:
    observation = _observe(RuntimePlayerCardVisualState.ACTIVE)

    assert observation.state is RuntimePlayerCardVisualState.ACTIVE
    assert observation.method is RuntimePlayerCardVisualStateMethod.LUMINANCE_BAND_COUNTS
    assert observation.luminance_ge_200_pixel_count == 400


def test_positive_spectating_or_dead_state_does_not_require_hp_zero() -> None:
    observation = _observe(RuntimePlayerCardVisualState.SPECTATING_OR_DEAD)

    assert observation.state is RuntimePlayerCardVisualState.SPECTATING_OR_DEAD
    assert observation.method is RuntimePlayerCardVisualStateMethod.LUMINANCE_BAND_COUNTS
    assert observation.luminance_ge_160_pixel_count == 1140
    assert observation.luminance_ge_200_pixel_count == 0


def test_positive_exited_state_does_not_require_prior_death_state() -> None:
    observation = _observe(RuntimePlayerCardVisualState.EXITED)

    assert observation.state is RuntimePlayerCardVisualState.EXITED
    assert observation.luminance_ge_150_pixel_count == 600
    assert observation.luminance_ge_160_pixel_count == 0


def test_weak_unknown_evidence_and_absence_of_inactive_icon_remain_unresolved() -> None:
    observation = _observe(RuntimePlayerCardVisualState.UNRESOLVED)

    assert observation.state is RuntimePlayerCardVisualState.UNRESOLVED
    assert observation.method is RuntimePlayerCardVisualStateMethod.UNRESOLVED


def test_visual_state_never_directly_asserts_participant_identity() -> None:
    names = {field.name for field in fields(_observe(RuntimePlayerCardVisualState.ACTIVE))}

    assert "session_player_id" not in names
    assert "participant_id" not in names
    assert "strategy_id" not in names


def test_unresolved_visual_state_does_not_invent_association_core_transition() -> None:
    visual = _observe(RuntimePlayerCardVisualState.UNRESOLVED)
    original = RuntimeSlotAssociationObservation(
        runtime_slot_id="slot.3",
        participation_state=RuntimeAssociationParticipationState.ACTIVE,
    )

    assert project_runtime_player_card_state_to_association_core(original, visual) is original


def test_active_spectating_then_exited_preserves_sticky_participant_association() -> None:
    prior = _association_input(RuntimeAssociationParticipationState.ACTIVE)
    spectating = project_runtime_player_card_state_to_association_core(
        prior.runtime_slots[0], _observe(RuntimePlayerCardVisualState.SPECTATING_OR_DEAD)
    )
    exited = project_runtime_player_card_state_to_association_core(
        spectating, _observe(RuntimePlayerCardVisualState.EXITED)
    )

    for state in (spectating, exited):
        result = derive_runtime_associations(prior.model_copy(update={"runtime_slots": (state,)}))
        resolution = result.for_slot("slot.3")
        assert resolution is not None
        assert resolution.status is RuntimeAssociationResolutionStatus.CONFIRMED
        assert resolution.session_player_id == "participant.a"


def test_active_to_exited_preserves_sticky_participant_association() -> None:
    prior = _association_input(RuntimeAssociationParticipationState.ACTIVE)
    exited = project_runtime_player_card_state_to_association_core(
        prior.runtime_slots[0], _observe(RuntimePlayerCardVisualState.EXITED)
    )

    result = derive_runtime_associations(prior.model_copy(update={"runtime_slots": (exited,)}))
    resolution = result.for_slot("slot.3")
    assert resolution is not None
    assert resolution.status is RuntimeAssociationResolutionStatus.CONFIRMED
    assert resolution.session_player_id == "participant.a"
