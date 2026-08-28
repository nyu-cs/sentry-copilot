# Encounter intelligence / 本局情报

## Scope

The v0.1 encounter preview is player-count independent. It shows four ordinary capture items—Map,
Boss, Enemy Types, and Banned Covenants—and progress is therefore always based on four items. A
future Secret Boss item is optional and does not change that denominator.

This first vertical slice captures a normalized map identity and one separately calibrated
difficulty label from a JP MuMu 1920×1080 `OPERATION` presentation. It does not yet recognize
Boss, Enemy Types, Banned Covenants, Secret Boss, or any gameplay mechanics from pixels.

## Encounter boundary

`情報確認 1/2` is the authoritative future start boundary for a new encounter session. It occurs
before strategy selection and before the `OPERATION` presentation, so `OPERATION` must only enrich
the current session with map/difficulty facts and must never reset it. The retained calibration
material does not yet support a robust `情報確認 1/2` detector or reliable revisit deduplication;
v0.1 therefore exposes an explicit `EncounterStartObservation`/`begin_encounter` boundary without
inventing timing-based resets. A later observer must debounce one continuous `1/2` presentation and
must not reset when the same encounter returns from `2/2` to `1/2`.

## Vision versus knowledge

Vision produces only an immutable, provenance-bearing observation:

```text
frame -> normalized map code -> map_id
```

It does not infer terrain, targeting, deployment, or tactics from screenshots. Those facts live in
the curated map catalog as localized `MapKnowledgeEntry` records. Entries have a lightweight source
note and can be general or scoped to one or more difficulty IDs. Missing knowledge is normal: a
successfully captured map remains complete even with no Map Intel section.

`MapDefinition` and `DifficultyDefinition` are separate records. A map has a stable `map_id`, stage
code, optional localized names, optional game-knowledge-backed allowed difficulty IDs, and factual
map knowledge. A difficulty has its own stable `difficulty_id`, localized names, and optional
global modifiers. In
the current retained JP `OPERATION` frames, `AC-3` is the map identity and the lower text `死地` is
calibrated as `difficulty.covenant_latter.deadland`. It is never used as a map name. This visual
calibration does not assert that AC-3 is game-rule-restricted to that difficulty, so AC-3 currently
has no `allowed_difficulty_ids`. Other OCR text in that ROI remains unresolved rather than being
inferred from the map code.

Future static Boss routes use the separate relationship `(boss_id, map_id) -> route asset / notes`.
They are not map facts and difficulty is not embedded in `map_id`.

## Presentation and safety

`present_encounter(...)` is a pure zh_CN/en view builder. It renders the separate values `Map:
AC-3` and, when captured, `Difficulty: 死地`, plus a 1/4 progress value and any curated localized
Map Intel entries. The optional Tk panel is a caller-owned, always-on-top-capable display; locale
switching changes only the view, never the immutable `EncounterSession`. Capture must read only the
game source window/frame, not this panel. Users should hide or suspend the panel when it would
obscure a capture target.

The included `AC-3` mapping contains only verified display metadata. No game image asset, replay,
or unlicensed screenshot is part of the repository. Broader online knowledge population, including
PRTS collection, is deliberately a later bounded task.
