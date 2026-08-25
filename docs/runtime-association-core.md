# Deterministic runtime association core

M0.6b1a adds a pure, query-style production contract for associating already-normalized
selection facts with already-normalized runtime-slot evidence. It does not inspect frames, use
OpenCV, mutate `SessionState`, or add a new durable association authority.

The core accepts session-local participant IDs, selection outcome, confirmed strategy ID, optional
expected initial HP, runtime participation state, optional self marker, accepted avatar-compatible
participant candidates, and explicit manual or previous confirmed mappings. A selection profile
avatar and a strategy initiator portrait are distinct evidence types.

All `ENTERED_BATTLE` participants participate in the active automatic problem, even when their
strategy is not yet known. A uniquely resolved participant association may therefore be
`confirmed` with a null strategy ID; later fallback inspection can identify that strategy without
re-associating the slot. Selection-stage exits with `strategy_not_observed` are excluded; multiple
exited unknowns need not be reconstructed one-to-one among exited runtime cards.

For at most four active slots, the core exhaustively enumerates valid one-to-one assignments. It
uses accepted avatar candidates, a unique self marker, and HP only when the runtime observation is
explicitly pre-loss and the candidate has an expected initial HP. Initial HP filters candidates;
it is never a strategy identity. Reduced current HP is ignored for initial-HP matching.

If one valid assignment remains, the result is `confirmed`. If multiple remain, it is
`unresolved` with remaining candidates and the smallest practical manual-confirmation target. If
no valid candidate remains, it stays unresolved; no confidence or ordering tie-break exists.
Manual confirmation is a hard constraint and can make the remaining assignment unique, including
for a participant whose strategy remains unknown. Trusted manual claims and previous confirmed
claims are one-to-one inputs: malformed data that maps one participant to two slots is rejected.

Previous confirmed mappings are sticky. A later `active -> exited` or
`active -> spectating_or_dead` observation retains its participant and strategy; only runtime
state changes. Contradictory later evidence surfaces a conflict and never silently remaps the
slot.

This is deliberately separate from the M0.2c.2 auditable direct association bases. Vision
integration, evidence persistence, and any reducer/event integration remain future work.

M0.6b1b2 adds a frame-only preparation-checkpoint adapter.  It may project a runtime self marker
only after exactly one marker is observed, and may project HP only from a historical,
round-one-preparation baseline.  A later current HP remains runtime-state evidence and is never
used as an initial-HP identity filter.  See [runtime preparation checkpoints](runtime-preparation-checkpoints.md).
