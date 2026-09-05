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
    BossCaptureConflict,
    BossCaptureSource,
    CapturedDifficulty,
    DifficultyCaptureConflict,
    DifficultyCaptureSource,
    EncounterSession,
    EnemyTypeCaptureConflict,
    EnemyTypeCaptureSource,
    MajorCovenantBanCaptureConflict,
    MajorCovenantBanSnapshot,
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
            capture_source=DifficultyCaptureSource.OPERATION_OCR,
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


def apply_info_difficulty_capture(
    session: EncounterSession, difficulty_id: str | None, catalog: EncounterMapCatalog
) -> EncounterSessionUpdate:
    """Capture a catalog-known INFO difficulty without making it a map identity."""
    definition = catalog.difficulty_by_id(difficulty_id or "")
    if definition is None or len(definition.simulation_codes) != 1:
        return EncounterSessionUpdate(session, EncounterUpdateStatus.UNRESOLVED)
    if session.captured_difficulty is None:
        return EncounterSessionUpdate(
            session.model_copy(
                update={
                    "captured_difficulty": CapturedDifficulty(
                        difficulty_id=definition.difficulty_id,
                        simulation_code=definition.simulation_codes[0],
                        capture_source=DifficultyCaptureSource.INITIAL_INFO_VISUAL,
                    )
                }
            ),
            EncounterUpdateStatus.CAPTURED,
        )
    if session.captured_difficulty.difficulty_id == definition.difficulty_id:
        return EncounterSessionUpdate(session, EncounterUpdateStatus.PRESERVED)
    return EncounterSessionUpdate(
        session.model_copy(
            update={
                "difficulty_conflict": DifficultyCaptureConflict(
                    existing_difficulty_id=session.captured_difficulty.difficulty_id,
                    conflicting_difficulty_id=definition.difficulty_id,
                )
            }
        ),
        EncounterUpdateStatus.CONFLICT,
    )


def apply_visual_difficulty_capture(
    session: EncounterSession,
    difficulty_id: str | None,
    catalog: EncounterMapCatalog,
    source: DifficultyCaptureSource,
) -> EncounterSessionUpdate:
    """Fill a missing Difficulty from a calibrated visual profile without replacement."""

    if source not in {
        DifficultyCaptureSource.POST_START_VISUAL,
        DifficultyCaptureSource.OPERATION_SPLASH_VISUAL,
    }:
        return EncounterSessionUpdate(session, EncounterUpdateStatus.UNRESOLVED)
    definition = catalog.difficulty_by_id(difficulty_id or "")
    if definition is None or len(definition.simulation_codes) != 1:
        return EncounterSessionUpdate(session, EncounterUpdateStatus.UNRESOLVED)
    if session.captured_difficulty is None:
        return EncounterSessionUpdate(
            session.model_copy(
                update={
                    "captured_difficulty": CapturedDifficulty(
                        difficulty_id=definition.difficulty_id,
                        simulation_code=definition.simulation_codes[0],
                        capture_source=source,
                    )
                }
            ),
            EncounterUpdateStatus.CAPTURED,
        )
    if session.captured_difficulty.difficulty_id == definition.difficulty_id:
        return EncounterSessionUpdate(session, EncounterUpdateStatus.PRESERVED)
    return EncounterSessionUpdate(
        session.model_copy(
            update={
                "difficulty_conflict": DifficultyCaptureConflict(
                    existing_difficulty_id=session.captured_difficulty.difficulty_id,
                    conflicting_difficulty_id=definition.difficulty_id,
                )
            }
        ),
        EncounterUpdateStatus.CONFLICT,
    )


def apply_boss_capture(
    session: EncounterSession,
    boss_id: str | None,
    catalog: EncounterMapCatalog,
    *,
    source: BossCaptureSource = BossCaptureSource.INITIAL_INFO_VISUAL,
) -> EncounterSessionUpdate:
    """Persist only a catalog-known Boss; later contradiction is auditable, never replacement."""
    if boss_id is None or catalog.boss_by_id(boss_id) is None:
        return EncounterSessionUpdate(session, EncounterUpdateStatus.UNRESOLVED)
    if session.boss_id is None:
        return EncounterSessionUpdate(
            session.model_copy(update={"boss_id": boss_id, "boss_capture_source": source}),
            EncounterUpdateStatus.CAPTURED,
        )
    if session.boss_id == boss_id:
        return EncounterSessionUpdate(session, EncounterUpdateStatus.PRESERVED)
    return EncounterSessionUpdate(
        session.model_copy(
            update={
                "boss_conflict": BossCaptureConflict(
                    existing_boss_id=session.boss_id, conflicting_boss_id=boss_id
                )
            }
        ),
        EncounterUpdateStatus.CONFLICT,
    )


def apply_enemy_type_capture(
    session: EncounterSession,
    enemy_type_ids: tuple[str, ...] | None,
    catalog: EncounterMapCatalog,
    *,
    source: EnemyTypeCaptureSource = EnemyTypeCaptureSource.INITIAL_INFO_VISUAL,
) -> EncounterSessionUpdate:
    """Persist exactly two or three distinct catalog-known categories, preserving conflicts."""
    if (
        enemy_type_ids is None
        or len(enemy_type_ids) not in {2, 3}
        or len(set(enemy_type_ids)) != len(enemy_type_ids)
        or any(catalog.enemy_category_by_id(item) is None for item in enemy_type_ids)
    ):
        return EncounterSessionUpdate(session, EncounterUpdateStatus.UNRESOLVED)
    if session.enemy_type_ids is None:
        return EncounterSessionUpdate(
            session.model_copy(
                update={
                    "enemy_type_ids": enemy_type_ids,
                    "enemy_type_capture_source": source,
                }
            ),
            EncounterUpdateStatus.CAPTURED,
        )
    if session.enemy_type_ids == enemy_type_ids:
        return EncounterSessionUpdate(session, EncounterUpdateStatus.PRESERVED)
    return EncounterSessionUpdate(
        session.model_copy(
            update={
                "enemy_type_conflict": EnemyTypeCaptureConflict(
                    existing_enemy_type_ids=session.enemy_type_ids,
                    conflicting_enemy_type_ids=enemy_type_ids,
                )
            }
        ),
        EncounterUpdateStatus.CONFLICT,
    )


def apply_major_covenant_ban_capture(
    session: EncounterSession,
    snapshot: MajorCovenantBanSnapshot | None,
) -> EncounterSessionUpdate:
    """Persist Major/Core Ban evidence without completing the global Ban item.

    Additional Covenant Ban evidence is intentionally absent from this bounded slice, so this
    function never writes ``banned_covenant_ids`` and never changes ordinary Ban progress.
    """

    if snapshot is None:
        return EncounterSessionUpdate(session, EncounterUpdateStatus.UNRESOLVED)
    if session.major_covenant_ban is None:
        return EncounterSessionUpdate(
            session.model_copy(update={"major_covenant_ban": snapshot}),
            EncounterUpdateStatus.CAPTURED,
        )
    existing = session.major_covenant_ban
    if existing.covenant_states == snapshot.covenant_states:
        return EncounterSessionUpdate(session, EncounterUpdateStatus.PRESERVED)
    return EncounterSessionUpdate(
        session.model_copy(
            update={
                "major_covenant_ban_conflict": MajorCovenantBanCaptureConflict(
                    existing_disabled_covenant_ids=existing.disabled_covenant_ids,
                    conflicting_disabled_covenant_ids=snapshot.disabled_covenant_ids,
                )
            }
        ),
        EncounterUpdateStatus.CONFLICT,
    )
