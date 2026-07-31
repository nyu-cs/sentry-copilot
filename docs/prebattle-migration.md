# Legacy prebattle snapshot migration

## Purpose and authority boundary

M0.2b.3 keeps the M0.1a `StrategySelectionSnapshot` intact as an immutable legacy prebattle
materialized view. Migration is an explicit compatibility operation that preserves old field
observations in the typed evidence and identification histories. It does not turn the snapshot
into the authority for commitment, concrete occupancy, a battle roster, runtime slots, assignment,
annotation, or active-team membership.

`build_team_strategy_context` therefore keeps its old snapshot projection. New ruleset-aware code
must use commitment, effective-identification, uncontested-occupancy, and conflict queries.

## Explicit API

The caller creates `ImportLegacyStrategySnapshotEvidence` with:

- the current normalized session ID;
- a stable migration operation ID;
- the canonical fingerprint returned by
  `LegacyPrebattleSnapshotMigrationService.fingerprint_snapshot`;
- a timezone-aware `migrated_at`;
- an optional audit reason.

The service validates the command and current snapshot, builds one accepted
`LegacyPrebattleSnapshotMigrated` event, and asks the generic reducer to validate and return one
new immutable `SessionState`. No constructor or read query performs implicit migration.

## Idempotency and audit history

The canonical snapshot fingerprint is a lowercase SHA-256 digest of deterministic JSON. Stable
evidence and weak-identification IDs combine that fingerprint, participant ID, and source field.
`LegacyPrebattleMigrationState` records each imported fingerprint and operation.

- same operation ID and equal command content: no-op;
- same operation ID and different command content: typed rejection;
- different operation ID for an already imported fingerprint: no-op;
- any evidence/record ID collision with different content: atomic rejection.

Equal pixels or equal values from genuinely separate future observations remain separate because
ordinary typed evidence uses its own caller-supplied IDs. Migration does not use content-only
deduplication for those observations.

## Ready values

Legacy `ready=true` creates `LegacyReadySnapshotImported`. The entry retains the original field
`EvidenceRecord`, original observation time, migration time, operation ID, and fingerprint. It can
establish or strengthen the one ready-confirmed commitment. An already earlier `confirmed_at` does
not move.

Legacy `ready=false` and unknown values create no negative evidence. They cannot withdraw an
existing commitment. Imported positive evidence can be targeted by the normal manual
false-positive correction. Because its stable evidence ID remains excluded, replaying migration
cannot reactivate it.

Selection outcome alone does not create commitment. In particular,
`EXITED_AFTER_STRATEGY` without prior ready or other reliable formal-selection evidence remains
historical only. A first stable battle frame already showing departure is still not battle-entry
confirmation.

## Legacy strategy values

`LegacyStrategyInterpretationImported` retains the original legacy strategy string and its field
evidence. It is intentionally not a raw visual candidate. Repeated strategy observations are valid
snapshot history and never make snapshot or `SessionState` construction fail.

If the string is a valid normalized strategy ID available in the current catalog, migration may
also append a `LEGACY_SNAPSHOT_INTERPRETATION` record with the exact current
`RulesetDependencyStamp`. This is weak audit history only:

- it cannot become current identification or occupancy;
- it becomes stale when any stamp field changes;
- early → late → early cannot revive the old generation;
- a manual confirmation must explicitly supersede it;
- repeated migration cannot remove that supersession.

Duplicate strong concrete claims remain the responsibility of the existing
`DUPLICATE_CONFIRMED_STRATEGY_CLAIM` query. Snapshot duplication is not used to synthesize that
conflict.

## Frozen snapshots and revision correction

`StrategySelectionSnapshot.frozen` closes only ordinary merging into the legacy materialized
view. The independent evidence ledger, corrections, commitments, direct/manual identification,
battle-entry evidence, and migration history remain open.

Revision correction does not delete or rewrite any of those histories. Catalog-derived and weak
legacy interpretation records are filtered by dependency freshness. Direct/manual claims remain
generation-independent and are rechecked against the current catalog; an incompatible strong
claim produces the existing catalog-compatibility conflict.

## Excluded scope

This migration creates no `BattleRoster`, runtime slot, slot association, assignment, HP matching,
annotation, coverage, session outcome, OCR, OpenCV, frame processing, Windows capture, UI, click
automation, real catalog, real icon asset, PRTS data, or M1 route behavior.
