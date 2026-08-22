"""Translate vision-only strategy rows into identity-free domain candidates."""

from __future__ import annotations

from dataclasses import dataclass

from sentry_copilot.domain.enums import EvidenceKind
from sentry_copilot.vision.local_feature_matching import LocalFeatureVisualMatchResult
from sentry_copilot.vision.strategy_selection_probe import (
    StrategySelectionProbeResult,
    StrategySelectionProbeStatus,
)

STRATEGY_SELECTION_VISION_PROBE_SOURCE = "strategy-selection-vision-probe"


@dataclass(frozen=True)
class StrategySelectionCandidateObservation:
    """One row candidate with no invented player or session identity."""

    selection_row: int
    strategy_id: str | None
    vision_status: StrategySelectionProbeStatus
    provenance: EvidenceKind
    source: str
    matcher_result: LocalFeatureVisualMatchResult


def adapt_strategy_selection_probe(
    result: StrategySelectionProbeResult,
) -> tuple[StrategySelectionCandidateObservation, ...]:
    """Preserve every row observation, including unresolved and duplicate claims."""

    return tuple(
        StrategySelectionCandidateObservation(
            selection_row=row.selection_row,
            strategy_id=row.strategy_id
            if row.status is StrategySelectionProbeStatus.MATCHED_STRATEGY
            else None,
            vision_status=row.status,
            provenance=EvidenceKind.OBSERVED,
            source=STRATEGY_SELECTION_VISION_PROBE_SOURCE,
            matcher_result=row.matcher_result,
        )
        for row in result.rows
    )
