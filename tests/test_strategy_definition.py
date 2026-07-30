import pytest
from pydantic import ValidationError

from sentry_copilot.domain.identifiers import LocaleId
from sentry_copilot.domain.strategy import (
    LocaleStrategyResource,
    ProtocolRuleset,
    RulesetRevision,
    RulesetStrategyProfile,
    StrategyAvailability,
    StrategyCatalog,
    StrategyIdentity,
)


def synthetic_catalog() -> StrategyCatalog:
    ruleset_id = "demo.synthetic_ruleset"
    revision_id = "demo.synthetic_ruleset.pre_update"
    strategy_id = "strategy.synthetic.guard"
    return StrategyCatalog(
        catalog_version="catalog.synthetic.unit",
        is_synthetic=True,
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
                revision_order=0,
            ),
        ),
        strategy_identities=(StrategyIdentity(strategy_id=strategy_id),),
        profiles=(
            RulesetStrategyProfile(
                ruleset_revision_id=revision_id,
                strategy_id=strategy_id,
                availability=StrategyAvailability.AVAILABLE,
                initial_hp=101,
                icon_visual_key="icon.synthetic.guard.pre_update",
                icon_asset_reference="icons/pre_update/guard.svg",
            ),
        ),
        locale_resources=(
            LocaleStrategyResource(
                ruleset_revision_id=revision_id,
                strategy_id=strategy_id,
                locale_id=LocaleId.ZH_CN,
                name="合成守备方案甲",
                description="仅供合成测试的描述。",
                ocr_aliases=frozenset({"合成守备甲"}),
                visible_text_variants=frozenset({"合成守备方案 A"}),
            ),
        ),
    )


def test_strategy_identity_has_no_icon_authority() -> None:
    identity = StrategyIdentity(strategy_id="strategy.synthetic.guard")
    assert identity.model_dump() == {"strategy_id": "strategy.synthetic.guard"}
    with pytest.raises(ValidationError, match="icon_visual_key"):
        StrategyIdentity.model_validate(
            {
                "strategy_id": "strategy.synthetic.guard",
                "icon_visual_key": "icon.synthetic.guard",
            }
        )


def test_revision_profile_owns_icon_and_initial_hp() -> None:
    profile = synthetic_catalog().profiles[0]
    assert profile.initial_hp == 101
    assert profile.icon_visual_key == "icon.synthetic.guard.pre_update"
    assert profile.icon_asset_reference == "icons/pre_update/guard.svg"
    with pytest.raises(ValidationError, match="greater than 0"):
        RulesetStrategyProfile(
            ruleset_revision_id=profile.ruleset_revision_id,
            strategy_id=profile.strategy_id,
            availability=profile.availability,
            initial_hp=0,
            icon_visual_key=profile.icon_visual_key,
            icon_asset_reference=profile.icon_asset_reference,
        )


def test_locale_resource_is_revision_and_locale_scoped() -> None:
    resource = synthetic_catalog().locale_resources[0]
    assert resource.ruleset_revision_id == "demo.synthetic_ruleset.pre_update"
    assert resource.locale_id == LocaleId.ZH_CN
    assert resource.name == "合成守备方案甲"


def test_catalog_models_are_deeply_immutable() -> None:
    catalog = synthetic_catalog()
    with pytest.raises(ValidationError, match="frozen"):
        catalog.catalog_version = "catalog.synthetic.changed"
    with pytest.raises(AttributeError):
        catalog.rulesets[0].revision_ids.add("demo.synthetic_ruleset.other")
    with pytest.raises(AttributeError):
        catalog.locale_resources[0].ocr_aliases.clear()


def test_catalog_round_trips_immutable_containers() -> None:
    catalog = synthetic_catalog()
    assert StrategyCatalog.model_validate(catalog.model_dump()) == catalog
    assert StrategyCatalog.model_validate_json(catalog.model_dump_json()) == catalog
