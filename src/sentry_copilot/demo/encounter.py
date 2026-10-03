"""Deterministic synthetic facts through the production encounter/session/UI pipeline.

No observers run here. Existing capture-source enums describe simulated INFO surfaces, not
actual image recognition. All fixture text and memberships are authored for this demonstration.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite

from sentry_copilot.encounter.additional_covenant_ban_catalog import (
    AdditionalCovenantPresentationCatalog,
    AdditionalCovenantPresentationDefinition,
)
from sentry_copilot.encounter.catalog import EncounterMapCatalog
from sentry_copilot.encounter.confirmed_banned_operators import (
    BannedOperatorDefinition,
    ConfirmedBannedOperatorCatalog,
    CovenantDefinition,
)
from sentry_copilot.encounter.major_covenant_ban_catalog import (
    MajorCovenantPresentationCatalog,
    MajorCovenantPresentationDefinition,
)
from sentry_copilot.encounter.models import (
    ADDITIONAL_COVENANT_IDS,
    MAJOR_COVENANT_IDS,
    AdditionalCovenantBanCaptureSource,
    AdditionalCovenantBanSnapshot,
    BossCaptureSource,
    BossDefinition,
    CovenantBanState,
    DifficultyDefinition,
    EncounterSession,
    EnemyCategoryDefinition,
    LocalizedText,
    MajorCovenantBanSnapshot,
    MajorCovenantBanStateEntry,
)
from sentry_copilot.encounter.presentation import EncounterPanelView, present_encounter
from sentry_copilot.encounter.session import (
    apply_additional_covenant_ban_capture,
    apply_boss_capture,
    apply_enemy_type_capture,
    apply_info_difficulty_capture,
    apply_major_covenant_ban_capture,
)

_MAJOR_IDS = tuple(sorted(MAJOR_COVENANT_IDS))
_ADDITIONAL_IDS = tuple(sorted(ADDITIONAL_COVENANT_IDS))
_DISABLED_MAJOR = _MAJOR_IDS[:3]
_DISABLED_ADDITIONAL = tuple(
    item
    for item in _ADDITIONAL_IDS
    if not item.endswith((".support_operator", ".ultimate_technique"))
)[:4]
_ENEMY_IDS = ("enemy.demo.aerial", "enemy.demo.stealth")
_DIFFICULTY_ID = "difficulty.demo.challenge"
_BOSS_ID = "boss.demo.warden"


@dataclass(frozen=True)
class DemoEncounterStep:
    """One immutable synthetic state and the exact view consumed by the real desktop UI."""

    index: int
    session: EncounterSession
    presentation: EncounterPanelView
    locale_id: str
    description: str
    recovery_reminder_text: str | None = None

    @property
    def status_message(self) -> str:
        """Keep synthetic provenance visible throughout GUI playback, including the final step."""

        return f"SYNTHETIC DEMO: {self.description}"


def _names(text: str) -> tuple[LocalizedText, ...]:
    return (LocalizedText(locale_id="en", text=text),)


def _demo_catalogs() -> tuple[
    EncounterMapCatalog,
    MajorCovenantPresentationCatalog,
    AdditionalCovenantPresentationCatalog,
    ConfirmedBannedOperatorCatalog,
]:
    """Construct tiny fictional catalogs in memory, with no filesystem/media dependency."""

    catalog = EncounterMapCatalog(
        definitions=(),
        difficulties=(
            DifficultyDefinition(
                difficulty_id=_DIFFICULTY_ID,
                simulation_codes=("DEMO-3",),
                names=_names("Demo Challenge"),
            ),
        ),
        bosses=(BossDefinition(boss_id=_BOSS_ID, names=_names("Demo Warden")),),
        enemy_categories=tuple(
            EnemyCategoryDefinition(enemy_category_id=item, names=_names(name))
            for item, name in zip(_ENEMY_IDS, ("Aerial", "Stealth"), strict=True)
        ),
    )
    major = MajorCovenantPresentationCatalog(
        tuple(
            MajorCovenantPresentationDefinition(item, _names(f"Major {chr(65 + index)}"))
            for index, item in enumerate(_MAJOR_IDS)
        )
    )
    additional = AdditionalCovenantPresentationCatalog(
        tuple(
            AdditionalCovenantPresentationDefinition(item, _names(f"Extra {chr(65 + index)}"))
            for index, item in enumerate(_ADDITIONAL_IDS)
        )
    )
    definitions: tuple[
        MajorCovenantPresentationDefinition | AdditionalCovenantPresentationDefinition, ...
    ] = (*major.definitions, *additional.definitions)
    operators = ConfirmedBannedOperatorCatalog(
        operators=tuple(
            BannedOperatorDefinition(
                f"operator.demo.{index}", f"Demo Op {chr(65 + index)}", 4 - index
            )
            for index in range(4)
        ),
        covenant_definitions=tuple(
            CovenantDefinition(
                item.covenant_id,
                item.names[0].text,
                static_recruitment_route=not item.covenant_id.endswith(".ultimate_technique"),
                disableable_ban_target=not item.covenant_id.endswith(
                    (".support_operator", ".ultimate_technique")
                ),
            )
            for item in definitions
        ),
        membership_ids_by_operator=tuple(
            (
                f"operator.demo.{index}",
                ((_DISABLED_MAJOR[index],) if index < 3 else ()) + (_DISABLED_ADDITIONAL[index],),
            )
            for index in range(4)
        ),
    )
    return catalog, major, additional, operators


def build_demo_timeline(locale_id: str = "en") -> tuple[DemoEncounterStep, ...]:
    """Build seven deterministic immutable steps; never capture, recognize, sleep, or load files."""

    if locale_id not in {"en", "zh_CN"}:
        raise ValueError("demo locale must be en or zh_CN")
    catalog, major, additional, operators = _demo_catalogs()
    session = EncounterSession(encounter_id="synthetic-demo:encounter-1")
    steps: list[DemoEncounterStep] = []
    messages = (
        (
            "Waiting for confirmed synthetic facts",
            "Difficulty captured: Demo Challenge",
            "Enemy Types captured: Aerial / Stealth",
            "Major snapshot captured; Bans incomplete",
            "Major + Additional captured; Banned Covenants complete",
            "Boss missing; recovery available",
            "Boss recovered from synthetic returned-INFO fact",
        )
        if locale_id == "en"
        else (
            "等待已确认的合成情报",
            "已采集合成难度：Demo Challenge",
            "已采集合成敌人类型：Aerial / Stealth",
            "已采集主盟约；禁用盟约仍不完整",
            "主盟约与追加盟约均已采集；禁用盟约完整",
            "Boss 缺失；可返回情报页补采",
            "已通过合成返回情报事实补采 Boss",
        )
    )

    def record(reminder: str | None = None) -> None:
        view = present_encounter(
            session,
            catalog,
            locale_id=locale_id,
            major_covenant_catalog=major,
            additional_covenant_catalog=additional,
            confirmed_banned_operator_catalog=operators,
        )
        # Keep production projection/grouping; this public demo intentionally has no media keys.
        view = replace(
            view,
            title="Synthetic Encounter Demo" if locale_id == "en" else "合成对局演示",
            confirmed_banned_operator_rows=tuple(
                replace(
                    row, operators=tuple(replace(card, portrait_key=None) for card in row.operators)
                )
                for row in view.confirmed_banned_operator_rows
            ),
        )
        index = len(steps)
        steps.append(DemoEncounterStep(index, session, view, locale_id, messages[index], reminder))

    record()
    session = apply_info_difficulty_capture(session, _DIFFICULTY_ID, catalog).session
    record()
    session = apply_enemy_type_capture(session, _ENEMY_IDS, catalog).session
    record()
    session = apply_major_covenant_ban_capture(
        session,
        MajorCovenantBanSnapshot(
            covenant_states=tuple(
                MajorCovenantBanStateEntry(
                    covenant_id=item,
                    state=(
                        CovenantBanState.DISABLED
                        if item in _DISABLED_MAJOR
                        else CovenantBanState.UNRESTRICTED
                    ),
                )
                for item in _MAJOR_IDS
            ),
        ),
    ).session
    record()
    session = apply_additional_covenant_ban_capture(
        session,
        AdditionalCovenantBanSnapshot(
            disabled_covenant_ids=_DISABLED_ADDITIONAL,
            capture_source=AdditionalCovenantBanCaptureSource.INITIAL_INFO_VISUAL,
            confirmed_frame_id="synthetic-demo:additional-fact",
        ),
    ).session
    record()
    record(
        "Synthetic recovery: Boss missing; return to INFO."
        if locale_id == "en"
        else "合成补采提示：Boss 缺失，可返回情报页。"
    )
    session = apply_boss_capture(
        session, _BOSS_ID, catalog, source=BossCaptureSource.RETURNED_INFO_VISUAL
    ).session
    record()
    return tuple(steps)


def format_demo_timeline(timeline: tuple[DemoEncounterStep, ...]) -> str:
    """Return deterministic text for the same states shown in GUI playback."""

    return "\n".join(
        (
            "SYNTHETIC ENCOUNTER DEMO",
            "Project-authored confirmed facts; no live computer vision or capture.",
            *(
                f"{step.index}: {step.presentation.progress_label}  {step.description}"
                for step in timeline
            ),
        )
    )


def show_demo_encounter(
    *, locale_id: str = "en", step_seconds: float = 1.25, always_on_top: bool = True
) -> None:
    """Play the timeline in the real desktop UI, leaving the final state open until user close."""

    if not isfinite(step_seconds) or step_seconds <= 0:
        raise ValueError("step duration must be positive and finite")
    timeline = build_demo_timeline(locale_id)
    # GUI-only import: the timeline and headless CLI never import or initialize Tk.
    from sentry_copilot.encounter.desktop import LiveEncounterPreviewWindow

    index = 0

    def change_locale(selected: str) -> DemoEncounterStep:
        nonlocal timeline
        timeline = build_demo_timeline(selected)
        step = timeline[index]
        window.publish(step)  # supersede any queued snapshot in the previous locale
        return step

    window = LiveEncounterPreviewWindow(
        timeline[0],
        on_locale=change_locale,
        diagnostic_text=lambda: format_demo_timeline(timeline),
        on_close=lambda: None,
        always_on_top=always_on_top,
        load_default_resources=False,
        covenant_icon_sources={},
    )
    milliseconds = max(1, round(step_seconds * 1000))

    def advance() -> None:
        nonlocal index
        index += 1
        window.publish(timeline[index])
        if index < len(timeline) - 1:
            window.call_later(milliseconds, advance)

    window.call_later(milliseconds, advance)
    window.run()
