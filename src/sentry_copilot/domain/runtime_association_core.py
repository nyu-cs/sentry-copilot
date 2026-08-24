"""Pure deterministic association of normalized selection and runtime evidence.

This module intentionally consumes already-normalized evidence.  It neither reads images nor
mutates ``SessionState``; future vision work can replace its evidence producers independently.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from itertools import product

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .identifiers import RuntimeSlotId, SessionId, SessionParticipantId, StrategyId
from .strategy_selection import SelectionOutcome


class RuntimeAssociationParticipationState(StrEnum):
    ACTIVE = "active"
    SPECTATING_OR_DEAD = "spectating_or_dead"
    EXITED = "exited"
    UNKNOWN = "unknown"


class RuntimeAssociationResolutionStatus(StrEnum):
    CONFIRMED = "confirmed"
    UNRESOLVED = "unresolved"
    CONFLICT = "conflict"
    INACTIVE_UNRESOLVED = "inactive_unresolved"


class RuntimeAssociationUnresolvedReason(StrEnum):
    AMBIGUOUS_EVIDENCE = "ambiguous_evidence"
    NO_VALID_CANDIDATE = "no_valid_candidate"
    INACTIVE = "inactive"
    CONTRADICTS_STICKY_ASSOCIATION = "contradicts_sticky_association"


class SelectionParticipantAssociationFact(BaseModel):
    """Trusted, normalized selection facts for one session participant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_player_id: SessionParticipantId
    player_tag: str | None = None
    confirmed_strategy_id: StrategyId | None = None
    is_self: bool = False
    selection_outcome: SelectionOutcome = SelectionOutcome.UNKNOWN
    expected_initial_hp: int | None = Field(default=None, ge=0)

    @field_validator("player_tag")
    @classmethod
    def player_tag_must_be_four_digits(cls, value: str | None) -> str | None:
        if value is not None and (len(value) != 4 or not value.isdecimal()):
            raise ValueError("player_tag must be a four-digit string when present")
        return value


class RuntimeSlotAssociationObservation(BaseModel):
    """Normalized runtime evidence for one visible slot, not raw vision output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    runtime_slot_id: RuntimeSlotId
    participation_state: RuntimeAssociationParticipationState
    self_marker: bool | None = None
    avatar_candidate_participant_ids: frozenset[SessionParticipantId] | None = None
    current_hp: int | None = Field(default=None, ge=0)
    hp_is_known_initial: bool = False

    @model_validator(mode="after")
    def initial_hp_claim_requires_value(self) -> RuntimeSlotAssociationObservation:
        if self.hp_is_known_initial and self.current_hp is None:
            raise ValueError("hp_is_known_initial requires current_hp")
        return self


class TrustedRuntimeManualConfirmation(BaseModel):
    """An explicit user-confirmed slot-to-participant mapping."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    runtime_slot_id: RuntimeSlotId
    session_player_id: SessionParticipantId


class PreviousConfirmedRuntimeAssociation(BaseModel):
    """Sticky association established earlier in the same session.

    Strategy identification is independent from slot-to-participant association, so a
    previously confirmed participant may legitimately have no strategy ID yet.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    runtime_slot_id: RuntimeSlotId
    session_player_id: SessionParticipantId
    strategy_id: StrategyId | None = None


class RuntimeAssociationInput(BaseModel):
    """Complete pure-input boundary for one deterministic association pass."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    participants: tuple[SelectionParticipantAssociationFact, ...] = Field(
        default_factory=tuple, max_length=4
    )
    runtime_slots: tuple[RuntimeSlotAssociationObservation, ...] = Field(
        default_factory=tuple, max_length=4
    )
    manual_confirmations: tuple[TrustedRuntimeManualConfirmation, ...] = Field(
        default_factory=tuple
    )
    previous_confirmed_associations: tuple[PreviousConfirmedRuntimeAssociation, ...] = Field(
        default_factory=tuple
    )

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> RuntimeAssociationInput:
        _require_unique((item.session_player_id for item in self.participants), "session_player_id")
        _require_unique((item.runtime_slot_id for item in self.runtime_slots), "runtime_slot_id")
        known_participants = {item.session_player_id for item in self.participants}
        slot_ids = {item.runtime_slot_id for item in self.runtime_slots}
        for confirmation in self.manual_confirmations:
            if confirmation.runtime_slot_id not in slot_ids:
                raise ValueError("manual confirmation references an unknown runtime slot")
            if confirmation.session_player_id not in known_participants:
                raise ValueError("manual confirmation references an unknown participant")
        for association in self.previous_confirmed_associations:
            if association.runtime_slot_id not in slot_ids:
                raise ValueError("previous association references an unknown runtime slot")
            if association.session_player_id not in known_participants:
                raise ValueError("previous association references an unknown participant")
        _require_unique(
            (item.session_player_id for item in self.manual_confirmations),
            "manual confirmation participant",
        )
        _require_unique(
            (item.session_player_id for item in self.previous_confirmed_associations),
            "previous association participant",
        )
        previous_slot_by_participant = {
            item.session_player_id: item.runtime_slot_id
            for item in self.previous_confirmed_associations
        }
        for confirmation in self.manual_confirmations:
            previous_slot_id = previous_slot_by_participant.get(confirmation.session_player_id)
            if previous_slot_id is not None and previous_slot_id != confirmation.runtime_slot_id:
                raise ValueError("trusted association cannot map one participant to multiple slots")
        return self


class RuntimeAssociationResolution(BaseModel):
    """One immutable slot-level result; no association is persisted by this query."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    runtime_slot_id: RuntimeSlotId
    participation_state: RuntimeAssociationParticipationState
    status: RuntimeAssociationResolutionStatus
    session_player_id: SessionParticipantId | None = None
    strategy_id: StrategyId | None = None
    candidate_participant_ids: tuple[SessionParticipantId, ...] = ()
    unresolved_reason: RuntimeAssociationUnresolvedReason | None = None

    @model_validator(mode="after")
    def resolution_shape_is_consistent(self) -> RuntimeAssociationResolution:
        if self.status == RuntimeAssociationResolutionStatus.CONFIRMED:
            if self.session_player_id is None:
                raise ValueError("confirmed resolution requires a participant")
            if self.unresolved_reason is not None:
                raise ValueError("confirmed resolution cannot have unresolved reason")
        elif self.status == RuntimeAssociationResolutionStatus.CONFLICT:
            if self.unresolved_reason != (
                RuntimeAssociationUnresolvedReason.CONTRADICTS_STICKY_ASSOCIATION
            ):
                raise ValueError("conflict resolution requires sticky-association reason")
        elif self.status == RuntimeAssociationResolutionStatus.INACTIVE_UNRESOLVED:
            if self.unresolved_reason != RuntimeAssociationUnresolvedReason.INACTIVE:
                raise ValueError("inactive resolution requires inactive reason")
        elif self.status == RuntimeAssociationResolutionStatus.UNRESOLVED:
            if self.unresolved_reason is None:
                raise ValueError("unresolved resolution requires a reason")
        return self


class RuntimeAssociationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    resolutions: tuple[RuntimeAssociationResolution, ...]
    manual_confirmation_slot_ids: tuple[RuntimeSlotId, ...] = ()

    def for_slot(self, runtime_slot_id: RuntimeSlotId) -> RuntimeAssociationResolution | None:
        return next(
            (item for item in self.resolutions if item.runtime_slot_id == runtime_slot_id),
            None,
        )


def derive_runtime_associations(input: RuntimeAssociationInput) -> RuntimeAssociationResult:
    """Derive only deterministic associations from normalized, trusted evidence.

    The exhaustive search is deliberately bounded to four slots/participants.  More than one
    valid assignment remains unresolved instead of being selected by confidence or order.
    """

    eligible = {
        item.session_player_id: item
        for item in input.participants
        if item.selection_outcome == SelectionOutcome.ENTERED_BATTLE
    }
    manual_by_slot = _manual_claims(input.manual_confirmations)
    previous_by_slot = _previous_claims(input.previous_confirmed_associations)

    conflicts: set[RuntimeSlotId] = set()
    for slot_id, manual_claim_id in manual_by_slot.items():
        previous = previous_by_slot.get(slot_id)
        if previous is not None and previous.session_player_id != manual_claim_id:
            conflicts.add(slot_id)

    # Existing sticky mappings remain reserved even when their current card is inactive or a
    # later observation disagrees.  They cannot be silently reassigned elsewhere.
    reserved = {
        slot_id: association.session_player_id for slot_id, association in previous_by_slot.items()
    }
    reserved_participants = set(reserved.values())

    candidates: dict[RuntimeSlotId, tuple[SessionParticipantId, ...]] = {}
    active_slots = [
        item
        for item in input.runtime_slots
        if item.participation_state == RuntimeAssociationParticipationState.ACTIVE
        and item.runtime_slot_id not in conflicts
        and item.runtime_slot_id not in reserved
    ]
    self_ids = {item.session_player_id for item in eligible.values() if item.is_self}
    for slot in active_slots:
        allowed = set(eligible) - reserved_participants
        manual_id = manual_by_slot.get(slot.runtime_slot_id)
        if manual_id is not None:
            allowed &= {manual_id}
        if slot.self_marker is True:
            allowed &= self_ids
        if slot.avatar_candidate_participant_ids is not None:
            allowed &= set(slot.avatar_candidate_participant_ids)
        if slot.hp_is_known_initial and slot.current_hp is not None:
            allowed = {
                participant_id
                for participant_id in allowed
                if (
                    eligible[participant_id].expected_initial_hp is None
                    or eligible[participant_id].expected_initial_hp == slot.current_hp
                )
            }
        candidates[slot.runtime_slot_id] = tuple(sorted(allowed))

    assignments = _enumerate_assignments(candidates)
    resolutions: list[RuntimeAssociationResolution] = []
    manual_targets: set[RuntimeSlotId] = set()
    for slot in sorted(input.runtime_slots, key=lambda item: item.runtime_slot_id):
        previous = previous_by_slot.get(slot.runtime_slot_id)
        if slot.runtime_slot_id in conflicts:
            resolutions.append(
                RuntimeAssociationResolution(
                    runtime_slot_id=slot.runtime_slot_id,
                    participation_state=slot.participation_state,
                    status=RuntimeAssociationResolutionStatus.CONFLICT,
                    session_player_id=(
                        previous.session_player_id if previous is not None else None
                    ),
                    strategy_id=previous.strategy_id if previous is not None else None,
                    unresolved_reason=(
                        RuntimeAssociationUnresolvedReason.CONTRADICTS_STICKY_ASSOCIATION
                    ),
                )
            )
            continue
        if previous is not None:
            resolutions.append(
                RuntimeAssociationResolution(
                    runtime_slot_id=slot.runtime_slot_id,
                    participation_state=slot.participation_state,
                    status=RuntimeAssociationResolutionStatus.CONFIRMED,
                    session_player_id=previous.session_player_id,
                    strategy_id=previous.strategy_id,
                )
            )
            continue
        if slot.participation_state != RuntimeAssociationParticipationState.ACTIVE:
            resolutions.append(
                RuntimeAssociationResolution(
                    runtime_slot_id=slot.runtime_slot_id,
                    participation_state=slot.participation_state,
                    status=RuntimeAssociationResolutionStatus.INACTIVE_UNRESOLVED,
                    unresolved_reason=RuntimeAssociationUnresolvedReason.INACTIVE,
                )
            )
            continue

        candidates_for_slot = candidates[slot.runtime_slot_id]
        values = {assignment[slot.runtime_slot_id] for assignment in assignments}
        if len(values) == 1:
            participant_id = next(iter(values))
            participant = eligible[participant_id]
            resolutions.append(
                RuntimeAssociationResolution(
                    runtime_slot_id=slot.runtime_slot_id,
                    participation_state=slot.participation_state,
                    status=RuntimeAssociationResolutionStatus.CONFIRMED,
                    session_player_id=participant_id,
                    strategy_id=participant.confirmed_strategy_id,
                )
            )
            continue
        reason = (
            RuntimeAssociationUnresolvedReason.NO_VALID_CANDIDATE
            if not candidates_for_slot or not assignments
            else RuntimeAssociationUnresolvedReason.AMBIGUOUS_EVIDENCE
        )
        resolutions.append(
            RuntimeAssociationResolution(
                runtime_slot_id=slot.runtime_slot_id,
                participation_state=slot.participation_state,
                status=RuntimeAssociationResolutionStatus.UNRESOLVED,
                candidate_participant_ids=tuple(sorted(values or candidates_for_slot)),
                unresolved_reason=reason,
            )
        )

    unresolved = [
        item for item in resolutions if item.status == RuntimeAssociationResolutionStatus.UNRESOLVED
    ]
    if not assignments:
        manual_targets.update(item.runtime_slot_id for item in unresolved)
    else:
        for component in _ambiguous_components(unresolved):
            manual_targets.add(min(component, key=str))
    return RuntimeAssociationResult(
        session_id=input.session_id,
        resolutions=tuple(resolutions),
        manual_confirmation_slot_ids=tuple(sorted(manual_targets)),
    )


def _manual_claims(
    items: tuple[TrustedRuntimeManualConfirmation, ...],
) -> dict[RuntimeSlotId, SessionParticipantId]:
    result: dict[RuntimeSlotId, SessionParticipantId] = {}
    for item in items:
        existing = result.get(item.runtime_slot_id)
        if existing is not None and existing != item.session_player_id:
            raise ValueError("conflicting claims for one runtime slot")
        result[item.runtime_slot_id] = item.session_player_id
    return result


def _previous_claims(
    items: tuple[PreviousConfirmedRuntimeAssociation, ...],
) -> dict[RuntimeSlotId, PreviousConfirmedRuntimeAssociation]:
    result: dict[RuntimeSlotId, PreviousConfirmedRuntimeAssociation] = {}
    for item in items:
        existing = result.get(item.runtime_slot_id)
        if existing is not None and existing != item:
            raise ValueError("conflicting previous associations for one runtime slot")
        result[item.runtime_slot_id] = item
    return result


def _enumerate_assignments(
    candidates: dict[RuntimeSlotId, tuple[SessionParticipantId, ...]],
) -> tuple[dict[RuntimeSlotId, SessionParticipantId], ...]:
    if not candidates:
        return ({},)
    slot_ids = tuple(sorted(candidates))
    if any(not candidates[slot_id] for slot_id in slot_ids):
        return ()
    result: list[dict[RuntimeSlotId, SessionParticipantId]] = []
    for values in product(*(candidates[slot_id] for slot_id in slot_ids)):
        if len(values) == len(set(values)):
            result.append(dict(zip(slot_ids, values, strict=True)))
    return tuple(result)


def _ambiguous_components(
    unresolved: list[RuntimeAssociationResolution],
) -> tuple[set[RuntimeSlotId], ...]:
    remaining = set(item.runtime_slot_id for item in unresolved)
    candidates = {item.runtime_slot_id: set(item.candidate_participant_ids) for item in unresolved}
    components: list[set[RuntimeSlotId]] = []
    while remaining:
        component = {remaining.pop()}
        changed = True
        while changed:
            changed = False
            participant_ids = set().union(*(candidates[slot_id] for slot_id in component))
            linked = {
                slot_id
                for slot_id in remaining
                if participant_ids.intersection(candidates[slot_id])
            }
            if linked:
                component.update(linked)
                remaining.difference_update(linked)
                changed = True
        components.append(component)
    return tuple(components)


def _require_unique(values: Iterable[object], field_name: str) -> None:
    items = tuple(values)
    if len(items) != len(set(items)):
        raise ValueError(f"{field_name} values must be unique")
