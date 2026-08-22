"""Candidate-only completeness checks for strategy-selection vision rows."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sentry_copilot.vision.strategy_selection_observations import (
    StrategySelectionCandidateObservation,
)
from sentry_copilot.vision.strategy_selection_probe import StrategySelectionProbeStatus


@dataclass(frozen=True)
class StrategySelectionCandidatePrecheck:
    """Immutable candidate summary, not an authoritative snapshot."""

    total_rows: int
    selection_rows: tuple[int, ...]
    duplicate_selection_rows: tuple[int, ...]
    missing_selection_rows: tuple[int, ...]
    has_selection_row_conflict: bool
    matched_strategy_count: int
    matched_strategy_ids: tuple[str, ...]
    unresolved_rows: tuple[int, ...]
    no_strategy_candidate_rows: tuple[int, ...]
    duplicate_strategy_ids: tuple[str, ...]
    duplicate_rows: tuple[tuple[str, tuple[int, ...]], ...]
    has_duplicate_strategy_conflict: bool
    strategy_set_complete: bool


def precheck_strategy_selection_candidates(
    observations: tuple[StrategySelectionCandidateObservation, ...],
) -> StrategySelectionCandidatePrecheck:
    """Summarize candidates without inferring identity or mutating input."""
    claims: dict[str, list[int]] = defaultdict(list)
    unresolved: list[int] = []
    no_candidate: list[int] = []
    for observation in observations:
        if observation.strategy_id is not None:
            claims[observation.strategy_id].append(observation.selection_row)
        elif observation.vision_status is (
            StrategySelectionProbeStatus.NO_STRATEGY_PORTRAIT_CANDIDATE
        ):
            no_candidate.append(observation.selection_row)
        else:
            unresolved.append(observation.selection_row)
    duplicate_items = tuple(
        (strategy_id, tuple(rows)) for strategy_id, rows in sorted(claims.items()) if len(rows) > 1
    )
    selection_rows = tuple(observation.selection_row for observation in observations)
    row_counts: dict[int, int] = defaultdict(int)
    for row in selection_rows:
        row_counts[row] += 1
    duplicate_selection_rows = tuple(sorted(row for row, count in row_counts.items() if count > 1))
    expected_rows = {1, 2, 3, 4}
    missing_selection_rows = tuple(sorted(expected_rows - set(selection_rows)))
    matched_ids = tuple(
        observation.strategy_id
        for observation in observations
        if observation.strategy_id is not None
    )
    complete = (
        len(observations) == 4
        and set(selection_rows) == expected_rows
        and not duplicate_selection_rows
        and len(matched_ids) == 4
        and len(set(matched_ids)) == 4
        and not unresolved
        and not no_candidate
    )
    return StrategySelectionCandidatePrecheck(
        total_rows=len(observations),
        selection_rows=selection_rows,
        duplicate_selection_rows=duplicate_selection_rows,
        missing_selection_rows=missing_selection_rows,
        has_selection_row_conflict=bool(duplicate_selection_rows or missing_selection_rows),
        matched_strategy_count=len(matched_ids),
        matched_strategy_ids=matched_ids,
        unresolved_rows=tuple(unresolved),
        no_strategy_candidate_rows=tuple(no_candidate),
        duplicate_strategy_ids=tuple(strategy_id for strategy_id, _ in duplicate_items),
        duplicate_rows=duplicate_items,
        has_duplicate_strategy_conflict=bool(duplicate_items),
        strategy_set_complete=complete,
    )
