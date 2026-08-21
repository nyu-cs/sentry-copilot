from sentry_copilot.catalogs.repository import (
    StrategyCatalogRepository,
    load_catalog,
    load_support_registry,
)
from sentry_copilot.routes.repository import MapRepository

if __name__ == "__main__":
    map_repository = MapRepository.from_directory("data/maps")
    for map_id in map_repository.list_ids():
        print(map_id)

    catalog_repository = StrategyCatalogRepository.from_directory(
        "data/strategy_catalogs"
    )
    for catalog_version in catalog_repository.list_catalog_versions():
        print(catalog_version)

    jp_bootstrap = load_catalog(
        "data/strategy_catalog_bootstrap/sentry_protocol.covenant_latter.jp/catalog.yaml"
    )
    print(jp_bootstrap.catalog.catalog_version)

    support_registry = load_support_registry(
        "data/strategy_catalogs/support-targets.yaml"
    )
    print(f"support-targets:{len(support_registry.targets)}")
    print(f"validation-records:{len(support_registry.validation_records)}")
