from __future__ import annotations

from sentry_copilot.domain.runtime_association_core import (
    RuntimeAssociationInput,
    RuntimeAssociationParticipationState,
    RuntimeSlotAssociationObservation,
    SelectionParticipantAssociationFact,
)
from sentry_copilot.domain.strategy_selection import SelectionOutcome
from sentry_copilot.services.runtime_session_orchestrator import compose_runtime_session_team_view
from sentry_copilot.vision.runtime_player_state_tracker import RuntimePlayerCardStateTracker
from sentry_copilot.vision.runtime_preparation_checkpoint import RuntimeInitialHpEvidence


def test_composes_confirmed_association_strategy_self_and_initial_hp_without_slot_order() -> None:
    result = compose_runtime_session_team_view(
        RuntimeAssociationInput(
            session_id="session.synthetic",
            participants=(
                SelectionParticipantAssociationFact(
                    session_player_id="p1",
                    player_tag="0001",
                    confirmed_strategy_id="strategy.a",
                    expected_initial_hp=24,
                    selection_outcome=SelectionOutcome.ENTERED_BATTLE,
                ),
                SelectionParticipantAssociationFact(
                    session_player_id="p2",
                    player_tag="0002",
                    confirmed_strategy_id="strategy.b",
                    is_self=True,
                    expected_initial_hp=31,
                    selection_outcome=SelectionOutcome.ENTERED_BATTLE,
                ),
            ),
            runtime_slots=(
                RuntimeSlotAssociationObservation(
                    runtime_slot_id="slot.1",
                    participation_state=RuntimeAssociationParticipationState.ACTIVE,
                    avatar_candidate_participant_ids=frozenset({"p2"}),
                ),
                RuntimeSlotAssociationObservation(
                    runtime_slot_id="slot.2",
                    participation_state=RuntimeAssociationParticipationState.ACTIVE,
                    avatar_candidate_participant_ids=frozenset({"p1"}),
                ),
            ),
        ),
        RuntimePlayerCardStateTracker(),
        observed_initial_hp=(
            RuntimeInitialHpEvidence(
                runtime_slot_id="slot.1",
                known_initial_hp=31,
                current_hp=18,
                hp_loss_observed=True,
            ),
            RuntimeInitialHpEvidence(
                runtime_slot_id="slot.2",
                known_initial_hp=24,
                current_hp=24,
                hp_loss_observed=False,
            ),
        ),
    )
    assert [
        (item.runtime_slot_id, item.session_player_id, item.strategy_id) for item in result.slots
    ] == [("slot.1", "p2", "strategy.b"), ("slot.2", "p1", "strategy.a")]
    assert result.slots[0].is_self
    assert result.slots[1].expected_initial_hp == 24
    assert result.slots[1].observed_initial_hp == 24
    assert result.slots[0].expected_initial_hp == 31
    assert result.slots[0].observed_initial_hp == 31


def test_unknown_strategy_does_not_downgrade_confirmed_participant() -> None:
    result = compose_runtime_session_team_view(
        RuntimeAssociationInput(
            session_id="session.synthetic",
            participants=(
                SelectionParticipantAssociationFact(
                    session_player_id="p1", selection_outcome=SelectionOutcome.ENTERED_BATTLE
                ),
            ),
            runtime_slots=(
                RuntimeSlotAssociationObservation(
                    runtime_slot_id="slot.1",
                    participation_state=RuntimeAssociationParticipationState.ACTIVE,
                    avatar_candidate_participant_ids=frozenset({"p1"}),
                ),
            ),
        ),
        RuntimePlayerCardStateTracker(),
    )
    assert result.slots[0].session_player_id == "p1" and result.slots[0].strategy_id is None


def test_observed_initial_hp_is_not_backfilled_from_participant_expectation() -> None:
    result = compose_runtime_session_team_view(
        RuntimeAssociationInput(
            session_id="session.synthetic",
            participants=(
                SelectionParticipantAssociationFact(
                    session_player_id="p1",
                    expected_initial_hp=26,
                    selection_outcome=SelectionOutcome.ENTERED_BATTLE,
                ),
            ),
            runtime_slots=(
                RuntimeSlotAssociationObservation(
                    runtime_slot_id="slot.1",
                    participation_state=RuntimeAssociationParticipationState.ACTIVE,
                    avatar_candidate_participant_ids=frozenset({"p1"}),
                ),
            ),
        ),
        RuntimePlayerCardStateTracker(),
    )

    assert result.slots[0].expected_initial_hp == 26
    assert result.slots[0].observed_initial_hp is None
