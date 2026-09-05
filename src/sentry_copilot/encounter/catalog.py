"""Small explicit map catalog; recognition facts never infer knowledge from pixels."""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    BossDefinition,
    DifficultyDefinition,
    EncounterMapDefinition,
    EnemyCategoryDefinition,
    LocalizedText,
)


@dataclass(frozen=True)
class EncounterMapCatalog:
    """Exact normalized map-code lookup with no locale fallback for identity."""

    definitions: tuple[EncounterMapDefinition, ...]
    difficulties: tuple[DifficultyDefinition, ...] = ()
    bosses: tuple[BossDefinition, ...] = ()
    enemy_categories: tuple[EnemyCategoryDefinition, ...] = ()

    def __post_init__(self) -> None:
        codes = [item.map_code for item in self.definitions]
        ids = [item.map_id for item in self.definitions]
        if len(codes) != len(set(codes)) or len(ids) != len(set(ids)):
            raise ValueError("encounter map catalog map IDs and codes must be unique")
        difficulty_ids = [item.difficulty_id for item in self.difficulties]
        if len(difficulty_ids) != len(set(difficulty_ids)):
            raise ValueError("encounter map catalog difficulty IDs must be unique")
        simulation_codes = [code for item in self.difficulties for code in item.simulation_codes]
        if len(simulation_codes) != len(set(simulation_codes)):
            raise ValueError("encounter map catalog simulation codes must be unique")
        boss_ids = [item.boss_id for item in self.bosses]
        if len(boss_ids) != len(set(boss_ids)):
            raise ValueError("encounter catalog Boss IDs must be unique")
        enemy_category_ids = [item.enemy_category_id for item in self.enemy_categories]
        if len(enemy_category_ids) != len(set(enemy_category_ids)):
            raise ValueError("encounter catalog enemy category IDs must be unique")
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

    def difficulty_by_simulation_code(self, simulation_code: str) -> DifficultyDefinition | None:
        return next(
            (item for item in self.difficulties if simulation_code in item.simulation_codes), None
        )

    def boss_by_id(self, boss_id: str) -> BossDefinition | None:
        return next((item for item in self.bosses if item.boss_id == boss_id), None)

    def enemy_category_by_id(self, enemy_category_id: str) -> EnemyCategoryDefinition | None:
        return next(
            (item for item in self.enemy_categories if item.enemy_category_id == enemy_category_id),
            None,
        )


JP_MUMU_ENCOUNTER_MAP_CATALOG = EncounterMapCatalog(
    definitions=(),
    difficulties=(
        DifficultyDefinition(
            difficulty_id="difficulty.covenant_latter.standard",
            simulation_codes=("AC-1",),
            names=(
                LocalizedText(locale_id="zh_CN", text="标准模拟"),
                LocalizedText(locale_id="en", text="Standard"),
            ),
        ),
        DifficultyDefinition(
            difficulty_id="difficulty.covenant_latter.adversity",
            simulation_codes=("AC-2",),
            names=(
                LocalizedText(locale_id="zh_CN", text="险境模拟"),
                LocalizedText(locale_id="en", text="Adversity"),
            ),
        ),
        DifficultyDefinition(
            difficulty_id="difficulty.covenant_latter.deadland",
            simulation_codes=("AC-3",),
            names=(
                LocalizedText(locale_id="zh_CN", text="死地"),
                LocalizedText(locale_id="en", text="Deadland"),
                LocalizedText(locale_id="ja_JP", text="死地"),
            ),
            source_note="JP MuMu OPERATION retained-frame calibration",
        ),
        DifficultyDefinition(
            difficulty_id="difficulty.covenant_latter.ultimate",
            simulation_codes=("AC-4",),
            names=(LocalizedText(locale_id="zh_CN", text="终极模拟"),),
            source_note=(
                "JP live difficulty identity metadata; visual calibration is pending real material"
            ),
        ),
    ),
)
