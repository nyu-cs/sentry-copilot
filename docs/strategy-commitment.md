# Prebattle evidence and ready-confirmed commitment

## Scope

M0.2b.1 records typed prebattle candidate and ready-check evidence, then derives whether each known
session participant has a currently valid ready-confirmed commitment. M0.2b.2 adds minimal battle
entry and concrete-confirmation evidence plus a separate identification layer. Commitment itself
still does not assign a normalized strategy or bind a runtime slot.

## Identity and ownership

`SessionId`, `SessionParticipantId`, and `EvidenceId` are normalized, strict string types.
Every prebattle event carries all three identities. The reducer accepts an event only when:

- its session matches `SessionState.session_id`;
- a strategy-selection snapshot exists for that session;
- its participant already belongs to that snapshot.

This prevents a participant reference from crossing session boundaries. Selection row remains
independent from future runtime slot identity.

## Raw evidence

`StrategyCandidateObserved`, `ReadyCheckObserved`, `BattleEntryConfirmed`,
`BattleEntryNotConfirmed`, and `StrategySelectionConfirmedEvidence` are immutable, typed ledger
entries. They
retain raw references such as:

- replay frame or screenshot reference;
- normalized game-content ROI;
- observed visual cue;
- observed text;
- confidence;
- timezone-aware timestamp;
- provenance and optional source detail.

At least one raw reference or cue is required. Candidate evidence has no `strategy_id`; adding a
catalog-normalized ID here would incorrectly present a revision-dependent interpretation as a raw
fact.

Every entry has a caller-supplied stable evidence ID. Exact replay of the same ID and content is a
no-op. Reuse of an ID for different content is rejected. Separate IDs with identical content are
preserved because they may represent independent frames. This makes replay and future legacy
migration idempotent without content-based deduplication.

The later legacy adapter must derive stable evidence IDs from the source snapshot identity and
field identity. Reprocessing that same snapshot will therefore hit the exact-ID no-op path rather
than append duplicate evidence or create another commitment.

## Ready commitment

A positive ready-check observation means that the assistant observed the per-player formal
selection signal. The first currently effective ready observation determines `confirmed_at`.
Later ready observations add evidence IDs but:

- do not create a second commitment;
- do not move `confirmed_at`;
- do not imply another strategy selection.

The commitment read state contains no concrete strategy identity, so it remains
`READY_CONFIRMED_STRATEGY_UNKNOWN`. A participant without any effective formal-selection evidence
is `OBSERVING`.

Reliable observation of normal active battle participation is also proof that the player had
formally selected some strategy. Its first effective time may establish a commitment; later ready
or entry evidence only strengthens that same commitment. A participant merely appearing in the
battle UI is insufficient. If the first stable frame is already inactive and normal participation
was never observed, `BATTLE_ENTRY_NOT_CONFIRMED` records the conservative result and creates no
commitment. Existing ready evidence is never removed by that result.

Direct panel observation or explicit manual confirmation can atomically establish/strengthen the
commitment and add a separate concrete identification. Battle-entry evidence can never be used as
catalog-derived strategy evidence.

There is no normal game transition to unready or released. Later selection-stage exit, battle
entry, runtime departure, disconnect, elimination, or HP depletion cannot release a real
ready-confirmed selection.

## False-positive correction

Immutable observed history and the assistant's current interpretation are separate.
`ReadyFalsePositiveCorrected` is a manual, stable-ID ledger entry targeting one or more ready
evidence IDs for the same participant.

The reducer:

1. verifies every target exists and is ready-check evidence for that participant;
2. appends the correction without deleting the original observations;
3. excludes targeted evidence from the effective ready set;
4. rebuilds the current commitment materialization;
5. validates the entire candidate `SessionState` before returning it.

If another effective ready observation remains, the commitment remains. Independent reliable
battle-entry or concrete-selection confirmation also keeps the commitment valid. Only when no
effective confirmation evidence remains is the assistant materialization removed. This corrects a
false interpretation; it does not claim that the player cancelled ready in the game. Any failure
leaves the original state unchanged.

## Immutability and queries

The ledger, entries, ROI, commitment aggregate, and commitment records are frozen. Collections use
tuples or frozensets. `SessionState` validates that the materialized commitments exactly equal the
currently effective ready, reliable normal-entry, and concrete-selection confirmation evidence.

Read-only APIs:

- `get_prebattle_evidence_ledger`;
- `get_ready_confirmed_commitment`;
- `build_prebattle_commitment_context`.

The context is ordered by selection row only for stable display. It does not infer runtime slots
and contains no concrete strategy ID.

## Legacy snapshot compatibility

M0.2b.3 explicitly imports legacy `ready=true` as
`LegacyReadySnapshotImported`. It retains the source field evidence and observation time while
marking migration provenance, and it uses deterministic IDs so replay cannot create a second
commitment. Legacy `ready=false` or unknown values create no negative evidence and never withdraw
an existing commitment. Imported ready evidence participates in the same false-positive
correction mechanism; repeating migration does not reactivate an excluded evidence ID.

Snapshot `frozen` does not close the commitment or evidence histories. A migration after freeze can
establish or strengthen a commitment, but an existing earlier `confirmed_at` remains unchanged.

## Deferred

OCR, vision, capture, UI, runtime roster, slot association, assignment, and automatic clicking are
outside this milestone.
