# Concrete strategy identification and effective occupancy

## Scope

M0.2b.2 links a ready-confirmed commitment to a normalized strategy only when concrete evidence
exists. It stores immutable identification claims and derives the current uncontested occupancy.
M0.2b.2 itself does not create a battle roster, runtime slot, participant association, assignment,
annotation, coverage state, OCR recognizer, capture loop, or UI. M0.2c.1 later derives a roster
from the same entry facts without changing identification or occupancy.

## Identification records

Each `StrategyIdentificationRecord` has a stable record ID, normalized session participant and
strategy IDs, timezone-aware identification time, evidence IDs, basis, optional dependency stamp,
and optional explicit supersession links.

- `CATALOG_DERIVED` requires a full current `RulesetDependencyStamp` and at least one raw
  `StrategyCandidateObserved` evidence item. Ready or battle-entry evidence alone cannot identify a
  concrete strategy.
- `DIRECT_OBSERVATION` requires matching direct concrete-confirmation evidence and carries no
  dependency stamp.
- `MANUAL_CONFIRMATION` requires matching manual evidence and an audit reason, and carries no
  dependency stamp.
- `LEGACY_SNAPSHOT_INTERPRETATION` requires a full dependency stamp and matching typed legacy
  strategy evidence. It preserves an old normalized interpretation for audit but is never eligible
  for current identification or occupancy by itself.

Direct and manual records do not become stale merely because context generation changes. Their
strategy is nevertheless checked against the current revision catalog every time the read model is
derived. Catalog-derived records are fresh only when their entire stamp equals the current stamp.
Returning early → late → early therefore does not revive an old derived record because the
generation differs.

Legacy interpretation records follow the same dependency freshness test as catalog-derived
records. A fresh compatible legacy record is still exposed only in `legacy_record_ids`; a stale
one moves to `stale_record_ids`. A direct/manual correction must explicitly supersede it. Because
the original record and supersession remain append-only, rerunning migration cannot restore the
old interpretation as current.

## Commitment and battle entry

No identification becomes effective occupancy without a current ready-confirmed commitment.
Direct or manual concrete evidence may atomically establish that commitment and the identification.
Battle-entry reconciliation is more limited:

- reliable observation of normal active participation produces `BATTLE_ENTRY_CONFIRMED` and proves
  only that some strategy was formally selected;
- a participant displayed in the battle UI is not automatically an entrant;
- a first stable frame that already shows the participant inactive produces
  `BATTLE_ENTRY_NOT_CONFIRMED` and creates no commitment or concrete strategy;
- prior ready commitment and known strategy remain historical facts if the participant later
  departs;
- a manual false-positive entry correction preserves the original evidence and re-derives both
  commitment and the later roster from remaining effective entry evidence;
- no follow-up task or strategy annotation is created here.

The derived `BattleRoster` includes only effective confirmed entrants. It excludes participants
whose first reliable battle frame already showed departure and for whom normal active
participation was never observed. Runtime inactivation never releases commitment, identification,
or occupancy.

## Supersession and conflicts

Correction appends a manual record with explicit `supersedes_record_ids`. Superseded records and
all source evidence remain in history. This corrects the assistant interpretation; it is not a game
transition in which the player changes or releases a strategy. Multi-record correction is applied
to a candidate state and whole-state validation is atomic.

The derived read model distinguishes:

- `DUPLICATE_CONFIRMED_STRATEGY_CLAIM`: different participants claim the same strategy;
- `PARTICIPANT_STRATEGY_IDENTIFICATION_CONFLICT`: one participant has incompatible unsuperseded
  strong claims;
- `STRATEGY_CATALOG_COMPATIBILITY_CONFLICT`: a direct/manual claim is unavailable in the current
  revision catalog.

The first case is never a valid duplicate occupancy. It proves at least one assistant
identification, association, or manual record is wrong. Neither side wins automatically, both
claims and evidence remain, and the contested strategy produces no occupancy until explicit
correction resolves the conflict.

## Query-derived authority

`StrategyIdentificationState` stores claim history, not occupancy. Queries derive current state
from effective commitments, unsuperseded records, dependency freshness, catalog compatibility, and
conflicts. Public service queries are:

- `get_participant_strategy_identification`;
- `get_uncontested_strategy_occupancies`;
- `get_strategy_identification_conflicts`;
- `get_duplicate_confirmed_strategy_claims`;
- `get_strategy_occupancy_view`.

Zero eligible claims yields zero occupancies. One fresh compatible unconflicted strategy for one
committed participant yields one occupancy. Conflicting claims yield explicit conflict records and
no occupancy for the affected strategy. No latest-write-wins or silent revision switch is used.

Legacy `build_team_strategy_context` remains a separate snapshot projection and is intentionally
not used by any of these authority queries.
