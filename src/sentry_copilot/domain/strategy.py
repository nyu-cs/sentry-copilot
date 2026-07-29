from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LocalizedText(BaseModel):
    """Minimal localized text used by synthetic strategy definitions."""

    model_config = ConfigDict(frozen=True)

    zh_CN: str
    ja_JP: str

    @field_validator("zh_CN", "ja_JP")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("localized text cannot be blank")
        return value


class StrategyDefinition(BaseModel):
    """Ruleset-scoped strategy metadata without recommendation semantics."""

    model_config = ConfigDict(frozen=True)

    strategy_id: str
    names: LocalizedText
    ruleset_ids: frozenset[str] = Field(min_length=1)
    description: LocalizedText | None = None
    tags: frozenset[str] = Field(default_factory=frozenset)

    @field_validator("strategy_id")
    @classmethod
    def strategy_id_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("strategy_id cannot be blank")
        return value

    @field_validator("ruleset_ids", "tags")
    @classmethod
    def string_sets_must_not_contain_blanks(
        cls,
        values: frozenset[str],
    ) -> frozenset[str]:
        if any(not value.strip() for value in values):
            raise ValueError("strategy string sets cannot contain blank values")
        return values
