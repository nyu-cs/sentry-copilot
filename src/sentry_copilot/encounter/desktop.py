"""Minimal optional Tk desktop panel for an immutable encounter-preview view."""

from __future__ import annotations

from collections.abc import Callable
from queue import Empty, Queue

from sentry_copilot.services.live_encounter_preview import LiveEncounterPreviewSnapshot

from .presentation import EncounterPanelView

_LOCALE_OPTIONS = {"zh_CN": "简体中文", "en": "English"}
_LOCALE_IDS_BY_LABEL = {label: locale_id for locale_id, label in _LOCALE_OPTIONS.items()}


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
    """Tiny queue-driven Tk adapter; it is presentation-only and never reads capture pixels."""

    def __init__(
        self,
        initial: LiveEncounterPreviewSnapshot,
        *,
        on_locale: Callable[[str], LiveEncounterPreviewSnapshot],
        diagnostic_text: Callable[[], str],
        on_close: Callable[[], None],
        always_on_top: bool = True,
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
        self._root.minsize(400, 0)
        self._root.protocol("WM_DELETE_WINDOW", self._close)
        self._outer = ttk.Frame(self._root, padding=12)
        self._outer.grid()
        self._outer.grid_columnconfigure(0, weight=1)
        self._locale = tk.StringVar(value=_locale_label(initial.locale_id))
        self._title = tk.StringVar()
        self._status = tk.StringVar()
        self._recovery_reminder = tk.StringVar()
        self._build = tk.StringVar()
        self._diagnostics_label = tk.StringVar()
        self._items = [tk.StringVar() for _ in initial.presentation.items]
        self._build_widgets()
        self._render(initial)

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
        ttk.Label(self._outer, textvariable=self._title, style="Live.Title.TLabel").grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Label(
            self._outer, textvariable=self._status, wraplength=420, style="Live.Status.TLabel"
        ).grid(row=2, column=0, sticky="ew", pady=(5, 6))
        ttk.Label(
            self._outer,
            textvariable=self._recovery_reminder,
            wraplength=420,
            style="Live.Reminder.TLabel",
        ).grid(row=3, column=0, sticky="ew", pady=(0, 6))
        for index, item in enumerate(self._items, start=4):
            ttk.Label(self._outer, textvariable=item, style="Live.Item.TLabel").grid(
                row=index, column=0, sticky="w", pady=3
            )
        row = len(self._items) + 4
        controls = ttk.Frame(self._outer)
        controls.grid(row=row, column=0, sticky="w", pady=(8, 0))
        ttk.Button(
            controls, textvariable=self._diagnostics_label, command=self._copy_diagnostics
        ).grid(row=0, column=0)
        ttk.Label(self._outer, textvariable=self._build, style="Live.Build.TLabel").grid(
            row=row + 1, column=0, sticky="w", pady=(6, 0)
        )

    def _render(self, snapshot: LiveEncounterPreviewSnapshot) -> None:
        view = snapshot.presentation
        self._root.title(view.title)
        self._locale.set(_locale_label(snapshot.locale_id))
        self._title.set(f"{view.title}    {view.progress_label}")
        self._status.set(snapshot.status_message)
        self._recovery_reminder.set(snapshot.recovery_reminder_text or "")
        for target, item in zip(self._items, view.items, strict=True):
            marker = "✓" if item.complete else "○"
            target.set(f"{marker} {item.label}: {item.value}")
        self._build.set("Build: live-encounter-preview-v0.1")
        self._diagnostics_label.set(
            "复制诊断信息" if snapshot.locale_id == "zh_CN" else "Copy Diagnostics"
        )

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

    def _copy_diagnostics(self) -> None:
        self._root.clipboard_clear()
        self._root.clipboard_append(self._diagnostic_text())

    def _close(self) -> None:
        self._on_close()
        self._root.destroy()


def _locale_label(locale_id: str) -> str:
    """Map only the two existing locale IDs to friendly control text."""

    return _LOCALE_OPTIONS.get(locale_id, locale_id)
