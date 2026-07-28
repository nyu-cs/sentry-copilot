# Map and route system

## Output

The assistant can eventually show:

- current-wave enemy routes;
- alternate or branching routes;
- Boss routes such as phase-specific movement;
- teleport/jump transitions;
- wait or phase-change nodes;
- confidence and verification status.

## Coordinates

Route points use normalized battlefield coordinates:

```text
(0,0) ---------------- (1,0)
  |                      |
  |     battlefield      |
  |                      |
(0,1) ---------------- (1,1)
```

Four screen-space battlefield corners define a homography that projects those normalized points into the captured frame. This makes route geometry independent of resolution, window size, and minor perspective-like distortion.

## Route steps

- `move`: continuous polyline.
- `teleport`: discontinuous jump.
- `wait`: pause location.
- `phase_change`: route-relevant Boss state change.

## Conditions

Routes may be filtered by:

- stage type;
- wave number;
- actor ID (enemy or Boss);
- enemy profile;
- Boss phase.

All routes also belong to one `map_id` and one or more `ruleset_id` values.

## Data acquisition

1. **Manual annotation first**: watch a replay, click waypoints, store reviewed YAML.
2. **Assisted annotation**: track enemies and propose paths for human correction.
3. **Statistical discovery**: align trajectories from many recordings, cluster them, and create provisional routes.

Unknown or low-confidence map/calibration results must suppress the overlay rather than guess.
