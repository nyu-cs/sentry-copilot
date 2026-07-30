from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .enums import EvidenceKind


class EvidenceRecord(BaseModel):
    """Immutable evidence for one observed or selected domain value."""

    model_config = ConfigDict(frozen=True)

    source: EvidenceKind
    confidence: float = Field(ge=0.0, le=1.0)
    observed_at: AwareDatetime
    source_detail: str | None = None
