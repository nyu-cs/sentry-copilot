from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class InspectionStep(StrEnum):
    SELECT_PLAYER_FIELD = "select_player_field"
    OPEN_STRATEGY_PANEL = "open_strategy_panel"
    CAPTURE_STRATEGY = "capture_strategy"
    COMPLETE = "complete"


class InspectionProgress(BaseModel):
    slots: list[int] = Field(min_length=1)
    current_index: int = 0
    step: InspectionStep = InspectionStep.SELECT_PLAYER_FIELD
    completed_strategy_ids: dict[int, str] = Field(default_factory=dict)

    @property
    def current_slot(self) -> int | None:
        if self.current_index >= len(self.slots):
            return None
        return self.slots[self.current_index]


class PlayerInspectionWorkflow:
    """Guide the user and keep strategy observations bound to an explicit slot."""

    def __init__(self, slots: list[int]) -> None:
        if not slots:
            raise ValueError("at least one player slot is required")
        if len(set(slots)) != len(slots):
            raise ValueError("player slots must be unique")
        if any(slot < 1 or slot > 4 for slot in slots):
            raise ValueError("player slots must be between 1 and 4")
        self.progress = InspectionProgress(slots=slots)

    def instruction(self) -> str:
        slot = self.progress.current_slot
        if self.progress.step == InspectionStep.COMPLETE:
            return "所有目标玩家的策略检查已完成。"
        assert slot is not None
        if self.progress.step == InspectionStep.SELECT_PLAYER_FIELD:
            return f"请手动点击玩家 {slot} 的个性化头像，切换到他的场地。"
        if self.progress.step == InspectionStep.OPEN_STRATEGY_PANEL:
            return f"请在玩家 {slot} 的场地点击左上角，打开本局策略面板。"
        return f"请保持玩家 {slot} 的策略面板可见，助手将读取并等待确认。"

    def acknowledge_player_selected(self, slot: int) -> None:
        self._require_slot(slot)
        self._require_step(InspectionStep.SELECT_PLAYER_FIELD)
        self.progress.step = InspectionStep.OPEN_STRATEGY_PANEL

    def acknowledge_strategy_panel_opened(self, slot: int) -> None:
        self._require_slot(slot)
        self._require_step(InspectionStep.OPEN_STRATEGY_PANEL)
        self.progress.step = InspectionStep.CAPTURE_STRATEGY

    def record_strategy(self, slot: int, strategy_id: str) -> None:
        self._require_slot(slot)
        self._require_step(InspectionStep.CAPTURE_STRATEGY)
        if not strategy_id.strip():
            raise ValueError("strategy_id cannot be empty")
        self.progress.completed_strategy_ids[slot] = strategy_id
        self.progress.current_index += 1
        self.progress.step = (
            InspectionStep.COMPLETE
            if self.progress.current_index >= len(self.progress.slots)
            else InspectionStep.SELECT_PLAYER_FIELD
        )

    def _require_slot(self, slot: int) -> None:
        if slot != self.progress.current_slot:
            raise ValueError(
                f"expected player slot {self.progress.current_slot}, received slot {slot}"
            )

    def _require_step(self, step: InspectionStep) -> None:
        if self.progress.step != step:
            raise ValueError(f"expected step {step}, current step is {self.progress.step}")
