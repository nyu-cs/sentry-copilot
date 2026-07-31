# Battle participation and query-derived roster

## Scope

M0.2c.1 records battle-entry and runtime-inactivation facts and derives `BattleRoster` at query
time. It does not add runtime slots, participant association, slot-strategy assignment, OCR,
capture, UI, automatic clicks, or session-outcome logic.

`BattleRoster` is not persisted in `SessionState`. The state retains immutable evidence/history:

- `BattleEntryConfirmed`, `BattleEntryNotConfirmed`, and entry corrections in the prebattle
  ledger;
- `BattleParticipantInactivated` and inactivation corrections in `BattleParticipationState`.

`build_battle_roster(state)` combines the current effective facts. This avoids a second mutable
roster mirror.

## Entry boundary

`BattleEntryConfirmed` requires reliable observation that the participant appeared in normal
active battle participation. The following are not entry evidence:

- being present as a row or placeholder in the battle UI;
- a first stable frame that already shows departure/inactivity;
- ready commitment alone;
- concrete strategy occupancy alone;
- legacy selection outcome alone.

A first stable frame already showing departure is recorded as `BattleEntryNotConfirmed`. It does
not create a roster entrant, commitment, strategy, follow-up task, or assignment. Independent
ready/strategy history observed earlier remains intact.

Multiple valid entry observations strengthen the same entrant. The earliest effective timestamp
is `entered_at`. A manual `BattleEntryFalsePositiveCorrected` entry excludes targeted mistaken
evidence while preserving it for audit. If another effective entry remains, the participant stays
in the roster; otherwise the participant is no longer a confirmed entrant. Commitment is still
derived independently from any remaining ready, entry, or direct confirmation evidence.

## Participation lifecycle

Only a confirmed active entrant may receive `BattleParticipantInactivated`:

```text
ACTIVE -> INACTIVE
```

`INACTIVE` is terminal in normal game history. There is no `REACTIVATED`, `REENTERED`, or
`REVIVED` game event. Inactive entrants remain in the historical roster and keep their commitment,
identification, and strategy occupancy. `get_active_battle_participants` is a separate current
active-participant projection.

Runtime facts separate:

- `PlayerParticipationStatus`: `ACTIVE` or `INACTIVE`;
- `PlayerInactivationReason`: `LEFT_OR_DISCONNECTED`, `HP_DEPLETED`, or `UNKNOWN`;
- `InactivePresentation`: `DEPARTED`, `SPECTATING`, or `UNKNOWN`.

Active leave and disconnect share the business reason `LEFT_OR_DISCONNECTED` and use
`DEPARTED`. `SPECTATING` requires `HP_DEPLETED`. HP at or below zero also requires
`HP_DEPLETED`. `DEPARTED` by itself does not prove death, so `DEPARTED + UNKNOWN` is valid when
process evidence is insufficient.

## Stage context

Every inactivation records a timezone-aware `observed_at`, stage type, optional round, optional
wave, previous/new participation status, optional HP, evidence/provenance, and confidence. Stage
type distinguishes `NORMAL` and `SECRET_CORE`. Secret core is not disguised as an ordinary fixed
round, so its `round_number` is `None`; `wave_number` remains independently available.

## Assistant-record correction

Immutable game history and correctable assistant interpretation are separate. A manual
`BattleInactivationCorrected` entry targets the currently effective inactivation fact and either:

- invalidates a false positive, causing the query to show the entrant as active again; or
- replaces mistaken time/stage/reason/presentation/HP details.

This is an audit correction, not an in-game `INACTIVE -> ACTIVE` transition. Original observations
remain in history. Stable evidence IDs make exact replay idempotent; reuse with different content,
cross-session/participant targets, stale targets, and inconsistent replacements are rejected.
The reducer constructs and validates a complete candidate state, so failure leaves the input state
unchanged.

## Future slot and manual-panel boundary

M0.2c.1 creates no runtime slot authority. M0.2c.2 subsequently adds the first two association
steps of the approved fallback chain, while strategy assignment remains deferred:

```text
runtime slot
-> user manually visits that player's perspective
-> bottom name#XXXX establishes DIRECT_PLAYER_TAG association
-> user manually opens the strategy panel
-> panel evidence binds to the associated participant
-> participant direct identification and uncontested occupancy
-> derived slot-strategy assignment
```

If the tag cannot be read, association stays unresolved or requires explicit user confirmation.
Seeing a strategy panel never creates a slot-only strategy assignment. There is no
`DIRECT_SLOT_STRATEGY_PANEL` authority, and the system never automates clicks.
