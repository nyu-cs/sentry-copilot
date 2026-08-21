from __future__ import annotations

from pathlib import Path

from sentry_copilot.catalogs.repository import load_catalog
from sentry_copilot.domain.strategy import StrategyMetadataProvenance

BOOTSTRAP_PATH = Path(
    "data/strategy_catalog_bootstrap/sentry_protocol.covenant_latter.jp/catalog.yaml"
)
REVISION = "sentry_protocol.covenant_latter.post_update"


def test_jp_bootstrap_preserves_commercial_packaging_hp_and_ink_visible_forms() -> None:
    catalog = load_catalog(BOOTSTRAP_PATH).catalog
    commercial_packaging = next(
        profile
        for profile in catalog.profiles
        if profile.strategy_id == "strategy.covenant_latter.commercial_packaging"
    )
    true_ink_resources = tuple(
        resource
        for resource in catalog.locale_resources
        if resource.strategy_id == "strategy.covenant_latter.true_ink_portrait"
        and resource.ruleset_revision_id == REVISION
    )

    assert commercial_packaging.initial_hp == 28
    assert (
        commercial_packaging.initial_hp_provenance is StrategyMetadataProvenance.EXTERNAL_REFERENCE
    )
    assert len(true_ink_resources) == 1
    assert true_ink_resources[0].name == "墨色真颜"
    assert true_ink_resources[0].visible_text_variants == frozenset({"幻画为真"})
