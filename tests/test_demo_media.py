from __future__ import annotations

import base64
from dataclasses import replace
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from sentry_copilot.demo.encounter import build_demo_timeline
from sentry_copilot.demo.media import build_demo_media
from sentry_copilot.encounter import desktop


def test_procedural_media_is_deterministic_distinct_and_immutable() -> None:
    view = build_demo_timeline()[-1].presentation
    first, second = build_demo_media(view), build_demo_media(view)
    for first_images, second_images, size in (
        (first.covenant_icons, second.covenant_icons, 40),
        (first.operator_portraits, second.operator_portraits, 60),
    ):
        assert tuple(first_images) == tuple(second_images)
        assert len({image.tobytes() for image in first_images.values()}) == len(first_images)
        for identity, image in first_images.items():
            assert np.array_equal(image, second_images[identity])
            assert image.shape == (size, size, 4)
            assert image.dtype == np.uint8
            assert not image.flags.writeable
            assert np.count_nonzero(image[:, :, 3]) > 0
    assert all(image[0, 0, 3] == 0 for image in first.covenant_icons.values())
    with pytest.raises(TypeError):
        first.covenant_icons["new"] = np.zeros((40, 40, 4), dtype=np.uint8)  # type: ignore[index]


def test_media_covers_seven_rows_and_four_consistent_operator_identities() -> None:
    view = build_demo_timeline()[-1].presentation
    media = build_demo_media(view)
    assert len(media.covenant_icons) == len(view.confirmed_banned_operator_rows) == 7
    assert len(media.operator_portraits) == 4
    seen: dict[str, np.ndarray] = {}
    for row in view.confirmed_banned_operator_rows:
        assert row.covenant_id in media.covenant_icons
        for card in row.operators:
            portrait = media.operator_portraits[card.operator_id]
            assert portrait is seen.setdefault(card.operator_id, portrait)
    chinese = build_demo_media(build_demo_timeline("zh_CN")[-1].presentation)
    assert all(
        np.array_equal(image, chinese.operator_portraits[identity])
        for identity, image in media.operator_portraits.items()
    )


def test_media_generation_uses_no_file_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    view = build_demo_timeline()[-1].presentation

    def unexpected(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("procedural graphics attempted file access")

    for name in ("open", "read_text", "read_bytes"):
        monkeypatch.setattr(Path, name, unexpected)
    media = build_demo_media(view)
    assert len(media.covenant_icons) == 7 and len(media.operator_portraits) == 4


def test_in_memory_seam_owns_a_copy_and_preserves_alpha() -> None:
    source = np.zeros((60, 60, 4), dtype=np.uint8)
    source[20:40, 20:40] = (30, 40, 50, 255)
    original = source.copy()
    owned = desktop._copy_preview_images({"demo": source})
    source[:] = 0
    assert np.array_equal(owned["demo"], original)
    assert not owned["demo"].flags.writeable
    assert desktop._copy_preview_images(None) == {}


@pytest.mark.parametrize("shape", [(0, 60, 4), (60, 0, 3), (60, 60), (60, 60, 2)])
def test_in_memory_seam_rejects_invalid_pixels(shape: tuple[int, ...]) -> None:
    with pytest.raises(ValueError, match="BGR/BGRA"):
        desktop._copy_preview_images({"demo": np.zeros(shape, dtype=np.uint8)})


def _bare_window() -> desktop.LiveEncounterPreviewWindow:
    window = desktop.LiveEncounterPreviewWindow.__new__(desktop.LiveEncounterPreviewWindow)
    window._portrait_images = desktop._PortraitImageCache()
    window._covenant_images = desktop._PortraitImageCache()
    window._portrait_sources = None
    window._portrait_cache_root = None
    window._covenant_icon_sources = {}
    window._operator_portrait_images = {}
    window._covenant_icon_images = {}
    return window


def test_real_resolvers_use_in_memory_assets_and_cache_repeated_portraits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = build_demo_timeline()[-1].presentation
    media = build_demo_media(view)
    window = _bare_window()
    window._operator_portrait_images = desktop._copy_preview_images(media.operator_portraits)
    window._covenant_icon_images = desktop._copy_preview_images(media.covenant_icons)
    loads: list[int] = []

    def memory_loader(image: np.ndarray, size: int) -> object:
        assert image.shape == (size, size, 4)
        loads.append(size)
        return object()

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("memory-only Ban Detail attempted a file loader")

    monkeypatch.setattr(window, "_load_memory_photoimage", memory_loader)
    monkeypatch.setattr(window, "_load_portrait_photoimage", forbidden)
    monkeypatch.setattr(window, "_load_covenant_icon_photoimage", forbidden)
    resolved: dict[str, object] = {}
    for row in view.confirmed_banned_operator_rows:
        assert window._covenant_icon_for(row.covenant_id) is not None
        for card in row.operators:
            portrait = window._portrait_for(card)
            assert portrait is not None
            assert portrait is resolved.setdefault(card.operator_id, portrait)
    assert loads.count(40) == 7
    assert loads.count(60) == 4
    assert window._portrait_images.retained_image_count == 4
    assert window._covenant_images.retained_image_count == 7


def test_empty_overrides_preserve_file_backed_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    view = build_demo_timeline()[-1].presentation
    row = view.confirmed_banned_operator_rows[0]
    card = replace(row.operators[0], portrait_key="synthetic:existing-source")
    window = _bare_window()
    window._portrait_sources = object()
    icon_path = Path("synthetic-existing-icon")
    window._covenant_icon_sources = {row.covenant_id: icon_path}
    calls: list[object] = []
    portrait, icon = object(), object()

    def portrait_loader(key: str) -> object:
        calls.append(key)
        return portrait

    def icon_loader(path: Path) -> object:
        calls.append(path)
        return icon

    monkeypatch.setattr(window, "_load_portrait_photoimage", portrait_loader)
    monkeypatch.setattr(window, "_load_covenant_icon_photoimage", icon_loader)
    assert window._portrait_for(card) is portrait
    assert window._covenant_icon_for(row.covenant_id) is icon
    assert calls == [card.portrait_key, icon_path]


def test_memory_photoimage_keeps_production_dimensions_and_png_alpha() -> None:
    window = _bare_window()

    class FakeTk:
        TclError = RuntimeError

        @staticmethod
        def PhotoImage(*, data: bytes) -> bytes:
            return base64.b64decode(data)

    window._tk = FakeTk()
    media = build_demo_media(build_demo_timeline()[-1].presentation)
    for image, size in (
        (next(iter(media.covenant_icons.values())), 40),
        (next(iter(media.operator_portraits.values())), 60),
    ):
        encoded = window._load_memory_photoimage(image, size)
        assert isinstance(encoded, bytes)
        decoded = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        assert decoded.shape == (size, size, 4)
        assert np.array_equal(image, decoded)
