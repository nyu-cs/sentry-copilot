from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from sentry_copilot.encounter.desktop import (
    _BAN_DETAIL_MAX_CARDS_PER_ROW,
    _MAIN_CONTENT_LAYOUT,
    _PAGE_GEOMETRIES,
    PreviewPage,
    PreviewPageState,
    _ban_card_grid_position,
    _ban_detail_content_signature,
    _ban_detail_empty_text,
    _ban_detail_group_label,
    _BanDetailRenderState,
    _BanDetailScrollState,
    _covenant_icon_source,
    _load_covenant_ui_icon_sources,
    _PortraitImageCache,
    _resize_portrait_image,
    _set_if_changed,
)
from sentry_copilot.encounter.presentation import (
    ConfirmedBannedOperatorCardView,
    ConfirmedBannedOperatorRowView,
    EncounterPanelView,
)


def _ban_view(
    *, covenant_name: str = "拉特兰", operator_name: str = "玛恩纳"
) -> EncounterPanelView:
    return EncounterPanelView(
        title="",
        progress_label="",
        items=(),
        difficulty_label="",
        difficulty_value=None,
        confirmed_banned_operator_rows=(
            ConfirmedBannedOperatorRowView(
                covenant_id="covenant.laterano",
                display_name=covenant_name,
                operators=(
                    ConfirmedBannedOperatorCardView(
                        operator_id="operator.mlynar",
                        display_name=operator_name,
                        tier=5,
                        portrait_key="prts:玛恩纳",
                    ),
                ),
            ),
        ),
    )


def test_preview_navigation_has_explicit_fixed_main_and_ban_detail_geometries() -> None:
    initial = PreviewPageState()
    detail = initial.open_ban_detail()
    returned = detail.return_to_main()

    assert initial.page is PreviewPage.MAIN
    assert initial.geometry == _PAGE_GEOMETRIES[PreviewPage.MAIN]
    assert detail.page is PreviewPage.BAN_DETAIL
    assert detail.geometry == _PAGE_GEOMETRIES[PreviewPage.BAN_DETAIL]
    assert detail.geometry.tk_geometry == "780x560"
    assert returned.page is PreviewPage.MAIN
    assert returned.geometry.tk_geometry == "460x445"


def test_live_updates_and_locale_changes_preserve_the_current_ui_page() -> None:
    detail = PreviewPageState().open_ban_detail()

    assert detail.preserve_for_live_update() is detail
    assert detail.preserve_for_live_update().page is PreviewPage.BAN_DETAIL
    assert detail.preserve_for_live_update().geometry == _PAGE_GEOMETRIES[PreviewPage.BAN_DETAIL]


def test_ban_detail_rows_rebuild_only_for_visible_changed_content() -> None:
    view = _ban_view()
    signature = _ban_detail_content_signature(view, "zh_CN")
    state = _BanDetailRenderState()

    assert not state.needs_render(PreviewPage.MAIN, signature)
    assert state.needs_render(PreviewPage.BAN_DETAIL, signature)
    rendered = state.after_render(signature)
    assert not rendered.needs_render(PreviewPage.BAN_DETAIL, signature)
    changed_signature = _ban_detail_content_signature(_ban_view(operator_name="银灰"), "zh_CN")
    assert not rendered.needs_render(PreviewPage.MAIN, changed_signature)


def test_ban_detail_signature_rebuilds_for_visible_locale_or_card_content_change() -> None:
    view = _ban_view()
    chinese = _ban_detail_content_signature(view, "zh_CN")
    rendered = _BanDetailRenderState().after_render(chinese)

    assert rendered.needs_render(PreviewPage.BAN_DETAIL, _ban_detail_content_signature(view, "en"))
    assert rendered.needs_render(
        PreviewPage.BAN_DETAIL,
        _ban_detail_content_signature(_ban_view(covenant_name="Laterano"), "zh_CN"),
    )


def test_ban_detail_group_headers_use_covenant_category_in_both_locales() -> None:
    major = "covenant.covenant_latter.aegir"
    additional = "covenant.covenant_latter.assault"

    assert _ban_detail_group_label(major, "zh_CN") == "主盟约"
    assert _ban_detail_group_label(additional, "zh_CN") == "追加盟约"
    assert _ban_detail_group_label(major, "en") == "Major Covenants"
    assert _ban_detail_group_label(additional, "en") == "Additional Covenants"


def test_ban_detail_scroll_reset_is_keyed_only_to_encounter_identity() -> None:
    initial = _BanDetailScrollState().after_snapshot("live-encounter:1")

    assert initial.needs_reset("live-encounter:1") is False
    assert initial.needs_reset("live-encounter:2") is True


def test_ban_detail_cards_wrap_at_a_bounded_seven_cards_per_row() -> None:
    assert _BAN_DETAIL_MAX_CARDS_PER_ROW == 7
    assert [_ban_card_grid_position(index) for index in range(9)] == [
        (0, 0),
        (0, 1),
        (0, 2),
        (0, 3),
        (0, 4),
        (0, 5),
        (0, 6),
        (1, 0),
        (1, 1),
    ]


def test_covenant_ui_icon_loader_uses_only_manifest_ui_paths(tmp_path: Path) -> None:
    root = tmp_path / "covenant_icons"
    ui_directory = root / "ui_40"
    ui_directory.mkdir(parents=True)
    success, encoded = cv2.imencode(".png", np.zeros((40, 40, 4), dtype=np.uint8))
    assert success
    ui_path = ui_directory / "aegir.png"
    ui_path.write_bytes(encoded.tobytes())
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "covenant_id": "covenant.covenant_latter.aegir",
                        "master_path": "master_128/vision-reference.png",
                        "ui_path": "ui_40/aegir.png",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert _load_covenant_ui_icon_sources(root) == {
        "covenant.covenant_latter.aegir": ui_path
    }


def test_covenant_icon_source_uses_normalized_id_and_has_a_text_only_fallback(
    tmp_path: Path,
) -> None:
    icon = tmp_path / "neutral-ui-icon.png"
    sources = {"covenant.covenant_latter.aegir": icon}

    assert _covenant_icon_source(sources, "covenant.covenant_latter.aegir") is icon
    assert _covenant_icon_source(sources, "covenant.covenant_latter.assault") is None


def test_portrait_image_cache_retains_images_and_does_not_reload_on_later_snapshots() -> None:
    cache = _PortraitImageCache()
    loaded: list[object] = []
    image = object()

    def loader() -> object:
        loaded.append(image)
        return image

    first = cache.get_or_load("prts:玛恩纳", 60, loader)
    second = cache.get_or_load("prts:玛恩纳", 60, loader)

    assert first is image
    assert second is image
    assert loaded == [image]
    assert cache.retained_image_count == 1


def test_missing_portrait_is_cached_as_a_text_card_fallback_without_repeated_disk_loads() -> None:
    cache = _PortraitImageCache()
    attempts = 0

    def missing_loader() -> None:
        nonlocal attempts
        attempts += 1
        return None

    assert cache.get_or_load("prts:missing", 60, missing_loader) is None
    assert cache.get_or_load("prts:missing", 60, missing_loader) is None
    assert attempts == 1
    assert cache.retained_image_count == 0


class _StringVariable:
    def __init__(self, value: str) -> None:
        self.value = value
        self.write_count = 0

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value
        self.write_count += 1


def test_main_layout_reserves_the_same_slots_for_empty_or_long_live_text() -> None:
    assert _MAIN_CONTENT_LAYOUT.reminder_height == 42
    assert _MAIN_CONTENT_LAYOUT.item_height == 34
    assert _MAIN_CONTENT_LAYOUT.ban_item_height == 66
    assert _PAGE_GEOMETRIES[PreviewPage.MAIN].tk_geometry == "460x445"


def test_live_string_variables_are_only_written_when_value_changes() -> None:
    variable = _StringVariable("unchanged")

    assert _set_if_changed(variable, "unchanged") is False
    assert variable.write_count == 0
    assert _set_if_changed(variable, "changed") is True
    assert variable.write_count == 1


def test_ban_detail_empty_text_is_derived_from_current_row_content() -> None:
    assert _ban_detail_empty_text(has_rows=True, locale_id="zh_CN") == ""
    assert _ban_detail_empty_text(has_rows=False, locale_id="zh_CN") == "暂无已确认禁用干员"
    assert _ban_detail_empty_text(has_rows=False, locale_id="en") == "No confirmed banned operators"


def test_portrait_resize_preserves_target_size_and_alpha_channel() -> None:
    portrait = np.zeros((180, 180, 4), dtype=np.uint8)
    portrait[:, :, 3] = 255
    portrait[0, 0, 3] = 0

    resized = _resize_portrait_image(portrait, 60)

    assert resized.shape == (60, 60, 4)
    assert resized.dtype == np.uint8
