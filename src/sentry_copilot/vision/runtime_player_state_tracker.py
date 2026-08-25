"""Pure temporal debounce for runtime-card presentation observations."""

from __future__ import annotations

from dataclasses import dataclass

from sentry_copilot.domain.identifiers import RuntimeSlotId
from sentry_copilot.domain.runtime_association_core import RuntimeSlotAssociationObservation
from sentry_copilot.vision.runtime_player_card_state import (
    RuntimePlayerCardVisualState,
    RuntimePlayerCardVisualStateObservation,
    project_runtime_player_card_state_to_association_core,
)


@dataclass(frozen=True)
class RuntimePlayerStateTrackerConfig:
    confirmation_count: int = 2

    def __post_init__(self) -> None:
        if self.confirmation_count < 2:
            raise ValueError("runtime state confirmation count must be at least two")


@dataclass(frozen=True)
class RuntimePlayerCardStateChanged:
    runtime_slot_id: RuntimeSlotId
    previous_state: RuntimePlayerCardVisualState
    current_state: RuntimePlayerCardVisualState
    first_candidate_observation: RuntimePlayerCardVisualStateObservation
    confirmed_observation: RuntimePlayerCardVisualStateObservation


@dataclass(frozen=True)
class RuntimePlayerCardTemporalConflict:
    runtime_slot_id: RuntimeSlotId
    stable_state: RuntimePlayerCardVisualState
    contradictory_observation: RuntimePlayerCardVisualStateObservation


@dataclass(frozen=True)
class RuntimePlayerCardSlotTimeline:
    runtime_slot_id: RuntimeSlotId
    stable_observation: RuntimePlayerCardVisualStateObservation | None = None
    pending_observation: RuntimePlayerCardVisualStateObservation | None = None
    pending_count: int = 0
    conflicts: tuple[RuntimePlayerCardTemporalConflict, ...] = ()


@dataclass(frozen=True)
class RuntimePlayerCardStateTracker:
    config: RuntimePlayerStateTrackerConfig = RuntimePlayerStateTrackerConfig()
    slots: tuple[RuntimePlayerCardSlotTimeline, ...] = ()
    events: tuple[RuntimePlayerCardStateChanged, ...] = ()

    def apply(
        self, observation: RuntimePlayerCardVisualStateObservation
    ) -> RuntimePlayerCardStateTracker:
        """Return an updated immutable tracker; callers supply observations chronologically.

        The tracker owns neither capture timing nor frame scanning/background work.  ``UNRESOLVED``
        is absence of usable evidence, so it preserves pending evidence.  Only stable resolved
        state is projectable downstream; this never infers battle entry.
        """

        current = self.for_slot(observation.runtime_slot_id) or RuntimePlayerCardSlotTimeline(
            runtime_slot_id=observation.runtime_slot_id
        )
        updated, event = _apply_slot(current, observation, self.config.confirmation_count)
        slots = tuple(
            updated if item.runtime_slot_id == updated.runtime_slot_id else item
            for item in self.slots
        )
        if current not in self.slots:
            slots = (*slots, updated)
        return RuntimePlayerCardStateTracker(
            config=self.config,
            slots=tuple(sorted(slots, key=lambda item: item.runtime_slot_id)),
            events=(*self.events, event) if event is not None else self.events,
        )

    def for_slot(self, runtime_slot_id: RuntimeSlotId) -> RuntimePlayerCardSlotTimeline | None:
        return next((item for item in self.slots if item.runtime_slot_id == runtime_slot_id), None)


def project_stable_runtime_player_card_state_to_association_core(
    observation: RuntimeSlotAssociationObservation,
    tracker: RuntimePlayerCardStateTracker,
) -> RuntimeSlotAssociationObservation:
    """Project only a stable resolved state.

    Pending or unresolved evidence leaves the association-core input intact.
    """

    slot = tracker.for_slot(observation.runtime_slot_id)
    if slot is None or slot.stable_observation is None:
        return observation
    return project_runtime_player_card_state_to_association_core(
        observation, slot.stable_observation
    )


def _apply_slot(
    slot: RuntimePlayerCardSlotTimeline,
    observation: RuntimePlayerCardVisualStateObservation,
    confirmation_count: int,
) -> tuple[RuntimePlayerCardSlotTimeline, RuntimePlayerCardStateChanged | None]:
    if observation.state is RuntimePlayerCardVisualState.UNRESOLVED:
        return slot, None
    stable = slot.stable_observation
    if stable is not None and observation.state == stable.state:
        return RuntimePlayerCardSlotTimeline(
            runtime_slot_id=slot.runtime_slot_id,
            stable_observation=stable,
            conflicts=slot.conflicts,
        ), None
    if stable is not None and _rank(observation.state) < _rank(stable.state):
        conflict = RuntimePlayerCardTemporalConflict(
            slot.runtime_slot_id, stable.state, observation
        )
        return RuntimePlayerCardSlotTimeline(
            runtime_slot_id=slot.runtime_slot_id,
            stable_observation=stable,
            conflicts=(*slot.conflicts, conflict),
        ), None
    pending = slot.pending_observation
    count = (
        slot.pending_count + 1 if pending is not None and pending.state == observation.state else 1
    )
    first = pending if count > 1 else observation
    assert first is not None
    if count < confirmation_count:
        return RuntimePlayerCardSlotTimeline(
            slot.runtime_slot_id, stable, first, count, slot.conflicts
        ), None
    event = (
        None
        if stable is None
        else RuntimePlayerCardStateChanged(
            slot.runtime_slot_id, stable.state, observation.state, first, observation
        )
    )
    return RuntimePlayerCardSlotTimeline(
        slot.runtime_slot_id, observation, None, 0, slot.conflicts
    ), event


def _rank(state: RuntimePlayerCardVisualState) -> int:
    return {
        RuntimePlayerCardVisualState.ACTIVE: 0,
        RuntimePlayerCardVisualState.SPECTATING_OR_DEAD: 1,
        RuntimePlayerCardVisualState.EXITED: 2,
    }[state]
