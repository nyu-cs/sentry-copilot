from __future__ import annotations

from pathlib import Path

import pytest

from sentry_copilot.catalogs.repository import LoadedStrategyCatalog, StrategyCatalogRepository
from sentry_copilot.catalogs.validation import CatalogValidationError, validate_catalog
from sentry_copilot.domain.identifiers import LocaleId
from sentry_copilot.domain.strategy import (
    IconAssetMaterialization,
    LocaleStrategyResource,
    ProtocolRuleset,
    RulesetRevision,
    RulesetStrategyProfile,
    StrategyAvailability,
    StrategyCatalog,
    StrategyIdentity,
    StrategyMetadataProvenance,
    StrategyPhaseAvailability,
)


def _catalog(*, materialization: IconAssetMaterialization) -> StrategyCatalog:
    ruleset_id = "demo.synthetic_ruleset"
    revision_id = "demo.synthetic_ruleset.post_update"
    strategy_id = "strategy.synthetic.guard"
    return StrategyCatalog(
        catalog_version="catalog.synthetic.phase.v1",
        is_synthetic=True,
        icon_asset_materialization=materialization,
        rulesets=(
            ProtocolRuleset(
                ruleset_id=ruleset_id,
                revision_ids=frozenset({revision_id}),
                supported_locales=frozenset({LocaleId.ZH_CN}),
            ),
        ),
        revisions=(
            RulesetRevision(
                ruleset_revision_id=revision_id,
                ruleset_id=ruleset_id,
                revision_order=1,
            ),
        ),
        strategy_identities=(StrategyIdentity(strategy_id=strategy_id),),
        profiles=(
            RulesetStrategyProfile(
                ruleset_revision_id=revision_id,
                strategy_id=strategy_id,
                availability=StrategyAvailability.AVAILABLE,
                initial_hp=27,
                initial_hp_provenance=StrategyMetadataProvenance.LIVE_CONFIRMED,
                initial_hp_source_reference="synthetic-live-observation",
                icon_visual_key="icon.synthetic.guard",
                icon_asset_reference="private_assets/guard.png",
            ),
        ),
        locale_resources=(
            LocaleStrategyResource(
                ruleset_revision_id=revision_id,
                strategy_id=strategy_id,
                locale_id=LocaleId.ZH_CN,
                name="合成策略",
                description="合成测试描述。",
                initiator_display_name="合成发起人",
            ),
        ),
        phase_availabilities=(
            StrategyPhaseAvailability(
                phase_id="demo.synthetic.pre_ultimate",
                ruleset_revision_id=revision_id,
                strategy_id=strategy_id,
                availability=StrategyAvailability.UNAVAILABLE,
                provenance=StrategyMetadataProvenance.LIVE_CONFIRMED,
                source_reference="synthetic-phase-observation",
            ),
        ),
    )


def test_phase_overlay_is_global_and_keeps_profile_identity_and_hp_separate(tmp_path: Path) -> None:
    catalog = _catalog(materialization=IconAssetMaterialization.PRIVATE_LOCAL)

    validate_catalog(catalog, asset_root=tmp_path)

    profile = catalog.profiles[0]
    phase = catalog.phase_availabilities[0]
    assert profile.strategy_id == phase.strategy_id
    assert profile.initial_hp == 27
    assert phase.availability is StrategyAvailability.UNAVAILABLE
    assert phase.provenance is StrategyMetadataProvenance.LIVE_CONFIRMED
    assert "player" not in StrategyPhaseAvailability.model_fields


def test_phase_lookup_never_infers_an_absent_record(tmp_path: Path) -> None:
    catalog = _catalog(materialization=IconAssetMaterialization.PRIVATE_LOCAL)
    repository = StrategyCatalogRepository(
        (LoadedStrategyCatalog(catalog=catalog, asset_root=tmp_path),)
    )

    locked = repository.get_phase_availability(
        catalog_version=catalog.catalog_version,
        phase_id="demo.synthetic.pre_ultimate",
        ruleset_revision_id="demo.synthetic_ruleset.post_update",
        strategy_id="strategy.synthetic.guard",
    )
    unobserved = repository.get_phase_availability(
        catalog_version=catalog.catalog_version,
        phase_id="demo.synthetic.future",
        ruleset_revision_id="demo.synthetic_ruleset.post_update",
        strategy_id="strategy.synthetic.guard",
    )

    assert locked is not None
    assert locked.availability is StrategyAvailability.UNAVAILABLE
    assert unobserved is None


def test_private_local_assets_do_not_require_uncommitted_files_but_packaged_assets_do(
    tmp_path: Path,
) -> None:
    private_catalog = _catalog(materialization=IconAssetMaterialization.PRIVATE_LOCAL)
    validate_catalog(private_catalog, asset_root=tmp_path)

    packaged_catalog = private_catalog.model_copy(
        update={"icon_asset_materialization": IconAssetMaterialization.PACKAGED}
    )
    with pytest.raises(CatalogValidationError, match="does not resolve"):
        validate_catalog(packaged_catalog, asset_root=tmp_path)


def test_phase_availability_requires_a_profile_in_its_exact_revision(tmp_path: Path) -> None:
    catalog = _catalog(materialization=IconAssetMaterialization.PRIVATE_LOCAL)
    invalid_phase = catalog.phase_availabilities[0].model_copy(
        update={"strategy_id": "strategy.synthetic.missing"}
    )
    invalid = catalog.model_copy(update={"phase_availabilities": (invalid_phase,)})

    with pytest.raises(CatalogValidationError, match="without a profile"):
        validate_catalog(invalid, asset_root=tmp_path)
