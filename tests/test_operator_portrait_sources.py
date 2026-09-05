from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sentry_copilot.catalogs.operator_portrait_sources import (
    OperatorPortraitSource,
    OperatorPortraitSourceCatalog,
    load_default_operator_portrait_source_catalog,
    load_operator_portrait_source_catalog,
)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _source(name: str = "玛恩纳") -> OperatorPortraitSource:
    return OperatorPortraitSource(
        portrait_key=f"prts:{name}",
        name_zh_CN=name,
        provider="PRTS",
        file_title=f"头像 {name}.png",
        source_page=f"https://prts.wiki/w/文件:头像_{name}.png",
        base_variant="elite_0",
    )


def test_public_manifest_covers_current_ordinary_roster_without_owning_ruleset_metadata() -> None:
    root = _repository_root()
    manifest_raw = yaml.safe_load(
        (root / "data/catalogs/operator_portrait_sources.yaml").read_text(encoding="utf-8")
    )
    operator_raw = yaml.safe_load(
        (root / "data/catalogs/covenant_latter/operator_catalog.yaml").read_text(encoding="utf-8")
    )
    catalog = load_default_operator_portrait_source_catalog()

    assert manifest_raw["catalog_kind"] == "operator_portrait_sources"
    records = manifest_raw["portrait_sources"]
    assert isinstance(records, list)
    forbidden = {"tier", "covenant_ids", "memberships", "recruitment_route", "ban_state"}
    assert all(not forbidden.intersection(record) for record in records)
    assert all(record["provider"] == "PRTS" for record in records)
    assert all(record["file_title"] for record in records)
    assert all(record["source_page"] for record in records)

    ordinary_names = {
        record["name_zh_CN"]
        for record in operator_raw["operators"]
        if record.get("special_entry") is not True
    }
    special_support = next(
        record for record in operator_raw["operators"] if record.get("special_entry") is True
    )
    source_names = {source.name_zh_CN for source in catalog.sources}
    assert len(ordinary_names) == 112
    assert ordinary_names <= source_names
    assert special_support["name_zh_CN"] not in ordinary_names


def test_portrait_identity_reuses_the_name_across_ruleset_metadata_changes(tmp_path: Path) -> None:
    version_a = {
        "operator_id": "operator.covenant_latter.op_093",
        "name_zh_CN": "玛恩纳",
        "tier": 5,
        "memberships": ("covenant.covenant_latter.kazimierz",),
    }
    version_b = {
        "operator_id": "operator.future.op_001",
        "name_zh_CN": "玛恩纳",
        "tier": 3,
        "memberships": ("covenant.future.example",),
    }
    catalog = OperatorPortraitSourceCatalog((_source(),))

    resolved_a = catalog.by_name_zh_CN(version_a["name_zh_CN"])
    resolved_b = catalog.by_name_zh_CN(version_b["name_zh_CN"])

    assert resolved_a is not None
    assert resolved_b is not None
    assert resolved_a.portrait_key == "prts:玛恩纳"
    assert resolved_b.portrait_key == "prts:玛恩纳"
    assert OperatorPortraitSourceCatalog.private_cache_path(
        tmp_path, resolved_a.portrait_key
    ) == OperatorPortraitSourceCatalog.private_cache_path(tmp_path, resolved_b.portrait_key)


def test_loader_rejects_ruleset_gameplay_metadata(tmp_path: Path) -> None:
    path = tmp_path / "operator_portrait_sources.yaml"
    path.write_text(
        """portrait_sources:
- portrait_key: prts:玛恩纳
  name_zh_CN: 玛恩纳
  provider: PRTS
  file_title: 头像 玛恩纳.png
  source_page: https://prts.wiki/w/文件:头像_玛恩纳.png
  base_variant: elite_0
  tier: 5
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must not contain gameplay metadata"):
        load_operator_portrait_source_catalog(path)
