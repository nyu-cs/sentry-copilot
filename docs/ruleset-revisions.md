# Session ruleset and revision context

## Current target

The confirmed Chinese name of the current target ruleset is:

```text
卫戍协议：盟约 下半
```

The name's `下半` is part of the complete gameplay-version name. It is separate from the two
catalog revisions that the first version targets:

- pre-update / early revision;
- post-update / late revision.

The normalized ID candidates used by the M0.2a design are:

```text
ruleset_id:
sentry_protocol.covenant_latter

ruleset_revision_id:
sentry_protocol.covenant_latter.pre_update
sentry_protocol.covenant_latter.post_update
```

IDs are stable, language-independent, lowercase strings. They do not use a localized display name,
release date, or inferred official sequence number. The Japanese display name must eventually come
from official JP announcements, game captures, or verified locale resources rather than developer
translation.

## Authority and compatibility

`SessionRulesetContext` is the only authority for new ruleset-, revision-, locale-, and
catalog-aware code. It stores:

- normalized ruleset ID;
- optional normalized revision ID;
- locale ID;
- optional catalog version;
- selection method and time;
- field evidence;
- replaced revision selections;
- a monotonic context generation.

M0.1a `SessionState.ruleset_id` and `SessionState.locale` remain compatibility mirrors:

- when a context is supplied and mirrors are omitted, model construction fills them from context;
- when a context and explicit mirrors are both supplied, mismatches are rejected;
- when no context is supplied, legacy M0.1a construction remains valid.

`StrategySelectionSnapshot.ruleset_id` also remains for compatibility. It must match the effective
session ruleset, but it does not become a second authority and does not store a revision ID.

## Unknown revision

A session may know its ruleset and locale while revision remains unknown:

```text
ruleset_revision_id = None
catalog_version = None
selection_method = unknown
context_generation = 0
```

An unknown revision cannot support revision-dependent catalog lookup, initial-HP interpretation,
availability exclusion, or derived confirmation. Those behaviors are deferred beyond M0.2a.1.

## Context generation

A new session starts at generation zero. Every future successful context selection or explicit
correction increments the generation, including unknown-to-concrete selection. Failed operations
do not increment it. The domain does not impose a fixed correction-count limit.

Future revision-dependent derived data must carry:

```text
ruleset_id
ruleset_revision_id
locale_id
catalog_version
context_generation
```

Including locale prevents localized names, descriptions, or OCR resources from surviving an
incompatible locale change. Including generation prevents a stale result from becoming current
again after a sequence such as early → late → early.

M0.2a.1 defines this dependency identity but does not create assignment, annotation, occupancy, or
other future caches.

## Explicit selection and correction

M0.2a.3 supports two initial sources only:

- explicit manual selection;
- explicit replay metadata.

It does not infer revision from locale, file timestamps, upload dates, system time, or screen
content. If no context exists, initial selection creates generation one with empty history. If a
generation-zero unknown context exists, initial selection preserves it as the first history
record. Once concrete, further changes require explicit correction.

Correction keeps ruleset and locale fixed. It may change revision, or explicitly select a new
validated catalog version for the same revision. Every successful correction appends the complete
old selection—including method, selection/replacement times, evidence, reason, and generation—and
increments generation. There is no correction-count limit. Exact duplicates and mismatches are
typed rejections and do not change state.

The command service validates the target against `StrategyCatalogRepository`; the generic reducer
receives only accepted facts. Failure never partially updates mirrors, history, prebattle snapshot,
or evidence. The current dependency stamp is the complete invalidation contract until future
revision-dependent objects exist.

## Catalog lookup

M0.2a.2 resolves strategy profiles with:

```text
catalog_version + ruleset_revision_id + strategy_id
```

It resolves localized text with:

```text
catalog_version + ruleset_revision_id + strategy_id + locale_id
```

There is no implicit fallback between pre-update and post-update revisions or between `zh_CN` and
`ja_JP`. Revision profiles, not stable strategy identities or locale resources, own icon keys and
asset references. Current public fixtures are synthetic and do not establish validated support for
the four real target combinations.

## Legacy strategy interpretation

`StrategySelectionParticipant.strategy_id` predates revision-aware catalogs. A stored value may be
a normalized interpretation produced under an older catalog rather than a revision-independent raw
visual fact.

M0.2a therefore:

- preserves the value and all field evidence;
- does not delete historical observations;
- does not use the field to create new occupancy, runtime assignment, or catalog-dependent
  confirmation;
- defers separation of raw visual observations from normalized strategy interpretation to M0.2b.
