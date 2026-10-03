# Architecture

Sentry Copilot has three distinct engineering paths. The live encounter assistant is the product
entry point; strategy/player evidence and route rendering are independent supporting subsystems.
They share primitives where useful, not one universal session or execution pipeline.

## Live encounter pipeline

```text
MuMu renderer IPC / Windows display
                  |
             immutable Frame
                  |
          visual observations
                  |
     LiveEncounterPreviewController
                  |
          EncounterSession facts
                  |
       immutable presentation views
                  |
             Tk desktop UI
```

### Capture and observations

`capture/` produces frames only. Every `Frame` owns a copied, read-only BGR array and records
frame identity, source type, dimensions, processing time, and optional source time. Image-sequence
and local-video sources implement the same boundary for offline work.

The MuMu source wraps screenshot-only native renderer IPC. It converts the target ABI's
upside-down RGBA framebuffer into the shared BGR representation and releases its connection on
exit. The installed DLL and emulator paths are supplied explicitly. Windows physical-display
capture is a secondary source; neither adapter performs game recognition or input automation.

`vision/` returns typed observations, never mutations of domain state. Generic viewport, ROI,
template, OCR, and local-feature primitives coexist with fixed-layout JP MuMu encounter
observers. Generic ROI geometry is source-neutral; that does not make the encounter profile
resolution-independent. The current live encounter path is visual and does not depend on OCR.

### Controller and confirmed state

`services/live_encounter_preview.py` coordinates page observations, temporal confirmation,
encounter identity, recovery eligibility, and capture status. Its `EncounterSession` is separate
from the strategy/player subsystem's `SessionState`.

Initial INFO is the authoritative start boundary. Once an encounter exists, departure and
strict next-initial-page confirmation distinguish a new encounter from returned INFO.
Returning to INFO or observing INFO 2/2 does not create another session.

`encounter/session.py` applies validated capture candidates. The four product facts are
Difficulty, Boss, Enemy Types, and Banned Covenants. Bans is complete only with both Major/Core
and Additional snapshots. Weak observations do not erase confirmed facts; contradictions are
explicit conflicts rather than silent replacements. Returned-INFO recovery fills missing facts
within a controller-owned scan context. See [Encounter Intelligence](encounter-intelligence.md)
for recognition gates and lifecycle details.

### Presentation and desktop boundary

`encounter/presentation.py` derives localized, immutable views from confirmed session facts and
catalog metadata. The UI consumes these views and is not a fact authority. MuMu IPC captures the
game framebuffer without the desktop assistant window; physical-display capture can include
assistant windows or other overlays if they overlap calibrated game-content/ROI areas.
Ban Detail groups Major and Additional results, projects conservatively confirmed banned
operators, and wraps cards at seven per row. Pure layout/navigation helpers are testable without
a running game.

Missing private media is handled separately from confirmed state. Diagnostics remain local,
with no gameplay recording or upload performed by the preview.

## Strategy/player evidence pipeline

```text
explicit observations / manual commands / legacy import
                         |
        catalog-validating application services
                         |
                 domain reducer facts
                         |
          SessionState + immutable histories
                         |
     commitment / roster / association / occupancy queries
```

This subsystem models auditable identity and evidence; it is not wired into the live encounter
panel as an end-to-end player tracker.

- `SessionRulesetContext` is the ruleset/revision/locale/catalog authority. Explicit command
  services validate selections and corrections; the generic reducer never loads YAML, accesses
  the filesystem, or infers a revision.
- A reducer-owned strategy-selection snapshot stores legacy prebattle history for at most four
  participants. Completeness is field coverage relative to an explicit entrant count, not
  confirmed strategy occupancy.
- Raw candidates, ready observations, and corrections use stable evidence IDs. Commitments do
  not themselves identify a strategy. A false-positive correction preserves the original
  observation rather than claiming an in-game cancellation.
- Reliable normal active participation establishes battle entry. Runtime participation is
  `ACTIVE` or terminal `INACTIVE`; historical selection remains unchanged by departure.
- Layout-epoch slot identities are distinct from screen order, selection rows, avatars, and HP.
  Durable direct association claims target confirmed entrants and preserve one-to-one conflicts.
- Concrete strategy claims are checked against commitment and the current catalog. Occupancy
  and slot-strategy assignments are query-derived; contested claims produce no occupancy.
- Legacy snapshot migration is explicit, audited, and idempotent. Imported weak interpretations
  are not current identification or assignment authority.

Visual selection/runtime probes and a deterministic normalized association core are also
implemented. The core's accepted avatar/pre-loss-HP constraints do not bypass the auditable
direct-association authority or create durable claims. User-guided fallback contracts require
participant association before interpreting a strategy panel; all game navigation is manual.

See [Domain invariants](domain-invariants.md), [Data contracts](data-contracts.md),
[Runtime slots](runtime-slots.md), and [Runtime association core](runtime-association-core.md).

## Independent route pipeline

```text
ruleset/map-scoped route YAML + explicit scene context
                         |
        map selection + battlefield calibration
                         |
            route selection / projection
                         |
                    rendering
```

`routes/` owns schemas, filtering, normalized coordinates, projection, and drawing.
`RouteOverlayService` orchestrates map-recognition and calibration providers; the repository
includes manual providers and a synthetic CLI demonstration, not a claim of general automatic
game-map recognition.

Every route is scoped by ruleset and map identity. Four battlefield corners define a homography
from normalized points into the captured frame. Insufficient map or calibration confidence
returns an explicit unknown result and suppresses the overlay. Route steps include movement,
teleport, wait, and phase-change nodes.

Route rendering is not part of encounter progress and is not an encounter-panel roadmap.
The reusable catalog name `EncounterMapCatalog` remains a compatibility API for metadata,
including difficulties, Bosses, and enemies; it does not add a live product information item.
See [Route system](route-system.md).

## Module boundaries and testing

| Module | Responsibility |
| --- | --- |
| `capture/` | Frame acquisition and media I/O. |
| `vision/` | Immutable visual observations and geometry. |
| `encounter/` | Encounter models, capture updates, catalogs, presentation, and desktop UI. |
| `domain/` | Strategy/player state, immutable evidence, reducer invariants, and derived views. |
| `catalogs/` | Exact revision-aware loading, lookup, and shared validation. |
| `services/` | Explicit validation and orchestration across boundaries. |
| `player/` | User-guided fallback inspection helpers. |
| `routes/` | Route models, selection, projection, and rendering. |

Synthetic inputs and injected adapters make these boundaries testable when the game mode is
unavailable. Public tests cover logic and bounded visual cases; private calibrated references
are not part of the checkout. See [Validation](validation.md) and
[Contributing](../CONTRIBUTING.md).
