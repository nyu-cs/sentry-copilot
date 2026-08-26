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

## Frame input boundary

M0.3a.1 provides source-neutral immutable `Frame` objects from local image sequences and local
videos. The capture layer performs only media I/O and raw dumping; it does not identify viewport
geometry, derive ROI, recognize game UI, or mutate domain state. Future Windows capture will
implement the same `FrameSource` contract.

## Content viewport boundary

M0.3a.2 adds immutable, caller-calibrated `ContentViewport` and `NormalizedRoi` geometry in the
vision layer. A viewport is bound to one source frame and can represent either an arbitrary game
content rectangle or the explicit full frame; it never assumes desktop coordinates, a fixed
resolution, or that black bars are absent. Normalized ROIs resolve only inside that viewport, and
the crop/debug helpers create copies so the source frame remains unchanged. Automatic viewport
detection and all game recognition remain out of scope.

The offline validation runner accepts only a caller-supplied image directory or local video path.
It applies optional frame-index sampling, explicit viewport geometry, and named normalized ROIs,
then writes copied debug PNGs plus a JSONL manifest. It does not scan private data, mutate frames,
or emit domain observations.

M0.3a.4 adds a read-only Windows physical-display `FrameSource` for manual smoke testing. It uses
an explicit MSS physical-monitor index, emits the same immutable frames as offline sources, and
records the actual captured pixel dimensions. It has no window-title tracking, viewport detection,
or recognition responsibility.

M0.3b.1 adds a source-neutral template-matching primitive in `vision/`. It consumes an explicit
frame, content viewport, ROI, and caller-owned template, then returns immutable geometric result
data only. It does not encode Sentry Protocol screen semantics or mutate domain state.

M0.3b.2 adds source-neutral OCR over one caller-supplied ROI. `recognize_text` copies only the
resolved BGR crop, passes that immutable crop to an async backend, and returns immutable raw and
NFKC/whitespace-normalized text, optional backend confidence, geometry, and frame/source
provenance (including processing and optional source timestamps). Unknown and empty outputs remain
distinct. The Windows adapter uses the OS OCR
component through Python/WinRT rather than a separate executable or model download; it raises a
typed unavailable error when the requested OCR language capability (such as `ja-JP`) is absent.
It performs no game-specific parsing, page detection, or domain mutation.

M0.3b.3 adds a bounded developer probe around the existing physical-display source and OCR
primitive. The caller explicitly chooses a monitor, language, output directory, and normalized or
pixel ROI. It captures only one frame, writes an unannotated copy and unannotated ROI crop, and
records a compact JSON result. Missing system OCR language support is a typed `ocr_unavailable`
outcome after the capture artifacts are written; the probe never installs Windows features.

M0.3c adds a one-frame, caller-driven recognition probe harness. It reuses the existing frame,
viewport, OCR, and template interfaces for one or more explicit normalized or pixel ROIs. The
harness writes only caller-owned source/crop/optional diagnostic/report artifacts; it has no
automatic ROI discovery, game semantics, domain-state mutation, or UI interaction.

M0.7a1c1 adds independent, immutable fixed-layout observations for JP MuMu 1920×1080 outside-run
pages: main lobby, party room, party-room matching overlay, solo matchmaking, success result,
post-clear rematch, and the match-success transition.  Each observation is `present`, `absent`, or
`unresolved` and retains only non-identity pixel-cue metrics plus frame provenance.  The module
does not infer why a previous run ended. `SelectionLifecycleWatcher` reduces the independent
observations to a single semantic outside-run boolean and debounces it separately from OPERATION;
the watcher stores no page kind or termination cause.
`PARTY_ROOM` denotes its visible base/context, so it can intentionally co-occur with the distinct
`PARTY_ROOM_MATCHING_OVERLAY` observation.

## State ownership

Recognizers do not edit `SessionState`. The reducer enforces:

- avatar observations never change strategy;
- strategy-selection observations merge field by field into one reducer-owned snapshot;
- raw prebattle candidate and ready observations append to an evidence-ID-addressed ledger;
- applying an identical evidence ID is idempotent, while an ID collision with different evidence
  is rejected;
- only effective ready, normal-entry, or concrete-selection confirmation evidence materializes a
  ready-confirmed commitment;
- reliable normal battle participation can strengthen the same commitment, but merely being
  displayed inactive in the battle UI cannot establish entry;
- false-positive correction preserves the original ready observation and changes only the
  assistant's effective interpretation;
- concrete strategy claims remain append-only while explicit manual records supersede assistant
  interpretations without representing an in-game strategy switch;
- uncontested occupancy is derived from commitment, freshness, compatibility, supersession, and
  conflict state; it is never persisted as a second authority;
- `selection_row` never implies a runtime player slot;
- expected participant count is explicit and never inferred from recognized rows;
- M0.1a snapshot completeness measures only whether expected entered-player legacy strategy
  fields have values; repeated interpretations remain valid snapshot history and are not occupancy;
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
raw candidate / formal-selection observation
        ↓ append-only, stable evidence ID
PrebattleEvidenceLedger
        ↓ exclude corrected ready false positives
StrategyCommitmentState
        ↓ read-only projection
formal-selection commitment, concrete strategy still separate
```

Raw candidate records contain frame references, normalized ROI, observed visual cues, observed
text, confidence, time, and provenance. They deliberately contain no normalized strategy ID.
M0.2b.2 interprets them only in a separate concrete-identification record.

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

## Legacy snapshot migration

M0.2b.3 keeps `StrategySelectionSnapshot` as the legacy prebattle materialized view and imports it
only through an explicit service:

```text
ImportLegacyStrategySnapshotEvidence
        ↓ validate session + canonical snapshot fingerprint
LegacyPrebattleSnapshotMigrationService
        ↓ deterministic field IDs + one atomic accepted event
typed legacy evidence + ready commitment + weak interpretation history
```

The migration history is keyed independently by a caller-supplied operation ID and by the
canonical SHA-256 snapshot fingerprint. Repeating one operation with equal command content or
using a different operation for an already imported fingerprint is a no-op. Reusing an operation
ID for different command content is rejected. Legacy `ready=true` becomes typed positive evidence;
`false` or unknown never withdraws another commitment. A legacy strategy value and its original
field evidence are preserved as catalog-dependent interpretation history, never as a raw visual
candidate or effective occupancy.

`snapshot.frozen` means only that ordinary legacy snapshot capture has closed. It does not close
the independent evidence ledger, corrections, commitments, direct/manual identification, battle
entry evidence, or migration history. Revision correction performs no destructive rewrite:
revision-independent evidence and commitment remain, stamp-dependent records become stale, and
direct/manual claims are rechecked against the current catalog by the existing read model.

## Concrete identification and effective occupancy

Concrete claims use one of three bases. `CATALOG_DERIVED` requires raw candidate evidence and an
exact `RulesetDependencyStamp`; any ruleset, revision, locale, catalog-version, or generation
change makes it stale. `DIRECT_OBSERVATION` and `MANUAL_CONFIRMATION` carry strong evidence rather
than a dependency stamp. They survive generation changes but are checked against the current
revision catalog on every query.

Identification history is append-only. Manual correction adds a record with explicit
`supersedes_record_ids`; the replaced record remains available for audit. Current identification
is derived only from fresh, compatible, unsuperseded claims for a participant with a current
commitment. Occupancy is then derived from those identifications and is not stored in
`SessionState`.

The game invariant is one formal occupant per strategy. Candidate duplicates remain legal because
candidates are not occupancy. Two participants making the same concrete confirmed claim produce
`DUPLICATE_CONFIRMED_STRATEGY_CLAIM`, no winner and no occupancy for that strategy. Distinct strong
claims for one participant produce `PARTICIPANT_STRATEGY_IDENTIFICATION_CONFLICT`; a direct/manual
claim outside the current catalog produces `STRATEGY_CATALOG_COMPATIBILITY_CONFLICT`.

M0.2b battle reconciliation records only whether normal active participation was reliably
observed. `BATTLE_ENTRY_CONFIRMED` can establish or strengthen a strategy-unknown commitment, but
contains no strategy ID. `BATTLE_ENTRY_NOT_CONFIRMED` is used when the first stable frame is already
inactive or normal participation was never observed. A participant remaining visible as a departed
row is not thereby a battle entrant. M0.2c.1 now consumes those facts to derive `BattleRoster`, but
still creates no runtime slot, follow-up queue, or annotation.

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
expected count matches the number of `entered_battle` participants and each legacy strategy field
has a value. Repeated values are allowed because this is field coverage, not confirmed occupancy.
Selection-stage exits remain in the raw snapshot but are excluded from the default final-team
query. The expected count may be one to four and is never inferred from recognition results.
Identity completion, runtime survival, and runtime-slot association are separate concerns.

The current `StrategySelectionSnapshot` in `SessionState` remains an immutable prebattle
materialized view and historical query source. It is not the future runtime-slot annotation
authority. M0.1a does not implement recognition, confirmed occupancy, or runtime association.

Its legacy participant `strategy_id` may contain catalog-dependent normalized interpretation.
M0.2b.3 preserves that value and field evidence through explicit migration. A compatible value may
produce a stamped weak legacy record for audit, but the current read model excludes that basis from
effective identification and occupancy until a later direct/manual confirmation explicitly
supersedes it. Raw visual observations and normalized strategy interpretation remain separate.

Runtime participation is a separate observation stream. It distinguishes `normal` from
`secret_core`, requires `round_number=None` for secret core, carries an optional wave number, and
records status transitions without writing back into selection outcome or strategy history.

The runtime business model separates participation (`ACTIVE` or terminal `INACTIVE`),
inactivation reason (`LEFT_OR_DISCONNECTED`, `HP_DEPLETED`, or `UNKNOWN`), and inactive
presentation (`DEPARTED`, `SPECTATING`, or `UNKNOWN`). `DISCONNECTED` is not a separate business
reason. `BattleParticipationState` retains append-only observations/corrections, while
`build_battle_roster` derives entrants and current participation. `get_active_battle_participants`
is separate from the historical team strategy context.

Assistant-record correction does not add a game-domain re-entry or reactivation. Entry correction
excludes mistaken `BattleEntryConfirmed` evidence; inactivation correction can invalidate or
replace the current assistant interpretation while preserving every original fact for audit.

Future runtime slots remain a separate authority chain. The manual panel fallback must first use
the bottom `name#XXXX` display to establish a strong `DIRECT_PLAYER_TAG` participant association.
Only then may participant-bound direct panel evidence strengthen strategy identification and
derive assignment through uncontested occupancy. There is no slot-only panel authority or
`DIRECT_SLOT_STRATEGY_PANEL` bypass.

M0.2c.2 now persists immutable runtime-slot observation and association-claim history. Current
`BattleRuntimeSlot` and association/conflict views remain query-derived. Slot identity is scoped to
one explicit layout epoch; visual index is never identity, and an uncertain reorder starts a new
layout without inheriting old claims. Only current confirmed battle entrants may be associated.
Tag, self marker, and manual confirmation are the only accepted bases; legacy slot position,
selection row, avatar, HP, and strategy fields are isolated from this layer.

## Route subsystem boundaries

1. **Map recognition**: identify `map_id`.
2. **Calibration**: locate the battlefield in the current frame.
3. **Route selection**: select map-specific routes for the current encounter.
4. **Projection**: map normalized coordinates to frame pixels.
5. **Rendering**: draw paths, arrows, teleports and nodes.

The first version uses manual map choice and manual four-corner calibration. Real recognition can replace those providers without changing route data or rendering.
