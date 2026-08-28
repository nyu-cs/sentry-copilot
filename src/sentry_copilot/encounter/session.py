"""Pure encounter-session updates from normalized OPERATION difficulty observations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sentry_copilot.vision.operation_difficulty import (
    OperationDifficultyObservation,
    OperationDifficultyState,
)

from .catalog import EncounterMapCatalog
from .models import (
    CapturedDifficulty,
    DifficultyCaptureConflict,
    EncounterSession,
)


class EncounterUpdateStatus(StrEnum):
    CAPTURED = "captured"
    ENRICHED = "enriched"
    PRESERVED = "preserved"
    CONFLICT = "conflict"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class EncounterSessionUpdate:
    session: EncounterSession
    status: EncounterUpdateStatus


def apply_operation_difficulty_observation(
    session: EncounterSession,
    observation: OperationDifficultyObservation,
    catalog: EncounterMapCatalog,
) -> EncounterSessionUpdate:
    """Capture one difficulty fact or preserve prior facts without weak-frame erasure."""

    if (
        observation.state is not OperationDifficultyState.OBSERVED
        or observation.simulation_code is None
        or observation.difficulty_id is None
    ):
        return EncounterSessionUpdate(session, EncounterUpdateStatus.UNRESOLVED)
    definition = catalog.difficulty_by_simulation_code(observation.simulation_code)
    if definition is None or definition.difficulty_id != observation.difficulty_id:
        return EncounterSessionUpdate(session, EncounterUpdateStatus.UNRESOLVED)
    if session.captured_difficulty is None:
        captured = CapturedDifficulty(
            difficulty_id=definition.difficulty_id,
            simulation_code=observation.simulation_code,
            observed_label=observation.observed_difficulty,
        )
        return EncounterSessionUpdate(
            session.model_copy(update={"captured_difficulty": captured}),
            EncounterUpdateStatus.CAPTURED,
        )
    existing = session.captured_difficulty
    if existing.difficulty_id == definition.difficulty_id:
        return EncounterSessionUpdate(session, EncounterUpdateStatus.PRESERVED)
    difficulty_conflict = DifficultyCaptureConflict(
        existing_difficulty_id=existing.difficulty_id,
        conflicting_difficulty_id=definition.difficulty_id,
    )
    return EncounterSessionUpdate(
        session.model_copy(update={"difficulty_conflict": difficulty_conflict}),
        EncounterUpdateStatus.CONFLICT,
    )
