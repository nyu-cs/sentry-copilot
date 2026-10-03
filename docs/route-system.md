# Independent map and route system

This supporting subsystem is independently testable and is not wired into the live encounter
panel or counted in its progress. The public demo uses synthetic data.

## Supported route representation

The route schemas, selection, projection, and rendering support:

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

## Inputs and demonstration

Routes are explicitly supplied, reviewed YAML. Manual map selection and battlefield calibration
providers are implemented; automatic route learning and a waypoint-annotation UI are not claimed.
Unknown or low-confidence map/calibration results suppress the overlay rather than guessing.

```bash
python -m sentry_copilot.cli validate-data --maps data/maps
python -m sentry_copilot.cli demo-route-overlay --map-file data/maps/demo.synthetic_training_map.yaml --output outputs/demo_route_overlay.png
```

The synthetic output demonstrates engineering behavior, not verified real-game routes. Keep
recordings and unpublished annotations local; see [Validation](validation.md).
