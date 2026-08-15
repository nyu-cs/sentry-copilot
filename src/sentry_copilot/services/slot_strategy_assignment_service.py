from __future__ import annotations

from sentry_copilot.catalogs.repository import CatalogLookupError, StrategyCatalogRepository
from sentry_copilot.domain.identifiers import RuntimeSlotId, StrategyId
from sentry_copilot.domain.models import SessionState
from sentry_copilot.domain.queries import (
    derive_current_slot_strategy_assignment_view,
)
from sentry_copilot.domain.slot_strategy_assignments import (
    SlotStrategyAssignment,
    SlotStrategyAssignmentView,
    UnresolvedSlotStrategyAssignment,
)
from sentry_copilot.domain.strategy_identification import derive_strategy_occupancy_view


class SlotStrategyAssignmentService:
    """Read-only catalog-aware derivation of current runtime slot assignments."""

    def __init__(self, catalog_repository: StrategyCatalogRepository) -> None:
        self._catalog_repository = catalog_repository

    def get_current_slot_assignment(
        self,
        state: SessionState,
        runtime_slot_id: RuntimeSlotId,
    ) -> SlotStrategyAssignment | None:
        return self.get_current_slot_assignment_view(state).for_slot(runtime_slot_id)

    def get_all_current_slot_assignments(
        self,
        state: SessionState,
    ) -> tuple[SlotStrategyAssignment, ...]:
        return self.get_current_slot_assignment_view(state).assignments

    def get_unresolved_slot_assignments(
        self,
        state: SessionState,
    ) -> tuple[UnresolvedSlotStrategyAssignment, ...]:
        return self.get_current_slot_assignment_view(state).unresolved

    def get_current_slot_assignment_view(
        self,
        state: SessionState,
    ) -> SlotStrategyAssignmentView:
        """Derive labels at read time; never cache or mutate assignment state."""

        stamp = state.ruleset_dependency_stamp
        catalog_available = False
        available_strategy_ids: frozenset[StrategyId] = frozenset()
        if stamp is not None:
            try:
                available_strategy_ids = self._catalog_repository.available_strategy_ids(
                    catalog_version=stamp.catalog_version,
                    ruleset_revision_id=stamp.ruleset_revision_id,
                )
                catalog_available = True
            except CatalogLookupError:
                pass
        occupancy_view = derive_strategy_occupancy_view(
            state.strategy_identifications,
            committed_participant_ids=frozenset(
                commitment.session_player_id
                for commitment in (
                    state.strategy_commitments.commitments
                    if state.strategy_commitments is not None
                    else ()
                )
            ),
            current_dependency_stamp=stamp,
            available_strategy_ids=available_strategy_ids,
        )
        return derive_current_slot_strategy_assignment_view(
            state,
            occupancy_view=occupancy_view,
            catalog_available=catalog_available,
        )
