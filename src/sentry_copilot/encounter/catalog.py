"""Small explicit map catalog; recognition facts never infer knowledge from pixels."""

from __future__ import annotations

from dataclasses import dataclass

from .models import DifficultyDefinition, EncounterMapDefinition, LocalizedText


@dataclass(frozen=True)
class EncounterMapCatalog:
    """Exact normalized map-code lookup with no locale fallback for identity."""

    definitions: tuple[EncounterMapDefinition, ...]
    difficulties: tuple[DifficultyDefinition, ...] = ()

    def __post_init__(self) -> None:
        codes = [item.map_code for item in self.definitions]
        ids = [item.map_id for item in self.definitions]
        if len(codes) != len(set(codes)) or len(ids) != len(set(ids)):
            raise ValueError("encounter map catalog map IDs and codes must be unique")
        difficulty_ids = [item.difficulty_id for item in self.difficulties]
        if len(difficulty_ids) != len(set(difficulty_ids)):
            raise ValueError("encounter map catalog difficulty IDs must be unique")
        known_difficulty_ids = set(difficulty_ids)
        for definition in self.definitions:
            referenced_ids = set(definition.allowed_difficulty_ids)
            referenced_ids.update(
                difficulty_id
                for entry in definition.knowledge_entries
                for difficulty_id in entry.difficulty_ids
            )
            if not referenced_ids <= known_difficulty_ids:
                raise ValueError("map catalog references an unknown difficulty ID")

    def by_code(self, map_code: str) -> EncounterMapDefinition | None:
        return next(
            (item for item in self.definitions if item.map_code == map_code),
            None,
        )

    def by_id(self, map_id: str) -> EncounterMapDefinition | None:
        return next((item for item in self.definitions if item.map_id == map_id), None)

    def difficulty_by_id(self, difficulty_id: str) -> DifficultyDefinition | None:
        return next(
            (item for item in self.difficulties if item.difficulty_id == difficulty_id), None
        )


JP_MUMU_ENCOUNTER_MAP_CATALOG = EncounterMapCatalog(
    definitions=(
        EncounterMapDefinition(
            map_id="map.covenant_latter.ac_3",
            map_code="AC-3",
        ),
    ),
    difficulties=(
        DifficultyDefinition(
            difficulty_id="difficulty.covenant_latter.deadland",
            names=(
                LocalizedText(locale_id="zh_CN", text="死地"),
                LocalizedText(locale_id="ja_JP", text="死地"),
            ),
            source_note="JP MuMu OPERATION retained-frame calibration",
        ),
    ),
)
