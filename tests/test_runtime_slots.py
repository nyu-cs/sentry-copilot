from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from sentry_copilot.domain.battle_roster import (
    BattleParticipantInactivated,
    BattleRuntimeStageType,
    InactivePresentation,
    PlayerInactivationReason,
)
from sentry_copilot.domain.enums import EvidenceKind
from sentry_copilot.domain.events import (
    SessionRulesetRevisionCorrected,
    SlotAssociationRecordsAppended,
    SlotAssociationsCorrected,
)
from sentry_copilot.domain.evidence import EvidenceRecord
from sentry_copilot.domain.identifiers import LocaleId
from sentry_copilot.domain.models import PlayerState, SessionState
from sentry_copilot.domain.prebattle import (
    BattleEntryConfirmed,
    BattleEntryFalsePositiveCorrected,
    BattleEntryNotConfirmed,
    BattleEntryNotConfirmedReason,
    NormalizedRoi,
    ReadyCheckObserved,
)
from sentry_copilot.domain.queries import (
    build_current_runtime_slots,
    get_effective_slot_participant_association,
    get_runtime_slot,
    get_slot_association_conflicts,
    get_slot_association_view,
    get_uncontested_slot_participant_associations,
    get_unresolved_runtime_slots,
)
from sentry_copilot.domain.reducer import InvalidObservationError, reduce_session
from sentry_copilot.domain.rulesets import (
    RevisionSelectionMethod,
    SessionRulesetContext,
)
from sentry_copilot.domain.runtime_slots import (
    RuntimeSlotEvidenceLedger,
    RuntimeSlotObservation,
    RuntimeSlotObservationCorrected,
    RuntimeSlotPresentation,
    SlotAssociationConflictType,
    SlotAssociationCorrection,
    SlotAssociationState,
    SlotParticipantAssociationBasis,
    SlotParticipantAssociationRecord,
)
from sentry_copilot.domain.strategy_selection import (
    ParticipantField,
    StrategySelectionParticipant,
    StrategySelectionSnapshot,
)

NOW = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
SESSION_ID = "session.synthetic"
RULESET_ID = "demo.synthetic_covenant_latter"
EARLY_REVISION = "demo.synthetic_covenant_latter.pre_update"
LATE_REVISION = "demo.synthetic_covenant_latter.post_update"
CATALOG_VERSION = "catalog.synthetic.v1"
LAYOUT_1 = "layout.synthetic.1"
LAYOUT_2 = "layout.synthetic.2"
SLOT_1 = "runtime-slot.synthetic.1"
SLOT_2 = "runtime-slot.synthetic.2"
SLOT_3 = "runtime-slot.synthetic.3"
P1 = "session-player-1"
P2 = "session-player-2"
P3 = "session-player-3"


def field_evidence(offset: int = 0) -> EvidenceRecord:
    return EvidenceRecord(
        source=EvidenceKind.OBSERVED,
        confidence=0.99,
        observed_at=NOW + timedelta(seconds=offset),
    )


def participant(
    participant_id: str,
    *,
    selection_row: int,
    player_tag: str | None = None,
    display_name: str | None = None,
    is_self: bool | None = None,
    avatar_visual_key: str | None = None,
    strategy_id: str | None = None,
) -> StrategySelectionParticipant:
    evidence: dict[ParticipantField, EvidenceRecord] = {}
    if player_tag is not None:
        evidence[ParticipantField.PLAYER_TAG] = field_evidence()
    if display_name is not None:
        evidence[ParticipantField.DISPLAY_NAME] = field_evidence()
    if is_self is not None:
        evidence[ParticipantField.IS_SELF] = field_evidence()
    if avatar_visual_key is not None:
        evidence[ParticipantField.AVATAR] = field_evidence()
    if strategy_id is not None:
        evidence[ParticipantField.STRATEGY] = field_evidence()
    return StrategySelectionParticipant(
        session_player_id=participant_id,
        selection_row=selection_row,
        player_tag=player_tag,
        display_name=display_name,
        is_self=is_self,
        avatar_visual_key=avatar_visual_key,
        strategy_id=strategy_id,
        field_evidence=evidence,
    )


def session_state(
    *,
    frozen: bool = False,
    solo: bool = False,
    with_ruleset_context: bool = False,
    include_legacy_cache: bool = False,
) -> SessionState:
    participants = (
        (
            participant(
                P1,
                selection_row=3,
                player_tag="0038",
                display_name="Synthetic Alpha",
                is_self=True,
                avatar_visual_key="avatar.synthetic.alpha",
                strategy_id="strategy.synthetic.legacy-alpha",
            ),
        )
        if solo
        else (
            participant(
                P1,
                selection_row=3,
                player_tag="0038",
                display_name="Synthetic Alpha",
                is_self=True,
                avatar_visual_key="avatar.synthetic.alpha",
                strategy_id="strategy.synthetic.legacy-alpha",
            ),
            participant(
                P2,
                selection_row=1,
                player_tag="1042",
                display_name="Synthetic Beta",
            ),
            participant(
                P3,
                selection_row=2,
                player_tag="2207",
                display_name="Synthetic Gamma",
            ),
        )
    )
    context = (
        SessionRulesetContext(
            ruleset_id=RULESET_ID,
            ruleset_revision_id=EARLY_REVISION,
            locale_id=LocaleId.ZH_CN,
            catalog_version=CATALOG_VERSION,
            selection_method=RevisionSelectionMethod.MANUAL,
            selected_at=NOW,
            selection_reason="synthetic test context",
            context_generation=1,
        )
        if with_ruleset_context
        else None
    )
    return SessionState(
        session_id=SESSION_ID,
        ruleset_id=RULESET_ID,
        ruleset_context=context,
        players=(
            [
                PlayerState(
                    slot=1,
                    is_self=True,
                    avatar_visual_key="avatar.synthetic.legacy-cache",
                    hp=38,
                    strategy_id="strategy.synthetic.legacy-cache",
                )
            ]
            if include_legacy_cache
            else []
        ),
        strategy_selection=StrategySelectionSnapshot(
            session_id=SESSION_ID,
            ruleset_id=RULESET_ID,
            captured_at=NOW,
            participants=participants,
            frozen=frozen,
        ),
        updated_at=NOW,
    )


def battle_entry(
    participant_id: str,
    *,
    evidence_id: str | None = None,
    timestamp: datetime = NOW,
) -> BattleEntryConfirmed:
    entry_id = evidence_id or f"evidence.entry.{participant_id}"
    return BattleEntryConfirmed(
        evidence_id=entry_id,
        session_id=SESSION_ID,
        session_player_id=participant_id,
        timestamp=timestamp,
        provenance=EvidenceKind.OBSERVED,
        confidence=0.99,
        frame_reference=f"private/synthetic/{entry_id}.png",
        observed_visual_cue="synthetic normal active battle participation",
    )


def with_entrants(
    *participant_ids: str,
    state: SessionState | None = None,
) -> SessionState:
    current = state or session_state()
    for index, participant_id in enumerate(participant_ids):
        current = reduce_session(
            current,
            battle_entry(
                participant_id,
                timestamp=NOW + timedelta(seconds=index),
            ),
        )
    return current


def roi(*, x: float = 0.02, y: float = 0.10) -> NormalizedRoi:
    return NormalizedRoi(x=x, y=y, width=0.12, height=0.14)


def observation(
    *,
    evidence_id: str = "evidence.slot.1",
    layout_id: str = LAYOUT_1,
    runtime_slot_id: str = SLOT_1,
    observed_at: datetime = NOW + timedelta(seconds=10),
    visual_index: int = 1,
    region: NormalizedRoi | None = None,
    slot_visible: bool = True,
    active: bool = True,
    inactive_presentation: InactivePresentation | None = None,
    display_name: str | None = None,
    player_tag: str | None = None,
    self_marker: bool = False,
    provenance: EvidenceKind = EvidenceKind.OBSERVED,
) -> RuntimeSlotObservation:
    return RuntimeSlotObservation(
        evidence_id=evidence_id,
        session_id=SESSION_ID,
        layout_id=layout_id,
        runtime_slot_id=runtime_slot_id,
        observed_at=observed_at,
        visual_index=visual_index,
        roi=region or roi(),
        slot_visible=slot_visible,
        normal_active_presentation_visible=active,
        inactive_presentation=inactive_presentation,
        observed_display_name=display_name,
        observed_player_tag=player_tag,
        self_marker_visible=self_marker,
        provenance=provenance,
        confidence=0.97,
        frame_reference=f"private/synthetic/{evidence_id}.png",
        source_detail="synthetic runtime slot observation",
    )


def correct_observation(
    *target_ids: str,
    evidence_id: str = "correction.slot-observation.1",
    layout_id: str = LAYOUT_1,
    runtime_slot_id: str = SLOT_1,
    corrected_at: datetime = NOW + timedelta(seconds=20),
) -> RuntimeSlotObservationCorrected:
    return RuntimeSlotObservationCorrected(
        evidence_id=evidence_id,
        session_id=SESSION_ID,
        layout_id=layout_id,
        runtime_slot_id=runtime_slot_id,
        corrected_at=corrected_at,
        invalidated_observation_ids=target_ids,
        reason="synthetic false-positive slot observation",
    )


def association_record(
    participant_id: str,
    *,
    record_id: str | None = None,
    layout_id: str = LAYOUT_1,
    runtime_slot_id: str = SLOT_1,
    basis: SlotParticipantAssociationBasis = (
        SlotParticipantAssociationBasis.DIRECT_PLAYER_TAG
    ),
    evidence_ids: tuple[str, ...] = ("evidence.slot.1",),
    associated_at: datetime = NOW + timedelta(seconds=12),
    supersedes: tuple[str, ...] = (),
    manual_reason: str | None = None,
) -> SlotParticipantAssociationRecord:
    return SlotParticipantAssociationRecord(
        record_id=record_id or f"association.{runtime_slot_id}.{participant_id}",
        session_id=SESSION_ID,
        layout_id=layout_id,
        runtime_slot_id=runtime_slot_id,
        session_player_id=participant_id,
        basis=basis,
        associated_at=associated_at,
        evidence_ids=evidence_ids,
        supersedes_record_ids=supersedes,
        manual_reason=manual_reason,
    )


def append_associations(
    state: SessionState,
    *records: SlotParticipantAssociationRecord,
) -> SessionState:
    return reduce_session(
        state,
        SlotAssociationRecordsAppended(
            session_id=SESSION_ID,
            records=records,
            timestamp=max(record.associated_at for record in records),
        ),
    )


def correction_event(
    *replacements: SlotParticipantAssociationRecord,
    correction_id: str = "correction.association.1",
    corrected_at: datetime = NOW + timedelta(seconds=30),
    reason: str = "synthetic association correction",
) -> SlotAssociationsCorrected:
    normalized = tuple(
        record.model_copy(
            update={
                "basis": SlotParticipantAssociationBasis.MANUAL_CONFIRMATION,
                "associated_at": corrected_at,
                "manual_reason": reason,
            }
        )
        for record in replacements
    )
    return SlotAssociationsCorrected(
        session_id=SESSION_ID,
        correction=SlotAssociationCorrection(
            correction_id=correction_id,
            session_id=SESSION_ID,
            corrected_at=corrected_at,
            replacement_record_ids=tuple(record.record_id for record in normalized),
            reason=reason,
        ),
        replacement_records=normalized,
    )


def state_with_tag_association(
    *,
    participant_id: str = P1,
    player_tag: str = "0038",
    runtime_slot_id: str = SLOT_1,
    evidence_id: str = "evidence.slot.1",
    state: SessionState | None = None,
) -> SessionState:
    current = state or with_entrants(P1, P2)
    current = reduce_session(
        current,
        observation(
            evidence_id=evidence_id,
            runtime_slot_id=runtime_slot_id,
            player_tag=player_tag,
            display_name="Synthetic observed name",
        ),
    )
    return append_associations(
        current,
        association_record(
            participant_id,
            record_id=f"association.{evidence_id}",
            runtime_slot_id=runtime_slot_id,
            evidence_ids=(evidence_id,),
        ),
    )


def test_runtime_slot_observation_creates_current_slot() -> None:
    state = reduce_session(session_state(), observation())

    view = build_current_runtime_slots(state)

    assert view.current_layout_id == LAYOUT_1
    assert len(view.slots) == 1
    assert view.slots[0].runtime_slot_id == SLOT_1
    assert view.slots[0].current_presentation == RuntimeSlotPresentation.NORMAL_ACTIVE


def test_slot_exists_with_unknown_association() -> None:
    state = reduce_session(session_state(), observation())

    assert get_effective_slot_participant_association(state, SLOT_1) is None
    assert tuple(slot.runtime_slot_id for slot in get_unresolved_runtime_slots(state)) == (
        SLOT_1,
    )


def test_entrant_can_exist_without_any_runtime_slot() -> None:
    state = with_entrants(P1)

    assert build_current_runtime_slots(state).slots == ()
    assert get_uncontested_slot_participant_associations(state) == ()


def test_first_frame_departed_placeholder_cannot_be_associated() -> None:
    state = session_state()
    state = reduce_session(
        state,
        BattleEntryNotConfirmed(
            evidence_id="evidence.entry-not-confirmed.p3",
            session_id=SESSION_ID,
            session_player_id=P3,
            timestamp=NOW,
            provenance=EvidenceKind.OBSERVED,
            confidence=0.99,
            frame_reference="private/synthetic/departed-placeholder.png",
            observed_visual_cue="synthetic first stable frame already departed",
            reason=(
                BattleEntryNotConfirmedReason.FIRST_STABLE_FRAME_ALREADY_INACTIVE
            ),
        ),
    )
    state = reduce_session(
        state,
        observation(
            player_tag="2207",
            active=False,
            inactive_presentation=InactivePresentation.DEPARTED,
        ),
    )

    with pytest.raises(InvalidObservationError):
        append_associations(state, association_record(P3))

    assert get_unresolved_runtime_slots(state)


def test_ready_only_nonentrant_association_is_rejected() -> None:
    state = reduce_session(
        session_state(),
        ReadyCheckObserved(
            evidence_id="evidence.ready.p3",
            session_id=SESSION_ID,
            session_player_id=P3,
            timestamp=NOW,
            provenance=EvidenceKind.OBSERVED,
            confidence=0.99,
            frame_reference="private/synthetic/ready-p3.png",
            observed_visual_cue="synthetic ready check",
        ),
    )
    state = reduce_session(state, observation(player_tag="2207"))

    with pytest.raises(InvalidObservationError):
        append_associations(state, association_record(P3))


def test_direct_player_tag_establishes_association() -> None:
    state = state_with_tag_association()

    result = get_effective_slot_participant_association(state, SLOT_1)

    assert result is not None
    assert result.session_player_id == P1
    assert result.bases == (SlotParticipantAssociationBasis.DIRECT_PLAYER_TAG,)
    assert get_unresolved_runtime_slots(state) == ()


def test_direct_player_tag_must_match_session_participant_tag() -> None:
    state = with_entrants(P1)
    state = reduce_session(state, observation(player_tag="1042"))

    with pytest.raises(InvalidObservationError):
        append_associations(state, association_record(P1))


def test_observed_player_tag_is_strict_and_preserves_leading_zero() -> None:
    result = observation(player_tag="0038")

    assert result.observed_player_tag == "0038"
    payload = result.model_dump()
    payload["observed_player_tag"] = 38
    with pytest.raises(ValidationError):
        RuntimeSlotObservation.model_validate(payload)


def test_display_name_alone_is_not_a_strong_association() -> None:
    state = with_entrants(P1)
    state = reduce_session(
        state,
        observation(display_name="Synthetic Alpha", player_tag=None),
    )

    with pytest.raises(InvalidObservationError):
        append_associations(state, association_record(P1))

    assert get_unresolved_runtime_slots(state)
    assert "display_name_only" not in {
        basis.value for basis in SlotParticipantAssociationBasis
    }


def test_display_name_conflict_does_not_override_matching_tag() -> None:
    state = with_entrants(P1)
    state = reduce_session(
        state,
        observation(display_name="Different Synthetic Name", player_tag="0038"),
    )

    state = append_associations(state, association_record(P1))

    assert get_effective_slot_participant_association(state, SLOT_1) is not None


def test_direct_self_marker_only_associates_snapshot_self_participant() -> None:
    state = with_entrants(P1, P2)
    state = reduce_session(state, observation(self_marker=True))
    self_record = association_record(
        P1,
        basis=SlotParticipantAssociationBasis.DIRECT_SELF_MARKER,
    )

    state = append_associations(state, self_record)

    assert get_effective_slot_participant_association(state, SLOT_1) is not None
    with pytest.raises(InvalidObservationError):
        append_associations(
            reduce_session(with_entrants(P1, P2), observation(self_marker=True)),
            association_record(
                P2,
                record_id="association.wrong-self",
                basis=SlotParticipantAssociationBasis.DIRECT_SELF_MARKER,
            ),
        )


def test_self_is_not_inferred_from_visual_or_selection_order() -> None:
    state = with_entrants(P1)
    state = reduce_session(state, observation(visual_index=3, self_marker=False))

    with pytest.raises(InvalidObservationError):
        append_associations(
            state,
            association_record(
                P1,
                basis=SlotParticipantAssociationBasis.DIRECT_SELF_MARKER,
            ),
        )


def test_manual_confirmation_establishes_association_without_tag() -> None:
    state = with_entrants(P1)
    state = reduce_session(state, observation(display_name="Synthetic Alpha"))
    record = association_record(
        P1,
        basis=SlotParticipantAssociationBasis.MANUAL_CONFIRMATION,
        manual_reason="synthetic user confirmed target slot",
    )

    state = append_associations(state, record)

    result = get_effective_slot_participant_association(state, SLOT_1)
    assert result is not None
    assert result.bases == (SlotParticipantAssociationBasis.MANUAL_CONFIRMATION,)


def test_selection_row_does_not_map_to_runtime_slot() -> None:
    state = state_with_tag_association(participant_id=P1, player_tag="0038")

    result = get_effective_slot_participant_association(state, SLOT_1)

    assert result is not None
    assert result.session_player_id == P1
    assert state.strategy_selection is not None
    assert state.strategy_selection.participants[0].selection_row == 3
    assert SLOT_1 != "3"


def test_avatar_hp_and_legacy_slot_cache_do_not_establish_association() -> None:
    state = with_entrants(
        P1,
        state=session_state(include_legacy_cache=True),
    )
    state = reduce_session(state, observation())

    assert get_uncontested_slot_participant_associations(state) == ()
    assert {
        "avatar_match",
        "hp_match",
        "selection_row_match",
        "highest_confidence",
    }.isdisjoint({basis.value for basis in SlotParticipantAssociationBasis})


def test_observation_evidence_id_replay_is_idempotent() -> None:
    event = observation()
    state = reduce_session(session_state(), event)

    assert reduce_session(state, event) is state


def test_observation_evidence_id_collision_is_rejected() -> None:
    event = observation()
    state = reduce_session(session_state(), event)
    changed = event.model_copy(update={"visual_index": 2})

    with pytest.raises(InvalidObservationError):
        reduce_session(state, changed)


def test_same_slot_multiple_participant_claims_form_conflict() -> None:
    state = with_entrants(P1, P2)
    state = reduce_session(state, observation(player_tag="0038"))
    state = reduce_session(
        state,
        observation(
            evidence_id="evidence.slot.2",
            observed_at=NOW + timedelta(seconds=11),
            player_tag="1042",
        ),
    )
    state = append_associations(
        state,
        association_record(P1),
        association_record(
            P2,
            record_id="association.slot-1.p2",
            evidence_ids=("evidence.slot.2",),
            associated_at=NOW + timedelta(seconds=13),
        ),
    )

    conflicts = get_slot_association_conflicts(state)

    assert {item.conflict_type for item in conflicts} == {
        SlotAssociationConflictType.SLOT_MULTIPLE_PARTICIPANT_CLAIMS
    }
    assert get_effective_slot_participant_association(state, SLOT_1) is None
    assert set(conflicts[0].record_ids) == {
        "association.runtime-slot.synthetic.1.session-player-1",
        "association.slot-1.p2",
    }
    assert state.slot_associations is not None
    assert len(state.slot_associations.records) == 2


def test_same_participant_multiple_current_slots_form_conflict() -> None:
    state = with_entrants(P1)
    state = reduce_session(state, observation(player_tag="0038"))
    state = reduce_session(
        state,
        observation(
            evidence_id="evidence.slot.2",
            runtime_slot_id=SLOT_2,
            observed_at=NOW + timedelta(seconds=11),
            visual_index=2,
            region=roi(y=0.30),
            player_tag="0038",
        ),
    )
    state = append_associations(
        state,
        association_record(P1),
        association_record(
            P1,
            record_id="association.slot-2.p1",
            runtime_slot_id=SLOT_2,
            evidence_ids=("evidence.slot.2",),
            associated_at=NOW + timedelta(seconds=13),
        ),
    )

    conflicts = get_slot_association_conflicts(state)

    assert {item.conflict_type for item in conflicts} == {
        SlotAssociationConflictType.PARTICIPANT_MULTIPLE_SLOT_CLAIMS
    }
    assert get_uncontested_slot_participant_associations(state) == ()
    assert set(conflicts[0].runtime_slot_ids) == {SLOT_1, SLOT_2}


def slot_conflict_state() -> SessionState:
    state = with_entrants(P1, P2)
    state = reduce_session(state, observation(player_tag="0038"))
    state = reduce_session(
        state,
        observation(
            evidence_id="evidence.slot.2",
            observed_at=NOW + timedelta(seconds=11),
            player_tag="1042",
        ),
    )
    return append_associations(
        state,
        association_record(P1),
        association_record(
            P2,
            record_id="association.slot-1.p2",
            evidence_ids=("evidence.slot.2",),
            associated_at=NOW + timedelta(seconds=13),
        ),
    )


def test_manual_correction_resolves_slot_conflict_and_preserves_history() -> None:
    state = slot_conflict_state()
    replacement = association_record(
        P1,
        record_id="association.corrected.slot-1.p1",
        basis=SlotParticipantAssociationBasis.MANUAL_CONFIRMATION,
        evidence_ids=("evidence.slot.1",),
        supersedes=(
            "association.runtime-slot.synthetic.1.session-player-1",
            "association.slot-1.p2",
        ),
        manual_reason="synthetic association correction",
    )

    corrected = reduce_session(state, correction_event(replacement))

    assert get_slot_association_conflicts(corrected) == ()
    result = get_effective_slot_participant_association(corrected, SLOT_1)
    assert result is not None and result.session_player_id == P1
    assert corrected.slot_associations is not None
    assert len(corrected.slot_associations.records) == 3
    assert corrected.slot_associations.superseded_record_ids == frozenset(
        (
            "association.runtime-slot.synthetic.1.session-player-1",
            "association.slot-1.p2",
        )
    )


def test_manual_correction_resolves_participant_multiple_slot_conflict() -> None:
    state = with_entrants(P1)
    state = reduce_session(state, observation(player_tag="0038"))
    state = reduce_session(
        state,
        observation(
            evidence_id="evidence.slot.2",
            runtime_slot_id=SLOT_2,
            observed_at=NOW + timedelta(seconds=11),
            visual_index=2,
            region=roi(y=0.30),
            player_tag="0038",
        ),
    )
    first = association_record(P1)
    second = association_record(
        P1,
        record_id="association.slot-2.p1",
        runtime_slot_id=SLOT_2,
        evidence_ids=("evidence.slot.2",),
        associated_at=NOW + timedelta(seconds=13),
    )
    state = append_associations(state, first, second)
    replacement = association_record(
        P1,
        record_id="association.corrected.slot-1.p1",
        basis=SlotParticipantAssociationBasis.MANUAL_CONFIRMATION,
        supersedes=(first.record_id, second.record_id),
        manual_reason="synthetic association correction",
    )

    state = reduce_session(state, correction_event(replacement))

    assert get_slot_association_conflicts(state) == ()
    assert get_effective_slot_participant_association(state, SLOT_1) is not None
    assert get_effective_slot_participant_association(state, SLOT_2) is None


def test_failed_multi_record_correction_is_atomic() -> None:
    state = slot_conflict_state()
    before = state.model_dump()
    first = association_record(
        P1,
        record_id="association.correction.valid",
        basis=SlotParticipantAssociationBasis.MANUAL_CONFIRMATION,
        supersedes=("association.runtime-slot.synthetic.1.session-player-1",),
        manual_reason="synthetic association correction",
    )
    second = association_record(
        P2,
        record_id="association.correction.invalid",
        basis=SlotParticipantAssociationBasis.MANUAL_CONFIRMATION,
        evidence_ids=("evidence.missing",),
        supersedes=("association.slot-1.p2",),
        manual_reason="synthetic association correction",
    )

    with pytest.raises(InvalidObservationError):
        reduce_session(state, correction_event(first, second))

    assert state.model_dump() == before


def test_correction_id_replay_is_idempotent_and_collision_rejected() -> None:
    state = slot_conflict_state()
    replacement = association_record(
        P1,
        record_id="association.corrected.slot-1.p1",
        basis=SlotParticipantAssociationBasis.MANUAL_CONFIRMATION,
        supersedes=(
            "association.runtime-slot.synthetic.1.session-player-1",
            "association.slot-1.p2",
        ),
        manual_reason="synthetic association correction",
    )
    event = correction_event(replacement)
    corrected = reduce_session(state, event)

    assert reduce_session(corrected, event) is corrected
    collision = event.model_copy(
        update={
            "correction": event.correction.model_copy(
                update={"reason": "different synthetic reason"}
            )
        }
    )
    with pytest.raises(InvalidObservationError):
        reduce_session(corrected, collision)


def test_association_record_id_replay_and_collision() -> None:
    state = with_entrants(P1)
    state = reduce_session(state, observation(player_tag="0038"))
    record = association_record(P1)
    event = SlotAssociationRecordsAppended(
        session_id=SESSION_ID,
        records=(record,),
        timestamp=record.associated_at,
    )
    associated = reduce_session(state, event)

    assert reduce_session(associated, event) is associated
    collision = record.model_copy(update={"session_player_id": P2})
    with pytest.raises(InvalidObservationError):
        reduce_session(
            associated,
            SlotAssociationRecordsAppended(
                session_id=SESSION_ID,
                records=(collision,),
                timestamp=collision.associated_at,
            ),
        )


def test_false_slot_observation_is_audit_correctable() -> None:
    event = observation()
    state = reduce_session(session_state(), event)

    corrected = reduce_session(
        state,
        correct_observation(event.evidence_id),
    )

    assert build_current_runtime_slots(corrected).slots == ()
    assert corrected.runtime_slot_evidence is not None
    assert len(corrected.runtime_slot_evidence.entries) == 2
    assert corrected.runtime_slot_evidence.get(event.evidence_id) == event


def test_observation_correction_rederives_association_as_unresolved() -> None:
    state = with_entrants(P1)
    base = observation(
        evidence_id="evidence.slot.base",
        observed_at=NOW + timedelta(seconds=9),
    )
    tagged = observation(player_tag="0038")
    state = reduce_session(state, base)
    state = reduce_session(state, tagged)
    state = append_associations(state, association_record(P1))
    assert get_effective_slot_participant_association(state, SLOT_1) is not None

    state = reduce_session(state, correct_observation(tagged.evidence_id))

    assert get_effective_slot_participant_association(state, SLOT_1) is None
    assert get_unresolved_runtime_slots(state)
    assert state.slot_associations is not None
    assert len(state.slot_associations.records) == 1


def test_observation_correction_is_idempotent_and_collision_rejected() -> None:
    state = reduce_session(session_state(), observation())
    correction = correct_observation("evidence.slot.1")
    corrected = reduce_session(state, correction)

    assert reduce_session(corrected, correction) is corrected
    collision = correction.model_copy(update={"reason": "different reason"})
    with pytest.raises(InvalidObservationError):
        reduce_session(corrected, collision)


def test_reliable_movement_within_layout_preserves_slot_identity() -> None:
    state = state_with_tag_association()
    moved_roi = roi(x=0.03, y=0.12)
    state = reduce_session(
        state,
        observation(
            evidence_id="evidence.slot.moved",
            observed_at=NOW + timedelta(seconds=20),
            visual_index=2,
            region=moved_roi,
        ),
    )

    slot = get_runtime_slot(state, SLOT_1)

    assert slot is not None
    assert slot.current_visual_index == 2
    assert slot.current_roi == moved_roi
    assert slot.observation_evidence_ids == (
        "evidence.slot.1",
        "evidence.slot.moved",
    )
    assert get_effective_slot_participant_association(state, SLOT_1) is not None


def test_unreliable_reorder_uses_new_layout_and_does_not_inherit_association() -> None:
    state = state_with_tag_association()
    state = reduce_session(
        state,
        observation(
            evidence_id="evidence.layout-2.slot-3",
            layout_id=LAYOUT_2,
            runtime_slot_id=SLOT_3,
            observed_at=NOW + timedelta(seconds=30),
            player_tag=None,
        ),
    )

    view = build_current_runtime_slots(state)

    assert view.current_layout_id == LAYOUT_2
    assert tuple(slot.runtime_slot_id for slot in view.slots) == (SLOT_3,)
    assert get_effective_slot_participant_association(state, SLOT_1) is None
    assert get_effective_slot_participant_association(state, SLOT_3) is None
    assert get_slot_association_conflicts(state) == ()


def test_new_layout_rejects_reuse_of_old_runtime_slot_id() -> None:
    state = state_with_tag_association()

    with pytest.raises(InvalidObservationError):
        reduce_session(
            state,
            observation(
                evidence_id="evidence.layout-2.reused-slot-id",
                layout_id=LAYOUT_2,
                runtime_slot_id=SLOT_1,
                observed_at=NOW + timedelta(seconds=30),
                player_tag=None,
            ),
        )


def test_historical_layout_conflict_does_not_conflict_with_current_layout() -> None:
    state = slot_conflict_state()
    assert get_slot_association_conflicts(state)
    state = reduce_session(
        state,
        observation(
            evidence_id="evidence.layout-2.slot-3",
            layout_id=LAYOUT_2,
            runtime_slot_id=SLOT_3,
            observed_at=NOW + timedelta(seconds=30),
        ),
    )

    assert get_slot_association_conflicts(state) == ()
    assert get_slot_association_view(state).ineligible_record_ids


def test_non_current_layout_cannot_receive_a_new_current_association() -> None:
    state = state_with_tag_association()
    state = reduce_session(
        state,
        observation(
            evidence_id="evidence.layout-2.slot-3",
            layout_id=LAYOUT_2,
            runtime_slot_id=SLOT_3,
            observed_at=NOW + timedelta(seconds=30),
        ),
    )

    with pytest.raises(InvalidObservationError):
        append_associations(
            state,
            association_record(
                P1,
                record_id="association.historical-layout",
                evidence_ids=("evidence.slot.1",),
            ),
        )


def test_ambiguous_latest_layout_time_produces_no_current_layout() -> None:
    state = reduce_session(
        session_state(),
        observation(layout_id=LAYOUT_1),
    )
    state = reduce_session(
        state,
        observation(
            evidence_id="evidence.layout-2.same-time",
            layout_id=LAYOUT_2,
            runtime_slot_id=SLOT_2,
        ),
    )

    assert build_current_runtime_slots(state).current_layout_id is None
    assert build_current_runtime_slots(state).slots == ()


def test_inactive_entrant_keeps_association() -> None:
    state = state_with_tag_association()
    before = get_effective_slot_participant_association(state, SLOT_1)
    state = reduce_session(
        state,
        BattleParticipantInactivated(
            evidence_id="evidence.inactivation.p1",
            session_id=SESSION_ID,
            session_player_id=P1,
            observed_at=NOW + timedelta(seconds=40),
            stage_type=BattleRuntimeStageType.NORMAL,
            round_number=2,
            wave_number=1,
            reason=PlayerInactivationReason.HP_DEPLETED,
            presentation=InactivePresentation.SPECTATING,
            hp=0,
            provenance=EvidenceKind.OBSERVED,
            confidence=0.99,
            evidence_reference="private/synthetic/spectating-p1.png",
        ),
    )

    assert get_effective_slot_participant_association(state, SLOT_1) == before
    assert state.slot_associations is not None


def test_entry_correction_keeps_association_history_but_removes_current_relation() -> None:
    state = state_with_tag_association(participant_id=P1, player_tag="0038")
    assert get_effective_slot_participant_association(state, SLOT_1) is not None

    state = reduce_session(
        state,
        BattleEntryFalsePositiveCorrected(
            evidence_id="correction.entry.p1",
            session_id=SESSION_ID,
            session_player_id=P1,
            timestamp=NOW + timedelta(seconds=40),
            invalidated_battle_entry_evidence_ids=("evidence.entry.session-player-1",),
            reason="synthetic false-positive entry correction",
        ),
    )

    assert get_effective_slot_participant_association(state, SLOT_1) is None
    assert state.slot_associations is not None
    assert len(state.slot_associations.records) == 1


def test_revision_correction_preserves_slots_and_associations() -> None:
    state = state_with_tag_association(
        state=with_entrants(
            P1,
            P2,
            state=session_state(with_ruleset_context=True),
        )
    )
    before_evidence = state.runtime_slot_evidence
    before_associations = state.slot_associations
    before_view = get_slot_association_view(state)

    state = reduce_session(
        state,
        SessionRulesetRevisionCorrected(
            session_id=SESSION_ID,
            ruleset_id=RULESET_ID,
            ruleset_revision_id=LATE_REVISION,
            locale_id=LocaleId.ZH_CN,
            catalog_version="catalog.synthetic.v2",
            selected_at=NOW + timedelta(minutes=1),
            reason="synthetic revision correction",
        ),
    )

    assert state.runtime_slot_evidence == before_evidence
    assert state.slot_associations == before_associations
    assert get_slot_association_view(state) == before_view


def test_frozen_snapshot_does_not_block_runtime_slot_evidence() -> None:
    state = with_entrants(P1, state=session_state(frozen=True))

    state = reduce_session(state, observation(player_tag="0038"))
    state = append_associations(state, association_record(P1))

    assert get_effective_slot_participant_association(state, SLOT_1) is not None
    assert state.strategy_selection is not None and state.strategy_selection.frozen


def test_legacy_strategy_selection_row_and_hp_are_ignored() -> None:
    state = with_entrants(
        P1,
        state=session_state(include_legacy_cache=True),
    )
    snapshot_before = state.strategy_selection
    players_before = state.players
    state = reduce_session(state, observation())

    assert get_uncontested_slot_participant_associations(state) == ()
    assert state.strategy_selection == snapshot_before
    assert state.players == players_before


def test_solo_entrant_and_slot_association() -> None:
    state = with_entrants(P1, state=session_state(solo=True))
    state = reduce_session(state, observation(player_tag="0038"))
    state = append_associations(state, association_record(P1))

    associations = get_uncontested_slot_participant_associations(state)

    assert len(associations) == 1
    assert associations[0].session_player_id == P1


def test_runtime_slot_models_are_immutable_and_json_round_trip() -> None:
    state = state_with_tag_association()
    assert state.runtime_slot_evidence is not None
    assert state.slot_associations is not None

    with pytest.raises(ValidationError):
        state.runtime_slot_evidence.entries[0].visual_index = 4
    with pytest.raises(ValidationError):
        state.slot_associations.records[0].session_player_id = P2

    assert RuntimeSlotEvidenceLedger.model_validate_json(
        state.runtime_slot_evidence.model_dump_json()
    ) == state.runtime_slot_evidence
    assert SlotAssociationState.model_validate_json(
        state.slot_associations.model_dump_json()
    ) == state.slot_associations


def test_correction_models_complete_json_round_trip() -> None:
    slot_observation = observation()
    slot_correction = correct_observation(slot_observation.evidence_id)
    ledger = RuntimeSlotEvidenceLedger(
        session_id=SESSION_ID,
        entries=(slot_observation, slot_correction),
    )
    conflict = slot_conflict_state()
    replacement = association_record(
        P1,
        record_id="association.corrected.slot-1.p1",
        basis=SlotParticipantAssociationBasis.MANUAL_CONFIRMATION,
        supersedes=(
            "association.runtime-slot.synthetic.1.session-player-1",
            "association.slot-1.p2",
        ),
        manual_reason="synthetic association correction",
    )
    corrected = reduce_session(conflict, correction_event(replacement))
    assert corrected.slot_associations is not None

    assert RuntimeSlotEvidenceLedger.model_validate_json(
        ledger.model_dump_json()
    ) == ledger
    assert SlotAssociationState.model_validate_json(
        corrected.slot_associations.model_dump_json()
    ) == corrected.slot_associations


def test_runtime_slot_public_times_reject_naive_and_accept_aware() -> None:
    with pytest.raises(ValidationError):
        observation(observed_at=datetime(2026, 8, 4, 9, 0))
    aware = datetime(
        2026,
        8,
        4,
        18,
        0,
        tzinfo=timezone(timedelta(hours=9)),
    )

    assert observation(observed_at=aware).observed_at == aware
    with pytest.raises(ValidationError):
        correct_observation(
            "evidence.slot.1",
            corrected_at=datetime(2026, 8, 4, 9, 0),
        )


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    (
        ("runtime_slot_id", 1),
        ("layout_id", 1),
        ("evidence_id", 1),
    ),
)
def test_runtime_slot_ids_are_strict_strings(
    field_name: str,
    bad_value: object,
) -> None:
    payload = observation().model_dump()
    payload[field_name] = bad_value

    with pytest.raises(ValidationError):
        RuntimeSlotObservation.model_validate(payload)


def test_cross_session_observation_and_association_are_rejected() -> None:
    state = with_entrants(P1)
    wrong_observation = observation().model_copy(update={"session_id": "session.other"})
    with pytest.raises(InvalidObservationError):
        reduce_session(state, wrong_observation)

    state = reduce_session(state, observation(player_tag="0038"))
    wrong_record = association_record(P1).model_copy(
        update={"session_id": "session.other"}
    )
    with pytest.raises(ValidationError):
        SlotAssociationRecordsAppended(
            session_id=SESSION_ID,
            records=(wrong_record,),
            timestamp=NOW + timedelta(seconds=12),
        )


def test_queries_do_not_mutate_session_state() -> None:
    state = state_with_tag_association()
    before = state.model_dump()

    build_current_runtime_slots(state)
    get_runtime_slot(state, SLOT_1)
    get_slot_association_view(state)
    get_uncontested_slot_participant_associations(state)
    get_slot_association_conflicts(state)
    get_unresolved_runtime_slots(state)

    assert state.model_dump() == before


def test_raw_observation_has_no_association_or_strategy_authority_fields() -> None:
    fields = RuntimeSlotObservation.model_fields

    assert "session_player_id" not in fields
    assert "strategy_id" not in fields
    assert "selection_row" not in fields
    assert "avatar_visual_key" not in fields
    assert "hp" not in fields


def test_no_slot_only_strategy_panel_basis_exists() -> None:
    assert "direct_slot_strategy_panel" not in {
        basis.value for basis in SlotParticipantAssociationBasis
    }
