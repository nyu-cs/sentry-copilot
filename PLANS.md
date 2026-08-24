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

### M0.2c.1 — Battle participation facts and BattleRoster

- [x] Derive battle entrants only from effective confirmed normal-participation evidence.
- [x] Preserve entry-not-confirmed evidence for a first stable frame already showing departure.
- [x] Add `ACTIVE` / terminal `INACTIVE`, inactivation reason, presentation, and normal/secret-core
  stage context.
- [x] Correct false-positive entry and inactivation interpretations without deleting evidence or
  adding game-domain re-entry/reactivation transitions.
- [x] Keep `BattleRoster` query-derived rather than persisting a second materialized mirror.

### M0.2c.2 — Runtime slots and participant association

- [x] Add query-derived runtime player slots without binding them to selection rows by order.
- [x] Add layout epochs and preserve slot identity only when continuity is explicitly reliable.
- [x] Add conflict-aware, one-to-one slot-participant association for confirmed entrants.
- [x] Support `DIRECT_PLAYER_TAG` from the manually visited player's bottom `name#XXXX` display.
- [x] Support direct self-marker and explicit manual confirmation without avatar/HP matching.
- [x] Keep association unresolved when the tag cannot be read; preserve auditable corrections.

### M0.2c.3 — Slot-strategy assignment

- [x] Derive assignment only through uncontested slot-participant association, confirmed entry,
  effective participant identification, and uncontested occupancy.
- [x] Bind manual strategy-panel evidence to an already associated participant through existing
  direct-observation identification.
- [x] Do not create `DIRECT_SLOT_STRATEGY_PANEL` or any slot-only strategy authority.

## M0.2d — Manual fallback and conflict resolution

- [ ] Redefine the top-left strategy panel workflow as fallback.
- [ ] Allow unresolved fallback observations with explicit runtime context.
- [ ] Resolve participant association by player tag or user confirmation before applying direct
  panel evidence to that participant.
- [ ] Do not create selection participants from fallback observations.

## M0.3a — Offline frame input foundation

### M0.3a.1 — FrameSource and raw frame dump

- [x] Add immutable `Frame` and source-neutral `FrameSource` contracts.
- [x] Read caller-provided image sequences and local videos with OpenCV I/O only.
- [x] Export caller-directed raw PNG dumps with minimal source/session metadata.
- [x] Keep capture input independent of domain, vision, viewport, and recognition logic.

### M0.3a.2 — Content viewport and ROI debug

- [x] Add immutable caller-calibrated game-content viewports bound to individual frames.
- [x] Add normalized content-relative ROI to pixel conversion and safe immutable cropping.
- [x] Export caller-directed debug images without changing source frames or adding recognition.

### M0.3a.3 — Offline validation runner

- [x] Run an explicitly supplied image sequence or local video through the frame/viewport pipeline.
- [x] Support explicit full-frame or pixel viewport configuration, named normalized ROIs, and
  frame-index sampling.
- [x] Export selected frame/ROI debug PNGs and a compact JSONL manifest without private-data scans.

### M0.3a.4 — Windows live display capture

- [x] Add an explicit physical-monitor Windows `FrameSource` with bounded read-only smoke capture.
- [x] Preserve physical pixel dimensions and immutable frames across configurable target FPS capture.
- [x] Export caller-directed sampled PNGs and a minimal JSONL manifest without window tracking or recognition.

## M0.3b — Vision foundations

### M0.3b.1 — Template matching

- [x] Add source-neutral OpenCV matching against explicit frame, content viewport, ROI, and template inputs.
- [x] Return immutable score, threshold, bounds, and frame/source provenance with opt-in debug output.
- [x] Keep tests and interfaces synthetic and free of game-specific screen rules or assets.

### M0.3b.2 — OCR foundation

- [x] Add source-neutral OCR over caller-supplied content-relative regions only.
- [x] Return immutable raw/normalized text, optional confidence, pixel geometry, and frame/source
  provenance while preserving explicit unknown and empty outcomes.
- [x] Use Windows built-in OCR through Python/WinRT without external OCR executables or models;
  report unavailable system language capabilities explicitly.

### M0.3b.3 — Live OCR probe

- [x] Add an explicit one-frame Windows-display probe with one normalized or pixel ROI and no
  game-specific interpretation.
- [x] Export a caller-owned frame, unannotated ROI crop, and compact OCR/provenance JSON result.
- [x] Check local OCR language capabilities without installing Windows features, and preserve a
  typed unavailable probe result when a capability such as `ja-JP` is absent.

## M0.3c — Recognition probe harness

- [x] Run explicit OCR and template-matching operations over one caller-selected local image or
  one explicitly selected Windows display frame.
- [x] Preserve caller-defined normalized or pixel ROIs, source/template/language provenance, and
  typed per-operation failures in caller-owned diagnostic artifacts.
- [x] Keep the harness game-agnostic: it does not discover ROIs, inspect private inputs, mutate
  domain state, or add game recognition rules.

## M0.4 — Visual identity references and matching

### M0.4a — Visual reference catalog foundation

- [x] Load caller-declared strategy or avatar references without directory scanning.
- [x] Preserve stable identity, render context, asset provenance, and deterministic catalog
  fingerprints independently from player identity or strategy occupancy.

### M0.4b — JP strategy catalog bootstrap

- [x] Bootstrap revision-aware JP strategy metadata and private visual-reference workflows without
  committing real assets or claiming full live validation.

### M0.4c — Local-feature visual matcher foundation

- [x] Add catalog-backed SIFT, Lowe-ratio, and similarity-RANSAC matching as an independent
  cross-layout option while retaining exact template matching for same-layout renders.
- [x] Aggregate multiple references per stable identity, expose transform/inlier evidence, and
  return typed unresolved or ambiguous results without identity-specific tuning.
- [x] Cache reference descriptors in memory and provide an explicit, non-scanning JSON probe CLI.

## M0.6b — Runtime participant association

### M0.6b1a — Deterministic normalized-evidence core

- [x] Add a pure, bounded exhaustive association query for up to four active runtime slots.
- [x] Keep selection profile-avatar compatibility, self markers, and explicitly pre-loss initial
  HP as supporting normalized evidence, never standalone identities or scorers.
- [x] Return deterministic confirmed, unresolved/manual-confirmation-needed, inactive, or
  conflict results without persisting a second association authority.
- [x] Preserve previous confirmed mappings across later inactive runtime states and surface later
  contradiction rather than silently remapping.

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

- Observe every player at least once per wave, continue monitoring within a wave, and emit events
  only when status changes.
- Allow roster checkpoints at wave start or wave end without mutating strategy-selection history.
- Add a separate current-active-team query later; keep M0.1a `TeamStrategyContext` historical.
- Automatic clicks.
- Shop recognition.
- Automatic deployment.
- End-to-end reinforcement learning.
- Fully automatic route discovery from unlabelled videos.
