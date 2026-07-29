import pytest
from pydantic import ValidationError

from sentry_copilot.domain.strategy import LocalizedText, StrategyDefinition


def test_minimal_synthetic_strategy_definition() -> None:
    definition = StrategyDefinition(
        strategy_id="strategy.synthetic.guard",
        names=LocalizedText(zh_CN="合成守备策略", ja_JP="合成防衛戦略"),
        ruleset_ids={"demo.v1"},
    )
    assert definition.description is None
    assert definition.ruleset_ids == frozenset({"demo.v1"})
    assert definition.tags == frozenset()


def test_strategy_definition_requires_ruleset() -> None:
    with pytest.raises(ValidationError):
        StrategyDefinition(
            strategy_id="strategy.synthetic.guard",
            names=LocalizedText(zh_CN="合成守备策略", ja_JP="合成防衛戦略"),
            ruleset_ids=set(),
        )


def test_strategy_definition_sets_are_deeply_immutable() -> None:
    definition = StrategyDefinition(
        strategy_id="strategy.synthetic.guard",
        names=LocalizedText(zh_CN="合成守备策略", ja_JP="合成防衛戦略"),
        ruleset_ids={"demo.v1"},
        tags={"synthetic"},
    )
    assert isinstance(definition.ruleset_ids, frozenset)
    assert isinstance(definition.tags, frozenset)
    for values in (definition.ruleset_ids, definition.tags):
        with pytest.raises(AttributeError):
            values.clear()
        with pytest.raises(AttributeError):
            values.add("other")
        with pytest.raises(AttributeError):
            values.remove("synthetic")


def test_strategy_definition_round_trips_frozen_sets() -> None:
    definition = StrategyDefinition(
        strategy_id="strategy.synthetic.guard",
        names=LocalizedText(zh_CN="合成守备策略", ja_JP="合成防衛戦略"),
        ruleset_ids={"demo.v1"},
        tags={"synthetic"},
    )
    assert StrategyDefinition.model_validate(definition.model_dump()) == definition
    assert StrategyDefinition.model_validate_json(definition.model_dump_json()) == definition
