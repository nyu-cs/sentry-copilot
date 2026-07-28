# Data contracts

## Player state

```json
{
  "slot": 2,
  "avatar_visual_key": "opaque-hash",
  "hp": 31,
  "status": "active",
  "strategy_id": null,
  "strategy_confidence": null
}
```

`avatar_visual_key` is not a strategy ID.

## Route query

```json
{
  "map_id": "demo.synthetic_training_map",
  "ruleset_id": "demo.v1",
  "actor_type": "boss",
  "stage_type": "final_boss",
  "wave": null,
  "actor_id": "boss.phantom_placeholder",
  "enemy_profiles": [],
  "boss_phase": "phase_1"
}
```

## Calibration

Corners are clockwise: top-left, top-right, bottom-right, bottom-left.

```json
{
  "frame_width": 1280,
  "frame_height": 720,
  "battlefield_corners": [
    {"x": 100, "y": 90},
    {"x": 1180, "y": 90},
    {"x": 1180, "y": 650},
    {"x": 100, "y": 650}
  ],
  "confidence": 1.0,
  "source": "manual"
}
```
