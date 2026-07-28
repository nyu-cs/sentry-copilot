from enum import StrEnum


class Server(StrEnum):
    CN = "cn"
    JP = "jp"


class GameMode(StrEnum):
    SOLO = "solo"
    ALLIANCE = "alliance"


class StageType(StrEnum):
    BRIEFING = "briefing"
    STRATEGY_SELECTION = "strategy_selection"
    REGULAR = "regular"
    FINAL_BOSS = "final_boss"
    SECRET_CORE = "secret_core"
    RESULT = "result"
    UNKNOWN = "unknown"


class Phase(StrEnum):
    PREPARATION = "preparation"
    COMBAT = "combat"
    TRANSITION = "transition"
    REWARD = "reward"
    UNKNOWN = "unknown"


class PlayerStatus(StrEnum):
    UNKNOWN = "unknown"
    ACTIVE = "active"
    ELIMINATED = "eliminated"
    LEFT = "left"
    DISCONNECTED = "disconnected"


class EvidenceKind(StrEnum):
    OBSERVED = "observed"
    MANUAL = "manual"
    DERIVED = "derived"
    PREDICTED = "predicted"
