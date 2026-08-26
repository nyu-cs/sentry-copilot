"""Caller-owned accumulation of strategy evidence after visual row confirmation.

The selection matcher remains responsible for resolving a strategy candidate and
M0.7a2a remains responsible for sticky row confirmation.  This module only
joins those already established facts.  It stores no player identity, domain
state, battle-entry claim, or runtime-slot assertion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.vision.strategy_selection_observations import (
    StrategySelectionCandidateObservation,
)
from sentry_copilot.vision.strategy_selection_probe import StrategySelectionProbeStatus
from sentry_copilot.vision.visual_references import VisualMatchStatus

_ROWS = (1, 2, 3, 4)


class ConfirmedSelectionStrategyState(StrEnum):
    """Caller-driven end-of-selection result for one visual selection row."""

    NOT_CONFIRMED = "not_confirmed"
    CONFIRMED_IDENTIFIED = "confirmed_identified"
    CONFIRMED_BUT_UNRESOLVED = "confirmed_but_unresolved"
    CONFIRMED_STRATEGY_CONFLICT = "confirmed_strategy_conflict"


@dataclass(frozen=True)
class ConfirmedSelectionStrategyEvidence:
    """One eligible strategy result observed after its row was sticky-confirmed."""

    selection_row: int
    strategy_id: str
    strategy_observation: StrategySelectionCandidateObservation
    frame_id: str
    frame_index: int
    processed_at: datetime
    source_timestamp: timedelta | None
    source_type: FrameSourceType
    source_id: str
    source_reference: str

    def __post_init__(self) -> None:
        if self.selection_row not in _ROWS:
            raise ValueError("confirmed strategy evidence row must be between 1 and 4")
        if not self.strategy_id.strip():
            raise ValueError("confirmed strategy evidence strategy_id must not be blank")
        if self.strategy_observation.selection_row != self.selection_row:
            raise ValueError("confirmed strategy evidence row must match its observation")
        if self.strategy_observation.strategy_id != self.strategy_id:
            raise ValueError("confirmed strategy evidence strategy_id must match its observation")
        if not (
            self.frame_id.strip()
            and self.source_id.strip()
            and self.source_reference.strip()
        ):
            raise ValueError("confirmed strategy evidence provenance text fields must not be blank")
        if self.frame_index < 0:
            raise ValueError("confirmed strategy evidence frame index must be non-negative")
        if self.processed_at.tzinfo is None or self.processed_at.utcoffset() is None:
            raise ValueError("confirmed strategy evidence processing time must be timezone-aware")
        if self.source_timestamp is not None and self.source_timestamp.total_seconds() < 0:
            raise ValueError("confirmed strategy evidence source timestamp must be non-negative")


@dataclass(frozen=True)
class ConfirmedSelectionStrategyFinalization:
    """Immutable finalized view for one row; conflict evidence is retained, never ranked."""

    selection_row: int
    state: ConfirmedSelectionStrategyState
    strategy_ids: tuple[str, ...]
    evidence: tuple[ConfirmedSelectionStrategyEvidence, ...]

    def __post_init__(self) -> None:
        if self.selection_row not in _ROWS:
            raise ValueError("finalized selection row must be between 1 and 4")
        if self.strategy_ids != tuple(sorted(set(self.strategy_ids))):
            raise ValueError("finalized strategy IDs must be unique and sorted")
        if any(not strategy_id.strip() for strategy_id in self.strategy_ids):
            raise ValueError("finalized strategy IDs must not be blank")
        if any(item.selection_row != self.selection_row for item in self.evidence):
            raise ValueError("finalized evidence must belong to its selection row")
        if self.state is ConfirmedSelectionStrategyState.NOT_CONFIRMED:
            if self.strategy_ids or self.evidence:
                raise ValueError("unconfirmed row must not expose confirmed strategy evidence")
        elif self.state is ConfirmedSelectionStrategyState.CONFIRMED_BUT_UNRESOLVED:
            if self.strategy_ids or self.evidence:
                raise ValueError("unresolved confirmed row must not expose strategy evidence")
        elif self.state is ConfirmedSelectionStrategyState.CONFIRMED_IDENTIFIED:
            if len(self.strategy_ids) != 1 or not self.evidence:
                raise ValueError(
                    "identified confirmed row requires exactly one strategy and evidence"
                )
        elif len(self.strategy_ids) < 2 or not self.evidence:
            raise ValueError(
                "confirmed strategy conflict requires distinct strategies and evidence"
            )

    @property
    def strategy_id(self) -> str | None:
        """Return the sole resolved strategy, never choose one from a conflict."""

        return (
            self.strategy_ids[0]
            if self.state is ConfirmedSelectionStrategyState.CONFIRMED_IDENTIFIED
            else None
        )


@dataclass(frozen=True)
class ConfirmedSelectionStrategyAccumulator:
    """Immutable one-selection-session accumulation, finalized only by an explicit caller query."""

    locked_confirmed_rows: frozenset[int] = frozenset()
    evidence: tuple[ConfirmedSelectionStrategyEvidence, ...] = ()

    def __post_init__(self) -> None:
        if not self.locked_confirmed_rows.issubset(_ROWS):
            raise ValueError("locked confirmed rows must be between 1 and 4")
        if any(item.selection_row not in self.locked_confirmed_rows for item in self.evidence):
            raise ValueError("confirmed strategy evidence requires a locked confirmation row")
        if any(not _is_reliably_resolved(item.strategy_observation) for item in self.evidence):
            raise ValueError("confirmed strategy evidence requires a reliable resolved observation")

    def apply(
        self,
        frame: Frame,
        locked_confirmed_rows: frozenset[int],
        observations: tuple[StrategySelectionCandidateObservation, ...],
    ) -> ConfirmedSelectionStrategyAccumulator:
        """Accumulate only reliable same-frame strategy results after sticky row confirmation.

        ``locked_confirmed_rows`` is expected from the *updated* M0.7a2a tracker,
        so the frame that locks a row may supply eligible evidence.  Missing or
        unresolved later observations preserve existing history.
        """

        if not locked_confirmed_rows.issubset(_ROWS):
            raise ValueError("locked confirmed rows must be between 1 and 4")
        _validate_unique_rows(observations)
        effective_locked_rows = frozenset(self.locked_confirmed_rows | locked_confirmed_rows)
        additions = tuple(
            _evidence_from(frame, item)
            for item in observations
            if item.selection_row in effective_locked_rows and _is_reliably_resolved(item)
        )
        return ConfirmedSelectionStrategyAccumulator(
            locked_confirmed_rows=effective_locked_rows,
            evidence=self.evidence + additions,
        )

    def finalize(self) -> tuple[ConfirmedSelectionStrategyFinalization, ...]:
        """Return a deterministic row view without mutating this accumulator."""

        return tuple(self.finalize_row(row) for row in _ROWS)

    def finalize_row(self, selection_row: int) -> ConfirmedSelectionStrategyFinalization:
        """Return one deterministic row result without choosing a conflict winner."""

        if selection_row not in _ROWS:
            raise ValueError("finalized selection row must be between 1 and 4")
        if selection_row not in self.locked_confirmed_rows:
            return ConfirmedSelectionStrategyFinalization(
                selection_row=selection_row,
                state=ConfirmedSelectionStrategyState.NOT_CONFIRMED,
                strategy_ids=(),
                evidence=(),
            )
        evidence = tuple(item for item in self.evidence if item.selection_row == selection_row)
        strategy_ids = tuple(sorted({item.strategy_id for item in evidence}))
        if not strategy_ids:
            state = ConfirmedSelectionStrategyState.CONFIRMED_BUT_UNRESOLVED
        elif len(strategy_ids) == 1:
            state = ConfirmedSelectionStrategyState.CONFIRMED_IDENTIFIED
        else:
            state = ConfirmedSelectionStrategyState.CONFIRMED_STRATEGY_CONFLICT
        return ConfirmedSelectionStrategyFinalization(
            selection_row=selection_row,
            state=state,
            strategy_ids=strategy_ids,
            evidence=evidence,
        )


def _is_reliably_resolved(observation: StrategySelectionCandidateObservation) -> bool:
    selected = observation.matcher_result.selected_identity
    return (
        observation.vision_status is StrategySelectionProbeStatus.MATCHED_STRATEGY
        and observation.strategy_id is not None
        and bool(observation.strategy_id.strip())
        and observation.matcher_result.status is VisualMatchStatus.MATCHED
        and selected is not None
        and selected.identity_id == observation.strategy_id
    )


def _evidence_from(
    frame: Frame,
    observation: StrategySelectionCandidateObservation,
) -> ConfirmedSelectionStrategyEvidence:
    strategy_id = observation.strategy_id
    if strategy_id is None:
        raise ValueError("reliably resolved strategy observation must have a strategy_id")
    return ConfirmedSelectionStrategyEvidence(
        selection_row=observation.selection_row,
        strategy_id=strategy_id,
        strategy_observation=observation,
        frame_id=frame.frame_id,
        frame_index=frame.frame_index,
        processed_at=frame.processed_at,
        source_timestamp=frame.source_timestamp,
        source_type=frame.source_type,
        source_id=frame.source_id,
        source_reference=frame.source_reference,
    )


def _validate_unique_rows(observations: tuple[StrategySelectionCandidateObservation, ...]) -> None:
    rows = tuple(item.selection_row for item in observations)
    if any(row not in _ROWS for row in rows):
        raise ValueError("strategy observations must have selection rows between 1 and 4")
    if len(rows) != len(set(rows)):
        raise ValueError("strategy observations must not repeat a selection row per frame")
