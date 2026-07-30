from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from .enums import EvidenceKind, PlayerStatus
from .events import (
    MapObserved,
    PlayerAvatarObserved,
    PlayerHealthObserved,
    PlayerStrategyObserved,
    SessionEvent,
    SessionRulesetContextSelected,
    SessionRulesetRevisionCorrected,
    StageObserved,
    StrategySelectionSnapshotCorrected,
    StrategySelectionSnapshotFrozen,
    StrategySelectionSnapshotObserved,
)
from .identifiers import LocaleId, RulesetId
from .models import SessionState
from .rulesets import RevisionSelectionRecord, SessionRulesetContext
from .strategy_selection import (
    EvidenceRecord,
    ParticipantField,
    SelectionOutcome,
    StrategySelectionParticipant,
    StrategySelectionSnapshot,
)


class InvalidObservationError(ValueError):
    """Raised when an observation cannot safely be assigned to session state."""


_EVIDENCE_PRIORITY = {
    EvidenceKind.PREDICTED: 0,
    EvidenceKind.DERIVED: 1,
    EvidenceKind.OBSERVED: 2,
    EvidenceKind.MANUAL: 3,
}

_PARTICIPANT_ATTRIBUTES = {
    ParticipantField.PLAYER_TAG: "player_tag",
    ParticipantField.DISPLAY_NAME: "display_name",
    ParticipantField.AVATAR: "avatar_visual_key",
    ParticipantField.STRATEGY: "strategy_id",
    ParticipantField.READY: "ready",
    ParticipantField.IS_SELF: "is_self",
    ParticipantField.SELECTION_OUTCOME: "selection_outcome",
}

EvidenceEvent = (
    PlayerAvatarObserved
    | PlayerHealthObserved
    | PlayerStrategyObserved
    | MapObserved
    | StageObserved
    | StrategySelectionSnapshotObserved
    | StrategySelectionSnapshotFrozen
    | StrategySelectionSnapshotCorrected
)


def reduce_session(state: SessionState, event: SessionEvent) -> SessionState:
    """Apply one event while enforcing domain invariants."""

    if isinstance(event, SessionRulesetContextSelected):
        return _apply_ruleset_context_selection(state, event)
    if isinstance(event, SessionRulesetRevisionCorrected):
        return _apply_ruleset_revision_correction(state, event)

    next_state = state.model_copy(deep=True)

    if isinstance(event, PlayerAvatarObserved):
        player = next_state.player(event.slot)
        player.avatar_visual_key = event.avatar_visual_key
        # A personalized avatar must never mutate strategy_id.
    elif isinstance(event, PlayerHealthObserved):
        player = next_state.player(event.slot)
        player.hp = event.hp
        player.status = PlayerStatus.ELIMINATED if event.hp <= 0 else PlayerStatus.ACTIVE
    elif isinstance(event, PlayerStrategyObserved):
        if event.slot != event.selected_player_slot:
            raise InvalidObservationError(
                "strategy observation slot does not match the explicitly selected player slot"
            )
        player = next_state.player(event.slot)
        player.strategy_id = event.strategy_id
        player.strategy_confidence = event.confidence
        player.strategy_observed_at = event.timestamp
    elif isinstance(event, MapObserved):
        next_state.current_map_id = event.map_id
    elif isinstance(event, StageObserved):
        next_state.stage.stage_type = event.stage_type
        next_state.stage.phase = event.phase
        next_state.stage.round_number = event.round_number
        next_state.stage.display_round = event.display_round
    elif isinstance(event, StrategySelectionSnapshotObserved):
        _require_snapshot_context(next_state, event.snapshot.session_id, event.snapshot.ruleset_id)
        _require_non_manual_snapshot_observation(event)
        if event.snapshot.frozen:
            raise InvalidObservationError("an observed snapshot cannot arrive pre-frozen")
        next_state.strategy_selection = _merge_snapshot_observation(
            next_state.strategy_selection,
            event.snapshot,
            _event_evidence(event),
        )
    elif isinstance(event, StrategySelectionSnapshotFrozen):
        _require_snapshot_context(next_state, event.session_id, event.ruleset_id)
        if next_state.strategy_selection is None:
            raise InvalidObservationError("cannot freeze a missing strategy selection snapshot")
        next_state.strategy_selection = _rebuild_snapshot(
            next_state.strategy_selection,
            frozen=True,
            captured_at=event.timestamp,
            evidence=(*next_state.strategy_selection.evidence, _event_evidence(event)),
        )
    elif isinstance(event, StrategySelectionSnapshotCorrected):
        _require_snapshot_context(next_state, event.session_id, event.ruleset_id)
        if next_state.strategy_selection is None:
            raise InvalidObservationError("cannot correct a missing strategy selection snapshot")
        next_state.strategy_selection = _apply_manual_correction(
            next_state.strategy_selection,
            event.replacements,
            _event_evidence(event),
        )
    else:  # pragma: no cover
        raise TypeError(f"unsupported event: {type(event)!r}")

    next_state.updated_at = event.timestamp.astimezone(UTC)
    return next_state


def _require_snapshot_context(state: SessionState, session_id: str, ruleset_id: str) -> None:
    if session_id != state.session_id:
        raise InvalidObservationError("strategy snapshot session_id does not match SessionState")
    if ruleset_id != state.ruleset_id:
        raise InvalidObservationError("strategy snapshot ruleset_id does not match SessionState")


def _event_evidence(event: EvidenceEvent) -> EvidenceRecord:
    return EvidenceRecord(
        source=event.evidence,
        confidence=event.confidence,
        observed_at=event.timestamp,
        source_detail=event.type,
    )


def _apply_ruleset_context_selection(
    state: SessionState,
    event: SessionRulesetContextSelected,
) -> SessionState:
    _require_ruleset_event_session(state, event.session_id)
    current = state.ruleset_context
    if current is not None and current.ruleset_revision_id is not None:
        raise InvalidObservationError(
            "initial ruleset context selection cannot replace a concrete revision"
        )

    history: tuple[RevisionSelectionRecord, ...] = ()
    generation = 1
    if current is not None:
        _require_unchanged_ruleset_and_locale(
            current,
            ruleset_id=event.ruleset_id,
            locale_id=event.locale_id,
        )
        _require_non_decreasing_selection_time(current, event.selected_at)
        history = (
            *current.revision_history,
            _history_record(current, replaced_at=event.selected_at),
        )
        generation = current.context_generation + 1

    return _rebuild_state_with_ruleset_context(
        state,
        context=SessionRulesetContext(
            ruleset_id=event.ruleset_id,
            ruleset_revision_id=event.ruleset_revision_id,
            locale_id=event.locale_id,
            catalog_version=event.catalog_version,
            selection_method=event.selection_method,
            selected_at=event.selected_at,
            selection_evidence=event.selection_evidence,
            selection_reason=event.reason,
            revision_history=history,
            context_generation=generation,
        ),
        updated_at=event.selected_at,
    )


def _apply_ruleset_revision_correction(
    state: SessionState,
    event: SessionRulesetRevisionCorrected,
) -> SessionState:
    _require_ruleset_event_session(state, event.session_id)
    current = state.ruleset_context
    if current is None or current.ruleset_revision_id is None:
        raise InvalidObservationError(
            "ruleset revision correction requires a concrete current context"
        )
    _require_unchanged_ruleset_and_locale(
        current,
        ruleset_id=event.ruleset_id,
        locale_id=event.locale_id,
    )
    if (
        current.ruleset_revision_id == event.ruleset_revision_id
        and current.catalog_version == event.catalog_version
    ):
        raise InvalidObservationError("identical ruleset context cannot be corrected")
    _require_non_decreasing_selection_time(current, event.selected_at)

    context = SessionRulesetContext(
        ruleset_id=event.ruleset_id,
        ruleset_revision_id=event.ruleset_revision_id,
        locale_id=event.locale_id,
        catalog_version=event.catalog_version,
        selection_method=event.selection_method,
        selected_at=event.selected_at,
        selection_evidence=event.selection_evidence,
        selection_reason=event.reason,
        revision_history=(
            *current.revision_history,
            _history_record(current, replaced_at=event.selected_at),
        ),
        context_generation=current.context_generation + 1,
    )
    return _rebuild_state_with_ruleset_context(
        state,
        context=context,
        updated_at=event.selected_at,
    )


def _require_ruleset_event_session(state: SessionState, session_id: str) -> None:
    if state.session_id != session_id:
        raise InvalidObservationError(
            "ruleset context event session_id does not match SessionState"
        )


def _require_unchanged_ruleset_and_locale(
    current: SessionRulesetContext,
    *,
    ruleset_id: RulesetId,
    locale_id: LocaleId,
) -> None:
    if current.ruleset_id != ruleset_id:
        raise InvalidObservationError("ruleset context event cannot change ruleset_id")
    if current.locale_id != locale_id:
        raise InvalidObservationError("ruleset context event cannot change locale_id")


def _require_non_decreasing_selection_time(
    current: SessionRulesetContext,
    selected_at: datetime,
) -> None:
    if selected_at < current.selected_at:
        raise InvalidObservationError(
            "ruleset context selected_at cannot precede the current selection"
        )


def _history_record(
    current: SessionRulesetContext,
    *,
    replaced_at: datetime,
) -> RevisionSelectionRecord:
    return RevisionSelectionRecord(
        ruleset_revision_id=current.ruleset_revision_id,
        catalog_version=current.catalog_version,
        selection_method=current.selection_method,
        selected_at=current.selected_at,
        replaced_at=replaced_at,
        context_generation=current.context_generation,
        evidence=current.selection_evidence,
        reason=current.selection_reason,
    )


def _rebuild_state_with_ruleset_context(
    state: SessionState,
    *,
    context: SessionRulesetContext,
    updated_at: datetime,
) -> SessionState:
    payload = state.model_dump()
    payload.update(
        {
            "ruleset_context": context,
            "ruleset_id": context.ruleset_id,
            "locale": context.locale_id.value,
            "updated_at": updated_at.astimezone(UTC),
        }
    )
    try:
        return SessionState.model_validate(payload)
    except ValidationError as exc:
        raise InvalidObservationError(
            "ruleset context event violates SessionState invariants"
        ) from exc


def _require_non_manual_snapshot_observation(
    event: StrategySelectionSnapshotObserved,
) -> None:
    evidence_records = [
        *event.snapshot.evidence,
        *(
            record
            for participant in event.snapshot.participants
            for record in participant.field_evidence.values()
        ),
    ]
    if event.evidence == EvidenceKind.MANUAL or any(
        record.source == EvidenceKind.MANUAL for record in evidence_records
    ):
        raise InvalidObservationError(
            "manual strategy changes require StrategySelectionSnapshotCorrected"
        )


def _merge_snapshot_observation(
    current: StrategySelectionSnapshot | None,
    incoming: StrategySelectionSnapshot,
    event_evidence: EvidenceRecord,
) -> StrategySelectionSnapshot:
    if current is None:
        return _rebuild_snapshot(
            incoming,
            frozen=False,
            evidence=(*incoming.evidence, event_evidence),
        )

    if current.session_id != incoming.session_id or current.ruleset_id != incoming.ruleset_id:
        raise InvalidObservationError("incoming snapshot does not match the current snapshot")

    expected_participant_count = current.expected_participant_count
    if incoming.expected_participant_count is not None:
        if (
            expected_participant_count is not None
            and incoming.expected_participant_count != expected_participant_count
        ):
            raise InvalidObservationError(
                "ordinary observation cannot replace expected_participant_count"
            )
        expected_participant_count = incoming.expected_participant_count

    participants = list(current.participants)
    indices = {
        participant.session_player_id: index for index, participant in enumerate(participants)
    }
    for incoming_participant in incoming.participants:
        index = indices.get(incoming_participant.session_player_id)
        if index is None:
            if current.frozen:
                raise InvalidObservationError(
                    "ordinary observation cannot add a participant to a frozen snapshot"
                )
            indices[incoming_participant.session_player_id] = len(participants)
            participants.append(incoming_participant)
            continue
        existing = participants[index]
        if existing.selection_row != incoming_participant.selection_row:
            raise InvalidObservationError(
                "ordinary observation cannot change a participant selection_row"
            )
        participants[index] = _merge_participant_fields(
            existing,
            incoming_participant,
            frozen=current.frozen,
        )

    try:
        return _rebuild_snapshot(
            current,
            expected_participant_count=expected_participant_count,
            participants=tuple(participants),
            captured_at=max(current.captured_at, incoming.captured_at),
            evidence=(*current.evidence, *incoming.evidence, event_evidence),
        )
    except ValidationError as exc:
        raise InvalidObservationError("snapshot observation violates domain invariants") from exc


def _merge_participant_fields(
    current: StrategySelectionParticipant,
    incoming: StrategySelectionParticipant,
    *,
    frozen: bool,
) -> StrategySelectionParticipant:
    updates: dict[str, Any] = {}
    field_evidence = dict(current.field_evidence)

    for field_name, attribute in _PARTICIPANT_ATTRIBUTES.items():
        incoming_value = getattr(incoming, attribute)
        if not _participant_field_value_is_known(field_name, incoming_value):
            continue
        incoming_evidence = incoming.field_evidence[field_name]
        current_value = getattr(current, attribute)
        current_evidence = current.field_evidence.get(field_name)

        if not _participant_field_value_is_known(field_name, current_value):
            updates[attribute] = incoming_value
            field_evidence[field_name] = incoming_evidence
            continue

        if current_value == incoming_value:
            if current_evidence is None or _evidence_is_stronger(
                incoming_evidence, current_evidence
            ):
                field_evidence[field_name] = incoming_evidence
            continue

        if frozen and field_name == ParticipantField.STRATEGY:
            raise InvalidObservationError(
                "ordinary observation cannot replace a frozen participant strategy"
            )
        if current_evidence is None or _evidence_is_stronger(
            incoming_evidence, current_evidence
        ):
            updates[attribute] = incoming_value
            field_evidence[field_name] = incoming_evidence

    payload = current.model_dump()
    payload.update(updates)
    payload["field_evidence"] = field_evidence
    return StrategySelectionParticipant.model_validate(payload)


def _participant_field_value_is_known(field_name: ParticipantField, value: object) -> bool:
    if field_name == ParticipantField.SELECTION_OUTCOME:
        return value != SelectionOutcome.UNKNOWN
    return value is not None


def _evidence_is_stronger(incoming: EvidenceRecord, current: EvidenceRecord) -> bool:
    incoming_priority = _EVIDENCE_PRIORITY[incoming.source]
    current_priority = _EVIDENCE_PRIORITY[current.source]
    if incoming_priority != current_priority:
        return incoming_priority > current_priority
    if incoming.confidence != current.confidence:
        return incoming.confidence > current.confidence
    return incoming.observed_at > current.observed_at


def _apply_manual_correction(
    snapshot: StrategySelectionSnapshot,
    replacements: list[StrategySelectionParticipant],
    event_evidence: EvidenceRecord,
) -> StrategySelectionSnapshot:
    replacement_ids = [replacement.session_player_id for replacement in replacements]
    if len(replacement_ids) != len(set(replacement_ids)):
        raise InvalidObservationError("manual correction participant IDs must be unique")

    participants = list(snapshot.participants)
    indices = {
        participant.session_player_id: index
        for index, participant in enumerate(participants)
    }
    try:
        for replacement in replacements:
            index = indices.get(replacement.session_player_id)
            if index is None:
                raise InvalidObservationError(
                    "manual correction cannot create a new strategy selection participant"
                )
            participants[index] = _merge_manual_correction_fields(
                participants[index],
                replacement,
            )
        return _rebuild_snapshot(
            snapshot,
            participants=tuple(participants),
            captured_at=event_evidence.observed_at,
            evidence=(*snapshot.evidence, event_evidence),
        )
    except ValidationError as exc:
        raise InvalidObservationError("manual correction violates snapshot invariants") from exc


def _merge_manual_correction_fields(
    current: StrategySelectionParticipant,
    replacement: StrategySelectionParticipant,
) -> StrategySelectionParticipant:
    if current.selection_row != replacement.selection_row:
        raise InvalidObservationError("manual correction cannot change selection_row")

    updates: dict[str, Any] = {}
    field_evidence = dict(current.field_evidence)
    for field_name, attribute in _PARTICIPANT_ATTRIBUTES.items():
        current_value = getattr(current, attribute)
        replacement_value = getattr(replacement, attribute)
        replacement_evidence = replacement.field_evidence.get(field_name)

        if current_value != replacement_value:
            if (
                replacement_evidence is None
                or replacement_evidence.source != EvidenceKind.MANUAL
            ):
                raise InvalidObservationError(
                    f"corrected field {field_name.value} requires manual evidence"
                )
            updates[attribute] = replacement_value
            field_evidence[field_name] = replacement_evidence
            continue

        current_evidence = current.field_evidence.get(field_name)
        if replacement_evidence is not None and (
            current_evidence is None
            or _evidence_is_stronger(replacement_evidence, current_evidence)
        ):
            field_evidence[field_name] = replacement_evidence

    payload = current.model_dump()
    payload.update(updates)
    payload["field_evidence"] = field_evidence
    return StrategySelectionParticipant.model_validate(payload)


def _rebuild_snapshot(
    snapshot: StrategySelectionSnapshot,
    *,
    expected_participant_count: int | None = None,
    participants: tuple[StrategySelectionParticipant, ...] | None = None,
    captured_at: datetime | None = None,
    frozen: bool | None = None,
    evidence: tuple[EvidenceRecord, ...] | None = None,
) -> StrategySelectionSnapshot:
    return StrategySelectionSnapshot(
        session_id=snapshot.session_id,
        ruleset_id=snapshot.ruleset_id,
        expected_participant_count=(
            expected_participant_count
            if expected_participant_count is not None
            else snapshot.expected_participant_count
        ),
        captured_at=captured_at if captured_at is not None else snapshot.captured_at,
        participants=participants if participants is not None else snapshot.participants,
        frozen=frozen if frozen is not None else snapshot.frozen,
        evidence=evidence if evidence is not None else snapshot.evidence,
    )
