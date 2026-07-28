# Living implementation plan

## M0 — Seed framework

- [x] Separate personalized avatars from strategies.
- [x] Model health and elimination.
- [x] Add a user-guided player strategy inspection workflow.
- [x] Add versioned map and route schemas.
- [x] Add route selection by map/stage/wave/actor/phase.
- [x] Add homography projection and overlay rendering.
- [x] Add synthetic fixtures and tests.

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

- Automatic clicks.
- Shop recognition.
- Automatic deployment.
- End-to-end reinforcement learning.
- Fully automatic route discovery from unlabelled videos.
