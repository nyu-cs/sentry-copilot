# JP Sentry strategy catalog bootstrap

This bootstrap records the known strategy identities for `堅守協定：盟約 後期` without
claiming that the current Japanese live phase is the complete CN 2026-03-27 post-update state.
It reuses the existing normalized IDs:

```text
sentry_protocol.covenant_latter
sentry_protocol.covenant_latter.post_update
```

The public metadata catalog contains 40 stable strategy IDs, profile-owned `initial_hp`, Chinese
reference names, and an initiator display label. An initiator label or portrait is display/
provenance metadata, not a strategy ID. The bootstrap has no strategy-effect language beyond a
clear placeholder description, and it has no player occupancy semantics.

## Provenance and JP phase overlay

`initial_hp_provenance` distinguishes `external_reference`, `official_notice`, and
`live_confirmed`. Only `文火慢炖`'s current value of 27 is marked `live_confirmed` here. The
other PRTS-derived records are not thereby individual live confirmations.

The complete post-update revision contains all 40 globally available strategies. Current JP is
not identical to that complete CN state: it already shows some post-update operator-pool and balance
changes (including Archetto present, Earthspirit absent, and `文火慢炖` at 27), while the four
strategies below remain phase-locked. The independent `jp.live.pre_ultimate_simulation` overlay
records only those current live-confirmed JP locks:

- `strategy.covenant_latter.guardian_power` — 铃兰 / 御守之力 / 20
- `strategy.covenant_latter.assembly_directive` — 杰西卡 / 集结指示 / 22
- `strategy.covenant_latter.pure_condensation` — 缪尔赛思 / 至纯凝结 / 28
- `strategy.covenant_latter.cooperative_advancement` — 芬 / 协力共进 / 24

An absent phase record means *unobserved*, not available. It is global phase availability only,
not a per-player unlock condition. The transient UI countdown is deliberately not ruleset data. A
later JP transition requires a separately observed phase; it is never inferred from a date or from
Ultimate Simulation opening.

Japanese names, descriptions, and OCR aliases are still target support rather than complete
catalog resources: they must come from JP official material or live client evidence, never an
invented translation. The bootstrap therefore declares only its sourced `zh_CN` resources, while
the support registry separately retains `ja_JP` as a target.

## Private strategy visual references

The profile `private_assets/...` references declare expected private-local canonical
materialization; they do not ship files. Real initiator portraits, screen crops, and third-party
images stay under ignored `data/private/` and are never scanned. Create a caller-owned M0.4a
visual catalog using exact asset paths, for example:

```yaml
schema_version: 1
kind: strategy
assets:
  - asset_id: asset.private.canonical.focused-care
    asset_reference: canonical/focused-care.png
    sha256: <exact-sha256>
    provenance: official-or-private-reference
strategy_references:
  - strategy_id: strategy.covenant_latter.focused_care
    asset_id: asset.private.canonical.focused-care
    ruleset_revision_id: sentry_protocol.covenant_latter.post_update
    reference_kind: canonical_web
avatar_references: []
```

Pass the explicit bootstrap catalog path when matching so every strategy reference is checked
against the known identity/profile set. No directory discovery, download, PRTS crawling, or image
asset processing is performed automatically:

```powershell
.\.venv\Scripts\python.exe -m sentry_copilot.cli visual-catalog-match --kind strategy --strategy-catalog data/strategy_catalog_bootstrap/sentry_protocol.covenant_latter.jp/catalog.yaml --catalog data/private/visual_catalogs/jp-strategy-references.yaml --image data/private/queries/one-strategy.png --output data/private/live_validation/visual_matches/one-strategy
```

Multiple visual references may map to one strategy ID across canonical, selection, and battle
render contexts. A match is evidence only: below-threshold results remain unresolved and near ties
remain ambiguous. It never resolves cross-player occupancy conflicts.

## Reference baseline

The 36 pre-marker and four post-marker entries were transcribed from the
[PRTS strategy table](https://prts.wiki/w/%E5%8D%AB%E6%88%8D%E5%8D%8F%E8%AE%AE%EF%BC%9A%E7%9B%9F%E7%BA%A6_%E4%B8%8B%E5%8D%8A).
PRTS is bootstrap/reference data, not blanket JP live validation.
