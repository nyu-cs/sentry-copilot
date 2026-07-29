# Architecture

## Offline-first rule

Every live component has an offline equivalent so development can continue when the mode is closed.

```text
recording / image folder / live capture later
                    ↓
                FrameSource
                    ↓
 independent recognizers emit typed observations
                    ↓
              SessionReducer
                    ↓
               SessionState
              ↙    ↓     ↘
 strategy context  knowledge UI  route overlay service
```

## State ownership

Recognizers do not edit `SessionState`. The reducer enforces:

- avatar observations never change strategy;
- strategy-selection observations merge field by field into one reducer-owned snapshot;
- `selection_row` never implies a runtime player slot;
- expected participant count is explicit and never inferred from recognized rows;
- final-team strategies are unique among participants who entered battle;
- frozen strategies change only through explicit manual correction;
- runtime exit and elimination never mutate historical strategy selection;
- non-positive health marks elimination;
- unknown evidence remains unknown;
- map and ruleset identity are explicit.

## Strategy-selection subsystem

The strategy-selection screen is the primary acquisition source. Each participant has an opaque
session-local ID and independent evidence for tag, display name, avatar, strategy, ready state,
selection outcome, and self state. A frozen snapshot is strategy-complete when its explicit
expected count matches the number of `entered_battle` participants and each has a unique strategy.
Selection-stage exits remain in the raw snapshot but are excluded from the default final-team
query. The expected count may be one to four and is never inferred from recognition results.
Identity completion, runtime survival, and runtime-slot association are separate concerns.

The current `StrategySelectionSnapshot` in `SessionState` is authoritative regardless of whether
its fields came from the selection screen, a future fallback panel, or manual correction. M0.1a
does not implement recognition or runtime association. It remains an immutable historical account
of selection for query purposes when a runtime player later leaves, disconnects, or is eliminated.

Future runtime monitoring is a separate observation stream. It will distinguish `normal` from
`secret_core`, allow `round_number=None`, carry an optional wave number, and record status
transitions without writing back into selection outcome or strategy history.

The future runtime business model separates participation (`ACTIVE` or terminal `INACTIVE`),
inactivation reason (`LEFT_OR_DISCONNECTED`, `HP_DEPLETED`, or `UNKNOWN`), and inactive
presentation (`DEPARTED`, `SPECTATING`, or `UNKNOWN`). `DISCONNECTED` is not a separate business
reason. The historical team strategy context remains independent from a future current-active-team
query.

## Route subsystem boundaries

1. **Map recognition**: identify `map_id`.
2. **Calibration**: locate the battlefield in the current frame.
3. **Route selection**: select map-specific routes for the current encounter.
4. **Projection**: map normalized coordinates to frame pixels.
5. **Rendering**: draw paths, arrows, teleports and nodes.

The first version uses manual map choice and manual four-corner calibration. Real recognition can replace those providers without changing route data or rendering.
