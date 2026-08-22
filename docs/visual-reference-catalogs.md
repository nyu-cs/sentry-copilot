# Visual reference catalogs

M0.4a stores only explicit, caller-declared local visual references. Its generic workflow is:

```text
canonical web reference (when lawfully obtained)
    -> private local asset
    -> explicit visual catalog entry
    -> explicit query crop/image
    -> ranked template match
    -> strategy_id or avatar_id visual identity
```

Catalogs use YAML and reference assets by safe relative path. The loader reads only the catalog
file and the exact asset paths declared in it; it never scans, discovers, downloads, or imports
directories. Real game assets and footage belong in private, untracked locations such as
`data/private/`; committed examples and tests are synthetic only.

Each `strategy` reference contains an existing stable `strategy_id`, one asset ID, an optional
`ruleset_revision_id`, and a render-context metadata value: `canonical_web`, `selection_render`,
`selection_grid_render`, `battle_render`, or `other_explicit_render_context`. The context is provenance only; it never
creates another strategy identity. It has no `initial_hp`: that value remains revision-profile data
in the existing strategy catalog. A strategy may have multiple reference assets, whose borders,
masks, brightness, transparency, and size may legitimately differ. This visual catalog does not
model per-player occupancy or resolve duplicate confirmed strategy claims; those stay with the
session/domain conflict rules.

Each `avatar` reference contains a project-owned stable `avatar_id`, asset ID, and render context.
Multiple assets may refer to one avatar, and several players may legitimately use that same avatar
in one match. An `avatar_id` is therefore never a participant identity or a participant-association
shortcut. External page titles, filenames, display names, and URLs are provenance metadata only;
they never implicitly become an `avatar_id` or `strategy_id`.

`visual-catalog-match` ranks every compatible reference asset. It returns `matched` only if the
best identity meets the configured score and is sufficiently separated from every other identity.
Results below the threshold are `unresolved`; near-tied top identities are `ambiguous`, with no
selected winner.

```powershell
.\.venv\Scripts\python.exe -m sentry_copilot.cli visual-catalog-match --kind strategy --catalog data/private/visual_catalogs/strategy.synthetic.yaml --image data/private/queries/strategy_crop.png --output data/private/live_validation/visual_matches/strategy_probe --minimum-score 0.90 --ambiguity-margin 0.02
```

Every manifest declares `schema_version`; loading derives a deterministic fingerprint from its
declared metadata. The command writes only `visual-catalog-match.json` to the caller-specified
output directory. The report preserves that schema version and fingerprint, catalog/query paths
and hashes, dimensions, thresholds, ranked reference assets, match bounds, and the typed match
status. It writes no annotated image and performs no page, slot,
tag, player, or strategy-selection recognition.

For cross-layout references whose portrait geometry differs, use the independent
`visual-local-feature-match` command documented in
[Local-feature visual matching](local-feature-visual-matching.md). It consumes this same catalog
and identity model; it does not replace or change the same-layout template matcher.