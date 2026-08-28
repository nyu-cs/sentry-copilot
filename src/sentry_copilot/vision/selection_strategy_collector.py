"""Caller-owned per-frame composition for one strategy-selection session.

This module has no matcher, lifecycle, domain, or runtime authority.  A caller
supplies same-frame strategy observations from the existing matcher plus an
explicit confirmation render context.  When the caller also supplies the
fixed-layout participant-status and completion observations, the mandatory
order is sticky EXIT debounce, confirmation debounce, explicit completion
semantics, then confirmed-period strategy accumulation.
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
from sentry_copilot.vision.strategy_selection_participant_status import (
    SelectionCompletionPresentationObservation,
    SelectionExitCompletionState,
    SelectionExitCompletionTracker,
    SelectionParticipantStatusObservation,
    SelectionRowExitTracker,
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
    exit_tracker: SelectionRowExitTracker = SelectionRowExitTracker()
    exit_completion_tracker: SelectionExitCompletionTracker = SelectionExitCompletionTracker()

    def apply_frame(
        self,
        frame: Frame,
        viewport: ContentViewport,
        render_context: SelectionConfirmationRenderContext,
        strategy_observations: tuple[StrategySelectionCandidateObservation, ...],
        status_observations: tuple[SelectionParticipantStatusObservation, ...] | None = None,
        completion_observations: (
            tuple[SelectionCompletionPresentationObservation, ...] | None
        ) = None,
    ) -> SelectionSessionStrategyCollectorState:
        """Apply one frame in mandatory confirmation-before-strategy order.

        The confirmation observer handles non-selection and wrong-layout frames
        as unresolved.  The sticky tracker preserves prior locks, and an empty
        or unresolved strategy tuple cannot erase accumulated evidence.
        """

        confirmation_observations = observe_jp_mumu_selection_row_confirmations(
            frame, viewport, render_context
        )
        if (status_observations is None) != (completion_observations is None):
            raise ValueError(
                "selection status and completion observations must be supplied together"
            )
        if status_observations is None:
            updated_exit_tracker = self.exit_tracker
            updated_tracker = self.confirmation_tracker.apply(confirmation_observations)
            updated_exit_completion_tracker = self.exit_completion_tracker
        else:
            assert completion_observations is not None
            if any(not _observation_matches_frame(item, frame) for item in status_observations):
                raise ValueError("selection status observations must belong to the supplied frame")
            if any(
                not _observation_matches_frame(item, frame) for item in completion_observations
            ):
                raise ValueError(
                    "selection completion observations must belong to the supplied frame"
                )
            updated_exit_tracker = self.exit_tracker.apply(status_observations)
            updated_tracker = self.confirmation_tracker.apply(
                confirmation_observations,
                terminal_rows=updated_exit_tracker.locked_exit_rows,
            )
            updated_exit_completion_tracker = self.exit_completion_tracker.apply(
                updated_exit_tracker,
                completion_observations,
                updated_tracker.locked_confirmed_rows,
            )
        updated_accumulator = self.strategy_accumulator.apply(
            frame,
            updated_tracker.locked_confirmed_rows,
            tuple(
                item
                for item in strategy_observations
                if item.selection_row not in updated_exit_tracker.locked_exit_rows
            ),
        )
        return SelectionSessionStrategyCollectorState(
            confirmation_tracker=updated_tracker,
            strategy_accumulator=updated_accumulator,
            exit_tracker=updated_exit_tracker,
            exit_completion_tracker=updated_exit_completion_tracker,
        )

    def finalize(self) -> tuple[ConfirmedSelectionStrategyFinalization, ...]:
        """Delegate deterministic finalization; the caller decides when to invoke it."""

        return self.strategy_accumulator.finalize()

    def exit_completion_state(self, selection_row: int) -> SelectionExitCompletionState:
        """Return the sticky visual completion state for one selection row.

        This is presentation evidence only.  In particular, it never turns a
        portrait into a concrete strategy identity.
        """

        return self.exit_completion_tracker.state_for(selection_row)


def _observation_matches_frame(
    observation: SelectionParticipantStatusObservation | SelectionCompletionPresentationObservation,
    frame: Frame,
) -> bool:
    return (
        observation.frame_id == frame.frame_id
        and observation.frame_index == frame.frame_index
        and observation.source_id == frame.source_id
        and observation.source_reference == frame.source_reference
    )
