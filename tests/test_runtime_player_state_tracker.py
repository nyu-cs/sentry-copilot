from __future__ import annotations

from datetime import UTC, datetime

from sentry_copilot.capture.frame_source import FrameSourceType
from sentry_copilot.domain.runtime_association_core import (
    RuntimeAssociationParticipationState,
    RuntimeSlotAssociationObservation,
)
from sentry_copilot.vision.runtime_player_card_state import (
    RuntimePlayerCardVisualState,
    RuntimePlayerCardVisualStateMethod,
    RuntimePlayerCardVisualStateObservation,
)
from sentry_copilot.vision.runtime_player_state_tracker import (
    RuntimePlayerCardStateTracker,
    project_stable_runtime_player_card_state_to_association_core,
)
from sentry_copilot.vision.viewport import PixelRoi


def _observe(state: RuntimePlayerCardVisualState) -> RuntimePlayerCardVisualStateObservation:
    return RuntimePlayerCardVisualStateObservation(
        runtime_slot_id="slot.3",
        state=state,
        method=RuntimePlayerCardVisualStateMethod.UNRESOLVED
        if state is RuntimePlayerCardVisualState.UNRESOLVED
        else RuntimePlayerCardVisualStateMethod.LUMINANCE_BAND_COUNTS,
        frame_id=f"frame:{state.value}",
        frame_index=1,
        processed_at=datetime(2026, 8, 25, tzinfo=UTC),
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic",
        source_reference="synthetic.png",
        card_pixel_bounds=PixelRoi(x=0, y=0, width=121, height=119),
        cue_pixel_bounds=PixelRoi(x=0, y=0, width=121, height=88),
        luminance_ge_150_pixel_count=0,
        luminance_ge_160_pixel_count=0,
        luminance_ge_200_pixel_count=0,
    )


def _apply(*states: RuntimePlayerCardVisualState) -> RuntimePlayerCardStateTracker:
    tracker = RuntimePlayerCardStateTracker()
    for state in states:
        tracker = tracker.apply(_observe(state))
    return tracker


def test_baseline_and_unresolved_do_not_emit_events() -> None:
    tracker = _apply(
        RuntimePlayerCardVisualState.ACTIVE,
        RuntimePlayerCardVisualState.ACTIVE,
        RuntimePlayerCardVisualState.UNRESOLVED,
        RuntimePlayerCardVisualState.ACTIVE,
    )
    slot = tracker.for_slot("slot.3")
    assert slot is not None and slot.stable_observation is not None
    assert slot.stable_observation.state is RuntimePlayerCardVisualState.ACTIVE
    assert tracker.events == ()


def test_pending_change_requires_two_and_emits_one_event() -> None:
    interrupted = _apply(
        RuntimePlayerCardVisualState.ACTIVE,
        RuntimePlayerCardVisualState.ACTIVE,
        RuntimePlayerCardVisualState.SPECTATING_OR_DEAD,
        RuntimePlayerCardVisualState.ACTIVE,
    )
    assert interrupted.events == ()
    tracker = _apply(
        RuntimePlayerCardVisualState.ACTIVE,
        RuntimePlayerCardVisualState.ACTIVE,
        RuntimePlayerCardVisualState.SPECTATING_OR_DEAD,
        RuntimePlayerCardVisualState.SPECTATING_OR_DEAD,
        RuntimePlayerCardVisualState.EXITED,
        RuntimePlayerCardVisualState.EXITED,
    )
    assert [(event.previous_state, event.current_state) for event in tracker.events] == [
        (RuntimePlayerCardVisualState.ACTIVE, RuntimePlayerCardVisualState.SPECTATING_OR_DEAD),
        (RuntimePlayerCardVisualState.SPECTATING_OR_DEAD, RuntimePlayerCardVisualState.EXITED),
    ]


def test_reverse_is_conflict_and_stable_state_projects_without_identity() -> None:
    tracker = _apply(
        RuntimePlayerCardVisualState.ACTIVE,
        RuntimePlayerCardVisualState.ACTIVE,
        RuntimePlayerCardVisualState.EXITED,
        RuntimePlayerCardVisualState.EXITED,
        RuntimePlayerCardVisualState.ACTIVE,
    )
    slot = tracker.for_slot("slot.3")
    assert slot is not None and slot.stable_observation is not None
    assert slot.stable_observation.state is RuntimePlayerCardVisualState.EXITED
    assert len(slot.conflicts) == 1
    core = project_stable_runtime_player_card_state_to_association_core(
        RuntimeSlotAssociationObservation(
            runtime_slot_id="slot.3",
            participation_state=RuntimeAssociationParticipationState.ACTIVE,
        ),
        tracker,
    )
    assert core.participation_state is RuntimeAssociationParticipationState.EXITED
