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
                    │
          SessionRulesetContext
              ↙    ↓     ↘
 strategy context  knowledge UI  route overlay service
```

## State ownership

Recognizers do not edit `SessionState`. The reducer enforces:

- avatar observations never change strategy;
- strategy-selection observations merge field by field into one reducer-owned snapshot;
- raw prebattle candidate and ready observations append to an evidence-ID-addressed ledger;
- applying an identical evidence ID is idempotent, while an ID collision with different evidence
  is rejected;
- only currently effective ready evidence materializes a ready-confirmed commitment;
- false-positive correction preserves the original ready observation and changes only the
  assistant's effective interpretation;
- `selection_row` never implies a runtime player slot;
- expected participant count is explicit and never inferred from recognized rows;
- M0.1a snapshot completeness requires unique entered-player strategy values, without treating
  that compatibility check as confirmed occupancy;
- frozen strategies change only through explicit manual correction;
- runtime exit and elimination never mutate historical strategy selection;
- non-positive health marks elimination;
- unknown evidence remains unknown;
- map and ruleset identity are explicit.

`SessionRulesetContext` is the sole authority for new ruleset-, revision-, locale-, and
catalog-aware code. Legacy session ruleset/locale values are compatibility mirrors. If a context
is supplied without those legacy values, model construction fills the mirrors; explicitly
conflicting values are rejected.

The context owns a monotonic generation. Future revision-dependent derived values must carry a
dependency stamp containing ruleset, revision, locale, catalog version, and generation. M0.2a.1
defines the stamp but does not create future occupancy, assignment, annotation, or coverage state.

## Prebattle evidence and ready commitment

M0.2b.1 separates three concepts:

```text
raw candidate / ready observation
        ↓ append-only, stable evidence ID
PrebattleEvidenceLedger
        ↓ exclude manually corrected false positives
StrategyCommitmentState
        ↓ read-only projection
OBSERVING or READY_CONFIRMED_STRATEGY_UNKNOWN
```

Raw candidate records contain frame references, normalized ROI, observed visual cues, observed
text, confidence, time, and provenance. They deliberately contain no normalized strategy ID.
Catalog-dependent interpretation and concrete occupancy are deferred to M0.2b.2.

The first effective ready observation determines `confirmed_at`; later ready observations add
evidence without moving it or creating another commitment. There is no game-domain unready or
release transition. A manual false-positive correction is an assistant-record operation: it
preserves the original observation, records the correction under its own stable ID, and excludes
the targeted ready evidence when deriving current commitments. If no effective ready evidence
remains, the assistant materialization no longer contains that commitment.

Every prebattle event carries normalized session and participant IDs. The reducer rejects
cross-session events and participants absent from the session's strategy-selection snapshot.
Ledger and commitment aggregates are frozen; the reducer constructs and validates a complete new
`SessionState`, so a failed correction cannot partially change the input.

## Strategy catalog subsystem

Catalog data is immutable and revision-aware. `StrategyIdentity` owns only a normalized
`strategy_id`. `RulesetStrategyProfile` owns the revision-specific availability, initial HP,
`icon_visual_key`, and `icon_asset_reference`; it is the only current icon-mapping authority.
`LocaleStrategyResource` owns revision- and locale-specific names, descriptions, OCR aliases, and
visible text variants.

Runtime loading and repository validation both call the same PyYAML parser and cross-record
validator. Lookup is exact: locale resources require catalog version, revision, strategy, and
locale, with no implicit fallback across revisions or languages. Asset references must be safe
relative paths below the catalog directory.

Support targets and validation evidence are catalog-registry metadata, not session state. A target
declaration does not imply validated support, and passing the synthetic fixture validates only
that fixture. M0.2a.2 does not create assignment, occupancy, recognition, or derived HP matching.

## Ruleset context operations

Ruleset selection and correction use an application boundary:

```text
explicit command
→ RulesetContextService validates session and exact catalog target
→ accepted typed event
→ generic reducer builds a complete candidate SessionState
→ whole-state validation
→ new state returned
```

The reducer does not receive a catalog repository and never reads YAML or the file system. Initial
selection is manual or imported from explicit replay metadata; automatic detection is not part of
M0.2a.3. A concrete context requires explicit correction, while an unknown generation-zero
context uses initial selection and is preserved as generation-zero history.

Each successful replacement appends the old selection, increments `context_generation`, and
atomically synchronizes legacy mirrors. Exact duplicate correction is a typed rejection. Mismatch
checks never mutate or silently switch the session. Raw observations, field evidence, and the
prebattle snapshot remain revision-independent historical data.

## Strategy-selection subsystem

The strategy-selection screen is the primary acquisition source. Each participant has an opaque
session-local ID and independent evidence for tag, display name, avatar, strategy, ready state,
selection outcome, and self state. A frozen snapshot is strategy-complete when its explicit
expected count matches the number of `entered_battle` participants and each has a unique strategy.
Selection-stage exits remain in the raw snapshot but are excluded from the default final-team
query. The expected count may be one to four and is never inferred from recognition results.
Identity completion, runtime survival, and runtime-slot association are separate concerns.

The current `StrategySelectionSnapshot` in `SessionState` remains an immutable prebattle
materialized view and historical query source. It is not the future runtime-slot annotation
authority. M0.1a does not implement recognition, confirmed occupancy, or runtime association.

Its legacy participant `strategy_id` may contain catalog-dependent normalized interpretation.
M0.2a preserves that value and evidence but does not use it to create new revision-aware occupancy,
assignment, or catalog-dependent confirmation. Raw visual observations and normalized strategy
interpretation are separated in M0.2b.

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
