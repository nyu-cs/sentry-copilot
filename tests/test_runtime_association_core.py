from __future__ import annotations

import pytest

from sentry_copilot.domain.runtime_association_core import (
    PreviousConfirmedRuntimeAssociation,
    RuntimeAssociationInput,
    RuntimeAssociationParticipationState,
    RuntimeAssociationResolution,
    RuntimeAssociationResolutionStatus,
    RuntimeAssociationResult,
    RuntimeAssociationUnresolvedReason,
    RuntimeSlotAssociationObservation,
    SelectionParticipantAssociationFact,
    TrustedRuntimeManualConfirmation,
    derive_runtime_associations,
)
from sentry_copilot.domain.strategy_selection import SelectionOutcome


def _participant(
    identifier: str,
    *,
    strategy: str | None = None,
    avatar_hp: int | None = None,
    self: bool = False,
    outcome: SelectionOutcome = SelectionOutcome.ENTERED_BATTLE,
) -> SelectionParticipantAssociationFact:
    return SelectionParticipantAssociationFact(
        session_player_id=identifier,
        player_tag="0001",
        confirmed_strategy_id=strategy,
        expected_initial_hp=avatar_hp,
        is_self=self,
        selection_outcome=outcome,
    )


def _slot(
    identifier: str,
    *,
    state: RuntimeAssociationParticipationState = RuntimeAssociationParticipationState.ACTIVE,
    avatar: frozenset[str] | None = None,
    self_marker: bool | None = None,
    hp: int | None = None,
    initial: bool = False,
) -> RuntimeSlotAssociationObservation:
    return RuntimeSlotAssociationObservation(
        runtime_slot_id=identifier,
        participation_state=state,
        avatar_candidate_participant_ids=avatar,
        self_marker=self_marker,
        current_hp=hp,
        hp_is_known_initial=initial,
    )


def _input(
    participants: tuple[SelectionParticipantAssociationFact, ...],
    slots: tuple[RuntimeSlotAssociationObservation, ...],
    *,
    manual: tuple[TrustedRuntimeManualConfirmation, ...] = (),
    previous: tuple[PreviousConfirmedRuntimeAssociation, ...] = (),
) -> RuntimeAssociationInput:
    return RuntimeAssociationInput(
        session_id="session.synthetic",
        participants=participants,
        runtime_slots=slots,
        manual_confirmations=manual,
        previous_confirmed_associations=previous,
    )


def _resolution(result: RuntimeAssociationResult, slot_id: str) -> RuntimeAssociationResolution:
    resolution = result.for_slot(slot_id)
    assert resolution is not None
    return resolution


def test_unique_avatar_evidence_resolves_four_slots_without_selection_order() -> None:
    participants = tuple(
        _participant(f"participant.{index}", strategy=f"strategy.{index}") for index in range(1, 5)
    )
    result = derive_runtime_associations(
        _input(
            participants,
            (
                _slot("slot.1", avatar=frozenset({"participant.3"})),
                _slot("slot.2", avatar=frozenset({"participant.1"})),
                _slot("slot.3", avatar=frozenset({"participant.4"})),
                _slot("slot.4", avatar=frozenset({"participant.2"})),
            ),
        )
    )
    assert [item.session_player_id for item in result.resolutions] == [
        "participant.3",
        "participant.1",
        "participant.4",
        "participant.2",
    ]
    assert all(
        item.status == RuntimeAssociationResolutionStatus.CONFIRMED for item in result.resolutions
    )


def test_self_marker_is_a_strong_anchor() -> None:
    result = derive_runtime_associations(
        _input(
            (
                _participant("participant.self", strategy="strategy.self", self=True),
                _participant("participant.other", strategy="strategy.other"),
            ),
            (
                _slot("slot.1", self_marker=True),
                _slot("slot.2", avatar=frozenset({"participant.other"})),
            ),
        )
    )
    assert _resolution(result, "slot.1").session_player_id == "participant.self"


def test_initial_hp_resolves_duplicate_avatar_candidates() -> None:
    result = derive_runtime_associations(
        _input(
            (
                _participant("participant.a", strategy="strategy.a", avatar_hp=20),
                _participant("participant.b", strategy="strategy.b", avatar_hp=24),
            ),
            (
                _slot(
                    "slot.1",
                    avatar=frozenset({"participant.a", "participant.b"}),
                    hp=24,
                    initial=True,
                ),
                _slot(
                    "slot.2",
                    avatar=frozenset({"participant.a", "participant.b"}),
                    hp=20,
                    initial=True,
                ),
            ),
        )
    )
    assert _resolution(result, "slot.1").session_player_id == "participant.b"
    assert _resolution(result, "slot.2").session_player_id == "participant.a"


def test_initial_hp_collision_stays_ambiguous_and_requests_one_slot() -> None:
    result = derive_runtime_associations(
        _input(
            (
                _participant("participant.a", strategy="strategy.a", avatar_hp=20),
                _participant("participant.b", strategy="strategy.b", avatar_hp=20),
            ),
            (
                _slot("slot.1", hp=20, initial=True),
                _slot("slot.2", hp=20, initial=True),
            ),
        )
    )
    assert all(
        item.status == RuntimeAssociationResolutionStatus.UNRESOLVED for item in result.resolutions
    )
    assert result.manual_confirmation_slot_ids == ("slot.1",)


def test_avatar_and_hp_ambiguity_never_guesses() -> None:
    result = derive_runtime_associations(
        _input(
            (
                _participant("participant.a", strategy="strategy.a", avatar_hp=20),
                _participant("participant.b", strategy="strategy.b", avatar_hp=20),
            ),
            (_slot("slot.1"), _slot("slot.2")),
        )
    )
    assert (
        _resolution(result, "slot.1").unresolved_reason
        == RuntimeAssociationUnresolvedReason.AMBIGUOUS_EVIDENCE
    )


def test_reduced_hp_is_ignored() -> None:
    result = derive_runtime_associations(
        _input(
            (
                _participant("participant.a", strategy="strategy.a", avatar_hp=20),
                _participant("participant.b", strategy="strategy.b", avatar_hp=24),
            ),
            (
                _slot("slot.1", hp=5, initial=False),
                _slot("slot.2", hp=5, initial=False),
            ),
        )
    )
    assert all(
        item.status == RuntimeAssociationResolutionStatus.UNRESOLVED for item in result.resolutions
    )


def test_unknown_strategy_does_not_block_unique_avatar_participant_association() -> None:
    result = derive_runtime_associations(
        _input(
            (_participant("participant.a"),),
            (_slot("slot.1", avatar=frozenset({"participant.a"})),),
        )
    )
    resolution = _resolution(result, "slot.1")
    assert resolution.status == RuntimeAssociationResolutionStatus.CONFIRMED
    assert resolution.session_player_id == "participant.a"
    assert resolution.strategy_id is None


def test_unknown_strategy_does_not_block_unique_self_anchor() -> None:
    result = derive_runtime_associations(
        _input(
            (_participant("participant.self", self=True),),
            (_slot("slot.1", self_marker=True),),
        )
    )
    resolution = _resolution(result, "slot.1")
    assert resolution.status == RuntimeAssociationResolutionStatus.CONFIRMED
    assert resolution.session_player_id == "participant.self"
    assert resolution.strategy_id is None


def test_manual_confirmation_can_confirm_participant_with_unknown_strategy() -> None:
    result = derive_runtime_associations(
        _input(
            (_participant("participant.a"),),
            (_slot("slot.1"),),
            manual=(
                TrustedRuntimeManualConfirmation(
                    runtime_slot_id="slot.1", session_player_id="participant.a"
                ),
            ),
        )
    )
    resolution = _resolution(result, "slot.1")
    assert resolution.status == RuntimeAssociationResolutionStatus.CONFIRMED
    assert resolution.session_player_id == "participant.a"
    assert resolution.strategy_id is None


def test_multiple_unknown_strategy_participants_can_remain_association_ambiguous() -> None:
    result = derive_runtime_associations(
        _input(
            (_participant("participant.a"), _participant("participant.b")),
            (_slot("slot.1"), _slot("slot.2")),
        )
    )
    assert all(
        item.status == RuntimeAssociationResolutionStatus.UNRESOLVED for item in result.resolutions
    )
    assert result.manual_confirmation_slot_ids == ("slot.1",)


def test_manual_confirmation_resolves_remaining_assignment_by_elimination() -> None:
    result = derive_runtime_associations(
        _input(
            (
                _participant("participant.a", strategy="strategy.a"),
                _participant("participant.b", strategy="strategy.b"),
            ),
            (_slot("slot.1"), _slot("slot.2")),
            manual=(
                TrustedRuntimeManualConfirmation(
                    runtime_slot_id="slot.1", session_player_id="participant.a"
                ),
            ),
        )
    )
    assert _resolution(result, "slot.1").session_player_id == "participant.a"
    assert _resolution(result, "slot.2").session_player_id == "participant.b"


def test_selection_stage_exited_unknown_is_excluded_from_active_problem() -> None:
    result = derive_runtime_associations(
        _input(
            (
                _participant("participant.active", strategy="strategy.active"),
                _participant("participant.exited", outcome=SelectionOutcome.EXITED_BEFORE_STRATEGY),
            ),
            (
                _slot("slot.active", avatar=frozenset({"participant.active"})),
                _slot("slot.exited", state=RuntimeAssociationParticipationState.EXITED),
            ),
        )
    )
    assert _resolution(result, "slot.active").status == RuntimeAssociationResolutionStatus.CONFIRMED
    assert (
        _resolution(result, "slot.exited").status
        == RuntimeAssociationResolutionStatus.INACTIVE_UNRESOLVED
    )


def test_two_exited_unknowns_do_not_need_identity_reconstruction() -> None:
    result = derive_runtime_associations(
        _input(
            (
                _participant("participant.active", strategy="strategy.active"),
                _participant("participant.exit.a", outcome=SelectionOutcome.EXITED_BEFORE_STRATEGY),
                _participant("participant.exit.b", outcome=SelectionOutcome.EXITED_BEFORE_STRATEGY),
            ),
            (
                _slot("slot.active", avatar=frozenset({"participant.active"})),
                _slot("slot.exit.a", state=RuntimeAssociationParticipationState.EXITED),
                _slot("slot.exit.b", state=RuntimeAssociationParticipationState.EXITED),
            ),
        )
    )
    assert result.manual_confirmation_slot_ids == ()
    assert [item.status for item in result.resolutions[1:]] == [
        RuntimeAssociationResolutionStatus.INACTIVE_UNRESOLVED,
        RuntimeAssociationResolutionStatus.INACTIVE_UNRESOLVED,
    ]


def test_previous_confirmed_mapping_is_sticky_across_inactive_states() -> None:
    previous = PreviousConfirmedRuntimeAssociation(
        runtime_slot_id="slot.1", session_player_id="participant.a", strategy_id="strategy.a"
    )
    for state in (
        RuntimeAssociationParticipationState.EXITED,
        RuntimeAssociationParticipationState.SPECTATING_OR_DEAD,
    ):
        result = derive_runtime_associations(
            _input(
                (_participant("participant.a", strategy="strategy.a"),),
                (_slot("slot.1", state=state, avatar=frozenset()),),
                previous=(previous,),
            )
        )
        resolved = result.for_slot("slot.1")
        assert resolved is not None
        assert resolved.status == RuntimeAssociationResolutionStatus.CONFIRMED
        assert resolved.session_player_id == "participant.a"
        assert resolved.strategy_id == "strategy.a"


def test_previous_unknown_strategy_association_remains_sticky() -> None:
    result = derive_runtime_associations(
        _input(
            (_participant("participant.a"),),
            (
                _slot(
                    "slot.1",
                    state=RuntimeAssociationParticipationState.SPECTATING_OR_DEAD,
                ),
            ),
            previous=(
                PreviousConfirmedRuntimeAssociation(
                    runtime_slot_id="slot.1",
                    session_player_id="participant.a",
                ),
            ),
        )
    )
    resolution = _resolution(result, "slot.1")
    assert resolution.status == RuntimeAssociationResolutionStatus.CONFIRMED
    assert resolution.session_player_id == "participant.a"
    assert resolution.strategy_id is None


def test_contradictory_later_manual_evidence_surfaces_conflict_without_remap() -> None:
    result = derive_runtime_associations(
        _input(
            (
                _participant("participant.a", strategy="strategy.a"),
                _participant("participant.b", strategy="strategy.b"),
            ),
            (_slot("slot.1"),),
            manual=(
                TrustedRuntimeManualConfirmation(
                    runtime_slot_id="slot.1", session_player_id="participant.b"
                ),
            ),
            previous=(
                PreviousConfirmedRuntimeAssociation(
                    runtime_slot_id="slot.1",
                    session_player_id="participant.a",
                    strategy_id="strategy.a",
                ),
            ),
        )
    )
    resolution = result.for_slot("slot.1")
    assert resolution is not None
    assert resolution.status == RuntimeAssociationResolutionStatus.CONFLICT
    assert resolution.session_player_id == "participant.a"
    assert resolution.strategy_id == "strategy.a"


def test_rejects_same_participant_as_two_previous_confirmed_slots() -> None:
    with pytest.raises(ValueError, match="previous association participant"):
        _input(
            (_participant("participant.a", strategy="strategy.a"),),
            (_slot("slot.1"), _slot("slot.2")),
            previous=(
                PreviousConfirmedRuntimeAssociation(
                    runtime_slot_id="slot.1",
                    session_player_id="participant.a",
                    strategy_id="strategy.a",
                ),
                PreviousConfirmedRuntimeAssociation(
                    runtime_slot_id="slot.2",
                    session_player_id="participant.a",
                    strategy_id="strategy.a",
                ),
            ),
        )


def test_rejects_same_participant_as_two_manual_slots() -> None:
    with pytest.raises(ValueError, match="manual confirmation participant"):
        _input(
            (_participant("participant.a"),),
            (_slot("slot.1"), _slot("slot.2")),
            manual=(
                TrustedRuntimeManualConfirmation(
                    runtime_slot_id="slot.1", session_player_id="participant.a"
                ),
                TrustedRuntimeManualConfirmation(
                    runtime_slot_id="slot.2", session_player_id="participant.a"
                ),
            ),
        )


def test_rejects_cross_slot_manual_claim_against_previous_mapping() -> None:
    with pytest.raises(ValueError, match="multiple slots"):
        _input(
            (_participant("participant.a", strategy="strategy.a"),),
            (_slot("slot.1"), _slot("slot.2")),
            manual=(
                TrustedRuntimeManualConfirmation(
                    runtime_slot_id="slot.2", session_player_id="participant.a"
                ),
            ),
            previous=(
                PreviousConfirmedRuntimeAssociation(
                    runtime_slot_id="slot.1",
                    session_player_id="participant.a",
                    strategy_id="strategy.a",
                ),
            ),
        )


def test_models_round_trip_without_mutating_input() -> None:
    original = _input(
        (_participant("participant.a", strategy="strategy.a"),),
        (_slot("slot.1", avatar=frozenset({"participant.a"})),),
    )
    result = derive_runtime_associations(original)
    assert RuntimeAssociationInput.model_validate_json(original.model_dump_json()) == original
    assert type(result.resolutions) is tuple
