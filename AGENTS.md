# AGENTS.md

## Project objective

Build a portfolio-quality, replay-first, read-only assistant for Arknights Sentry Protocol.
The repository must remain useful and testable while the game mode is unavailable.

## Non-negotiable domain rules

1. The left-side portrait is a personalized player avatar, not the selected strategy.
2. Never derive or set `strategy_id` from `avatar_visual_key`.
3. The strategy-selection screen is the primary strategy acquisition source. The reducer-owned
   `StrategySelectionSnapshot` is the authoritative in-session strategy state.
4. `player_tag` is a session-local four-digit string. It is not a global account identifier.
5. `selection_row` is not a runtime player slot. Never bind them by order.
6. A strategy snapshot contains at most four participants. Completeness is relative to an explicit
   `expected_participant_count` of players whose `selection_outcome` is `entered_battle`; never
   infer that count from the number of observed participants.
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

## Module boundaries

- `capture/`: produces frames only.
- `vision/`: produces observations only; it must not mutate session state.
- `domain/reducer.py`: applies events and domain invariants to `SessionState`.
- `domain/strategy_selection.py`: owns the reducer-managed strategy snapshot for up to four players.
- `player/`: owns user-guided fallback inspection workflows.
- `routes/`: owns map/route schemas, selection, projection, and rendering.
- `services/`: orchestrates modules without embedding recognition heuristics.

## Commands

```bash
pip install -e ".[dev]"
pytest
ruff check .
python -m mypy
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
