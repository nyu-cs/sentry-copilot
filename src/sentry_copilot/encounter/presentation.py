"""Pure zh_CN/en encounter-preview presentation without desktop-window dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import EncounterMapCatalog
from .confirmed_banned_operators import (
    ConfirmedBannedOperatorCatalog,
    project_confirmed_banned_operator_rows,
)
from .major_covenant_ban_catalog import MajorCovenantPresentationCatalog
from .models import EncounterCaptureItem, EncounterSession, LocalizedText, MapKnowledgeEntry

_UI_TEXT: dict[str, dict[str, str]] = {
    "zh_CN": {
        "title": "本局情报",
        "map": "地图",
        "difficulty": "难度",
        "boss": "Boss",
        "enemy_types": "敌人类型",
        "banned_covenants": "禁用盟约",
        "not_captured": "尚未识别",
        "upcoming": "本版本暂未支持",
        "major_ban_unresolved": "主盟约：尚未识别；追加盟约：本版本暂未支持",
        "major_ban_captured": "{disabled}",
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
        "upcoming": "Not supported in this preview",
        "major_ban_unresolved": "Major: Not captured; Additional: Not supported in this preview",
        "major_ban_captured": "{disabled}",
        "map_intel": "Map Intel",
    },
}


@dataclass(frozen=True)
class EncounterCaptureItemView:
    item: EncounterCaptureItem
    label: str
    complete: bool
    implemented: bool
    value: str


@dataclass(frozen=True)
class MapKnowledgeView:
    title: str
    description: str


@dataclass(frozen=True)
class ConfirmedBannedOperatorCardView:
    """One compact Ban-detail card, independent from local Tk image objects."""

    operator_id: str
    display_name: str
    tier: int
    portrait_key: str | None


@dataclass(frozen=True)
class ConfirmedBannedOperatorRowView:
    """One Covenant row; membership-valid cards may intentionally repeat across rows."""

    covenant_id: str
    display_name: str
    operators: tuple[ConfirmedBannedOperatorCardView, ...]


@dataclass(frozen=True)
class EncounterPanelView:
    title: str
    progress_label: str
    items: tuple[EncounterCaptureItemView, ...]
    map_knowledge: tuple[MapKnowledgeView, ...]
    map_knowledge_heading: str | None
    difficulty_label: str
    difficulty_value: str | None
    confirmed_banned_operator_rows: tuple[ConfirmedBannedOperatorRowView, ...]


def present_encounter(
    session: EncounterSession,
    catalog: EncounterMapCatalog,
    *,
    locale_id: str,
    major_covenant_catalog: MajorCovenantPresentationCatalog | None = None,
    confirmed_banned_operator_catalog: ConfirmedBannedOperatorCatalog | None = None,
) -> EncounterPanelView:
    """Build an immutable preview view; absent knowledge is ordinary, not an error."""

    strings = _UI_TEXT.get(locale_id, _UI_TEXT["en"])
    mapping = {
        EncounterCaptureItem.DIFFICULTY: "difficulty",
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
            implemented=item
            in {
                EncounterCaptureItem.DIFFICULTY,
                EncounterCaptureItem.BOSS,
                EncounterCaptureItem.ENEMY_TYPES,
                EncounterCaptureItem.BANNED_COVENANTS,
            },
            value=(
                difficulty_value
                if item is EncounterCaptureItem.DIFFICULTY and difficulty_value is not None
                else (
                    map_value
                    if item is EncounterCaptureItem.MAP and map_value is not None
                    else (
                        _boss_value(session, catalog, locale_id)
                        if item is EncounterCaptureItem.BOSS and session.boss_id is not None
                        else (
                            _enemy_value(session, catalog, locale_id)
                            if item is EncounterCaptureItem.ENEMY_TYPES
                            and session.enemy_type_ids is not None
                            else (
                                _major_ban_value(
                                    session,
                                    major_covenant_catalog,
                                    locale_id,
                                    strings,
                                )
                                if item is EncounterCaptureItem.BANNED_COVENANTS
                                else (
                                    strings["not_captured"]
                                    if item
                                    in {
                                        EncounterCaptureItem.DIFFICULTY,
                                        EncounterCaptureItem.BOSS,
                                        EncounterCaptureItem.ENEMY_TYPES,
                                    }
                                    else strings["upcoming"]
                                )
                            )
                        )
                    )
                )
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
        confirmed_banned_operator_rows=_confirmed_banned_operator_rows(
            session,
            confirmed_banned_operator_catalog,
        ),
    )


def _map_value_and_knowledge(
    session: EncounterSession,
    catalog: EncounterMapCatalog,
    locale_id: str,
) -> tuple[str | None, str | None, tuple[MapKnowledgeEntry, ...]]:
    capture = session.captured_map
    difficulty_capture = session.captured_difficulty
    difficulty = (
        catalog.difficulty_by_id(difficulty_capture.difficulty_id)
        if difficulty_capture is not None
        else None
    )
    difficulty_value = (
        _localized(difficulty.names, locale_id)
        if difficulty is not None
        else (difficulty_capture.observed_label if difficulty_capture is not None else None)
    )
    if capture is None:
        return None, difficulty_value, ()
    definition = catalog.by_id(capture.map_id)
    if definition is None:
        return capture.map_code, difficulty_value, ()
    entries = tuple(
        entry
        for entry in definition.knowledge_entries
        if not entry.difficulty_ids
        or (
            difficulty_capture is not None
            and difficulty_capture.difficulty_id in entry.difficulty_ids
        )
    )
    map_value = (
        f"{capture.map_code} · {_localized(definition.names, locale_id)}"
        if definition.names
        else capture.map_code
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


def _boss_value(session: EncounterSession, catalog: EncounterMapCatalog, locale_id: str) -> str:
    definition = catalog.boss_by_id(session.boss_id or "")
    return (
        _localized(definition.names, locale_id)
        if definition is not None
        else (session.boss_id or "")
    )


def _enemy_value(session: EncounterSession, catalog: EncounterMapCatalog, locale_id: str) -> str:
    return " / ".join(
        _localized(definition.names, locale_id) if definition is not None else enemy_id
        for enemy_id in session.enemy_type_ids or ()
        for definition in (catalog.enemy_category_by_id(enemy_id),)
    )


def _major_ban_value(
    session: EncounterSession,
    catalog: MajorCovenantPresentationCatalog | None,
    locale_id: str,
    strings: dict[str, str],
) -> str:
    snapshot = session.major_covenant_ban
    if snapshot is None:
        return strings["major_ban_unresolved"]
    names = tuple(
        _major_covenant_name(covenant_id, catalog, locale_id)
        for covenant_id in snapshot.disabled_covenant_ids
    )
    separator = "、" if locale_id == "zh_CN" else ", "
    return strings["major_ban_captured"].format(disabled=separator.join(names))


def _confirmed_banned_operator_rows(
    session: EncounterSession,
    catalog: ConfirmedBannedOperatorCatalog | None,
) -> tuple[ConfirmedBannedOperatorRowView, ...]:
    """Project existing confirmed-Ban rows into presentation-only operator cards."""

    snapshot = session.major_covenant_ban
    if snapshot is None or catalog is None:
        return ()
    states = {item.covenant_id: item.state for item in snapshot.covenant_states}
    rows = project_confirmed_banned_operator_rows(states, catalog)
    return tuple(
        ConfirmedBannedOperatorRowView(
            covenant_id=row.covenant_id,
            display_name=row.covenant_name_zh_CN,
            operators=tuple(
                ConfirmedBannedOperatorCardView(
                    operator_id=operator.operator_id,
                    display_name=operator.name_zh_CN,
                    tier=operator.tier,
                    portrait_key=f"prts:{operator.name_zh_CN}",
                )
                for operator in row.operators
            ),
        )
        for row in rows
    )


def _major_covenant_name(
    covenant_id: str,
    catalog: MajorCovenantPresentationCatalog | None,
    locale_id: str,
) -> str:
    definition = catalog.by_id(covenant_id) if catalog is not None else None
    return _localized(definition.names, locale_id) if definition is not None else covenant_id
