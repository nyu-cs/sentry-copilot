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

The `strategy_id` fields on this runtime-slot model are retained as a legacy cache during M0.1.
New team strategy queries read `SessionState.strategy_selection`, not this field.
`PlayerState.status` is also a legacy observation/cache enum. Its `LEFT` and `DISCONNECTED` values
must not become separate business outcomes in the future runtime model.

## Minimal strategy definition

```json
{
  "strategy_id": "strategy.synthetic.guard",
  "names": {
    "zh_CN": "合成守备策略",
    "ja_JP": "合成防衛戦略"
  },
  "ruleset_ids": ["demo.v1"],
  "description": null,
  "tags": []
}
```

Only synthetic definitions are used until real strategy rules are confirmed.
In Python, `ruleset_ids` and `tags` are `frozenset[str]` so a validated definition cannot be
mutated later. JSON continues to represent them as arrays.

## Strategy-selection participant

`player_tag` stores four digits without the display `#`. Each known field has independent evidence.
Participant models are frozen. Their field-evidence mapping is immutable after validation but
continues to serialize as a JSON object with string enum keys.

```json
{
  "session_player_id": "session-player-a",
  "selection_row": 1,
  "player_tag": "0038",
  "display_name": null,
  "avatar_visual_key": null,
  "strategy_id": "strategy.synthetic.guard",
  "ready": true,
  "is_self": null,
  "selection_outcome": "entered_battle",
  "field_evidence": {
    "player_tag": {
      "source": "manual",
      "confidence": 1.0,
      "observed_at": "2026-01-01T00:00:00Z",
      "source_detail": "synthetic example"
    },
    "strategy": {
      "source": "observed",
      "confidence": 0.95,
      "observed_at": "2026-01-01T00:00:00Z",
      "source_detail": "synthetic example"
    },
    "ready": {
      "source": "observed",
      "confidence": 0.95,
      "observed_at": "2026-01-01T00:00:00Z",
      "source_detail": "synthetic example"
    },
    "selection_outcome": {
      "source": "observed",
      "confidence": 0.95,
      "observed_at": "2026-01-01T00:00:00Z",
      "source_detail": "synthetic example"
    }
  }
}
```

Selection outcome is one of `entered_battle`, `left_unready`, `exited_before_strategy`,
`exited_after_strategy`, or `unknown`. It describes the selection phase only and does not reuse
runtime `LEFT`, `DISCONNECTED`, or `ELIMINATED` status. Only `entered_battle` participates in final
team completeness, identity completeness, default team queries, and final-team strategy
uniqueness. An `exited_after_strategy` participant may retain a temporary strategy that duplicates
an entered participant's strategy.
Every `observed_at` value must include a timezone.

## Strategy-selection snapshot

```json
{
  "session_id": "session.synthetic",
  "ruleset_id": "demo.v1",
  "expected_participant_count": null,
  "captured_at": "2026-01-01T00:00:00Z",
  "participants": [],
  "frozen": false,
  "evidence": []
}
```

Derived properties:

- `strategy_complete`: the snapshot is frozen, expected count is known, `entered_battle` count
  equals it, and every entered participant has a unique strategy.
- `identity_complete`: strategy is complete and every entered participant has a valid unique
  four-digit player tag.
- `completeness_level`: `partial`, `strategies_complete`, or `fully_identified`.

`expected_participant_count` is `null` until reliably established and must never be inferred from
the number of recognized participants. It is the final number that entered battle, not initial
selection-screen population or current survivors. Its allowed range is one to four. Display names,
avatars, self recognition, and runtime-slot association do not affect completion. Runtime `LEFT`,
`DISCONNECTED`, `ELIMINATED`, or `hp <= 0` updates do not change `selection_outcome`, remove
participants, release their strategy IDs, or recompute snapshot completeness.

Snapshot models are frozen. Python stores participants and snapshot evidence as tuples; JSON
continues to use arrays. `captured_at` and all strategy-selection event timestamps must include a
timezone. Reducer updates rebuild and validate a new snapshot instead of mutating the existing one.

## Future runtime participation transition

This is a reserved contract, not an M0.1a recognizer or capture loop:

```json
{
  "observed_at": "2026-01-01T00:00:00Z",
  "stage_type": "secret_core",
  "round_number": null,
  "wave_number": 2,
  "previous_participation_status": "active",
  "new_participation_status": "inactive",
  "inactivation_reason": "hp_depleted",
  "inactive_presentation": "spectating",
  "hp": 0,
  "confidence": 0.99,
  "evidence": ["synthetic.spectating-icon"]
}
```

The reserved runtime domain has three independent concepts:

- `PlayerParticipationStatus`: `active` or terminal `inactive`;
- `PlayerInactivationReason`: `left_or_disconnected`, `hp_depleted`, or `unknown`;
- `InactivePresentation`: `departed`, `spectating`, or `unknown`.

Active leave and disconnect both map to `inactive + left_or_disconnected + departed`. HP depletion
maps to `inactive + hp_depleted` with either departed or spectating presentation. A departed icon
alone is ambiguous: without HP=0 or other death evidence it cannot establish `hp_depleted`, so
reason remains `unknown` with evidence and confidence retained. A spectating icon is explicit
evidence of HP depletion. Spectating means the player is still watching, not contributing.

`inactive` is terminal and does not automatically return to `active`. Once inactive, later HP,
actions, and team contribution are not analyzed. A future current-active-team query will exclude
all inactive players; M0.1a `TeamStrategyContext` remains a historical strategy query.

Runtime stage type must at least distinguish `normal` and `secret_core`. Secret core is not encoded
as a fixed ordinary round, so `round_number` may be `null`. Future live work should inspect every
player at least once per wave, continue observing the player bar within a wave, emit an event when
status changes, and optionally save roster checkpoints at wave start or end. These runtime records
may occur in any normal wave, stage interval, or secret-core wave and must never mutate
`StrategySelectionSnapshot`, lower expected participant count, or clear historical strategy IDs.

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
