# Ruleset context selection and correction

## Boundary

M0.2a.3 adds explicit session-context operations without adding UI or automatic revision
detection. Command models contain caller intent. `RulesetContextService` checks the current
session and exact validated catalog target. Only then does it create an accepted domain event for
the generic reducer.

The reducer has no catalog repository, YAML loader, file-system access, or fallback logic. It
rebuilds and validates a complete candidate `SessionState`; the original state is unchanged on
any failure.

## Initial selection

`SelectSessionRulesetContext` supports:

- `manual`;
- `imported_from_replay_metadata`.

With no context, it creates generation one and no history. With an unknown generation-zero
context, it records that unknown selection in history before creating generation one. A concrete
current revision rejects initial selection and requires explicit correction.

## Correction

`CorrectSessionRulesetRevision` is always explicit and manual. Ruleset and locale remain fixed.
The operation may:

- select another revision in the same ruleset;
- select a different validated catalog version for the same revision.

The old current selection becomes one immutable history record. The new current context increments
generation. Repeating early → late → early produces distinct dependency stamps because generation
never returns to an earlier value. There is no fixed correction-count limit.

An exactly identical target is a typed rejection. It does not create an event, history entry, or
new generation.

## Mismatch and atomic failure

Typed errors distinguish missing context, unknown revision, ruleset/revision/locale mismatch,
catalog mismatch, unknown catalog version, identical context, invalid revision ownership, invalid
time order, and session mismatch.

Mismatch validation never chooses another revision or catalog. Failure leaves legacy mirrors,
history, field evidence, and `StrategySelectionSnapshot` unchanged.

## Dependency query

The read-only queries are:

```text
get_session_ruleset_context(state)
get_current_ruleset_dependency_stamp(state)
```

The dependency stamp contains ruleset, revision, locale, catalog version, and generation. Future
revision-dependent objects are current only when their stored stamp exactly matches this query.
M0.2a.3 creates no placeholder occupancy, assignment, annotation, coverage, candidate cache, or
invalidation ledger.
