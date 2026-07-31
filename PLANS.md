# Living implementation plan

## M0 — Seed framework

- [x] Separate personalized avatars from strategies.
- [x] Model health and elimination.
- [x] Add a user-guided player strategy inspection workflow.
- [x] Add versioned map and route schemas.
- [x] Add route selection by map/stage/wave/actor/phase.
- [x] Add homography projection and overlay rendering.
- [x] Add synthetic fixtures and tests.

## M0.1a — Strategy-selection snapshot and in-session strategy query

- [x] Add minimal ruleset-scoped strategy definitions.
- [x] Add session-local strategy-selection participants with four-digit player tags.
- [x] Keep field-level evidence for tag, name, avatar, strategy, ready, self, and selection outcome.
- [x] Enforce participant, row, and non-empty tag uniqueness while preserving repeated legacy
  strategy observations for later interpretation.
- [x] Track an explicit expected participant count without inferring it from observations.
- [x] Compute strategy completeness for one to four participants who entered battle.
- [x] Preserve selection-stage exits in history while excluding them from the final team query.
- [x] Preserve selection history independently from runtime exit and elimination state.
- [x] Freeze snapshots while allowing explicit atomic manual correction.
- [x] Store the authoritative current snapshot in `SessionState`.
- [x] Expose a team strategy query that does not read runtime-slot strategy caches.

## M0.2a — Revision-aware session and strategy catalog foundation

### M0.2a.1 — SessionRulesetContext and normalized IDs

- [x] Add normalized ruleset, revision, strategy, catalog-version, and locale identifiers.
- [x] Add an immutable `SessionRulesetContext` with unknown-revision support and audit history.
- [x] Add a locale-aware dependency stamp and monotonic context generation contract.
- [x] Keep legacy session ruleset/locale fields as validated compatibility mirrors.
- [x] Keep the M0.1a snapshot ruleset as a compatibility assertion, not a second authority.

### M0.2a.2 — Revision-aware synthetic strategy catalog

- [x] Add ruleset, revision, strategy identity, revision profile, and locale resource models.
- [x] Keep both icon keys and asset references authoritative only on the revision profile.
- [x] Add revision-aware lookup and cross-record catalog validation.
- [x] Add synthetic strategies and icons without real game data.
- [x] Separate target support declarations from validated support records.
- [x] Reuse the existing PyYAML dependency and share one parser/validator between runtime loading
  and repository validation.
- [x] Keep revision profiles minimal; localized descriptions carry human-readable effects, with no
  structured effect language or recommendation fields in M0.2a.

### M0.2a.3 — Revision selection and correction

- [x] Add manual and replay-metadata revision selection.
- [x] Support repeated explicit corrections with atomic immutable updates.
- [x] Keep one current revision and an auditable revision-change history.
- [x] Preserve raw evidence while invalidating revision-dependent derived results by dependency stamp.
- [x] Report catalog mismatch without silently switching revisions.

## M0.2b — Confirmed strategy occupancy and prebattle migration

### M0.2b.1 — Prebattle evidence and ready-confirmed commitment

- [x] Add typed raw candidate and ready-check observations without normalized strategy identity.
- [x] Address every prebattle evidence item by stable ID and make event replay idempotent.
- [x] Preserve ready-confirmed strategy-unknown as a valid state.
- [x] Keep the first effective ready time stable while repeated ready observations add evidence.
- [x] Correct false-positive ready interpretations without deleting original evidence or adding an
  in-game unready/release transition.
- [x] Validate session and participant ownership for every new prebattle event.

### M0.2b.2 — Concrete strategy identification and occupancy conflicts

- [x] Add basis-aware concrete strategy identification with conditional dependency stamps.
- [x] Distinguish duplicate-confirmed-claim, participant-identification, and
  catalog-compatibility conflicts.
- [x] Derive only uncontested unique occupancy while preserving every claim and explicit
  supersession for audit.
- [x] Allow reliable normal battle-entry evidence to establish strategy-unknown commitment without
  inferring a concrete strategy or constructing a runtime roster.
- [x] Treat a first stable battle frame that is already inactive as entry-not-confirmed, not as
  proof that the displayed participant entered battle.

### M0.2b.3 — Legacy snapshot migration and revision invalidation

- [x] Migrate legacy snapshot evidence explicitly and idempotently with stable operation,
  fingerprint, evidence, and identification IDs.
- [x] Import legacy ready values into typed evidence without moving an earlier commitment time or
  restoring evidence excluded by a false-positive correction.
- [x] Preserve legacy strategy values as weak, revision-dependent interpretation history that
  cannot directly create current identification or occupancy.
- [x] Reposition snapshot completeness as prebattle data quality only and allow repeated legacy
  strategy observations.
- [x] Keep frozen snapshots open to independent evidence, correction, identification, and migration
  histories.
- [x] Preserve all history across revision correction and derive freshness and compatibility at
  query time.

## M0.2c — Runtime roster and slot assignment

- [ ] Add battle roster and runtime player slots.
- [ ] Add slot-participant association and slot-strategy assignment.
- [ ] Keep selection rows independent from runtime slots.

## M0.2d — Manual fallback and conflict resolution

- [ ] Redefine the top-left strategy panel workflow as fallback.
- [ ] Allow unresolved fallback observations with explicit runtime context.
- [ ] Resolve by player tag, unique legal strategy, direct panel, or user confirmation.
- [ ] Do not create selection participants from fallback observations.

## M1 — Replay route overlay

- [ ] Add image-folder input in addition to video input.
- [ ] Accept a manual calibration JSON containing battlefield corners.
- [ ] Export overlay images at requested timestamps.
- [ ] Export one JSONL route observation per processed frame.
- [ ] Save failures such as unknown map or low calibration confidence.
- [ ] Add a synthetic integration test.

## M2 — Player inspection panel

- [ ] Add a small desktop panel for four player slots.
- [ ] Show avatar fingerprint, health, status, strategy, confidence, and last observation.
- [ ] Guide the user through selecting a player and opening the top-left strategy panel.
- [ ] Add a fixture-backed placeholder strategy recognizer.
- [ ] Require confirmation for low-confidence results.

## M3 — Real map annotation workflow

- [ ] Build a click-based route annotation tool.
- [ ] Store routes in normalized coordinates.
- [ ] Support branching, teleport, wait, and phase-change steps.
- [ ] Associate routes with wave, enemy/Boss ID and ruleset.
- [ ] Add map-calibration examples without committing game assets.

## Deferred

- Add a typed runtime participation transition event carrying `observed_at`, stage, optional round,
  optional wave, previous/new participation status, inactivation reason, inactive presentation,
  HP, confidence, and evidence.
- Model participation as `ACTIVE` or terminal `INACTIVE`; group active leave and disconnect under
  `LEFT_OR_DISCONNECTED`, separate from `HP_DEPLETED`.
- Distinguish `DEPARTED`, `SPECTATING`, and unknown presentation without treating presentation
  alone as an inactivation reason.
- Reserve runtime stage values for `normal` and `secret_core`; secret core does not require a
  numeric round.
- Observe every player at least once per wave, continue monitoring within a wave, and emit events
  only when status changes.
- Allow roster checkpoints at wave start or wave end without mutating strategy-selection history.
- Add a separate current-active-team query later; keep M0.1a `TeamStrategyContext` historical.
- Automatic clicks.
- Shop recognition.
- Automatic deployment.
- End-to-end reinforcement learning.
- Fully automatic route discovery from unlabelled videos.
