# Runtime slots and participant association

## Scope

M0.2c.2 separates three domain layers:

1. `RuntimeSlotObservation`: immutable direct screen evidence;
2. `BattleRuntimeSlot`: current query projection of a visual slot in one layout epoch;
3. `SlotParticipantAssociationRecord`: an auditable strong participant claim.

This milestone does not implement strategy assignment, strategy-panel identification, avatar/HP
matching, a global solver, OCR, image processing, capture, UI, annotation, or automatic clicks.

## Raw observation and correction

Each observation has a stable `EvidenceId`, session/layout/slot IDs, timezone-aware time, visual
index, normalized content-viewport ROI, visibility and presentation facts, optional displayed name
and four-digit tag, optional self marker, provenance, confidence, and source reference. It contains
no participant ID, strategy ID, selection row, avatar identity, or HP identity.

Equal evidence-ID replay is a no-op; reuse with different content is rejected. A manual
`RuntimeSlotObservationCorrected` invalidates mistaken observations without deleting them. Current
slot and association views are re-derived. This is assistant-record correction, not an in-game
slot removal or player-move event.

## Layout epoch and current slots

`RuntimeSlotId` is stable only within its `RuntimeSlotLayoutId`. `visual_index` is a transient
screen position, not identity. Reliable small ROI/index movement can add another observation for
the same slot ID. When reorder continuity is uncertain, the producer must start a new layout and
new slot IDs. Historical layouts remain auditable but never conflict with or donate associations
to the current layout.

The current layout is derived conservatively from effective observation time. A tie between two
latest layouts yields no current layout rather than an arbitrary winner. `BattleRuntimeSlot`
returns first/last seen times, current index/ROI/presentation, observation IDs, and whether an
uncontested association exists. It is not persisted as a second mirror.

## Association authority

An association record targets only a participant currently present in query-derived
`BattleRoster`; ready, strategy occupancy, legacy selection outcome, snapshot presence, and a
departed placeholder are insufficient. A confirmed entrant remains eligible after later runtime
inactivation, so association history is not released.

Supported bases are:

- `DIRECT_PLAYER_TAG`: effective observed evidence contains the participant's exact four-digit
  session tag. Display name is auxiliary and cannot override the tag.
- `DIRECT_SELF_MARKER`: effective observed evidence contains a self marker and the participant is
  the unique snapshot self participant. Slot/selection order is not used.
- `MANUAL_CONFIRMATION`: an explicit user decision with audit reason and slot observation evidence.

There is no display-name-only, avatar, HP, selection-row, confidence-ranking, or slot-only strategy
panel basis.

## One-to-one conflicts

The effective current-layout relation is one-to-one:

```text
runtime slot -> zero or one participant
participant -> zero or one runtime slot
```

Contradictory claims remain legal history but produce either
`SLOT_MULTIPLE_PARTICIPANT_CLAIMS` or `PARTICIPANT_MULTIPLE_SLOT_CLAIMS`. Every record/evidence item
remains visible for audit; conflicting pairs produce no effective association, assignment, or
automatic winner.

Manual correction appends replacement records with explicit supersession plus one stable
`SlotAssociationCorrectionId`. Exact replay is idempotent. A batch is built and whole-state
validated once; any bad participant, evidence, target, layout, or ID collision leaves the input
state unchanged. Correction fixes assistant interpretation and never claims that a player moved
within the old layout.

## Queries and independence

Read-only APIs are:

- `build_current_runtime_slots`;
- `get_runtime_slot`;
- `get_effective_slot_participant_association`;
- `get_uncontested_slot_participant_associations`;
- `get_slot_association_conflicts`;
- `get_unresolved_runtime_slots`.

Unresolved slots are data only; no task, prompt, annotation, or coverage state is created.
Observation/association history has no ruleset dependency stamp and survives revision correction.
It never reads legacy strategy fields, legacy slot position, selection row, avatar, current HP, or
initial HP.

M0.6b1a separately introduces a pure deterministic association core for future normalized
selection-profile-avatar and pre-loss initial-HP evidence. It does not change these M0.2c.2
auditable direct bases, persist a new association record, or bypass their authority chain; see
[`runtime-association-core.md`](runtime-association-core.md).

## Derived slot-strategy assignment

M0.2c.3 derives a query-only `SlotStrategyAssignmentView` only through:

```text
current runtime slot
-> uncontested participant association
-> confirmed entrant
-> effective participant strategy identification
-> uncontested occupancy
-> slot-strategy assignment
```

The manual panel flow first reads bottom `name#XXXX` to establish participant association. If the
tag cannot be read, association stays unresolved or the user confirms it. Panel evidence must bind
the associated participant through existing direct-observation identification. There is no
`DIRECT_SLOT_STRATEGY_PANEL` authority.

`SlotStrategyAssignmentService` supplies the current assignment, all assignments, and unresolved
slots. It composes the current runtime layout, association view, confirmed-entry roster, and exact
revision-aware occupancy view at read time. No assignment cache is stored in `SessionState`.

An unresolved slot carries one explicit first unmet link: missing or conflicted association,
non-entrant participant, missing or stale identification, participant identification conflict,
duplicate confirmed strategy claim, catalog compatibility conflict, or absent uncontested
occupancy. The implementation never uses selection row, legacy snapshot strategy, legacy runtime
strategy cache, display name alone, avatar, current HP, initial HP, or candidate confidence to
fill that gap.

When a reliably assigned entrant later becomes `INACTIVE`, the assignment remains historical and
reports `participation_status=inactive`; no occupancy is released. An inactive entrant with no
effective concrete strategy remains unresolved. Ruleset revision correction leaves slot evidence
and associations intact, but assignment is re-derived: stale catalog-derived records cannot label
a slot, while compatible direct/manual records remain eligible.
