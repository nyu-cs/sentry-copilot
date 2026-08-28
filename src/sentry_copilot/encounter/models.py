"""Immutable encounter intelligence and curated map-knowledge contracts."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator


class EncounterCaptureItem(StrEnum):
    """The four ordinary, player-count-independent encounter capture items."""

    MAP = "map"
    BOSS = "boss"
    ENEMY_TYPES = "enemy_types"
    BANNED_COVENANTS = "banned_covenants"


class MapKnowledgeCategory(StrEnum):
    TERRAIN = "terrain"
    DEPLOYMENT = "deployment"
    TARGETING = "targeting"
    MECHANIC = "mechanic"
    WARNING = "warning"
    TIP = "tip"


class LocalizedText(BaseModel):
    """One locale-specific display value without making it a logical identifier."""

    model_config = ConfigDict(frozen=True)

    locale_id: str
    text: str

    @model_validator(mode="after")
    def non_blank(self) -> LocalizedText:
        if not self.locale_id.strip() or not self.text.strip():
            raise ValueError("localized text locale_id and text must not be blank")
        return self


class MapKnowledgeEntry(BaseModel):
    """Small curated, localized map intelligence entry with lightweight provenance."""

    model_config = ConfigDict(frozen=True)

    entry_id: str
    category: MapKnowledgeCategory
    titles: tuple[LocalizedText, ...]
    descriptions: tuple[LocalizedText, ...]
    source_note: str | None = None
    difficulty_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def locales_are_unique(self) -> MapKnowledgeEntry:
        for values, label in ((self.titles, "title"), (self.descriptions, "description")):
            locales = [item.locale_id for item in values]
            if len(locales) != len(set(locales)):
                raise ValueError(f"map knowledge {label} locales must be unique")
        return self


class EncounterMapDefinition(BaseModel):
    """Map identity, localized presentation, and persistent map-only knowledge."""

    model_config = ConfigDict(frozen=True)

    map_id: str
    map_code: str
    names: tuple[LocalizedText, ...] = ()
    allowed_difficulty_ids: tuple[str, ...] = ()
    knowledge_entries: tuple[MapKnowledgeEntry, ...] = ()
    future_route_asset_references: tuple[str, ...] = ()

    @model_validator(mode="after")
    def valid_identity_and_locales(self) -> EncounterMapDefinition:
        if not self.map_id.strip() or not _MAP_CODE.fullmatch(self.map_code):
            raise ValueError(
                "map_id must be non-blank and map_code must use normalized stage syntax"
            )
        locales = [item.locale_id for item in self.names]
        if len(locales) != len(set(locales)):
            raise ValueError("map definition name locales must be unique")
        entry_ids = [entry.entry_id for entry in self.knowledge_entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("map knowledge entry IDs must be unique within one map")
        return self


class DifficultyDefinition(BaseModel):
    """A stable simulation-difficulty identity, independent from map identity."""

    model_config = ConfigDict(frozen=True)

    difficulty_id: str
    names: tuple[LocalizedText, ...]
    source_note: str | None = None

    @model_validator(mode="after")
    def valid_locales(self) -> DifficultyDefinition:
        if not self.difficulty_id.strip():
            raise ValueError("difficulty_id must not be blank")
        locales = [item.locale_id for item in self.names]
        if len(locales) != len(set(locales)):
            raise ValueError("difficulty definition name locales must be unique")
        return self


class CapturedMap(BaseModel):
    """One durable, normalized map capture for an encounter session."""

    model_config = ConfigDict(frozen=True)

    map_id: str
    map_code: str
    difficulty_id: str | None = None
    observed_difficulty: str | None = None


class MapCaptureConflict(BaseModel):
    """A later reliable map fact that cannot silently replace the first capture."""

    model_config = ConfigDict(frozen=True)

    existing_map_id: str
    conflicting_map_code: str


class DifficultyCaptureConflict(BaseModel):
    """A same-map difficulty contradiction that cannot silently replace prior evidence."""

    model_config = ConfigDict(frozen=True)

    map_id: str
    existing_difficulty_id: str
    conflicting_difficulty_id: str


class EncounterSession(BaseModel):
    """Immutable encounter-static facts, deliberately independent from player count and slots."""

    model_config = ConfigDict(frozen=True)

    encounter_id: str
    captured_map: CapturedMap | None = None
    map_conflict: MapCaptureConflict | None = None
    difficulty_conflict: DifficultyCaptureConflict | None = None
    boss_id: str | None = None
    enemy_type_ids: tuple[str, str, str] | None = None
    banned_covenant_ids: tuple[str, ...] | None = None
    secret_boss_id: str | None = None

    @model_validator(mode="after")
    def non_blank_id(self) -> EncounterSession:
        if not self.encounter_id.strip():
            raise ValueError("encounter_id must not be blank")
        return self

    @property
    def complete_items(self) -> frozenset[EncounterCaptureItem]:
        items: set[EncounterCaptureItem] = set()
        if self.captured_map is not None:
            items.add(EncounterCaptureItem.MAP)
        if self.boss_id is not None:
            items.add(EncounterCaptureItem.BOSS)
        if self.enemy_type_ids is not None:
            items.add(EncounterCaptureItem.ENEMY_TYPES)
        if self.banned_covenant_ids is not None:
            items.add(EncounterCaptureItem.BANNED_COVENANTS)
        return frozenset(items)

    @property
    def ordinary_progress_count(self) -> int:
        return len(self.complete_items)

    @property
    def missing_items(self) -> tuple[EncounterCaptureItem, ...]:
        return tuple(item for item in EncounterCaptureItem if item not in self.complete_items)


_MAP_CODE = re.compile(r"[A-Z]{1,8}-\d{1,3}\Z")
