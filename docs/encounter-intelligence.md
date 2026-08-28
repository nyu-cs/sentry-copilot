# Encounter intelligence / 本局情报

## Scope

The v0.1 encounter preview is player-count independent. It shows four ordinary capture items—Map,
Boss, Enemy Types, and Banned Covenants—and progress is therefore always based on four items. A
future Secret Boss item is optional and does not change that denominator.

This first vertical slice captures one calibrated simulation difficulty from a JP MuMu 1920×1080
`OPERATION` presentation. It does not yet recognize the randomized battlefield/map, Boss, Enemy
Types, Banned Covenants, Secret Boss, or any gameplay mechanics from pixels.

## Encounter boundary

`情報確認 1/2` is the authoritative future start boundary for a new encounter session. It occurs
before strategy selection and before the `OPERATION` presentation, so `OPERATION` must only enrich
the current session with map/difficulty facts and must never reset it. The retained calibration
material does not yet support a robust `情報確認 1/2` detector or reliable revisit deduplication;
v0.1 therefore exposes an explicit `EncounterStartObservation`/`begin_encounter` boundary without
inventing timing-based resets. A later observer must debounce one continuous `1/2` presentation and
must not reset when the same encounter returns from `2/2` to `1/2`.

The live preview can nevertheless reuse the already validated outside-run page observations and
their two-frame semantic debounce to mark the current encounter ended. This is an END boundary only:
it preserves prior facts, shows that the previous encounter ended, and never starts a new one. Until
`情報確認 1/2` is implemented, the preview is single-encounter-per-launch: closing and relaunching
creates a fresh encounter, with no reset button and no timing guess.

## Vision versus knowledge

Vision produces only immutable, provenance-bearing identity evidence:

```text
frame -> normalized battlefield identity
frame -> normalized simulation code + label -> difficulty_id
```

It does not infer terrain, targeting, deployment, or tactics from screenshots. Those facts live in
the curated map catalog as localized `MapKnowledgeEntry` records. Entries have a lightweight source
note and can be general or scoped to one or more difficulty IDs. Missing knowledge is normal: a
successfully captured battlefield remains complete even with no Map Intel section. Difficulty alone
does not complete Map.

`MapDefinition` and `DifficultyDefinition` are separate records. A map has a stable `map_id`, stage
code, optional localized names, optional game-knowledge-backed allowed difficulty IDs, and factual
map knowledge. A difficulty has its own stable `difficulty_id`, localized names, and optional
global modifiers. In
the current retained JP `OPERATION` frames, `AC-3` is a simulation/difficulty code and the lower
text `死地` is calibrated as `difficulty.covenant_latter.deadland`. Neither identifies the
randomized battlefield. The current catalog records `AC-3` on the difficulty definition, not as a
map ID; other OCR text in that ROI remains unresolved rather than being inferred from the code.

Future static Boss routes use the separate relationship `(boss_id, map_id) -> route asset / notes`.
They are not map facts and difficulty is not embedded in `map_id`.

## Presentation and safety

`present_encounter(...)` is a pure zh_CN/en view builder. Before battlefield recognition exists, it
renders `Map: Not captured` separately from `Difficulty: 死地`, and remains at `0 / 4`. The optional
Tk panel is a caller-owned, always-on-top-capable display; locale
switching changes only the view, never the immutable `EncounterSession`. Capture must read only the
game source window/frame, not this panel. Users should hide or suspend the panel when it would
obscure a capture target.

The included `AC-3` difficulty mapping contains only verified display metadata. No game image asset, replay,
or unlicensed screenshot is part of the repository. Broader online knowledge population, including
PRTS collection, is deliberately a later bounded task.

## Live preview v0.1

On the supported Windows JP MuMu fullscreen 1920×1080 display, launch:

```powershell
.\.venv\Scripts\python.exe -m sentry_copilot.cli live-encounter-preview --monitor 1 --locale zh_CN
```

The selected physical monitor is sampled at two frames per second. The compact panel shows a
player-facing running/waiting/error state, the supported profile, a small build identifier, and a
Copy Diagnostics action. `--diagnostic-output path\to\diagnostic.json` writes the same
personal-data-free local JSON only after the window closes. It never uploads diagnostics or records
gameplay.

Only the calibrated `AC-3` / `死地` difficulty evidence is implemented in this preview; battlefield
recognition is deferred. Boss, Enemy Types, and Banned Covenants remain explicitly marked as not
supported in this build rather than looking like failed recognition. The panel uses physical-monitor capture, so keep it away from the
calibrated OPERATION ROIs; the panel is never a vision input, but it can obscure the game if placed
over that display area.
