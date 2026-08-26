"""Caller-owned per-frame composition for one strategy-selection session.

This module has no matcher, lifecycle, domain, or runtime authority.  A caller
supplies same-frame strategy observations from the existing matcher plus an
explicit confirmation render context.  The mandatory order is confirmation
debounce first, then confirmed-period strategy accumulation.
"""

from __future__ import annotations

from dataclasses import dataclass

from sentry_copilot.capture.frame_source import Frame
from sentry_copilot.vision.confirmed_selection_strategies import (
    ConfirmedSelectionStrategyAccumulator,
    ConfirmedSelectionStrategyFinalization,
)
from sentry_copilot.vision.strategy_selection_confirmation import (
    SelectionConfirmationRenderContext,
    SelectionRowConfirmationTracker,
    observe_jp_mumu_selection_row_confirmations,
)
from sentry_copilot.vision.strategy_selection_observations import (
    StrategySelectionCandidateObservation,
)
from sentry_copilot.vision.viewport import ContentViewport


@dataclass(frozen=True)
class SelectionSessionStrategyCollectorState:
    """Immutable composition state owned by one caller-created selection session.

    A fresh instance is required for a new selection session.  The caller owns
    lifecycle boundaries and must provide candidates produced from the same
    ``Frame`` supplied to :meth:`apply_frame`; the existing candidate type does
    not carry a frame ID that this layer can compare.
    """

    confirmation_tracker: SelectionRowConfirmationTracker = SelectionRowConfirmationTracker()
    strategy_accumulator: ConfirmedSelectionStrategyAccumulator = (
        ConfirmedSelectionStrategyAccumulator()
    )

    def apply_frame(
        self,
        frame: Frame,
        viewport: ContentViewport,
        render_context: SelectionConfirmationRenderContext,
        strategy_observations: tuple[StrategySelectionCandidateObservation, ...],
    ) -> SelectionSessionStrategyCollectorState:
        """Apply one frame in mandatory confirmation-before-strategy order.

        The confirmation observer handles non-selection and wrong-layout frames
        as unresolved.  The sticky tracker preserves prior locks, and an empty
        or unresolved strategy tuple cannot erase accumulated evidence.
        """

        confirmation_observations = observe_jp_mumu_selection_row_confirmations(
            frame, viewport, render_context
        )
        updated_tracker = self.confirmation_tracker.apply(confirmation_observations)
        updated_accumulator = self.strategy_accumulator.apply(
            frame,
            updated_tracker.locked_confirmed_rows,
            strategy_observations,
        )
        return SelectionSessionStrategyCollectorState(
            confirmation_tracker=updated_tracker,
            strategy_accumulator=updated_accumulator,
        )

    def finalize(self) -> tuple[ConfirmedSelectionStrategyFinalization, ...]:
        """Delegate deterministic finalization; the caller decides when to invoke it."""

        return self.strategy_accumulator.finalize()
