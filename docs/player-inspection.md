# Fallback player inspection workflow

## Sidebar semantics

- Portrait: personalized avatar only.
- Number below portrait: current health.
- `hp <= 0`: player is eliminated from active participation and may depart or spectate.
- Strategy: not visible in the portrait.

## Primary strategy source

M0.1a records the selected strategies of up to four participants from the strategy-selection
screen. A frozen snapshot is complete relative to the explicit expected number of participants
whose selection outcome is `entered_battle`. That value may be one to four and is never inferred
from recognized rows. Selection-stage exits remain available in the raw snapshot but are excluded
from the default final-team query.

The snapshot is historical selection state. A later runtime `LEFT`, `DISCONNECTED`, or
`ELIMINATED` state does not change an entered player's selection outcome, remove its participant,
or clear its strategy. Current survivors and recorded selection participants are independent
concepts.

Those current enum labels are legacy observation/cache values. M0.2c.1 runtime business state uses:

- participation: `ACTIVE` or terminal `INACTIVE`;
- reason: `LEFT_OR_DISCONNECTED`, `HP_DEPLETED`, or `UNKNOWN`;
- presentation: `DEPARTED`, `SPECTATING`, or `UNKNOWN`.

Active leave and disconnect map to the same reason. A departed icon alone cannot distinguish that
reason from death followed by departure, so it must not imply `HP_DEPLETED` without HP=0 or other
death evidence. A spectating icon is positive evidence of `HP_DEPLETED`. Once inactive, later HP,
actions, and team contribution are no longer analyzed.

## Future user-guided fallback

```text
select target slot in assistant
→ user clicks the corresponding personalized avatar in game
→ user manually visits that player's perspective
→ assistant reads the bottom display name + #XXXX
→ the four-digit tag establishes runtime slot -> session participant association
→ user manually opens the top-left strategy panel on that player's field
→ panel evidence binds to the already associated participant
→ participant direct identification and uncontested occupancy are derived
→ runtime slot -> participant -> strategy assignment is derived
→ user corrects low-confidence output if needed
```

Display name alone is not unique. If the four-digit tag cannot be read reliably, association stays
unresolved or the user must explicitly confirm it. Seeing the strategy panel does not permit the
assistant to bypass participant association or create an independent slot-only strategy fact.
`DIRECT_SLOT_STRATEGY_PANEL` is not an authority basis.

The legacy reducer rejects a strategy event when `slot != selected_player_slot`. This prevents a
valid recognition result from being assigned to the wrong teammate, but it is not the future
assignment authority.

The future fallback uses `DIRECT_PLAYER_TAG` or explicit user confirmation for participant
association, then existing participant-bound `DIRECT_OBSERVATION` for the panel strategy. It never
creates a fifth participant and never automates any click, perspective change, or panel opening.

Do not infer inactivation from one missing frame. Insufficient evidence produces reason `UNKNOWN`
with confidence and evidence retained.
