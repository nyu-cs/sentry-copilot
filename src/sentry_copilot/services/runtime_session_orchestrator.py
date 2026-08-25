"""Caller-driven, query-derived composition of existing runtime evidence components."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from sentry_copilot.domain.identifiers import RuntimeSlotId, SessionParticipantId
from sentry_copilot.domain.runtime_association_core import (
    RuntimeAssociationInput,
    RuntimeAssociationResolutionStatus,
    derive_runtime_associations,
)
from sentry_copilot.vision.runtime_player_card_state import RuntimePlayerCardVisualState
from sentry_copilot.vision.runtime_player_state_tracker import RuntimePlayerCardStateTracker
from sentry_copilot.vision.runtime_preparation_checkpoint import RuntimeInitialHpEvidence


class RuntimeTeamSlotView(BaseModel):
    """One non-authoritative current slot view assembled from established evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    runtime_slot_id: RuntimeSlotId
    association_status: RuntimeAssociationResolutionStatus
    session_player_id: SessionParticipantId | None = None
    player_tag: str | None = None
    strategy_id: str | None = None
    is_self: bool | None = None
    expected_initial_hp: int | None = Field(default=None, ge=0)
    observed_initial_hp: int | None = Field(default=None, ge=0)
    stable_presentation_state: RuntimePlayerCardVisualState | None = None
    manual_confirmation_needed: bool = False
    conflict: bool = False


class RuntimeSessionTeamView(BaseModel):
    """Query-derived output; it stores no new participant or strategy authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    slots: tuple[RuntimeTeamSlotView, ...]


def compose_runtime_session_team_view(
    association_input: RuntimeAssociationInput,
    tracker: RuntimePlayerCardStateTracker,
    *,
    observed_initial_hp: tuple[RuntimeInitialHpEvidence, ...] = (),
) -> RuntimeSessionTeamView:
    """Compose evidence without recognition, remapping, or persistence.

    ``expected_initial_hp`` is caller-supplied participant metadata.  Only an explicit
    round-one ``RuntimeInitialHpEvidence`` populates ``observed_initial_hp``.
    """

    association = derive_runtime_associations(association_input)
    participants = {item.session_player_id: item for item in association_input.participants}
    observed_by_slot = _observed_initial_hp_by_slot(
        observed_initial_hp,
        {item.runtime_slot_id for item in association_input.runtime_slots},
    )
    slots: list[RuntimeTeamSlotView] = []
    for resolution in association.resolutions:
        participant = (
            participants.get(resolution.session_player_id)
            if resolution.session_player_id is not None
            else None
        )
        timeline = tracker.for_slot(resolution.runtime_slot_id)
        slots.append(
            RuntimeTeamSlotView(
                runtime_slot_id=resolution.runtime_slot_id,
                association_status=resolution.status,
                session_player_id=resolution.session_player_id,
                player_tag=participant.player_tag if participant else None,
                strategy_id=(participant.confirmed_strategy_id if participant else None),
                is_self=(participant.is_self if participant else None),
                expected_initial_hp=(participant.expected_initial_hp if participant else None),
                observed_initial_hp=observed_by_slot.get(resolution.runtime_slot_id),
                stable_presentation_state=(
                    timeline.stable_observation.state
                    if timeline is not None and timeline.stable_observation is not None
                    else None
                ),
                manual_confirmation_needed=(
                    resolution.runtime_slot_id in association.manual_confirmation_slot_ids
                ),
                conflict=resolution.status is RuntimeAssociationResolutionStatus.CONFLICT,
            )
        )
    return RuntimeSessionTeamView(slots=tuple(slots))


def _observed_initial_hp_by_slot(
    evidence: tuple[RuntimeInitialHpEvidence, ...], slot_ids: set[RuntimeSlotId]
) -> dict[RuntimeSlotId, int]:
    values: dict[RuntimeSlotId, int] = {}
    for item in evidence:
        if item.runtime_slot_id not in slot_ids:
            raise ValueError("observed initial-HP evidence references an unknown runtime slot")
        if item.runtime_slot_id in values:
            raise ValueError("observed initial-HP evidence must have unique runtime slots")
        if item.known_initial_hp is not None:
            values[item.runtime_slot_id] = item.known_initial_hp
    return values
