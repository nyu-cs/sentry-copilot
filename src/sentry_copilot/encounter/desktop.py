"""Minimal optional Tk desktop panel for an immutable encounter-preview view."""

from __future__ import annotations

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
