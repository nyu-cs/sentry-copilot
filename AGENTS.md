# AGENTS.md

## Project objective

Build a portfolio-quality, replay-first, read-only assistant for Arknights Sentry Protocol.
The repository must remain useful and testable while the game mode is unavailable.

## Non-negotiable domain rules

1. The left-side portrait is a personalized player avatar, not the selected strategy.
2. Never derive or set `strategy_id` from `avatar_visual_key`.
3. The strategy-selection screen is the primary prebattle acquisition source. The reducer-owned
   `StrategySelectionSnapshot` is an immutable prebattle materialized view and historical query
   source; it is not the future runtime-slot annotation authority.
4. `player_tag` is a session-local four-digit string. It is not a global account identifier.
5. `selection_row` is not a runtime player slot. Never bind them by order.
6. A strategy snapshot contains at most four participants. Completeness is relative to an explicit
   `expected_participant_count` of players whose `selection_outcome` is `entered_battle`; never
   infer that count from the number of observed participants. Snapshot completeness is legacy
   prebattle field coverage, not confirmed occupancy; repeated legacy strategy values are allowed.
7. Strategy selection is historical state. Runtime inactivation must not change
   `selection_outcome`, remove participants, change strategies, or change snapshot completeness.
   Future business logic groups active leave and disconnect under `LEFT_OR_DISCONNECTED`; it must
   not treat disconnect as a separate inactivation reason.
8. The top-left strategy panel is a fallback. Using it requires the user to explicitly:
   - selects that player's portrait,
   - switches to that player's field,
   - opens the top-left strategy panel,
   - captures the panel with explicit runtime context.
9. The number below the portrait is health. `hp <= 0` means the player is eliminated.
10. Do not automate clicks in the MVP.
11. Every route is scoped by `ruleset_id` and `map_id`.
12. Store route points in normalized battlefield coordinates, never fixed screen pixels.
13. Low-confidence map recognition or calibration must produce an explicit unknown result and no overlay.
14. Do not add game assets, third-party recordings, or unlicensed screenshots to Git.
15. `SessionRulesetContext` is the sole authority for new ruleset-, revision-, locale-, and
    catalog-aware code. Legacy `SessionState.ruleset_id`, `SessionState.locale`, and snapshot
    `ruleset_id` values are compatibility mirrors or assertions only.
16. The target ruleset's confirmed Chinese name is `卫戍协议：盟约 下半`. Its pre-update and
    post-update revisions are separate data states; do not confuse the name's `下半` with a
    revision.
17. A legacy `StrategySelectionParticipant.strategy_id` may already contain catalog-dependent
    interpretation. Preserve it through the explicit, audited migration adapter, but never treat
    the imported weak interpretation as current identification, occupancy, or assignment.
18. `RulesetStrategyProfile` is the sole icon-mapping authority for a strategy in one revision.
    `StrategyIdentity` stores only the normalized strategy ID, and locale resources never store
    icons.
19. A target-support declaration is not validated support. Synthetic catalog validation proves
    only the synthetic fixture and must never be presented as validation of a real game revision.
20. Ruleset revision selection and correction are explicit command-service operations. The
    generic reducer accepts only catalog-validated facts and must never load YAML, access the file
    system, infer a revision, or silently switch contexts.
21. A raw prebattle strategy candidate is evidence, not a normalized `strategy_id` and not
    occupancy. Every prebattle evidence item has a stable ID; replaying the same ID is idempotent.
22. A visible ready check is the per-player evidence for an irreversible in-game selection.
    Repeated ready evidence does not create another commitment or move its first confirmation time.
    There is no game-domain unready or release transition.
23. False-positive ready recognition is a correctable assistant interpretation. Manual correction
    preserves the original observation and excludes it from the effective evidence set; it never
    claims that the player cancelled ready in the game.
24. Battle UI presence does not prove battle entry. Only reliable observation of normal active
    participation establishes a battle entrant; a first stable frame already showing departure
    remains entry-not-confirmed.
25. Runtime participation is `ACTIVE` or terminal `INACTIVE`. Assistant-record corrections may
    invalidate or replace mistaken entry/inactivation evidence, but they are not game-domain
    re-entry, reactivation, or revival transitions.
26. Future direct strategy-panel evidence must bind to an already associated participant. The
    manual fallback establishes `runtime slot -> participant` from the displayed `name#XXXX`
    before deriving participant strategy and slot assignment; do not add a slot-only strategy
    authority or `DIRECT_SLOT_STRATEGY_PANEL` bypass.
24. Concrete strategy identification is separate from raw evidence and commitment. Catalog-derived
    identification requires raw candidate evidence and the current dependency stamp; direct and
    manual identification remain generation-independent but must be checked against the current
    catalog.
25. A confirmed strategy has at most one valid occupant. Duplicate concrete claims are an
    assistant interpretation conflict, never a valid duplicate game occupancy. Keep every claim
    and its evidence, expose no contested occupancy, and require explicit correction.
26. Displayed in the battle UI does not mean entered battle. Only reliable observation of normal
    active participation may produce `BATTLE_ENTRY_CONFIRMED`. A first stable frame that already
    shows departure cannot create a commitment, concrete identification, or occupancy; prior ready
    evidence remains authoritative if it exists.
27. Legacy snapshot migration is explicit and idempotent by operation ID and canonical snapshot
    fingerprint. `snapshot.frozen` closes only ordinary legacy snapshot merging; it never closes
    the independent evidence, correction, commitment, identification, or migration histories.

## Module boundaries

- `capture/`: produces frames only.
- `vision/`: produces observations only; it must not mutate session state.
- `domain/reducer.py`: applies events and domain invariants to `SessionState`.
- `domain/rulesets.py`: owns immutable session ruleset/revision context and dependency identity.
- `catalogs/`: loads exact revision-aware strategy and locale data and applies shared validation.
- `services/ruleset_context_service.py`: validates explicit context commands against catalogs
  before dispatching accepted facts to the reducer.
- `domain/strategy_selection.py`: owns the reducer-managed strategy snapshot for up to four players.
- `domain/prebattle.py`: owns typed, immutable, evidence-ID-addressed raw prebattle history.
- `domain/prebattle_migration.py`: owns immutable legacy migration audit history.
- `domain/strategy_commitment.py`: derives current ready-confirmed commitments from effective
  ready evidence without assigning a concrete strategy.
- `domain/battle_roster.py`: owns immutable runtime participation history and derives the current
  `BattleRoster` from effective entry and inactivation evidence.
- `domain/strategy_identification.py`: owns immutable concrete claim history, supersession,
  conflict read models, and query-derived uncontested occupancy.
- `services/strategy_identification_service.py`: validates concrete claims against commitment and
  the current catalog before dispatching accepted immutable facts.
- `services/prebattle_migration_service.py`: explicitly imports one legacy snapshot into typed
  evidence and weak, non-authoritative interpretation history.
- `player/`: owns user-guided fallback inspection workflows.
- `routes/`: owns map/route schemas, selection, projection, and rendering.
- `services/`: orchestrates modules without embedding recognition heuristics.

## Commands

```bash
pip install -e ".[dev]"
pytest
ruff check .
python -m mypy
python tools/validate_repository.py
python -m sentry_copilot.cli validate-data --maps data/maps
python -m sentry_copilot.cli demo-route-overlay \
  --map-file data/maps/demo.synthetic_training_map.yaml \
  --output outputs/demo_route_overlay.png
```

## Definition of done

- Add or update tests for every domain behavior change.
- Keep public APIs typed and documented.
- Run `pytest` and `ruff check .`.
- Update the relevant file under `docs/` when a data contract changes.
- Do not silently expand scope into shop recognition, deployment, or input automation.

Read `PLANS.md` and `docs/CODEX_NEXT_TASK.md` before implementation work.
