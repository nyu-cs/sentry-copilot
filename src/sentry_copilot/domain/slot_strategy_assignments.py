from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .battle_roster import BattleRoster, PlayerParticipationStatus
from .identifiers import (
    RuntimeSlotId,
    RuntimeSlotLayoutId,
    SessionId,
    SessionParticipantId,
    SlotAssociationRecordId,
    StrategyId,
    StrategyIdentificationRecordId,
)
from .rulesets import RulesetDependencyStamp
from .runtime_slots import BattleRuntimeSlot, RuntimeSlotView, SlotAssociationView
from .strategy_identification import (
    StrategyIdentificationConflictType,
    StrategyIdentificationState,
    StrategyOccupancyView,
)


class SlotStrategyAssignmentUnresolvedReason(StrEnum):
    """The first unmet authority-link for one current runtime slot."""

    RULESET_CONTEXT_UNAVAILABLE = "ruleset_context_unavailable"
    PARTICIPANT_ASSOCIATION_UNKNOWN = "participant_association_unknown"
    PARTICIPANT_ASSOCIATION_CONFLICT = "participant_association_conflict"
    PARTICIPANT_NOT_CONFIRMED_ENTRANT = "participant_not_confirmed_entrant"
    STRATEGY_IDENTIFICATION_UNKNOWN = "strategy_identification_unknown"
    STRATEGY_IDENTIFICATION_STALE = "strategy_identification_stale"
    PARTICIPANT_STRATEGY_IDENTIFICATION_CONFLICT = (
        "participant_strategy_identification_conflict"
    )
    DUPLICATE_CONFIRMED_STRATEGY_CLAIM = "duplicate_confirmed_strategy_claim"
    STRATEGY_CATALOG_COMPATIBILITY_CONFLICT = (
        "strategy_catalog_compatibility_conflict"
    )
    UNOCCUPIED_STRATEGY_IDENTIFICATION = "unoccupied_strategy_identification"


class SlotStrategyAssignment(BaseModel):
    """A query-derived, uncontested strategy label for one current runtime slot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    layout_id: RuntimeSlotLayoutId
    runtime_slot_id: RuntimeSlotId
    session_player_id: SessionParticipantId
    strategy_id: StrategyId
    participation_status: PlayerParticipationStatus
    association_record_ids: tuple[SlotAssociationRecordId, ...] = Field(min_length=1)
    identification_record_ids: tuple[StrategyIdentificationRecordId, ...] = Field(
        min_length=1
    )
    dependency_stamp: RulesetDependencyStamp | None = None


class UnresolvedSlotStrategyAssignment(BaseModel):
    """A current slot whose authority chain is incomplete or conflicted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    layout_id: RuntimeSlotLayoutId
    runtime_slot_id: RuntimeSlotId
    reason: SlotStrategyAssignmentUnresolvedReason
    session_player_id: SessionParticipantId | None = None


class SlotStrategyAssignmentView(BaseModel):
    """Immutable read model; assignments are never persisted in SessionState."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    current_layout_id: RuntimeSlotLayoutId | None = None
    assignments: tuple[SlotStrategyAssignment, ...] = Field(default_factory=tuple)
    unresolved: tuple[UnresolvedSlotStrategyAssignment, ...] = Field(
        default_factory=tuple
    )

    def for_slot(self, runtime_slot_id: RuntimeSlotId) -> SlotStrategyAssignment | None:
        return next(
            (
                assignment
                for assignment in self.assignments
                if assignment.runtime_slot_id == runtime_slot_id
            ),
            None,
        )


def derive_slot_strategy_assignment_view(
    *,
    session_id: SessionId,
    slot_view: RuntimeSlotView,
    association_view: SlotAssociationView,
    roster: BattleRoster,
    occupancy_view: StrategyOccupancyView,
    identification_state: StrategyIdentificationState | None,
    dependency_stamp: RulesetDependencyStamp | None,
    catalog_available: bool,
) -> SlotStrategyAssignmentView:
    """Compose the sole permitted runtime-slot-to-strategy authority chain."""

    entrant_by_id = {
        participant.session_player_id: participant for participant in roster.participants
    }
    association_conflict_slots = {
        slot_id
        for conflict in association_view.conflicts
        for slot_id in conflict.runtime_slot_ids
    }
    identification_conflicts_by_participant: dict[
        SessionParticipantId, set[StrategyIdentificationConflictType]
    ] = {}
    for conflict in occupancy_view.conflicts:
        for participant_id in conflict.participant_ids:
            identification_conflicts_by_participant.setdefault(participant_id, set()).add(
                conflict.conflict_type
            )
    stale_participants = _stale_participants(
        occupancy_view=occupancy_view,
        identification_state=identification_state,
    )
    identification_by_participant = {
        item.session_player_id: item for item in occupancy_view.identifications
    }
    occupancy_by_participant = {
        item.session_player_id: item for item in occupancy_view.occupancies
    }

    assignments: list[SlotStrategyAssignment] = []
    unresolved: list[UnresolvedSlotStrategyAssignment] = []
    for slot in slot_view.slots:
        association = association_view.for_slot(slot.runtime_slot_id)
        if association is None:
            unresolved.append(
                UnresolvedSlotStrategyAssignment(
                    layout_id=slot.layout_id,
                    runtime_slot_id=slot.runtime_slot_id,
                    reason=(
                        SlotStrategyAssignmentUnresolvedReason.PARTICIPANT_ASSOCIATION_CONFLICT
                        if slot.runtime_slot_id in association_conflict_slots
                        else SlotStrategyAssignmentUnresolvedReason.PARTICIPANT_ASSOCIATION_UNKNOWN
                    ),
                )
            )
            continue

        participant_id = association.session_player_id
        entrant = entrant_by_id.get(participant_id)
        if entrant is None:
            unresolved.append(
                _unresolved(
                    slot,
                    SlotStrategyAssignmentUnresolvedReason.PARTICIPANT_NOT_CONFIRMED_ENTRANT,
                    participant_id,
                )
            )
            continue
        if not catalog_available or dependency_stamp is None:
            unresolved.append(
                _unresolved(
                    slot,
                    SlotStrategyAssignmentUnresolvedReason.RULESET_CONTEXT_UNAVAILABLE,
                    participant_id,
                )
            )
            continue

        reason = _identification_conflict_reason(
            identification_conflicts_by_participant.get(participant_id, set())
        )
        if reason is not None:
            unresolved.append(_unresolved(slot, reason, participant_id))
            continue
        identification = identification_by_participant.get(participant_id)
        if identification is None:
            unresolved.append(
                _unresolved(
                    slot,
                    (
                        SlotStrategyAssignmentUnresolvedReason.STRATEGY_IDENTIFICATION_STALE
                        if participant_id in stale_participants
                        else SlotStrategyAssignmentUnresolvedReason.STRATEGY_IDENTIFICATION_UNKNOWN
                    ),
                    participant_id,
                )
            )
            continue
        occupancy = occupancy_by_participant.get(participant_id)
        if occupancy is None or occupancy.strategy_id != identification.strategy_id:
            unresolved.append(
                _unresolved(
                    slot,
                    SlotStrategyAssignmentUnresolvedReason.UNOCCUPIED_STRATEGY_IDENTIFICATION,
                    participant_id,
                )
            )
            continue
        assignments.append(
            SlotStrategyAssignment(
                layout_id=slot.layout_id,
                runtime_slot_id=slot.runtime_slot_id,
                session_player_id=participant_id,
                strategy_id=occupancy.strategy_id,
                participation_status=entrant.participation_status,
                association_record_ids=association.supporting_record_ids,
                identification_record_ids=identification.supporting_record_ids,
                dependency_stamp=dependency_stamp,
            )
        )

    return SlotStrategyAssignmentView(
        session_id=session_id,
        current_layout_id=slot_view.current_layout_id,
        assignments=tuple(sorted(assignments, key=lambda item: item.runtime_slot_id)),
        unresolved=tuple(sorted(unresolved, key=lambda item: item.runtime_slot_id)),
    )


def _unresolved(
    slot: BattleRuntimeSlot,
    reason: SlotStrategyAssignmentUnresolvedReason,
    participant_id: SessionParticipantId,
) -> UnresolvedSlotStrategyAssignment:
    return UnresolvedSlotStrategyAssignment(
        layout_id=slot.layout_id,
        runtime_slot_id=slot.runtime_slot_id,
        reason=reason,
        session_player_id=participant_id,
    )


def _stale_participants(
    *,
    occupancy_view: StrategyOccupancyView,
    identification_state: StrategyIdentificationState | None,
) -> frozenset[SessionParticipantId]:
    if identification_state is None:
        return frozenset()
    stale_record_ids = set(occupancy_view.stale_record_ids)
    return frozenset(
        record.session_player_id
        for record in identification_state.records
        if record.record_id in stale_record_ids
    )


def _identification_conflict_reason(
    conflicts: set[StrategyIdentificationConflictType],
) -> SlotStrategyAssignmentUnresolvedReason | None:
    if (
        StrategyIdentificationConflictType.PARTICIPANT_STRATEGY_IDENTIFICATION_CONFLICT
        in conflicts
    ):
        return (
            SlotStrategyAssignmentUnresolvedReason.PARTICIPANT_STRATEGY_IDENTIFICATION_CONFLICT
        )
    if StrategyIdentificationConflictType.DUPLICATE_CONFIRMED_STRATEGY_CLAIM in conflicts:
        return SlotStrategyAssignmentUnresolvedReason.DUPLICATE_CONFIRMED_STRATEGY_CLAIM
    if (
        StrategyIdentificationConflictType.STRATEGY_CATALOG_COMPATIBILITY_CONFLICT
        in conflicts
    ):
        return (
            SlotStrategyAssignmentUnresolvedReason.STRATEGY_CATALOG_COMPATIBILITY_CONFLICT
        )
    return None
