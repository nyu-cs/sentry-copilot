"""Minimal optional Tk desktop panel for an immutable encounter-preview view."""

from __future__ import annotations

from collections.abc import Callable
from queue import Empty, Queue

from sentry_copilot.services.live_encounter_preview import LiveEncounterPreviewSnapshot

from .presentation import EncounterPanelView


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
    if view.difficulty_value is not None:
        ttk.Label(outer, text=f"{view.difficulty_label}: {view.difficulty_value}").grid(
            row=row, column=0, sticky="w", pady=2
        )
        row += 1
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
        if view.difficulty_value is not None:
            ttk.Label(outer, text=f"{view.difficulty_label}: {view.difficulty_value}").grid(
                row=row, column=0, sticky="w", pady=2
            )
            row += 1
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
        self._root.attributes("-topmost", always_on_top)
        self._root.resizable(False, False)
        self._root.protocol("WM_DELETE_WINDOW", self._close)
        self._outer = ttk.Frame(self._root, padding=10)
        self._outer.grid()
        self._locale = tk.StringVar(value=initial.locale_id)
        self._title = tk.StringVar()
        self._status = tk.StringVar()
        self._build = tk.StringVar()
        self._difficulty = tk.StringVar()
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
        ttk.Combobox(
            self._outer,
            textvariable=self._locale,
            values=("zh_CN", "en"),
            state="readonly",
            width=10,
        ).grid(row=0, column=0, sticky="w")
        self._outer.winfo_children()[0].bind("<<ComboboxSelected>>", self._change_locale)
        ttk.Label(self._outer, textvariable=self._title).grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )
        ttk.Label(self._outer, textvariable=self._status, wraplength=340).grid(
            row=2, column=0, sticky="w", pady=(4, 4)
        )
        for index, item in enumerate(self._items, start=3):
            ttk.Label(self._outer, textvariable=item).grid(row=index, column=0, sticky="w", pady=2)
        row = len(self._items) + 3
        ttk.Label(self._outer, textvariable=self._difficulty).grid(
            row=row, column=0, sticky="w", pady=2
        )
        controls = ttk.Frame(self._outer)
        controls.grid(row=row + 1, column=0, sticky="w", pady=(8, 0))
        ttk.Button(controls, text="Copy Diagnostics", command=self._copy_diagnostics).grid(
            row=0, column=0
        )
        ttk.Label(self._outer, textvariable=self._build).grid(
            row=row + 2, column=0, sticky="w", pady=(6, 0)
        )

    def _render(self, snapshot: LiveEncounterPreviewSnapshot) -> None:
        view = snapshot.presentation
        self._root.title(view.title)
        self._locale.set(snapshot.locale_id)
        self._title.set(f"{view.title}    {view.progress_label}")
        self._status.set(snapshot.status_message)
        for target, item in zip(self._items, view.items, strict=True):
            marker = "✓" if item.complete else "○"
            target.set(f"{marker} {item.label}: {item.value}")
        self._difficulty.set(
            f"{view.difficulty_label}: {view.difficulty_value}" if view.difficulty_value else ""
        )
        self._build.set("Build: live-encounter-preview-v0.1")

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
        self._render(self._on_locale(self._locale.get()))

    def _copy_diagnostics(self) -> None:
        self._root.clipboard_clear()
        self._root.clipboard_append(self._diagnostic_text())

    def _close(self) -> None:
        self._on_close()
        self._root.destroy()
