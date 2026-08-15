from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict

from .battle_roster import (
    BattleEntryStatus,
    BattleRoster,
    BattleRosterParticipant,
    PlayerParticipationStatus,
    battle_entry_status,
    derive_battle_roster,
)
from .identifiers import (
    EvidenceId,
    RuntimeSlotId,
    SessionId,
    SessionParticipantId,
)
from .models import SessionState
from .prebattle import PrebattleEvidenceLedger
from .prebattle_migration import LegacyPrebattleMigrationState
from .rulesets import RulesetDependencyStamp, SessionRulesetContext
from .runtime_slots import (
    BattleRuntimeSlot,
    EffectiveSlotParticipantAssociation,
    RuntimeSlotView,
    SlotAssociationConflict,
    SlotAssociationView,
    derive_runtime_slot_view,
    derive_slot_association_view,
)
from .slot_strategy_assignments import (
    SlotStrategyAssignmentView,
    derive_slot_strategy_assignment_view,
)
from .strategy_commitment import (
    ParticipantCommitmentLevel,
    ReadyConfirmedCommitment,
)
from .strategy_identification import StrategyOccupancyView
from .strategy_selection import SelectionOutcome, SnapshotCompleteness


class TeamStrategyParticipantContext(BaseModel):
    session_player_id: SessionParticipantId
    selection_row: int
    player_tag: str | None
    display_name: str | None
    strategy_id: str | None
    ready: bool | None


class TeamStrategyContext(BaseModel):
    session_id: SessionId
    ruleset_id: str
    frozen: bool
    completeness_level: SnapshotCompleteness
    participants: list[TeamStrategyParticipantContext]

    @property
    def strategy_ids(self) -> list[str]:
        return [
            participant.strategy_id
            for participant in self.participants
            if participant.strategy_id is not None
        ]


class ParticipantCommitmentContext(BaseModel):
    """Read-only formal-selection interpretation for one session participant."""

    model_config = ConfigDict(frozen=True)

    session_player_id: SessionParticipantId
    selection_row: int
    level: ParticipantCommitmentLevel
    confirmed_at: AwareDatetime | None = None
    ready_evidence_ids: tuple[EvidenceId, ...] = ()
    battle_entry_evidence_ids: tuple[EvidenceId, ...] = ()
    strategy_confirmation_evidence_ids: tuple[EvidenceId, ...] = ()


class PrebattleCommitmentContext(BaseModel):
    """Current ready commitments; no concrete strategy occupancy is included."""

    model_config = ConfigDict(frozen=True)

    session_id: SessionId
    participants: tuple[ParticipantCommitmentContext, ...]


def get_prebattle_evidence_ledger(
    state: SessionState,
) -> PrebattleEvidenceLedger | None:
    """Return the immutable append-only prebattle evidence history."""

    return state.prebattle_evidence


def build_battle_roster(state: SessionState) -> BattleRoster:
    """Derive confirmed entrants and current participation from audit history."""

    return derive_battle_roster(
        session_id=state.session_id,
        prebattle_evidence=state.prebattle_evidence,
        participation_state=state.battle_participation,
    )


def get_battle_entry_status(
    state: SessionState,
    session_player_id: SessionParticipantId,
) -> BattleEntryStatus:
    """Return explicit entry status without treating battle UI presence as entry."""

    return battle_entry_status(state.prebattle_evidence, session_player_id)


def get_active_battle_participants(
    state: SessionState,
) -> tuple[BattleRosterParticipant, ...]:
    """Return current active entrants; historical inactive entrants remain in roster."""

    return tuple(
        participant
        for participant in build_battle_roster(state).participants
        if participant.participation_status == PlayerParticipationStatus.ACTIVE
    )


def get_slot_association_view(state: SessionState) -> SlotAssociationView:
    """Derive current-layout associations without catalog or legacy slot caches."""

    snapshot = state.strategy_selection
    player_tags = {
        participant.session_player_id: participant.player_tag
        for participant in snapshot.participants
        if participant.player_tag is not None
    } if snapshot is not None else {}
    self_participant_id = next(
        (
            participant.session_player_id
            for participant in snapshot.participants
            if participant.is_self is True
        ),
        None,
    ) if snapshot is not None else None
    roster = build_battle_roster(state)
    return derive_slot_association_view(
        session_id=state.session_id,
        ledger=state.runtime_slot_evidence,
        association_state=state.slot_associations,
        entrant_ids=frozenset(
            participant.session_player_id for participant in roster.participants
        ),
        player_tags=player_tags,
        self_participant_id=self_participant_id,
    )


def build_current_runtime_slots(state: SessionState) -> RuntimeSlotView:
    """Derive current visible slots; layout epochs never inherit associations."""

    association_view = get_slot_association_view(state)
    return derive_runtime_slot_view(
        session_id=state.session_id,
        ledger=state.runtime_slot_evidence,
        associated_slot_ids=frozenset(
            association.runtime_slot_id
            for association in association_view.associations
        ),
    )


def get_runtime_slot(
    state: SessionState,
    runtime_slot_id: RuntimeSlotId,
) -> BattleRuntimeSlot | None:
    """Return one slot only from the current unambiguous layout epoch."""

    return build_current_runtime_slots(state).get(runtime_slot_id)


def get_effective_slot_participant_association(
    state: SessionState,
    runtime_slot_id: RuntimeSlotId,
) -> EffectiveSlotParticipantAssociation | None:
    """Return one association only when all strong claims are uncontested."""

    return get_slot_association_view(state).for_slot(runtime_slot_id)


def get_uncontested_slot_participant_associations(
    state: SessionState,
) -> tuple[EffectiveSlotParticipantAssociation, ...]:
    return get_slot_association_view(state).associations


def get_slot_association_conflicts(
    state: SessionState,
) -> tuple[SlotAssociationConflict, ...]:
    return get_slot_association_view(state).conflicts


def get_unresolved_runtime_slots(
    state: SessionState,
) -> tuple[BattleRuntimeSlot, ...]:
    """Return current slots lacking an uncontested participant; create no task/UI state."""

    return tuple(
        slot
        for slot in build_current_runtime_slots(state).slots
        if not slot.has_effective_association
    )


def derive_current_slot_strategy_assignment_view(
    state: SessionState,
    *,
    occupancy_view: StrategyOccupancyView,
    catalog_available: bool,
) -> SlotStrategyAssignmentView:
    """Compose assignment inputs without persisting or inferring a strategy label.

    Callers supply the exact revision-aware occupancy view; the catalog repository boundary lives
    in ``SlotStrategyAssignmentService``.
    """

    return derive_slot_strategy_assignment_view(
        session_id=state.session_id,
        slot_view=build_current_runtime_slots(state),
        association_view=get_slot_association_view(state),
        roster=build_battle_roster(state),
        occupancy_view=occupancy_view,
        identification_state=state.strategy_identifications,
        dependency_stamp=state.ruleset_dependency_stamp,
        catalog_available=catalog_available,
    )


def get_legacy_prebattle_migration_state(
    state: SessionState,
) -> LegacyPrebattleMigrationState | None:
    """Return explicit legacy import history without mutating or re-importing it."""

    return state.legacy_prebattle_migrations


def get_ready_confirmed_commitment(
    state: SessionState,
    session_player_id: SessionParticipantId,
) -> ReadyConfirmedCommitment | None:
    """Return one commitment when effective formal-selection evidence exists."""

    if state.strategy_commitments is None:
        return None
    return state.strategy_commitments.for_participant(session_player_id)


def build_prebattle_commitment_context(
    state: SessionState,
) -> PrebattleCommitmentContext | None:
    """Build a stable participant view without inferring any concrete strategy ID."""

    snapshot = state.strategy_selection
    if snapshot is None:
        return None
    commitments = state.strategy_commitments
    return PrebattleCommitmentContext(
        session_id=state.session_id,
        participants=tuple(
            ParticipantCommitmentContext(
                session_player_id=participant.session_player_id,
                selection_row=participant.selection_row,
                level=(
                    ParticipantCommitmentLevel.READY_CONFIRMED_STRATEGY_UNKNOWN
                    if (
                        commitments is not None
                        and commitments.for_participant(participant.session_player_id)
                        is not None
                    )
                    else ParticipantCommitmentLevel.OBSERVING
                ),
                confirmed_at=_commitment_confirmed_at(
                    commitments.for_participant(participant.session_player_id)
                    if commitments is not None
                    else None
                ),
                ready_evidence_ids=_commitment_evidence_ids(
                    commitments.for_participant(participant.session_player_id)
                    if commitments is not None
                    else None
                ),
                battle_entry_evidence_ids=_battle_entry_evidence_ids(
                    commitments.for_participant(participant.session_player_id)
                    if commitments is not None
                    else None
                ),
                strategy_confirmation_evidence_ids=(
                    _strategy_confirmation_evidence_ids(
                        commitments.for_participant(participant.session_player_id)
                        if commitments is not None
                        else None
                    )
                ),
            )
            for participant in sorted(
                snapshot.participants,
                key=lambda item: item.selection_row,
            )
        ),
    )


def _commitment_confirmed_at(
    commitment: ReadyConfirmedCommitment | None,
) -> AwareDatetime | None:
    return commitment.confirmed_at if commitment is not None else None


def _commitment_evidence_ids(
    commitment: ReadyConfirmedCommitment | None,
) -> tuple[EvidenceId, ...]:
    return commitment.ready_evidence_ids if commitment is not None else ()


def _battle_entry_evidence_ids(
    commitment: ReadyConfirmedCommitment | None,
) -> tuple[EvidenceId, ...]:
    return commitment.battle_entry_evidence_ids if commitment is not None else ()


def _strategy_confirmation_evidence_ids(
    commitment: ReadyConfirmedCommitment | None,
) -> tuple[EvidenceId, ...]:
    return (
        commitment.strategy_confirmation_evidence_ids
        if commitment is not None
        else ()
    )


def get_session_ruleset_context(
    state: SessionState,
) -> SessionRulesetContext | None:
    """Return the immutable current ruleset context without changing state."""

    return state.ruleset_context


def get_current_ruleset_dependency_stamp(
    state: SessionState,
) -> RulesetDependencyStamp | None:
    """Return the exact dependency identity for current revision-aware data."""

    return state.ruleset_dependency_stamp


def build_team_strategy_context(state: SessionState) -> TeamStrategyContext | None:
    """Build the legacy materialized strategy view for ENTERED_BATTLE snapshot rows.

    Players remain included after later leaving, disconnecting, being eliminated, or reaching
    non-positive HP. Snapshot values are not confirmed occupancy and this is not a current
    active-team query; new code must use commitment, identification, occupancy, and conflict
    queries instead.
    """

    snapshot = state.strategy_selection
    if snapshot is None:
        return None
    return TeamStrategyContext(
        session_id=snapshot.session_id,
        ruleset_id=snapshot.ruleset_id,
        frozen=snapshot.frozen,
        completeness_level=snapshot.completeness_level,
        participants=[
            TeamStrategyParticipantContext(
                session_player_id=participant.session_player_id,
                selection_row=participant.selection_row,
                player_tag=participant.player_tag,
                display_name=participant.display_name,
                strategy_id=participant.strategy_id,
                ready=participant.ready,
            )
            for participant in sorted(
                (
                    participant
                    for participant in snapshot.participants
                    if participant.selection_outcome == SelectionOutcome.ENTERED_BATTLE
                ),
                key=lambda participant: participant.selection_row,
            )
        ],
    )
