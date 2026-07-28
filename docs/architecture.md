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
                ↙      ↘
      knowledge UI     route overlay service
```

## State ownership

Recognizers do not edit `SessionState`. The reducer enforces:

- avatar observations never change strategy;
- strategy observations require an explicitly selected player slot;
- non-positive health marks elimination;
- unknown evidence remains unknown;
- map and ruleset identity are explicit.

## Route subsystem boundaries

1. **Map recognition**: identify `map_id`.
2. **Calibration**: locate the battlefield in the current frame.
3. **Route selection**: select map-specific routes for the current encounter.
4. **Projection**: map normalized coordinates to frame pixels.
5. **Rendering**: draw paths, arrows, teleports and nodes.

The first version uses manual map choice and manual four-corner calibration. Real recognition can replace those providers without changing route data or rendering.
