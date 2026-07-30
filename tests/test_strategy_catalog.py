from pathlib import Path

import pytest

from sentry_copilot.catalogs.repository import (
    CatalogLookupError,
    StrategyCatalogRepository,
)
from sentry_copilot.domain.identifiers import LocaleId

CATALOG_ROOT = Path("data/strategy_catalogs")
CATALOG_VERSION = "catalog.synthetic.v1"
EARLY_REVISION = "demo.synthetic_covenant_latter.pre_update"
LATE_REVISION = "demo.synthetic_covenant_latter.post_update"
GUARD_STRATEGY = "strategy.synthetic.guard"
SUPPORT_STRATEGY = "strategy.synthetic.support"


@pytest.fixture
def repository() -> StrategyCatalogRepository:
    return StrategyCatalogRepository.from_directory(CATALOG_ROOT)


def test_repository_loads_only_the_synthetic_catalog(
    repository: StrategyCatalogRepository,
) -> None:
    assert repository.list_catalog_versions() == (CATALOG_VERSION,)
    assert repository.catalog(CATALOG_VERSION).is_synthetic is True


def test_available_strategies_are_revision_aware(
    repository: StrategyCatalogRepository,
) -> None:
    assert repository.available_strategy_ids(
        catalog_version=CATALOG_VERSION,
        ruleset_revision_id=EARLY_REVISION,
    ) == frozenset(
        {
            "strategy.synthetic.guard",
            "strategy.synthetic.growth",
        }
    )
    assert repository.available_strategy_ids(
        catalog_version=CATALOG_VERSION,
        ruleset_revision_id=LATE_REVISION,
    ) == frozenset(
        {
            "strategy.synthetic.guard",
            "strategy.synthetic.growth",
            SUPPORT_STRATEGY,
        }
    )


def test_profile_lookup_returns_revision_specific_values(
    repository: StrategyCatalogRepository,
) -> None:
    early = repository.get_profile(
        catalog_version=CATALOG_VERSION,
        ruleset_revision_id=EARLY_REVISION,
        strategy_id=GUARD_STRATEGY,
    )
    late = repository.get_profile(
        catalog_version=CATALOG_VERSION,
        ruleset_revision_id=LATE_REVISION,
        strategy_id=GUARD_STRATEGY,
    )
    assert early.initial_hp == 101
    assert late.initial_hp == 111
    assert early.icon_visual_key != late.icon_visual_key
    assert early.icon_asset_reference != late.icon_asset_reference


def test_locale_lookup_requires_the_exact_revision_strategy_and_locale(
    repository: StrategyCatalogRepository,
) -> None:
    early_zh = repository.get_locale_resource(
        catalog_version=CATALOG_VERSION,
        ruleset_revision_id=EARLY_REVISION,
        strategy_id=GUARD_STRATEGY,
        locale_id=LocaleId.ZH_CN,
    )
    late_zh = repository.get_locale_resource(
        catalog_version=CATALOG_VERSION,
        ruleset_revision_id=LATE_REVISION,
        strategy_id=GUARD_STRATEGY,
        locale_id=LocaleId.ZH_CN,
    )
    late_ja = repository.get_locale_resource(
        catalog_version=CATALOG_VERSION,
        ruleset_revision_id=LATE_REVISION,
        strategy_id=GUARD_STRATEGY,
        locale_id=LocaleId.JA_JP,
    )
    assert early_zh.description != late_zh.description
    assert late_zh.name != late_ja.name


def test_locale_lookup_never_falls_back_across_revision_or_locale(
    repository: StrategyCatalogRepository,
) -> None:
    with pytest.raises(CatalogLookupError, match="exact"):
        repository.get_locale_resource(
            catalog_version=CATALOG_VERSION,
            ruleset_revision_id=EARLY_REVISION,
            strategy_id=SUPPORT_STRATEGY,
            locale_id=LocaleId.ZH_CN,
        )
    with pytest.raises(CatalogLookupError, match="exact"):
        repository.get_locale_resource(
            catalog_version=CATALOG_VERSION,
            ruleset_revision_id="demo.synthetic_covenant_latter.unknown",
            strategy_id=GUARD_STRATEGY,
            locale_id=LocaleId.ZH_CN,
        )


def test_unknown_catalog_version_is_rejected(
    repository: StrategyCatalogRepository,
) -> None:
    with pytest.raises(CatalogLookupError, match="catalog_version"):
        repository.catalog("catalog.synthetic.unknown")
