"""Fixed-layout visual evidence for JP MuMu runtime player-card presentation state.

This module observes card presentation only.  It does not identify a participant, rematch an
avatar, mutate session state, or infer game-domain entry semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

import cv2

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.domain.identifiers import RuntimeSlotId
from sentry_copilot.domain.runtime_association_core import (
    RuntimeAssociationParticipationState,
    RuntimeSlotAssociationObservation,
)
from sentry_copilot.vision.runtime_preparation_checkpoint import (
    JP_MUMU_1920_HEIGHT,
    JP_MUMU_1920_WIDTH,
    RuntimeSlotVisualPosition,
    runtime_card_roi,
)
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi

JP_MUMU_RUNTIME_STATE_CUE_HEIGHT = 88
"""Top card region only; lower HP/presentation text is deliberately excluded."""

_EXITED_MIN_LUMINANCE_GE_150_PIXELS = 400
_EXITED_LUMINANCE_GE_160_PIXELS = 0
_SPECTATING_MIN_LUMINANCE_GE_160_PIXELS = 1000
_SPECTATING_MAX_LUMINANCE_GE_200_PIXELS = 100
_ACTIVE_MIN_LUMINANCE_GE_200_PIXELS = 200


class RuntimePlayerCardVisualState(StrEnum):
    ACTIVE = "active"
    SPECTATING_OR_DEAD = "spectating_or_dead"
    EXITED = "exited"
    UNRESOLVED = "unresolved"


class RuntimePlayerCardVisualStateMethod(StrEnum):
    LUMINANCE_BAND_COUNTS = "luminance_band_counts"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class RuntimePlayerCardVisualStateObservation:
    """Immutable visual presentation evidence for one runtime card, never participant identity."""

    runtime_slot_id: RuntimeSlotId
    state: RuntimePlayerCardVisualState
    method: RuntimePlayerCardVisualStateMethod
    frame_id: str
    frame_index: int
    processed_at: datetime
    source_timestamp: timedelta | None
    source_type: FrameSourceType
    source_id: str
    source_reference: str
    card_pixel_bounds: PixelRoi
    cue_pixel_bounds: PixelRoi
    luminance_ge_150_pixel_count: int
    luminance_ge_160_pixel_count: int
    luminance_ge_200_pixel_count: int

    def __post_init__(self) -> None:
        if not self.runtime_slot_id.strip() or not self.frame_id.strip():
            raise ValueError("runtime slot and frame IDs must not be blank")
        if not self.source_id.strip() or not self.source_reference.strip():
            raise ValueError("runtime card state source provenance must not be blank")
        if self.frame_index < 0:
            raise ValueError("runtime card state frame index must be non-negative")
        if self.processed_at.tzinfo is None or self.processed_at.utcoffset() is None:
            raise ValueError("runtime card state processing time must be timezone-aware")
        if self.source_timestamp is not None and self.source_timestamp.total_seconds() < 0:
            raise ValueError("runtime card state source timestamp must be non-negative")
        if any(
            value < 0
            for value in (
                self.luminance_ge_150_pixel_count,
                self.luminance_ge_160_pixel_count,
                self.luminance_ge_200_pixel_count,
            )
        ):
            raise ValueError("runtime card state luminance counts must be non-negative")
        if self.state is RuntimePlayerCardVisualState.UNRESOLVED:
            if self.method is not RuntimePlayerCardVisualStateMethod.UNRESOLVED:
                raise ValueError("unresolved runtime card state requires unresolved method")
        elif self.method is not RuntimePlayerCardVisualStateMethod.LUMINANCE_BAND_COUNTS:
            raise ValueError("resolved runtime card state requires luminance-band evidence")


def runtime_player_card_state_cue_roi(visual_index: int) -> PixelRoi:
    """Return the fixed upper-card state cue ROI without using HP or bottom presentation text."""

    card = runtime_card_roi(visual_index)
    return PixelRoi(
        x=card.x,
        y=card.y,
        width=card.width,
        height=JP_MUMU_RUNTIME_STATE_CUE_HEIGHT,
    )


def observe_jp_mumu_runtime_player_card_states(
    frame: Frame,
    viewport: ContentViewport,
    positions: tuple[RuntimeSlotVisualPosition, ...],
) -> tuple[RuntimePlayerCardVisualStateObservation, ...]:
    """Observe caller-specified cards in the known full-frame 1920x1080 JP MuMu layout.

    The thresholds are deliberately positive-evidence rules calibrated against the persistent
    card presentations.  A dark/weak crop without the exit icon's visible low-band footprint is
    unresolved rather than assumed exited, and ACTIVE requires high-band avatar/card detail.
    """

    _validate_known_layout(frame, viewport)
    _validate_positions(positions)
    return tuple(_observe_card_state(frame, position) for position in positions)


def project_runtime_player_card_state_to_association_core(
    observation: RuntimeSlotAssociationObservation,
    visual_state: RuntimePlayerCardVisualStateObservation,
) -> RuntimeSlotAssociationObservation:
    """Project only a resolved presentation state into the pure association-core input.

    The visual observation names no participant.  An unresolved observation changes nothing, so it
    cannot invent an active/inactive transition or disturb a previously confirmed association.
    """

    if observation.runtime_slot_id != visual_state.runtime_slot_id:
        raise ValueError("runtime card state belongs to a different runtime slot")
    state_map = {
        RuntimePlayerCardVisualState.ACTIVE: RuntimeAssociationParticipationState.ACTIVE,
        RuntimePlayerCardVisualState.SPECTATING_OR_DEAD: (
            RuntimeAssociationParticipationState.SPECTATING_OR_DEAD
        ),
        RuntimePlayerCardVisualState.EXITED: RuntimeAssociationParticipationState.EXITED,
    }
    participation_state = state_map.get(visual_state.state)
    if participation_state is None:
        return observation
    return observation.model_copy(update={"participation_state": participation_state})


def _observe_card_state(
    frame: Frame,
    position: RuntimeSlotVisualPosition,
) -> RuntimePlayerCardVisualStateObservation:
    card = runtime_card_roi(position.visual_index)
    cue = runtime_player_card_state_cue_roi(position.visual_index)
    crop = frame.image[cue.y : cue.bottom, cue.x : cue.right]
    luminance = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    ge_150 = int((luminance >= 150).sum())
    ge_160 = int((luminance >= 160).sum())
    ge_200 = int((luminance >= 200).sum())
    state = _classify_luminance_bands(ge_150=ge_150, ge_160=ge_160, ge_200=ge_200)
    method = (
        RuntimePlayerCardVisualStateMethod.UNRESOLVED
        if state is RuntimePlayerCardVisualState.UNRESOLVED
        else RuntimePlayerCardVisualStateMethod.LUMINANCE_BAND_COUNTS
    )
    return RuntimePlayerCardVisualStateObservation(
        runtime_slot_id=position.runtime_slot_id,
        state=state,
        method=method,
        frame_id=frame.frame_id,
        frame_index=frame.frame_index,
        processed_at=frame.processed_at,
        source_timestamp=frame.source_timestamp,
        source_type=frame.source_type,
        source_id=frame.source_id,
        source_reference=frame.source_reference,
        card_pixel_bounds=card,
        cue_pixel_bounds=cue,
        luminance_ge_150_pixel_count=ge_150,
        luminance_ge_160_pixel_count=ge_160,
        luminance_ge_200_pixel_count=ge_200,
    )


def _classify_luminance_bands(
    *,
    ge_150: int,
    ge_160: int,
    ge_200: int,
) -> RuntimePlayerCardVisualState:
    if ge_160 == _EXITED_LUMINANCE_GE_160_PIXELS and ge_150 >= _EXITED_MIN_LUMINANCE_GE_150_PIXELS:
        return RuntimePlayerCardVisualState.EXITED
    if (
        ge_160 >= _SPECTATING_MIN_LUMINANCE_GE_160_PIXELS
        and ge_200 <= _SPECTATING_MAX_LUMINANCE_GE_200_PIXELS
    ):
        return RuntimePlayerCardVisualState.SPECTATING_OR_DEAD
    if ge_200 >= _ACTIVE_MIN_LUMINANCE_GE_200_PIXELS:
        return RuntimePlayerCardVisualState.ACTIVE
    return RuntimePlayerCardVisualState.UNRESOLVED


def _validate_known_layout(frame: Frame, viewport: ContentViewport) -> None:
    viewport.validate_frame(frame)
    if (
        viewport.pixel_roi
        != PixelRoi(x=0, y=0, width=JP_MUMU_1920_WIDTH, height=JP_MUMU_1920_HEIGHT)
    ):
        raise ValueError("runtime player-card state requires a full 1920x1080 JP MuMu viewport")


def _validate_positions(positions: tuple[RuntimeSlotVisualPosition, ...]) -> None:
    if not 1 <= len(positions) <= 4:
        raise ValueError("runtime player-card state requires one to four slots")
    slot_ids = tuple(item.runtime_slot_id for item in positions)
    visual_indices = tuple(item.visual_index for item in positions)
    if len(slot_ids) != len(set(slot_ids)):
        raise ValueError("runtime player-card state slot IDs must be unique")
    if len(visual_indices) != len(set(visual_indices)):
        raise ValueError("runtime player-card state visual indices must be unique")
