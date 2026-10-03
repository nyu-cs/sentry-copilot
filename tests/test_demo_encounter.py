from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from sentry_copilot.cli import build_parser, main
from sentry_copilot.demo.encounter import (
    DemoEncounterStep,
    build_demo_timeline,
    format_demo_timeline,
    show_demo_encounter,
)
from sentry_copilot.encounter import desktop
from sentry_copilot.encounter.models import (
    ADDITIONAL_COVENANT_IDS,
    MAJOR_COVENANT_IDS,
    BossCaptureSource,
    CovenantBanState,
    EncounterCaptureItem,
)


def test_timeline_is_deterministic_and_english_by_default() -> None:
    timeline = build_demo_timeline()
    assert timeline == build_demo_timeline()
    assert tuple(step.index for step in timeline) == tuple(range(7))
    assert all(step.locale_id == "en" for step in timeline)
    assert all("Synthetic" in step.presentation.title for step in timeline)
    assert all("SYNTHETIC" in step.status_message for step in timeline)
    assert timeline[0].session.complete_items == frozenset()


@pytest.mark.parametrize("index,progress", tuple(enumerate((0, 1, 2, 2, 3, 3, 4))))
def test_exact_four_item_progress_at_every_step(index: int, progress: int) -> None:
    step = build_demo_timeline()[index]
    assert step.session.ordinary_progress_count == progress
    assert step.presentation.progress_label == f"{progress} / 4"
    assert tuple(item.item for item in step.presentation.items) == tuple(EncounterCaptureItem)
    assert len(step.presentation.items) == 4
    assert "map" not in {item.item.value for item in step.presentation.items}


def test_major_alone_never_completes_bans_and_snapshots_keep_invariants() -> None:
    timeline = build_demo_timeline()
    partial = timeline[3].session
    major = partial.major_covenant_ban
    assert major is not None
    assert {item.covenant_id for item in major.covenant_states} == MAJOR_COVENANT_IDS
    assert len(major.covenant_states) == 8
    assert sum(item.state is CovenantBanState.UNRESTRICTED for item in major.covenant_states) == 5
    assert len(major.disabled_covenant_ids) == 3
    assert partial.additional_covenant_ban is None
    assert partial.banned_covenant_ids is None
    assert EncounterCaptureItem.BANNED_COVENANTS not in partial.complete_items
    assert "Bans incomplete" in timeline[3].description
    combined = timeline[4].session
    additional = combined.additional_covenant_ban
    assert additional is not None
    assert len(additional.disabled_covenant_ids) == 4
    assert set(additional.disabled_covenant_ids) <= ADDITIONAL_COVENANT_IDS
    assert len(ADDITIONAL_COVENANT_IDS - set(additional.disabled_covenant_ids)) == 11
    assert combined.banned_covenant_ids is not None
    assert len(combined.banned_covenant_ids) == 7
    assert EncounterCaptureItem.BANNED_COVENANTS in combined.complete_items


def test_sticky_facts_and_synthetic_returned_info_recovery() -> None:
    timeline = build_demo_timeline()
    before, reminder, final = timeline[4:]
    assert before.session is reminder.session
    assert reminder.session.boss_id is None
    assert "Boss missing" in (reminder.recovery_reminder_text or "")
    assert final.recovery_reminder_text is None
    assert final.session.boss_id == "boss.demo.warden"
    assert final.session.boss_capture_source is BossCaptureSource.RETURNED_INFO_VISUAL
    assert final.session.captured_difficulty == timeline[1].session.captured_difficulty
    assert final.session.enemy_type_ids == timeline[2].session.enemy_type_ids
    assert final.session.major_covenant_ban == timeline[3].session.major_covenant_ban
    assert final.session.additional_covenant_ban == before.session.additional_covenant_ban
    assert final.session.banned_covenant_ids == before.session.banned_covenant_ids
    assert final.session.complete_items == frozenset(EncounterCaptureItem)


def test_ban_detail_uses_only_synthetic_text_and_no_portrait_keys() -> None:
    rows = build_demo_timeline()[-1].presentation.confirmed_banned_operator_rows
    assert len(rows) == 7
    assert all(row.covenant_id in MAJOR_COVENANT_IDS for row in rows[:3])
    assert all(row.covenant_id in ADDITIONAL_COVENANT_IDS for row in rows[3:])
    assert all(row.display_name.startswith(("Major ", "Extra ")) for row in rows)
    cards = tuple(card for row in rows for card in row.operators)
    assert len({card.operator_id for card in cards}) == 4
    assert all(
        card.display_name.startswith("Demo Op ") and card.portrait_key is None for card in cards
    )


def test_chinese_shell_retains_synthetic_entity_labels() -> None:
    timeline = build_demo_timeline("zh_CN")
    assert timeline[-1].presentation.progress_label == "4 / 4"
    assert timeline[-1].presentation.title == "合成对局演示"
    assert "Demo Warden" in timeline[-1].presentation.items[1].value
    assert timeline[5].recovery_reminder_text is not None


def test_unknown_locale_is_rejected() -> None:
    with pytest.raises(ValueError, match="locale"):
        build_demo_timeline("ja_JP")
    with pytest.raises(SystemExit) as rejected:
        build_parser().parse_args(["demo-encounter", "--locale", "ja_JP"])
    assert rejected.value.code == 2


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "not-a-number"])
def test_invalid_step_duration_is_rejected(value: str) -> None:
    with pytest.raises(SystemExit) as rejected:
        build_parser().parse_args(["demo-encounter", "--step-seconds", value])
    assert rejected.value.code == 2


def test_cli_defaults_and_headless_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    args = build_parser().parse_args(["demo-encounter"])
    assert args.locale == "en"
    assert args.step_seconds == 1.25
    assert not args.headless
    monkeypatch.setattr(sys, "argv", ["sentry-copilot", "demo-encounter", "--headless"])
    main()
    output = capsys.readouterr().out
    assert output == format_demo_timeline(build_demo_timeline()) + "\n"
    assert "SYNTHETIC" in output and "no live computer vision" in output
    assert "2 / 4  Major snapshot captured; Bans incomplete" in output
    assert "3 / 4  Boss missing; recovery available" in output
    assert "4 / 4  Boss recovered from synthetic returned-INFO fact" in output


def test_headless_from_empty_cwd_never_imports_tk_or_reads_reference_files(tmp_path: Path) -> None:
    script = """
import sys
from pathlib import Path
from unittest.mock import patch
from sentry_copilot.cli import main
with patch.object(Path, 'read_text', side_effect=AssertionError('unexpected resource read')), \\
     patch.object(Path, 'read_bytes', side_effect=AssertionError('unexpected media read')), \\
     patch.object(Path, 'open', side_effect=AssertionError('unexpected file open')):
    main()
assert 'tkinter' not in sys.modules
assert 'sentry_copilot.encounter.desktop' not in sys.modules
assert 'sentry_copilot.demo.media' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script, "demo-encounter", "--headless"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == format_demo_timeline(build_demo_timeline()) + "\n"
    assert not tuple(tmp_path.iterdir())


def test_explicit_no_media_seam_never_calls_default_loaders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected() -> None:
        raise AssertionError("demo attempted a default resource loader")

    monkeypatch.setattr(desktop, "_try_load_portrait_sources", unexpected)
    monkeypatch.setattr(desktop, "default_operator_portrait_private_cache_root", unexpected)
    monkeypatch.setattr(desktop, "_load_covenant_ui_icon_sources", unexpected)
    assert desktop._resolve_preview_media(
        load_default_resources=False,
        portrait_sources=None,
        portrait_cache_root=None,
        covenant_icon_sources={},
    ) == (None, None, {})


def test_media_seam_keeps_existing_default_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = Path("synthetic-cache")
    icons = {"demo": Path("synthetic-icon")}
    calls: list[str] = []

    def portraits() -> None:
        calls.append("portraits")

    monkeypatch.setattr(desktop, "_try_load_portrait_sources", portraits)
    monkeypatch.setattr(desktop, "default_operator_portrait_private_cache_root", lambda: cache)
    monkeypatch.setattr(desktop, "_load_covenant_ui_icon_sources", lambda: icons)
    assert desktop._resolve_preview_media(
        load_default_resources=True,
        portrait_sources=None,
        portrait_cache_root=None,
        covenant_icon_sources=None,
    ) == (None, cache, icons)
    assert calls == ["portraits"]


def test_gui_playback_reuses_real_window_contract_without_tk_or_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows: list[FakeWindow] = []

    class FakeWindow:
        def __init__(self, initial: DemoEncounterStep, **options: Any) -> None:
            self.steps = [initial]
            self.pending: list[Callable[[], None]] = []
            self.options = options
            self.delays: list[int] = []
            windows.append(self)

        def publish(self, step: DemoEncounterStep) -> None:
            self.steps.append(step)

        def call_later(self, milliseconds: int, callback: Callable[[], None]) -> None:
            self.delays.append(milliseconds)
            self.pending.append(callback)

        def run(self) -> None:
            while self.pending:
                self.pending.pop(0)()
                if self.steps[-1].index == 3:
                    selected = self.options["on_locale"]("zh_CN")
                    assert selected.index == 3
            assert self.steps[-1].index == 6

    monkeypatch.setattr(desktop, "LiveEncounterPreviewWindow", FakeWindow)
    show_demo_encounter(always_on_top=False)
    window = windows[0]
    assert window.options["load_default_resources"] is False
    assert window.options["covenant_icon_sources"] == {}
    assert len(window.options["covenant_icon_images"]) == 7
    assert len(window.options["operator_portrait_images"]) == 4
    assert window.options["always_on_top"] is False
    assert window.delays == [1250] * 6
    assert window.steps[-1].presentation.progress_label == "4 / 4"
    assert window.steps[-1].locale_id == "zh_CN"
    assert "SYNTHETIC" in window.options["diagnostic_text"]()


@pytest.mark.parametrize("seconds", [0.0, -1.0, float("nan"), float("inf")])
def test_gui_rejects_invalid_duration_before_opening_window(seconds: float) -> None:
    with pytest.raises(ValueError, match="positive and finite"):
        show_demo_encounter(step_seconds=seconds)


def test_desktop_scheduling_seam_forwards_to_tk_without_a_display() -> None:
    calls: list[tuple[int, Callable[[], None]]] = []

    class FakeRoot:
        def after(self, milliseconds: int, callback: Callable[[], None]) -> None:
            calls.append((milliseconds, callback))

    window = desktop.LiveEncounterPreviewWindow.__new__(desktop.LiveEncounterPreviewWindow)
    window._root = FakeRoot()
    def callback() -> None:
        pass

    window.call_later(1250, callback)
    assert calls == [(1250, callback)]
    with pytest.raises(ValueError, match="positive"):
        window.call_later(0, callback)
    assert len(calls) == 1
