"""Pure zh_CN/en encounter-preview presentation without desktop-window dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import EncounterMapCatalog
from .models import EncounterCaptureItem, EncounterSession, LocalizedText, MapKnowledgeEntry

_UI_TEXT: dict[str, dict[str, str]] = {
    "zh_CN": {
        "title": "本局情报",
        "map": "地图",
        "difficulty": "难度",
        "boss": "Boss",
        "enemy_types": "敌人类型",
        "banned_covenants": "禁用盟约",
        "not_captured": "尚未记录",
        "map_intel": "地图情报",
    },
    "en": {
        "title": "Encounter Intel",
        "map": "Map",
        "difficulty": "Difficulty",
        "boss": "Boss",
        "enemy_types": "Enemy Types",
        "banned_covenants": "Bans",
        "not_captured": "Not captured",
        "map_intel": "Map Intel",
    },
}


@dataclass(frozen=True)
class EncounterCaptureItemView:
    item: EncounterCaptureItem
    label: str
    complete: bool
    value: str


@dataclass(frozen=True)
class MapKnowledgeView:
    title: str
    description: str


@dataclass(frozen=True)
class EncounterPanelView:
    title: str
    progress_label: str
    items: tuple[EncounterCaptureItemView, ...]
    map_knowledge: tuple[MapKnowledgeView, ...]
    map_knowledge_heading: str | None
    difficulty_label: str
    difficulty_value: str | None


def present_encounter(
    session: EncounterSession,
    catalog: EncounterMapCatalog,
    *,
    locale_id: str,
) -> EncounterPanelView:
    """Build an immutable preview view; absent knowledge is ordinary, not an error."""

    strings = _UI_TEXT.get(locale_id, _UI_TEXT["en"])
    mapping = {
        EncounterCaptureItem.MAP: "map",
        EncounterCaptureItem.BOSS: "boss",
        EncounterCaptureItem.ENEMY_TYPES: "enemy_types",
        EncounterCaptureItem.BANNED_COVENANTS: "banned_covenants",
    }
    map_value, difficulty_value, entries = _map_value_and_knowledge(session, catalog, locale_id)
    items = tuple(
        EncounterCaptureItemView(
            item=item,
            label=strings[mapping[item]],
            complete=item in session.complete_items,
            value=(
                map_value
                if item is EncounterCaptureItem.MAP and map_value is not None
                else strings["not_captured"]
            ),
        )
        for item in EncounterCaptureItem
    )
    views = tuple(
        MapKnowledgeView(
            title=_localized(entry.titles, locale_id),
            description=_localized(entry.descriptions, locale_id),
        )
        for entry in entries
    )
    return EncounterPanelView(
        title=strings["title"],
        progress_label=f"{session.ordinary_progress_count} / {len(EncounterCaptureItem)}",
        items=items,
        map_knowledge=views,
        map_knowledge_heading=strings["map_intel"] if views else None,
        difficulty_label=strings["difficulty"],
        difficulty_value=difficulty_value,
    )


def _map_value_and_knowledge(
    session: EncounterSession,
    catalog: EncounterMapCatalog,
    locale_id: str,
) -> tuple[str | None, str | None, tuple[MapKnowledgeEntry, ...]]:
    capture = session.captured_map
    if capture is None:
        return None, None, ()
    definition = catalog.by_id(capture.map_id)
    if definition is None:
        return capture.map_code, capture.observed_difficulty, ()
    entries = tuple(
        entry
        for entry in definition.knowledge_entries
        if not entry.difficulty_ids
        or (
            capture.difficulty_id is not None
            and capture.difficulty_id in entry.difficulty_ids
        )
    )
    map_value = (
        f"{capture.map_code} · {_localized(definition.names, locale_id)}"
        if definition.names
        else capture.map_code
    )
    difficulty = catalog.difficulty_by_id(capture.difficulty_id) if capture.difficulty_id else None
    difficulty_value = (
        _localized(difficulty.names, locale_id)
        if difficulty is not None
        else capture.observed_difficulty
    )
    return map_value, difficulty_value, entries


def _localized(values: tuple[LocalizedText, ...], locale_id: str) -> str:
    exact = next((item.text for item in values if item.locale_id == locale_id), None)
    if exact is not None:
        return exact
    english = next((item.text for item in values if item.locale_id == "en"), None)
    if english is not None:
        return english
    return values[0].text
