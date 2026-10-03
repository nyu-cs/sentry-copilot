# Documentation

Start with [the project overview](../README.md), then
[Architecture](architecture.md), [Encounter Intelligence](encounter-intelligence.md), and
[Validation boundaries](validation.md). [Product scope](product-scope-v0.1.md) distinguishes the
live application from independent supporting engineering.

These are maintained technical references, not a feature roadmap or task queue. Milestone
identifiers in detailed component documents record implementation provenance; they do not
mean every component is integrated into the live UI.

## Live encounter product

- [Encounter Intelligence](encounter-intelligence.md): four facts, recognition gates, lifecycle,
  recovery, Ban presentation, local resources, and diagnostics.
- [Architecture](architecture.md): separate encounter, strategy/player, and route paths.
- [Validation boundaries](validation.md): public reproducibility versus private calibration.

## Strategy/player evidence and catalogs

- [Domain invariants](domain-invariants.md) and [Data contracts](data-contracts.md)
- [Strategy selection](strategy-selection.md)
- [Ready commitment](strategy-commitment.md) and [Legacy migration](prebattle-migration.md)
- [Concrete identification and occupancy](strategy-identification.md)
- [Battle roster](battle-roster.md) and [Runtime slots](runtime-slots.md)
- [Ruleset revisions](ruleset-revisions.md) and [Explicit context operations](ruleset-context-operations.md)
- [Strategy catalog](strategy-catalog.md) and [JP catalog bootstrap](jp-strategy-catalog-bootstrap.md)
- [User-guided inspection boundary](player-inspection.md)

## Supporting visual and association components

- [Runtime association core](runtime-association-core.md)
- [Runtime player-card states](runtime-player-card-states.md)
- [Runtime preparation checkpoints](runtime-preparation-checkpoints.md)
- [Runtime profile-avatar evidence](runtime-profile-avatar-evidence.md)
- [Visual reference catalogs](visual-reference-catalogs.md)
- [Local-feature matching](local-feature-visual-matching.md) and [Template matching](template-matching.md)

## Capture, offline tools, and routes

- [Frame sources](frame-sources.md) and [Windows display capture](windows-display-capture.md)
- [Content viewport](content-viewport.md) and [Offline validation runner](offline-validation-runner.md)
- [OCR foundation](ocr-foundation.md), [Live OCR probe](live-ocr-probe.md),
  and [Recognition probe](recognition-probe.md)
- [Video frame extraction](video-frame-extraction.md)
- [Independent route system](route-system.md)

For contribution checks and resource policy, see [Contributing](../CONTRIBUTING.md) and
[Third-party notices](../THIRD_PARTY_NOTICES.md).
