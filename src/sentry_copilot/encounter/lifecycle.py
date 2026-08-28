"""Encounter-start boundary abstraction, separate from OPERATION map enrichment."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import EncounterSession


class EncounterStartState(StrEnum):
    """Whether a future information-page observer established a new encounter boundary."""

    PRESENT = "present"
    ABSENT = "absent"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class EncounterStartObservation:
    """Reserved provenance boundary for the JP `情報確認 1/2` page observer."""

    state: EncounterStartState
    frame_id: str


def begin_encounter(encounter_id: str) -> EncounterSession:
    """Create a clean session at an authoritative caller-confirmed start boundary."""

    return EncounterSession(encounter_id=encounter_id)
