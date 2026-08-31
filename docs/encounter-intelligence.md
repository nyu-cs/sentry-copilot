# Encounter intelligence / 本局情报

## Scope

The v0.1 encounter preview is player-count independent. Its five ordinary capture items are
Difficulty, Boss, Enemy Types, Banned Covenants, and Map; progress is therefore based on five
items. Difficulty, Boss, and Enemy Types are currently implemented. Banned Covenants and Map
remain unimplemented.

The current JP MuMu 1920×1080 slice recognizes Standard / AC-1, Adversity / AC-2, and Deadland /
AC-3 difficulty, plus Boss and two- or three-slot Enemy Types from genuine INFO 1/2. It does not
yet recognize the randomized battlefield/map, Banned Covenants, Secret Boss, or gameplay mechanics
from pixels.

## Encounter boundary

`情報確認 1/2` is the authoritative start boundary for a new encounter session. The first genuine
PRESENT starts an encounter; three consecutive genuine ABSENT observations arm re-entry, and two
consecutive genuine PRESENT observations then start a fresh next encounter. The first re-entry
frame cannot contaminate the old encounter. Same-process multi-run is implemented and live
validated. `OPERATION` only enriches the active session and never resets it.

Broad outside-run END detection is deliberately disabled in the production live preview. Hard Exit
remains postponed; it is not currently an encounter-end authority.

## Vision versus knowledge

Vision produces only immutable, provenance-bearing identity evidence:

```text
frame -> normalized battlefield identity
frame -> normalized simulation code + label -> difficulty_id
frame -> boss visual evidence -> boss_id
frame -> enemy-card visual evidence -> enemy_type_ids
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
renders Map separately from Difficulty and uses the five-item progress model. The optional
Tk panel is a caller-owned, always-on-top-capable display; locale
switching changes only the view, never the immutable `EncounterSession`. Capture must read only the
game source window/frame, not this panel. Users should hide or suspend the panel when it would
obscure a capture target.

The included difficulty mappings contain only verified display metadata. No game image asset, replay,
or unlicensed screenshot is part of the repository. Broader online knowledge population, including
PRTS collection, is deliberately a later bounded task.

## Current recovery status

The JP MuMu 1920×1080 INFO recovery subsystem is live validated and frozen pending
contradictory live evidence: `2/2` detection, reminder, returned-info detection,
returned Boss recovery, and returned Enemy recovery. Returned Enemy supports both
two- and three-card layouts with fill-missing-only semantics. Broad outside-run END
is disabled in the production live preview; Hard Exit remains postponed. Map and
Banned Covenants remain unimplemented. The validation-only
`--debug-skip-initial-enemy-capture` flag defaults off and exists solely to test the
returned Enemy path without changing initial visual observation.

## Live preview v0.1

On the primary supported Windows JP MuMu fullscreen 1920×1080 profile, capture uses MuMu renderer
IPC at an approximately 5 FPS target. Physical-monitor capture remains a secondary supported path
where applicable. Launch the IPC preview with the locally configured MuMu paths:

```powershell
.\.venv\Scripts\python.exe -m sentry_copilot.cli live-encounter-preview `
  --capture-backend mumu-ipc `
  --mumu-install-root '<MuMu install root>' `
  --mumu-ipc-dll '<path to external_renderer_ipc.dll>' `
  --mumu-instance-id 0 `
  --mumu-display-id 0 `
  --locale zh_CN
```

The install root and IPC DLL path depend on the local MuMu installation.

The compact panel shows a player-facing running/waiting/error state, the supported profile, a small build identifier, and a
Copy Diagnostics action. `--diagnostic-output path\to\diagnostic.json` writes the same
personal-data-free local JSON only after the window closes. It never uploads diagnostics or records
gameplay.

Battlefield recognition and Banned Covenants remain deferred. The panel is never a vision input.
