from pathlib import Path

import pytest

from sentry_copilot.catalogs.repository import load_catalog
from sentry_copilot.catalogs.validation import (
    CatalogValidationError,
    validate_catalog,
)

CATALOG_PATH = Path(
    "data/strategy_catalogs/demo.synthetic_covenant_latter/catalog.yaml"
)


def load_synthetic_catalog():
    return load_catalog(CATALOG_PATH).catalog


def test_catalog_validator_rejects_duplicate_revision_profiles() -> None:
    catalog = load_synthetic_catalog()
    duplicate = catalog.model_copy(
        update={"profiles": catalog.profiles + (catalog.profiles[0],)}
    )
    with pytest.raises(CatalogValidationError, match="duplicate strategy profile"):
        validate_catalog(duplicate, asset_root=CATALOG_PATH.parent)


def test_catalog_validator_rejects_unknown_strategy_identity() -> None:
    catalog = load_synthetic_catalog()
    invalid_profile = catalog.profiles[0].model_copy(
        update={"strategy_id": "strategy.synthetic.missing"}
    )
    invalid = catalog.model_copy(
        update={"profiles": (invalid_profile,) + catalog.profiles[1:]}
    )
    with pytest.raises(CatalogValidationError, match="unknown strategy identity"):
        validate_catalog(invalid, asset_root=CATALOG_PATH.parent)


def test_catalog_validator_requires_locale_resource_for_each_supported_locale() -> None:
    catalog = load_synthetic_catalog()
    missing_resource = catalog.model_copy(
        update={"locale_resources": catalog.locale_resources[1:]}
    )
    with pytest.raises(CatalogValidationError, match="missing locale resource"):
        validate_catalog(missing_resource, asset_root=CATALOG_PATH.parent)


def test_catalog_validator_rejects_cross_revision_locale_resource() -> None:
    catalog = load_synthetic_catalog()
    early_resource = catalog.locale_resources[0]
    invalid_resource = early_resource.model_copy(
        update={"strategy_id": "strategy.synthetic.support"}
    )
    invalid = catalog.model_copy(
        update={"locale_resources": (invalid_resource,) + catalog.locale_resources[1:]}
    )
    with pytest.raises(
        CatalogValidationError,
        match="without a profile in the same revision",
    ):
        validate_catalog(invalid, asset_root=CATALOG_PATH.parent)


def test_catalog_validator_rejects_locale_not_declared_by_ruleset() -> None:
    catalog = load_synthetic_catalog()
    zh_only_ruleset = catalog.rulesets[0].model_copy(
        update={"supported_locales": frozenset({"zh_CN"})}
    )
    invalid = catalog.model_copy(update={"rulesets": (zh_only_ruleset,)})
    with pytest.raises(CatalogValidationError, match="locale not declared"):
        validate_catalog(invalid, asset_root=CATALOG_PATH.parent)


@pytest.mark.parametrize(
    "reference",
    [
        "C:/private/synthetic.svg",
        "../private/synthetic.svg",
        r"icons\pre_update\guard.svg",
    ],
)
def test_catalog_validator_rejects_unsafe_asset_references(reference: str) -> None:
    catalog = load_synthetic_catalog()
    invalid_profile = catalog.profiles[0].model_copy(
        update={"icon_asset_reference": reference}
    )
    invalid = catalog.model_copy(
        update={"profiles": (invalid_profile,) + catalog.profiles[1:]}
    )
    with pytest.raises(CatalogValidationError, match="safe relative path"):
        validate_catalog(invalid, asset_root=CATALOG_PATH.parent)


def test_catalog_validator_requires_icon_asset_to_exist() -> None:
    catalog = load_synthetic_catalog()
    invalid_profile = catalog.profiles[0].model_copy(
        update={"icon_asset_reference": "icons/pre_update/missing.svg"}
    )
    invalid = catalog.model_copy(
        update={"profiles": (invalid_profile,) + catalog.profiles[1:]}
    )
    with pytest.raises(CatalogValidationError, match="does not resolve"):
        validate_catalog(invalid, asset_root=CATALOG_PATH.parent)
