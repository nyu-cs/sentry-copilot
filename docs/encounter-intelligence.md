# Encounter intelligence / 本局情报

## Scope

The v0.1 encounter preview is player-count independent. Its four product information items are
Difficulty, Boss, Enemy Types, and Banned Covenants. Initial progress is `0 / 4`; a complete
supported encounter reaches `4 / 4`. Banned Covenants contributes exactly one item only when
both the complete Major/Core and Additional snapshots have been captured.

Map is outside encounter product scope. The independent route subsystem retains its map schemas,
synthetic map data, normalized coordinates, calibration, projection, and rendering.

The current JP MuMu 1920×1080 slice visually recognizes Standard / AC-1, Adversity / AC-2, Deadland /
AC-3, and Ultimate / AC-4 difficulty, plus Boss and two- or three-slot Enemy Types from genuine
INFO 1/2. Initial INFO and semantically authorized `2/2` recovery use the frozen circular-HSV
four-way candidate ranker with no local score or margin acceptance gate; existing page semantics and
two-frame confirmation authorize capture. OPERATION remains on its separately calibrated grayscale
recovery path. For Adversity and Deadland initial INFO 1/2, it can retain a complete Major/Core
pre-run Ban state after two matching observations. Additional recognition remains bounded to
supported surfaces and scroll configurations. Secret Boss and gameplay mechanics are not recognized
from pixels.

## Encounter boundary

`情報確認 1/2` is the authoritative start boundary for a new encounter session. The first genuine
PRESENT starts an encounter. Three consecutive genuine ABSENT observations arm the existing
session for a possible next initial INFO page; arming does not end, discard, or make its retained
facts stale. While armed, three consecutive strict next-initial-INFO candidates start a fresh next
encounter. A strict candidate requires the generic INFO anchor, resolved two- or three-slot enemy
structure, independently reliable canonical INFO content, and no returned-info or `2/2` evidence.
Generic INFO-anchor hits alone never replace the retained encounter. Same-process multi-run is
implemented and live validated. `OPERATION` only enriches the active session and never resets it.

Broad outside-run END detection is deliberately disabled in the production live preview. Hard Exit
remains postponed; it is not currently an encounter-end authority.

## Vision versus knowledge

Vision produces only immutable, provenance-bearing identity evidence:

```text
frame -> normalized simulation code + label -> difficulty_id
frame -> boss visual evidence -> boss_id
frame -> enemy-card visual evidence -> enemy_type_ids
```

Vision does not infer terrain, targeting, deployment, or tactics from screenshots. Difficulty has
its own stable `difficulty_id`, localized names, and simulation code. `AC-3` / `死地` is difficulty
evidence, not a route map ID.

`EncounterMapCatalog`, `EncounterMapDefinition`, and `MapKnowledgeEntry` remain reusable library
APIs. Their map queries and metadata do not participate in `EncounterSession`, the live view,
diagnostics, or progress. Independent route APIs continue to use explicit `(ruleset_id, map_id)`
and route filtering/projection contracts.

## Presentation and safety

`present_encounter(...)` is a pure zh_CN/en view builder with exactly four product rows. There is
no Map row, placeholder, or Map Intel section. The optional
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
returned Boss recovery, and returned Enemy recovery. Fill-missing-only returned Major/Core
recovery for supported AC-2/AC-3 has passed retained-frame production-observer validation and
still needs live MuMu validation. Returned Enemy supports both two- and three-card layouts;
returned Major/Core requires two matching complete observations and cannot complete the Banned
Covenants item alone. Supported missing Major and Additional components use the existing INFO
recovery reminder; returned INFO fills missing components only, with scroll guidance for Additional.
Both complete snapshots are required for Ban completion. Broad outside-run END is disabled in
the production live preview; Hard Exit remains postponed. The validation-only
`--debug-skip-initial-enemy-capture` flag defaults off and exists solely to test the
returned Enemy path without changing initial visual observation.

Ultimate / AC-4 has real JP SOLO evidence. The OPERATION-splash template remains registered for the
existing fill-missing-only recovery surface, while the semantically gated `2/2` top bar uses the
frozen four-way color candidate. The returned-INFO
page is calibrated for Boss, two-slot Enemy recovery, and Major/Core recovery. Its Major structure is
authoritatively 8 total / 5 UNRESTRICTED / 3 DISABLED; the canonical disabled IDs in the retained run
are Yan, Kjerag, and Laterano. Initial-INFO Major glyph validation has not passed its existing gate,
so initial AC-4 Major capture remains disabled. Additional structure is authoritatively 15 total / 11
UNRESTRICTED / 4 DISABLED, with bounded Additional visual recognition. Future initial
Difficulty promotion retains page/lifecycle authorization and two-frame confirmation rather than a
surface-local color-score gate. The loader never discovers assets from directories and loads the
explicit AC-4 Initial INFO reference with the other frozen physical templates at startup.

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

The panel is never a vision input.
