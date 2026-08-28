"""Pure encounter-session updates from normalized map observations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sentry_copilot.vision.operation_map import OperationMapObservation, OperationMapState

from .catalog import EncounterMapCatalog
from .models import (
    CapturedMap,
    DifficultyCaptureConflict,
    EncounterSession,
    MapCaptureConflict,
)


class MapCaptureUpdateStatus(StrEnum):
    CAPTURED = "captured"
    ENRICHED = "enriched"
    PRESERVED = "preserved"
    CONFLICT = "conflict"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class EncounterSessionUpdate:
    session: EncounterSession
    status: MapCaptureUpdateStatus


def apply_operation_map_observation(
    session: EncounterSession,
    observation: OperationMapObservation,
    catalog: EncounterMapCatalog,
) -> EncounterSessionUpdate:
    """Capture one static map fact or preserve prior facts without weak-frame erasure."""

    if observation.state is not OperationMapState.OBSERVED or observation.map_code is None:
        return EncounterSessionUpdate(session, MapCaptureUpdateStatus.UNRESOLVED)
    definition = catalog.by_code(observation.map_code)
    if definition is None:
        return EncounterSessionUpdate(session, MapCaptureUpdateStatus.UNRESOLVED)
    difficulty_id, observed_difficulty = _validated_difficulty(
        observation,
        definition.allowed_difficulty_ids,
        catalog,
    )
    if session.captured_map is None:
        captured = CapturedMap(
            map_id=definition.map_id,
            map_code=definition.map_code,
            difficulty_id=difficulty_id,
            observed_difficulty=observed_difficulty,
        )
        return EncounterSessionUpdate(
            session.model_copy(update={"captured_map": captured}), MapCaptureUpdateStatus.CAPTURED
        )
    existing = session.captured_map
    if existing.map_id == definition.map_id:
        if existing.difficulty_id is None and difficulty_id is not None:
            enriched = existing.model_copy(
                update={
                    "difficulty_id": difficulty_id,
                    "observed_difficulty": observed_difficulty,
                }
            )
            return EncounterSessionUpdate(
                session.model_copy(update={"captured_map": enriched}),
                MapCaptureUpdateStatus.ENRICHED,
            )
        if (
            existing.difficulty_id is not None
            and difficulty_id is not None
            and existing.difficulty_id != difficulty_id
        ):
            difficulty_conflict = DifficultyCaptureConflict(
                map_id=existing.map_id,
                existing_difficulty_id=existing.difficulty_id,
                conflicting_difficulty_id=difficulty_id,
            )
            return EncounterSessionUpdate(
                session.model_copy(update={"difficulty_conflict": difficulty_conflict}),
                MapCaptureUpdateStatus.CONFLICT,
            )
        return EncounterSessionUpdate(session, MapCaptureUpdateStatus.PRESERVED)
    conflict = MapCaptureConflict(
        existing_map_id=session.captured_map.map_id,
        conflicting_map_code=definition.map_code,
    )
    return EncounterSessionUpdate(
        session.model_copy(update={"map_conflict": conflict}), MapCaptureUpdateStatus.CONFLICT
    )


def _validated_difficulty(
    observation: OperationMapObservation,
    allowed_difficulty_ids: tuple[str, ...],
    catalog: EncounterMapCatalog,
) -> tuple[str | None, str | None]:
    """Keep a difficulty only when its normalized ID is catalog-known and map-allowed."""

    difficulty_id = observation.difficulty_id
    if difficulty_id is None or catalog.difficulty_by_id(difficulty_id) is None:
        return None, None
    if allowed_difficulty_ids and difficulty_id not in allowed_difficulty_ids:
        return None, None
    return difficulty_id, observation.observed_difficulty
