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

## Session ruleset context

New revision-aware code reads one immutable `SessionRulesetContext`:

```json
{
  "ruleset_id": "sentry_protocol.covenant_latter",
  "ruleset_revision_id": "sentry_protocol.covenant_latter.pre_update",
  "locale_id": "zh_CN",
  "catalog_version": "catalog.synthetic.v1",
  "selection_method": "manual",
  "selected_at": "2026-01-01T00:00:00Z",
  "selection_evidence": [],
  "selection_reason": "synthetic explicit selection",
  "revision_history": [],
  "context_generation": 1
}
```

The normalized ruleset corresponds to the confirmed Chinese display name
`卫戍协议：盟约 下半`. Display names are not IDs. The name's `下半` is distinct from the
pre-update and post-update catalog revisions.

An unknown revision uses `null` for revision and catalog version, `unknown` selection method, and
generation zero. When replaced, it is retained as a generation-zero history record. A selected
revision requires a catalog version, a non-unknown selection method, and a positive generation.
All selection and replacement times must include a timezone, and `replaced_at >= selected_at`.

`SessionState.ruleset_id` and `SessionState.locale` remain compatibility mirrors. Construction
fills omitted mirrors from context and rejects explicitly conflicting mirrors. Without a context,
legacy M0.1a construction remains valid. Snapshot `ruleset_id` must match the effective context but
does not become a second authority.

Future revision-dependent values use this stamp:

```json
{
  "ruleset_id": "sentry_protocol.covenant_latter",
  "ruleset_revision_id": "sentry_protocol.covenant_latter.pre_update",
  "locale_id": "zh_CN",
  "catalog_version": "catalog.synthetic.v1",
  "context_generation": 1
}
```

M0.2a.1 defines only the dependency identity. It does not create occupancy, assignment,
annotation, coverage, or other future caches.

Explicit operations use `SelectSessionRulesetContext` or `CorrectSessionRulesetRevision`. The
application service verifies the exact catalog, ruleset, revision, and locale before creating
`SessionRulesetContextSelected` or `SessionRulesetRevisionCorrected`. The reducer applies only
these accepted facts. A complete duplicate is rejected without adding history or generation;
same revision with a different validated catalog version is an explicit correction.

`get_session_ruleset_context(state)` and
`get_current_ruleset_dependency_stamp(state)` are read-only queries. The latter returns `null`
while revision is unknown. M0.2a.3 creates no occupancy, assignment, annotation, coverage, or
invalidation ledger.

## Revision-aware strategy catalog

Stable identity is deliberately minimal:

```json
{"strategy_id": "strategy.synthetic.guard"}
```

Revision-specific facts live on the profile:

```json
{
  "ruleset_revision_id": "demo.synthetic_covenant_latter.pre_update",
  "strategy_id": "strategy.synthetic.guard",
  "availability": "available",
  "initial_hp": 101,
  "icon_visual_key": "icon.synthetic.guard.pre_update",
  "icon_asset_reference": "icons/pre_update/guard.svg"
}
```

The profile is the only icon-mapping authority. `StrategyIdentity` has no icon field, and locale
resources have no icon field. Human-readable resources use an exact revision/strategy/locale key:

```json
{
  "ruleset_revision_id": "demo.synthetic_covenant_latter.pre_update",
  "strategy_id": "strategy.synthetic.guard",
  "locale_id": "zh_CN",
  "name": "合成守备方案甲",
  "description": "仅供合成测试的描述。",
  "ocr_aliases": ["合成守备甲"],
  "visible_text_variants": ["合成守备方案 A"]
}
```

There is no implicit revision or locale fallback. The catalog loader validates references,
uniqueness, required locale coverage, positive initial HP, safe relative assets, resolved files,
and catalog-version identity before exposing any lookup.

`SupportTarget` declares intended product support. `ValidationRecord` stores only a validation
kind, outcome, aware timestamp, catalog version, and evidence references. Neither a target
declaration nor a passing synthetic fixture means that a real ruleset/revision/locale combination
has validated support. Support metadata is registry data and is not copied into `SessionState`.

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
runtime `LEFT`, `DISCONNECTED`, or `ELIMINATED` status. In the M0.1a compatibility model, only
`entered_battle` participates in snapshot completeness, identity completeness, default team
queries, and snapshot-level strategy uniqueness. This is not the approved confirmed-occupancy
rule. An `exited_after_strategy` record may currently retain duplicate legacy strategy evidence;
M0.2b will distinguish candidates from ready-confirmed permanent occupancy.
Every `observed_at` value must include a timezone.

The legacy `strategy_id` field may contain normalized interpretation produced by an older catalog,
not a revision-independent raw visual fact. M0.2a preserves the field and evidence but new
revision-aware logic must not use it to establish occupancy, runtime assignment, or
catalog-dependent confirmation. M0.2b will separate raw strategy observations from normalized
interpretation.

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
