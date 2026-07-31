from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import StringConstraints

_NORMALIZED_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"

RulesetId = Annotated[
    str,
    StringConstraints(strict=True, pattern=_NORMALIZED_ID_PATTERN),
]
RulesetRevisionId = Annotated[
    str,
    StringConstraints(strict=True, pattern=_NORMALIZED_ID_PATTERN),
]
StrategyId = Annotated[
    str,
    StringConstraints(strict=True, pattern=_NORMALIZED_ID_PATTERN),
]
CatalogVersion = Annotated[
    str,
    StringConstraints(strict=True, pattern=_NORMALIZED_ID_PATTERN),
]
SessionId = Annotated[
    str,
    StringConstraints(strict=True, pattern=_NORMALIZED_ID_PATTERN),
]
SessionParticipantId = Annotated[
    str,
    StringConstraints(strict=True, pattern=_NORMALIZED_ID_PATTERN),
]
EvidenceId = Annotated[
    str,
    StringConstraints(strict=True, pattern=_NORMALIZED_ID_PATTERN),
]
StrategyIdentificationRecordId = Annotated[
    str,
    StringConstraints(strict=True, pattern=_NORMALIZED_ID_PATTERN),
]
LegacyMigrationOperationId = Annotated[
    str,
    StringConstraints(strict=True, pattern=_NORMALIZED_ID_PATTERN),
]
SnapshotFingerprint = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]


class LocaleId(StrEnum):
    """Supported normalized locale identifiers."""

    ZH_CN = "zh_CN"
    JA_JP = "ja_JP"
