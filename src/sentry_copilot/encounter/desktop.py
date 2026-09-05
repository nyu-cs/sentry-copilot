"""Minimal optional Tk desktop panel for an immutable encounter-preview view."""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from queue import Empty, Queue
from typing import Any

import cv2
import numpy as np

from sentry_copilot.catalogs.operator_portrait_sources import (
    OperatorPortraitSourceCatalog,
    default_operator_portrait_private_cache_root,
    load_default_operator_portrait_source_catalog,
)
from sentry_copilot.services.live_encounter_preview import LiveEncounterPreviewSnapshot

from .presentation import ConfirmedBannedOperatorCardView, EncounterPanelView

_LOCALE_OPTIONS = {"zh_CN": "简体中文", "en": "English"}
_LOCALE_IDS_BY_LABEL = {label: locale_id for locale_id, label in _LOCALE_OPTIONS.items()}


class PreviewPage(StrEnum):
    """Window-local navigation only; never part of encounter/controller state."""

    MAIN = "main"
    BAN_DETAIL = "ban_detail"


@dataclass(frozen=True)
class PreviewPageGeometry:
    width: int
    height: int

    @property
    def tk_geometry(self) -> str:
        return f"{self.width}x{self.height}"


_PAGE_GEOMETRIES = {
    PreviewPage.MAIN: PreviewPageGeometry(width=460, height=450),
    PreviewPage.BAN_DETAIL: PreviewPageGeometry(width=780, height=560),
}


@dataclass(frozen=True)
class _MainContentLayout:
    """Fixed MAIN-page slots; live text changes must not alter row geometry."""

    content_width: int = 420
    header_height: int = 28
    reminder_height: int = 42
    item_height: int = 34
    details_button_height: int = 32
    footer_height: int = 32


_MAIN_CONTENT_LAYOUT = _MainContentLayout()


@dataclass(frozen=True)
class PreviewPageState:
    """Pure navigation seam that makes page stability testable without Tk."""

    page: PreviewPage = PreviewPage.MAIN

    @property
    def geometry(self) -> PreviewPageGeometry:
        return _PAGE_GEOMETRIES[self.page]

    def open_ban_detail(self) -> PreviewPageState:
        return PreviewPageState(PreviewPage.BAN_DETAIL)

    def return_to_main(self) -> PreviewPageState:
        return PreviewPageState(PreviewPage.MAIN)

    def preserve_for_live_update(self) -> PreviewPageState:
        return self


BanDetailContentSignature = tuple[
    str,
    tuple[
        tuple[
            str,
            str,
            tuple[tuple[str, str, int, str | None], ...],
        ],
        ...,
    ],
]


def _ban_detail_content_signature(
    view: EncounterPanelView,
    locale_id: str,
) -> BanDetailContentSignature:
    """Return the complete visible Ban-card content identity for one locale."""

    return (
        locale_id,
        tuple(
            (
                row.covenant_id,
                row.display_name,
                tuple(
                    (
                        card.operator_id,
                        card.display_name,
                        card.tier,
                        card.portrait_key,
                    )
                    for card in row.operators
                ),
            )
            for row in view.confirmed_banned_operator_rows
        ),
    )


@dataclass(frozen=True)
class _BanDetailRenderState:
    """Track the last materialized detail view without making it controller state."""

    rendered_signature: BanDetailContentSignature | None = None

    def needs_render(
        self,
        page: PreviewPage,
        signature: BanDetailContentSignature,
    ) -> bool:
        return page is PreviewPage.BAN_DETAIL and signature != self.rendered_signature

    def after_render(self, signature: BanDetailContentSignature) -> _BanDetailRenderState:
        return _BanDetailRenderState(rendered_signature=signature)


class _PortraitImageCache:
    """Retain Tk images strongly and avoid repeated private-cache reads across live updates."""

    def __init__(self) -> None:
        self._images: dict[tuple[str, int], Any] = {}
        self._unavailable: set[tuple[str, int]] = set()

    def get_or_load(
        self,
        portrait_key: str,
        display_size: int,
        loader: Callable[[], Any | None],
    ) -> Any | None:
        cache_key = (portrait_key, display_size)
        if cache_key in self._images:
            return self._images[cache_key]
        if cache_key in self._unavailable:
            return None
        image = loader()
        if image is None:
            self._unavailable.add(cache_key)
            return None
        self._images[cache_key] = image
        return image

    @property
    def retained_image_count(self) -> int:
        return len(self._images)


def _set_if_changed(variable: Any, value: str) -> bool:
    """Avoid invalidating Tk text when a live snapshot repeats the same value."""

    if variable.get() == value:
        return False
    variable.set(value)
    return True


def _ban_detail_empty_text(*, has_rows: bool, locale_id: str) -> str:
    """Derive the empty-state text from current content, not row-render side effects."""

    if has_rows:
        return ""
    return "暂无已确认禁用干员" if locale_id == "zh_CN" else "No confirmed banned operators"


def _resize_portrait_image(image: np.ndarray, display_size: int) -> np.ndarray:
    """Locally downscale a decoded BGR/BGRA portrait once while retaining alpha."""

    if display_size <= 0:
        raise ValueError("portrait display size must be positive")
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError("portrait image must be BGR or BGRA")
    return cv2.resize(image, (display_size, display_size), interpolation=cv2.INTER_AREA)


def show_encounter_panel(view: EncounterPanelView, *, always_on_top: bool = True) -> None:
    """Open a compact caller-owned panel; capture code never reads this window as input."""

    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(view.title)
    root.attributes("-topmost", always_on_top)
    root.resizable(False, False)
    outer = ttk.Frame(root, padding=10)
    outer.grid()
    ttk.Label(outer, text=f"{view.title}    {view.progress_label}").grid(
        row=0, column=0, sticky="w"
    )
    for index, item in enumerate(view.items, start=1):
        marker = "✓" if item.complete else "○"
        ttk.Label(outer, text=f"{marker} {item.label}: {item.value}").grid(
            row=index, column=0, sticky="w", pady=2
        )
    row = len(view.items) + 1
    if view.map_knowledge_heading is not None:
        ttk.Label(outer, text=view.map_knowledge_heading).grid(
            row=row, column=0, sticky="w", pady=(8, 2)
        )
        for entry in view.map_knowledge:
            row += 1
            ttk.Label(outer, text=f"• {entry.title}: {entry.description}", wraplength=320).grid(
                row=row, column=0, sticky="w"
            )
    root.mainloop()


def show_localized_encounter_panel(
    views_by_locale: dict[str, EncounterPanelView],
    *,
    initial_locale_id: str = "zh_CN",
    always_on_top: bool = True,
) -> None:
    """Open one optional panel whose language can change without changing encounter facts."""

    if not views_by_locale:
        raise ValueError("at least one localized encounter view is required")
    import tkinter as tk
    from tkinter import ttk

    current_locale_id = (
        initial_locale_id if initial_locale_id in views_by_locale else next(iter(views_by_locale))
    )
    root = tk.Tk()
    root.attributes("-topmost", always_on_top)
    root.resizable(False, False)
    outer = ttk.Frame(root, padding=10)
    outer.grid()
    locale = tk.StringVar(value=current_locale_id)

    def render() -> None:
        view = views_by_locale[locale.get()]
        root.title(view.title)
        for child in outer.winfo_children():
            child.destroy()
        ttk.Combobox(
            outer,
            textvariable=locale,
            values=tuple(views_by_locale),
            state="readonly",
            width=10,
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(outer, text=f"{view.title}    {view.progress_label}").grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )
        for index, item in enumerate(view.items, start=2):
            marker = "✓" if item.complete else "○"
            ttk.Label(outer, text=f"{marker} {item.label}: {item.value}").grid(
                row=index, column=0, sticky="w", pady=2
            )
        row = len(view.items) + 2
        if view.map_knowledge_heading is not None:
            ttk.Label(outer, text=view.map_knowledge_heading).grid(
                row=row, column=0, sticky="w", pady=(8, 2)
            )
            for entry in view.map_knowledge:
                row += 1
                ttk.Label(
                    outer,
                    text=f"• {entry.title}: {entry.description}",
                    wraplength=320,
                ).grid(row=row, column=0, sticky="w")
        selector = outer.winfo_children()[0]
        selector.bind("<<ComboboxSelected>>", lambda _event: render())

    render()
    root.mainloop()


class LiveEncounterPreviewWindow:
    """Queue-driven same-window preview with page-local navigation and no capture authority."""

    def __init__(
        self,
        initial: LiveEncounterPreviewSnapshot,
        *,
        on_locale: Callable[[str], LiveEncounterPreviewSnapshot],
        diagnostic_text: Callable[[], str],
        on_close: Callable[[], None],
        always_on_top: bool = True,
        portrait_sources: OperatorPortraitSourceCatalog | None = None,
        portrait_cache_root: Path | None = None,
    ) -> None:
        import tkinter as tk
        from tkinter import ttk

        self._tk = tk
        self._ttk = ttk
        self._queue: Queue[LiveEncounterPreviewSnapshot] = Queue()
        self._on_locale = on_locale
        self._diagnostic_text = diagnostic_text
        self._on_close = on_close
        self._root = tk.Tk()
        # Keep the standard Windows title bar: it is the primary drag surface.
        self._root.overrideredirect(False)
        self._root.attributes("-topmost", always_on_top)
        self._root.resizable(False, False)
        self._root.protocol("WM_DELETE_WINDOW", self._close)
        self._outer = ttk.Frame(self._root, padding=12)
        self._outer.grid()
        self._outer.grid_columnconfigure(0, weight=1)
        self._page_state = PreviewPageState()
        self._ban_detail_render_state = _BanDetailRenderState()
        self._portrait_sources = portrait_sources or _try_load_portrait_sources()
        self._portrait_cache_root = (
            portrait_cache_root or default_operator_portrait_private_cache_root()
        )
        self._portrait_images = _PortraitImageCache()
        self._locale = tk.StringVar(value=_locale_label(initial.locale_id))
        self._title = tk.StringVar()
        self._status = tk.StringVar()
        self._recovery_reminder = tk.StringVar()
        self._build = tk.StringVar()
        self._diagnostics_label = tk.StringVar()
        self._items = [tk.StringVar() for _ in initial.presentation.items]
        self._ban_details_label = tk.StringVar()
        self._back_label = tk.StringVar()
        self._ban_detail_title = tk.StringVar()
        self._ban_detail_subtitle = tk.StringVar()
        self._ban_detail_empty = tk.StringVar()
        self._latest_ban_view = initial.presentation
        self._latest_ban_locale_id = initial.locale_id
        self._build_widgets()
        self._render(initial)
        self._apply_page()

    def publish(self, snapshot: LiveEncounterPreviewSnapshot) -> None:
        """Thread-safe producer entrypoint for the capture worker."""

        self._queue.put(snapshot)

    def run(self) -> None:
        self._root.after(100, self._drain)
        self._root.mainloop()

    def _build_widgets(self) -> None:
        ttk = self._ttk
        style = ttk.Style(self._root)
        style.configure("Live.Title.TLabel", font=("TkDefaultFont", 14, "bold"))
        style.configure("Live.Item.TLabel", font=("TkDefaultFont", 12))
        style.configure("Live.Status.TLabel", font=("TkDefaultFont", 11))
        style.configure("Live.Reminder.TLabel", font=("TkDefaultFont", 11, "bold"))
        style.configure("Live.Build.TLabel", font=("TkDefaultFont", 8))
        selector_row = ttk.Frame(self._outer)
        selector_row.grid(row=0, column=0, sticky="ew")
        ttk.Label(selector_row, text="语言 / Language", style="Live.Status.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        selector = ttk.Combobox(
            selector_row,
            textvariable=self._locale,
            values=tuple(_LOCALE_OPTIONS.values()),
            state="readonly",
            width=12,
        )
        selector.grid(row=0, column=1, sticky="w")
        selector.bind("<<ComboboxSelected>>", self._change_locale)
        self._main_page = ttk.Frame(self._outer)
        self._main_page.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self._main_page.grid_columnconfigure(0, weight=1)
        self._fixed_main_text_slot(
            row=0,
            height=_MAIN_CONTENT_LAYOUT.header_height,
            variable=self._title,
            style="Live.Title.TLabel",
        )
        self._fixed_main_text_slot(
            row=1,
            height=_MAIN_CONTENT_LAYOUT.reminder_height,
            variable=self._recovery_reminder,
            style="Live.Reminder.TLabel",
            pady=(5, 6),
        )
        for index, item in enumerate(self._items, start=2):
            self._fixed_main_text_slot(
                row=index,
                height=_MAIN_CONTENT_LAYOUT.item_height,
                variable=item,
                style="Live.Item.TLabel",
                pady=3,
            )
        details_slot = ttk.Frame(
            self._main_page,
            width=_MAIN_CONTENT_LAYOUT.content_width,
            height=_MAIN_CONTENT_LAYOUT.details_button_height,
        )
        details_slot.grid(row=len(self._items) + 2, column=0, sticky="w", pady=(7, 0))
        details_slot.grid_propagate(False)
        self._ban_details_button = ttk.Button(
            details_slot,
            textvariable=self._ban_details_label,
            command=self._open_ban_detail,
        )
        self._ban_details_button.place(x=0, y=0)

        self._ban_detail_page = ttk.Frame(self._outer)
        self._ban_detail_page.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self._ban_detail_page.grid_columnconfigure(1, weight=1)
        ttk.Button(
            self._ban_detail_page,
            textvariable=self._back_label,
            command=self._return_to_main,
        ).grid(row=0, column=0, sticky="w", padx=(0, 12))
        detail_heading = ttk.Frame(self._ban_detail_page)
        detail_heading.grid(row=0, column=1, sticky="w")
        ttk.Label(
            detail_heading,
            textvariable=self._ban_detail_title,
            style="Live.Title.TLabel",
        ).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            detail_heading,
            textvariable=self._ban_detail_subtitle,
            style="Live.Status.TLabel",
        ).grid(
            row=1, column=0, sticky="w"
        )
        self._ban_rows = ttk.Frame(self._ban_detail_page)
        self._ban_rows.grid(row=1, column=0, columnspan=2, sticky="nw", pady=(14, 0))
        ttk.Label(
            self._ban_detail_page,
            textvariable=self._ban_detail_empty,
            style="Live.Status.TLabel",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 0))

        footer = ttk.Frame(
            self._outer,
            width=_MAIN_CONTENT_LAYOUT.content_width,
            height=_MAIN_CONTENT_LAYOUT.footer_height,
        )
        footer.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        footer.grid_propagate(False)
        ttk.Label(
            footer,
            textvariable=self._status,
            wraplength=_MAIN_CONTENT_LAYOUT.content_width,
            justify="left",
            style="Live.Status.TLabel",
        ).place(x=0, y=0, relwidth=1, relheight=1)
        controls = ttk.Frame(self._outer)
        controls.grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Button(
            controls, textvariable=self._diagnostics_label, command=self._copy_diagnostics
        ).grid(row=0, column=0)
        ttk.Label(self._outer, textvariable=self._build, style="Live.Build.TLabel").grid(
            row=4, column=0, sticky="w", pady=(6, 0)
        )

    def _fixed_main_text_slot(
        self,
        *,
        row: int,
        height: int,
        variable: Any,
        style: str,
        pady: int | tuple[int, int] = 0,
    ) -> None:
        """Build one immutable, bounded MAIN text slot exactly once."""

        slot = self._ttk.Frame(
            self._main_page,
            width=_MAIN_CONTENT_LAYOUT.content_width,
            height=height,
        )
        slot.grid(row=row, column=0, sticky="w", pady=pady)
        slot.grid_propagate(False)
        self._ttk.Label(
            slot,
            textvariable=variable,
            wraplength=_MAIN_CONTENT_LAYOUT.content_width,
            justify="left",
            style=style,
            anchor="nw",
        ).place(x=0, y=0, relwidth=1, relheight=1)

    def _render(self, snapshot: LiveEncounterPreviewSnapshot) -> None:
        view = snapshot.presentation
        self._latest_ban_view = view
        self._latest_ban_locale_id = snapshot.locale_id
        self._root.title(view.title)
        _set_if_changed(self._locale, _locale_label(snapshot.locale_id))
        _set_if_changed(self._title, f"{view.title}    {view.progress_label}")
        _set_if_changed(self._status, snapshot.status_message)
        _set_if_changed(self._recovery_reminder, snapshot.recovery_reminder_text or "")
        for target, item in zip(self._items, view.items, strict=True):
            marker = "✓" if item.complete else "○"
            _set_if_changed(target, f"{marker} {item.label}: {item.value}")
        _set_if_changed(self._build, "Build: live-encounter-preview-v0.1")
        _set_if_changed(
            self._diagnostics_label,
            "复制诊断信息" if snapshot.locale_id == "zh_CN" else "Copy Diagnostics"
        )
        _set_if_changed(
            self._ban_details_label, "禁用详情" if snapshot.locale_id == "zh_CN" else "Ban Details"
        )
        _set_if_changed(self._back_label, "< 返回" if snapshot.locale_id == "zh_CN" else "< Back")
        _set_if_changed(
            self._ban_detail_title, "禁用详情" if snapshot.locale_id == "zh_CN" else "Ban Details"
        )
        _set_if_changed(
            self._ban_detail_subtitle,
            "当前仅主盟约" if snapshot.locale_id == "zh_CN" else "Major Covenants only"
        )
        _set_if_changed(
            self._ban_detail_empty,
            _ban_detail_empty_text(
                has_rows=bool(view.confirmed_banned_operator_rows), locale_id=snapshot.locale_id
            ),
        )
        self._ban_details_button.configure(
            state="normal" if view.confirmed_banned_operator_rows else "disabled"
        )
        self._render_ban_rows_if_needed(view, snapshot.locale_id)
        self._page_state = self._page_state.preserve_for_live_update()

    def _drain(self) -> None:
        latest: LiveEncounterPreviewSnapshot | None = None
        while True:
            try:
                latest = self._queue.get_nowait()
            except Empty:
                break
        if latest is not None:
            self._render(latest)
        self._root.after(100, self._drain)

    def _change_locale(self, _event: object) -> None:
        locale_id = _LOCALE_IDS_BY_LABEL.get(self._locale.get())
        if locale_id is not None:
            self._render(self._on_locale(locale_id))

    def _open_ban_detail(self) -> None:
        self._page_state = self._page_state.open_ban_detail()
        self._render_ban_rows_if_needed(self._latest_ban_view, self._latest_ban_locale_id)
        self._apply_page()

    def _return_to_main(self) -> None:
        self._page_state = self._page_state.return_to_main()
        self._apply_page()

    def _apply_page(self) -> None:
        if self._page_state.page is PreviewPage.MAIN:
            self._ban_detail_page.grid_remove()
            self._main_page.grid()
        else:
            self._main_page.grid_remove()
            self._ban_detail_page.grid()
        geometry = self._page_state.geometry
        self._root.minsize(geometry.width, geometry.height)
        self._root.maxsize(geometry.width, geometry.height)
        self._root.geometry(geometry.tk_geometry)

    def _render_ban_rows_if_needed(self, view: EncounterPanelView, locale_id: str) -> None:
        signature = _ban_detail_content_signature(view, locale_id)
        if not self._ban_detail_render_state.needs_render(self._page_state.page, signature):
            return
        for child in self._ban_rows.winfo_children():
            child.destroy()
        for row_index, row in enumerate(view.confirmed_banned_operator_rows):
            row_frame = self._ttk.Frame(self._ban_rows)
            row_frame.grid(row=row_index, column=0, sticky="w", pady=(0, 12))
            self._ttk.Label(
                row_frame,
                text=row.display_name,
                style="Live.Item.TLabel",
                width=12,
            ).grid(row=0, column=0, sticky="n", padx=(0, 10))
            cards = self._ttk.Frame(row_frame)
            cards.grid(row=0, column=1, sticky="w")
            for card_index, card in enumerate(row.operators):
                self._render_ban_card(cards, card, locale_id, card_index)
        self._ban_detail_render_state = self._ban_detail_render_state.after_render(signature)

    def _render_ban_card(
        self,
        parent: Any,
        card: ConfirmedBannedOperatorCardView,
        locale_id: str,
        column: int,
    ) -> None:
        frame = self._ttk.Frame(parent)
        frame.grid(row=0, column=column, padx=(0, 10))
        image = self._portrait_for(card)
        if image is None:
            self._ttk.Label(frame, text="—", width=8, anchor="center").grid(row=0, column=0)
        else:
            self._ttk.Label(frame, image=image).grid(row=0, column=0)
        self._ttk.Label(frame, text=card.display_name, width=10, anchor="center").grid(
            row=1, column=0
        )
        tier = f"{card.tier}本" if locale_id == "zh_CN" else f"Tier {card.tier}"
        self._ttk.Label(frame, text=tier, anchor="center").grid(row=2, column=0)

    def _portrait_for(self, card: ConfirmedBannedOperatorCardView) -> Any | None:
        portrait_key = card.portrait_key
        if portrait_key is None or self._portrait_sources is None:
            return None
        return self._portrait_images.get_or_load(
            portrait_key,
            60,
            lambda: self._load_portrait_photoimage(portrait_key),
        )

    def _load_portrait_photoimage(self, portrait_key: str) -> Any | None:
        source = (
            self._portrait_sources.by_portrait_key(portrait_key)
            if self._portrait_sources
            else None
        )
        if source is None:
            return None
        path = OperatorPortraitSourceCatalog.private_cache_path(
            self._portrait_cache_root,
            source.portrait_key,
        )
        try:
            decoded = cv2.imdecode(
                np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_UNCHANGED
            )
            if decoded is None:
                return None
            resized = _resize_portrait_image(decoded, 60)
            success, encoded = cv2.imencode(".png", resized)
            if not success:
                return None
            image = self._tk.PhotoImage(data=base64.b64encode(encoded.tobytes()))
        except (OSError, ValueError, self._tk.TclError):
            return None
        return image

    def _copy_diagnostics(self) -> None:
        self._root.clipboard_clear()
        self._root.clipboard_append(self._diagnostic_text())

    def _close(self) -> None:
        self._on_close()
        self._root.destroy()


def _locale_label(locale_id: str) -> str:
    """Map only the two existing locale IDs to friendly control text."""

    return _LOCALE_OPTIONS.get(locale_id, locale_id)


def _try_load_portrait_sources() -> OperatorPortraitSourceCatalog | None:
    """Optional local-only manifest load; portrait failure must not affect Ban text rendering."""

    try:
        return load_default_operator_portrait_source_catalog()
    except (OSError, ValueError):
        return None
