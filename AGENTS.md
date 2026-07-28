# AGENTS.md

## Project objective

Build a portfolio-quality, replay-first, read-only assistant for Arknights Sentry Protocol.
The repository must remain useful and testable while the game mode is unavailable.

## Non-negotiable domain rules

1. The left-side portrait is a personalized player avatar, not the selected strategy.
2. Never derive or set `strategy_id` from `avatar_visual_key`.
3. In v0.1, another player's strategy is observed only after the user explicitly:
   - selects that player's portrait,
   - switches to that player's field,
   - opens the top-left strategy panel,
   - captures the panel with an explicit `player_slot` context.
4. The number below the portrait is health. `hp <= 0` means the player is eliminated.
5. Do not automate clicks in the MVP.
6. Every route is scoped by `ruleset_id` and `map_id`.
7. Store route points in normalized battlefield coordinates, never fixed screen pixels.
8. Low-confidence map recognition or calibration must produce an explicit unknown result and no overlay.
9. Do not add game assets, third-party recordings, or unlicensed screenshots to Git.

## Module boundaries

- `capture/`: produces frames only.
- `vision/`: produces observations only; it must not mutate session state.
- `domain/reducer.py`: applies events and domain invariants to `SessionState`.
- `player/`: owns the user-guided strategy inspection workflow.
- `routes/`: owns map/route schemas, selection, projection, and rendering.
- `services/`: orchestrates modules without embedding recognition heuristics.

## Commands

```bash
pip install -e ".[dev]"
pytest
ruff check .
mypy src
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
