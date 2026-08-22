from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

from sentry_copilot.domain.enums import EvidenceKind
from sentry_copilot.vision.local_feature_matching import LocalFeatureVisualMatchResult
from sentry_copilot.vision.strategy_selection_observations import (
    STRATEGY_SELECTION_VISION_PROBE_SOURCE,
    adapt_strategy_selection_probe,
)
from sentry_copilot.vision.strategy_selection_probe import (
    JP_MUMU_1920X1080_PROFILE_ID,
    StrategySelectionProbeResult,
    StrategySelectionProbeStatus,
    StrategySelectionRowObservation,
)
from sentry_copilot.vision.viewport import PixelRoi


def _row(
    row: int, status: StrategySelectionProbeStatus, strategy_id: str | None
) -> StrategySelectionRowObservation:
    selected = SimpleNamespace(identity_id=strategy_id) if strategy_id is not None else None
    matcher = cast(LocalFeatureVisualMatchResult, SimpleNamespace(selected_identity=selected))
    return StrategySelectionRowObservation(
        row, PixelRoi(0, row, 4, 4), PixelRoi(0, row, 2, 2), status, matcher
    )


def _result(*rows: StrategySelectionRowObservation) -> StrategySelectionProbeResult:
    return StrategySelectionProbeResult(
        Path("synthetic.png"), 1920, 1080, JP_MUMU_1920X1080_PROFILE_ID, rows
    )


def test_adapter_preserves_order_ids_and_provenance() -> None:
    candidates = adapt_strategy_selection_probe(
        _result(
            _row(1, StrategySelectionProbeStatus.MATCHED_STRATEGY, "strategy.synthetic.a"),
            _row(2, StrategySelectionProbeStatus.MATCHED_STRATEGY, "strategy.synthetic.b"),
            _row(3, StrategySelectionProbeStatus.MATCHED_STRATEGY, "strategy.synthetic.c"),
            _row(4, StrategySelectionProbeStatus.MATCHED_STRATEGY, "strategy.synthetic.d"),
        )
    )
    assert [(item.selection_row, item.strategy_id) for item in candidates] == [
        (1, "strategy.synthetic.a"),
        (2, "strategy.synthetic.b"),
        (3, "strategy.synthetic.c"),
        (4, "strategy.synthetic.d"),
    ]
    assert all(item.provenance is EvidenceKind.OBSERVED for item in candidates)
    assert all(item.source == STRATEGY_SELECTION_VISION_PROBE_SOURCE for item in candidates)


def test_unresolved_and_no_candidate_have_no_strategy_id() -> None:
    candidates = adapt_strategy_selection_probe(
        _result(
            _row(1, StrategySelectionProbeStatus.UNRESOLVED_STRATEGY, "strategy.synthetic.fake"),
            _row(2, StrategySelectionProbeStatus.NO_STRATEGY_PORTRAIT_CANDIDATE, None),
        )
    )
    assert [item.strategy_id for item in candidates] == [None, None]
    assert not any(
        hasattr(item, field)
        for item in candidates
        for field in ("player_tag", "display_name", "exited", "runtime_slot")
    )


def test_duplicate_strategy_claims_are_preserved() -> None:
    candidates = adapt_strategy_selection_probe(
        _result(
            _row(1, StrategySelectionProbeStatus.MATCHED_STRATEGY, "strategy.synthetic.same"),
            _row(2, StrategySelectionProbeStatus.MATCHED_STRATEGY, "strategy.synthetic.same"),
        )
    )
    assert [item.strategy_id for item in candidates] == [
        "strategy.synthetic.same",
        "strategy.synthetic.same",
    ]
