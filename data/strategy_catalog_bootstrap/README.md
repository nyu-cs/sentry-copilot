# Strategy catalog bootstrap data

This directory contains reviewed metadata bootstrap catalogs, not bundled game assets.

- `sentry_protocol.covenant_latter.jp/catalog.yaml` contains the 40 known stable strategy
  identities and complete post-update profile reference metadata.
- Its `jp.live.pre_ultimate_simulation` overlay lists only four live-confirmed locked strategies.
  Missing entries are unobserved rather than available.
- `private_assets/...` references are expected private-local materializations. They are safe,
  explicit paths but deliberately have no committed files.
- Real or third-party visual assets must stay in ignored `data/private/` and be addressed only by
  an explicit M0.4a visual catalog supplied by the caller.

The bootstrap is reference data, not a claim of validated JP locale, OCR, or live-game support.
