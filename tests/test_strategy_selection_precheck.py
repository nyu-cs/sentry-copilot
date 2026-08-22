from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from sentry_copilot.domain.enums import EvidenceKind
from sentry_copilot.vision.local_feature_matching import LocalFeatureVisualMatchResult
from sentry_copilot.vision.strategy_selection_observations import (
    StrategySelectionCandidateObservation,
)
from sentry_copilot.vision.strategy_selection_precheck import precheck_strategy_selection_candidates
from sentry_copilot.vision.strategy_selection_probe import StrategySelectionProbeStatus


def _observation(
    row: int, status: StrategySelectionProbeStatus, strategy: str | None
) -> StrategySelectionCandidateObservation:
    selected = SimpleNamespace(identity_id=strategy) if strategy else None
    matcher = cast(LocalFeatureVisualMatchResult, SimpleNamespace(selected_identity=selected))
    return StrategySelectionCandidateObservation(
        row, strategy, status, EvidenceKind.OBSERVED, "synthetic", matcher
    )


def test_four_unique_rows_are_complete() -> None:
    observations = tuple(
        _observation(i, StrategySelectionProbeStatus.MATCHED_STRATEGY, f"strategy.synthetic.{i}")
        for i in range(1, 5)
    )
    result = precheck_strategy_selection_candidates(observations)
    assert result.strategy_set_complete
    assert result.matched_strategy_count == 4


def test_unresolved_and_no_candidate_are_distinct_incomplete() -> None:
    observations = (
        _observation(1, StrategySelectionProbeStatus.MATCHED_STRATEGY, "strategy.synthetic.a"),
        _observation(2, StrategySelectionProbeStatus.UNRESOLVED_STRATEGY, None),
        _observation(3, StrategySelectionProbeStatus.NO_STRATEGY_PORTRAIT_CANDIDATE, None),
    )
    result = precheck_strategy_selection_candidates(observations)
    assert result.unresolved_rows == (2,)
    assert result.no_strategy_candidate_rows == (3,)
    assert not result.strategy_set_complete


def test_duplicate_claims_are_preserved_as_conflict() -> None:
    names = ("a", "a", "b", "c")
    observations = tuple(
        _observation(i, StrategySelectionProbeStatus.MATCHED_STRATEGY, f"strategy.synthetic.{name}")
        for i, name in enumerate(names, 1)
    )
    result = precheck_strategy_selection_candidates(observations)
    assert result.duplicate_strategy_ids == ("strategy.synthetic.a",)
    assert result.duplicate_rows == (("strategy.synthetic.a", (1, 2)),)
    assert not result.strategy_set_complete
    assert observations[0].strategy_id == "strategy.synthetic.a"


def test_fewer_than_four_rows_are_incomplete() -> None:
    observations = (
        _observation(1, StrategySelectionProbeStatus.MATCHED_STRATEGY, "strategy.synthetic.a"),
    )
    result = precheck_strategy_selection_candidates(observations)
    assert result.total_rows == 1
    assert not result.strategy_set_complete


def test_duplicate_selection_row_is_incomplete() -> None:
    observations = tuple(
        _observation(
            row,
            StrategySelectionProbeStatus.MATCHED_STRATEGY,
            f"strategy.synthetic.{i}",
        )
        for i, row in enumerate((1, 1, 2, 3), 1)
    )
    result = precheck_strategy_selection_candidates(observations)
    assert result.selection_rows == (1, 1, 2, 3)
    assert result.duplicate_selection_rows == (1,)
    assert result.missing_selection_rows == (4,)
    assert result.has_selection_row_conflict
    assert not result.strategy_set_complete


def test_missing_expected_row_is_incomplete() -> None:
    observations = tuple(
        _observation(
            row,
            StrategySelectionProbeStatus.MATCHED_STRATEGY,
            f"strategy.synthetic.{i}",
        )
        for i, row in enumerate((1, 2, 4), 1)
    )
    result = precheck_strategy_selection_candidates(observations)
    assert result.missing_selection_rows == (3,)
    assert not result.strategy_set_complete
