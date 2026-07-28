# Player inspection workflow

## Sidebar semantics

- Portrait: personalized avatar only.
- Number below portrait: current health.
- `hp <= 0`: player is eliminated and leaves the match.
- Strategy: not visible in the portrait.

## v0.1 user-guided flow

```text
select target slot in assistant
→ user clicks the corresponding personalized avatar in game
→ user opens the top-left strategy panel on that player's field
→ assistant captures and recognizes the panel
→ assistant binds the result to the explicit target slot
→ user corrects low-confidence output if needed
```

The reducer rejects a strategy event when `slot != selected_player_slot`. This prevents a valid recognition result from being assigned to the wrong teammate.

Do not infer `LEFT` or `DISCONNECTED` from one missing frame. Those states require repeated evidence or manual confirmation.
