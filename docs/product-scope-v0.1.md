# Product scope v0.1

## Included

### Player status

- Read four fixed player slots.
- Treat the portrait as an opaque personalized avatar fingerprint.
- OCR the health below each portrait.
- Mark `hp <= 0` as eliminated.
- Guide the user through inspecting another player's strategy.
- Keep manual correction and confidence visible.

### Route panel

- Show recognized/manual map name and ruleset.
- Show current round and selected enemy/Boss.
- Toggle enemy routes, Boss routes, provisional routes, and labels.
- Draw movement arrows, teleport segments, wait nodes, and phase-change nodes.
- Display `unknown map`, `calibration required`, or `no matching route` rather than guessing.

### Offline development

- Read videos and image folders.
- Use manual map selection and calibration first.
- Store route knowledge in YAML.
- Export observations for regression tests.

## Excluded for now

- Shop recognition.
- Automatic clicks.
- Automatic placement.
- Strategy recommendation.
- Fully automatic route learning.

## Suggested desktop layout

```text
┌──────────────── Sentry Copilot ────────────────┐
│ Session: CN / demo.v1   Map: [recognized/manual]│
├─────────────────────────────────────────────────┤
│ Players                                         │
│ 1  avatar  HP 16  SELF   Strategy: known        │
│ 2  avatar  HP 31  ACTIVE Strategy: ? [inspect]  │
│ 3  avatar  HP 24  ACTIVE Strategy: ? [inspect]  │
│ 4  avatar  HP  0  OUT    Strategy: known        │
├─────────────────────────────────────────────────┤
│ Routes                                          │
│ Round 7   Enemy/Boss: ...                       │
│ [x] enemy routes  [x] Boss routes  [ ] labels   │
│ Map confidence 0.94  Calibration 0.91           │
│ Route source: video-verified / provisional      │
├─────────────────────────────────────────────────┤
│ Current prompt                                  │
│ Click player 2, then open the top-left strategy │
│ panel.                                          │
└─────────────────────────────────────────────────┘
```
