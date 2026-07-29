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
- [x] Enforce participant, row, non-empty tag, and non-empty strategy uniqueness.
- [x] Track an explicit expected participant count without inferring it from observations.
- [x] Compute strategy completeness for one to four participants who entered battle.
- [x] Preserve selection-stage exits in history while excluding them from the final team query.
- [x] Preserve selection history independently from runtime exit and elimination state.
- [x] Freeze snapshots while allowing explicit atomic manual correction.
- [x] Store the authoritative current snapshot in `SessionState`.
- [x] Expose a team strategy query that does not read runtime-slot strategy caches.

## M0.1b — Fallback inspection and runtime association

- [ ] Redefine the top-left strategy panel workflow as fallback.
- [ ] Allow unresolved fallback observations with a runtime slot and unique strategy.
- [ ] Model runtime association candidates and explicit user confirmation.
- [ ] Resolve by player tag, unique strategy, or manual binding without creating participants.
- [ ] Review removal of legacy `PlayerState.strategy_id` only after association exists.

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
