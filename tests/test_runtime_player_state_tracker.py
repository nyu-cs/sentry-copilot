from __future__ import annotations

from dataclasses import replace
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
    RuntimePlayerStateTrackerConfig,
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


def test_confirmation_count_three_and_unresolved_preserve_pending_candidate() -> None:
    tracker = RuntimePlayerCardStateTracker(config=RuntimePlayerStateTrackerConfig(3))
    for state in (RuntimePlayerCardVisualState.ACTIVE, RuntimePlayerCardVisualState.ACTIVE):
        tracker = tracker.apply(_observe(state))
    slot = tracker.for_slot("slot.3")
    assert slot is not None and slot.stable_observation is None and slot.pending_count == 2
    tracker = tracker.apply(_observe(RuntimePlayerCardVisualState.ACTIVE))
    tracker = tracker.apply(_observe(RuntimePlayerCardVisualState.SPECTATING_OR_DEAD))
    tracker = tracker.apply(_observe(RuntimePlayerCardVisualState.UNRESOLVED))
    slot = tracker.for_slot("slot.3")
    assert slot is not None and slot.pending_count == 1
    tracker = tracker.apply(_observe(RuntimePlayerCardVisualState.SPECTATING_OR_DEAD))
    tracker = tracker.apply(_observe(RuntimePlayerCardVisualState.SPECTATING_OR_DEAD))
    assert len(tracker.events) == 1


def test_first_exited_is_presentation_only_and_independent_slots_do_not_interfere() -> None:
    tracker = _apply(RuntimePlayerCardVisualState.EXITED, RuntimePlayerCardVisualState.EXITED)
    slot = tracker.for_slot("slot.3")
    assert slot is not None and slot.stable_observation is not None
    assert slot.stable_observation.state is RuntimePlayerCardVisualState.EXITED
    assert tracker.events == ()
    other = _observe(RuntimePlayerCardVisualState.ACTIVE)
    other = replace(other, runtime_slot_id="slot.4")
    tracker = tracker.apply(other).apply(other)
    assert (
        tracker.for_slot("slot.3").stable_observation.state is RuntimePlayerCardVisualState.EXITED
    )
    assert (
        tracker.for_slot("slot.4").stable_observation.state is RuntimePlayerCardVisualState.ACTIVE
    )
