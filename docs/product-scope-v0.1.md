# Product scope v0.1

## Main application

Live Encounter Intelligence is a read-only desktop assistant with exactly four information items:
Difficulty, Boss, Enemy Types, and Banned Covenants. Complete supported progress is `4 / 4`.
Bans requires both Major/Core and Additional snapshots.

The application captures a supported game surface, observes it visually, confirms facts over
time, recovers missing information on returned INFO, and presents confirmed state.
The desktop shell supports English and Chinese locale modes; some game entity names retain
Chinese/localized catalog labels when no deliberate English display name exists. Its calibrated
recognition profile is Japanese MuMu 1920x1080.

Initial AC-4 Major recognition is implemented using bounded local crop refinement.
Additional recognition is implemented but may remain unresolved at extreme low-row scroll
positions. Standard / AC-1 Bans is explicitly unsupported. These are current boundaries,
not promises of universal recognition.

See [Encounter Intelligence](encounter-intelligence.md) for the detailed contract.

## Independent supporting engineering

The strategy/player subsystem provides revision-aware evidence, commitment, participation,
association, identification, occupancy, migration, and correction APIs, plus visual probes.
Those components are not an end-to-end player tracker in the live encounter UI.

The route subsystem provides ruleset/map-scoped schemas, normalized coordinates, filtering,
calibration, projection, and rendering. Its public demonstration uses synthetic data.
It is independent of encounter progress and is not part of the live panel.

Local videos, image sequences, generic OCR/template/local-feature probes, and synthetic tests
keep supporting engineering reproducible while the game mode is unavailable.
See [Architecture](architecture.md).

## Outside product scope

- Automatic clicks, perspective changes, deployment, or game input.
- Shop recognition or strategy recommendations.
- Automatic route learning from unlabelled recordings.
- General recognition across arbitrary languages, resolutions, and scaling.

No private reference pack or recording is distributed. The public `demo-encounter` command
uses project-authored synthetic facts with the production session/presentation/desktop path;
it does not exercise capture, observers, or recognition calibration. See
[the demo commands](../README.md#public-synthetic-demo), [Validation](validation.md), and
[Resources](../THIRD_PARTY_NOTICES.md).
