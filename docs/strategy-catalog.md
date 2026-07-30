# Revision-aware strategy catalog

## Scope

M0.2a.2 provides immutable catalog schemas, exact lookups, shared validation, synthetic fixtures,
and a minimal support registry. It does not implement strategy recognition, confirmed occupancy,
runtime assignment, current-HP matching, or revision selection/correction.

All files under `data/strategy_catalogs/demo.synthetic_covenant_latter/` are synthetic. They contain
invented strategy IDs, localized text, initial HP values, revision differences, and SVG icons.
They are suitable for public tests but are not evidence about the game.

## Ownership

- `StrategyIdentity` stores only stable `strategy_id`.
- `RulesetStrategyProfile` stores revision-specific availability, `initial_hp`,
  `icon_visual_key`, and `icon_asset_reference`.
- `LocaleStrategyResource` stores revision- and locale-specific name, description, OCR aliases,
  and visible text variants.
- `StrategyCatalog` groups these immutable records under one `catalog_version`.

The revision profile is the only icon-mapping authority. Locale resources never store icons, and
the identity layer does not assume an icon remains unchanged across revisions.

## Exact lookup

Profile lookup requires:

```text
catalog_version + ruleset_revision_id + strategy_id
```

Locale lookup requires:

```text
catalog_version + ruleset_revision_id + strategy_id + locale_id
```

Missing exact keys raise `CatalogLookupError`. The repository never borrows a description, OCR
alias, or other text from another revision or locale.

## Validation

Pydantic construction checks local shape, normalized IDs, positive initial HP, nonblank icon
values, nonblank localized text, and immutable containers. The explicit shared validator checks:

- unique ruleset, revision, strategy, profile, and locale keys;
- revision-to-ruleset and profile-to-identity references;
- ruleset revision declarations;
- one locale resource for every available profile and supported locale;
- same-revision locale/profile association;
- relative, non-escaping icon paths and resolved asset files.

`StrategyCatalogRepository.from_directory` and `tools/validate_repository.py` both use
`load_catalog`, which uses PyYAML and this same validator. There is no second repository-only
validation implementation.

## Support metadata

`SupportTarget` means the product intends to support a ruleset/revision/locale combination.
`ValidationRecord` is only an evidence record with kind, outcome, aware time, catalog version, and
evidence references. The model does not contain approval, signing, or release-certification
workflow and never infers validated support.

The four declared combinations for `卫戍协议：盟约 下半` remain `TARGET_SUPPORT` only. The
synthetic catalog has a separate synthetic ruleset ID and cannot promote any real target to
`VALIDATED_SUPPORT`.
