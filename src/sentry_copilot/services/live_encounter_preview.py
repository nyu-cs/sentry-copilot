"""Small in-memory live encounter preview orchestration over existing capture and vision seams."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from threading import Thread

from sentry_copilot.capture.frame_source import Frame, FrameSource
from sentry_copilot.capture.windows_display import (
    WindowsDisplayCaptureError,
    WindowsDisplayFrameSource,
)
from sentry_copilot.encounter.catalog import JP_MUMU_ENCOUNTER_MAP_CATALOG, EncounterMapCatalog
from sentry_copilot.encounter.lifecycle import begin_encounter
from sentry_copilot.encounter.models import EncounterSession
from sentry_copilot.encounter.presentation import EncounterPanelView, present_encounter
from sentry_copilot.encounter.session import (
    EncounterSessionUpdate,
    EncounterUpdateStatus,
    apply_operation_difficulty_observation,
)
from sentry_copilot.vision.ocr import (
    OcrBackend,
    OcrBackendError,
    OcrBackendUnavailableError,
    WindowsOcrBackend,
)
from sentry_copilot.vision.operation_difficulty import (
    OperationDifficultyObservation,
    OperationDifficultyState,
    observe_jp_mumu_operation_difficulty,
)
from sentry_copilot.vision.outside_run_pages import (
    OutsideRunPageObservation,
    observe_jp_mumu_outside_run_pages,
)
from sentry_copilot.vision.selection_session_lifecycle import has_definite_outside_run_evidence
from sentry_copilot.vision.viewport import ContentViewport

LIVE_ENCOUNTER_PREVIEW_BUILD = "live-encounter-preview-v0.1"
SUPPORTED_FRAME_SIZE = (1920, 1080)


class LiveEncounterPreviewStatus(StrEnum):
    WAITING_FOR_SUPPORTED_FRAME = "waiting_for_supported_frame"
    RUNNING = "running"
    CAPTURE_UNAVAILABLE = "capture_unavailable"
    OCR_UNAVAILABLE = "ocr_unavailable"
    ENDED_WAITING_NEXT = "ended_waiting_next"
    STOPPED = "stopped"


@dataclass(frozen=True)
class LiveEncounterPreviewSnapshot:
    """UI-facing, personal-data-free view of one caller-owned live preview."""

    session: EncounterSession
    presentation: EncounterPanelView
    status: LiveEncounterPreviewStatus
    status_message: str
    locale_id: str
    monitor_index: int
    frame_size: tuple[int, int] | None
    operation_state: OperationDifficultyState | None
    update_status: EncounterUpdateStatus | None
    latest_map_id: str | None
    latest_difficulty_id: str | None
    latest_simulation_code: str | None
    latest_observed_difficulty: str | None
    reason: str | None
    encounter_ended: bool


class LiveEncounterPreviewController:
    """Own one in-memory encounter and apply bounded, source-neutral live observations."""

    def __init__(
        self,
        backend: OcrBackend,
        *,
        catalog: EncounterMapCatalog = JP_MUMU_ENCOUNTER_MAP_CATALOG,
        locale_id: str = "zh_CN",
        monitor_index: int = 1,
    ) -> None:
        if monitor_index < 1:
            raise ValueError("monitor_index must select a physical monitor starting at 1")
        self._backend = backend
        self._catalog = catalog
        self._locale_id = locale_id
        self._monitor_index = monitor_index
        self._session = begin_encounter("live-encounter:process")
        self._status = LiveEncounterPreviewStatus.WAITING_FOR_SUPPORTED_FRAME
        self._frame_size: tuple[int, int] | None = None
        self._operation_state: OperationDifficultyState | None = None
        self._update_status: EncounterUpdateStatus | None = None
        self._reason: str | None = None
        self._end_watcher = _OutsideRunEndWatcher()

    @property
    def session(self) -> EncounterSession:
        return self._session

    def snapshot(self) -> LiveEncounterPreviewSnapshot:
        map_capture = self._session.captured_map
        difficulty_capture = self._session.captured_difficulty
        presentation = present_encounter(self._session, self._catalog, locale_id=self._locale_id)
        if self._end_watcher.ended:
            presentation = replace(
                presentation,
                title="上一局情报" if self._locale_id == "zh_CN" else "Previous Encounter",
            )
        return LiveEncounterPreviewSnapshot(
            session=self._session,
            presentation=presentation,
            status=self._status,
            status_message=_status_message(self._status, self._locale_id),
            locale_id=self._locale_id,
            monitor_index=self._monitor_index,
            frame_size=self._frame_size,
            operation_state=self._operation_state,
            update_status=self._update_status,
            latest_map_id=map_capture.map_id if map_capture is not None else None,
            latest_difficulty_id=(
                difficulty_capture.difficulty_id if difficulty_capture is not None else None
            ),
            latest_simulation_code=(
                difficulty_capture.simulation_code if difficulty_capture is not None else None
            ),
            latest_observed_difficulty=(
                difficulty_capture.observed_label if difficulty_capture is not None else None
            ),
            reason=self._reason,
            encounter_ended=self._end_watcher.ended,
        )

    async def process_frame(self, frame: Frame) -> LiveEncounterPreviewSnapshot:
        """Observe one frame; ordinary unresolved evidence never clears retained encounter facts."""

        self._frame_size = (frame.width, frame.height)
        if self._frame_size != SUPPORTED_FRAME_SIZE:
            self._status = LiveEncounterPreviewStatus.WAITING_FOR_SUPPORTED_FRAME
            self._reason = f"requires {SUPPORTED_FRAME_SIZE[0]}x{SUPPORTED_FRAME_SIZE[1]}"
            return self.snapshot()
        if self._end_watcher.ended:
            return self.snapshot()
        if self._session.captured_map is not None or self._session.captured_difficulty is not None:
            self.apply_outside_run_observations(
                observe_jp_mumu_outside_run_pages(frame, ContentViewport.full_frame(frame))
            )
            if self._end_watcher.ended:
                return self.snapshot()
        try:
            observation = await observe_jp_mumu_operation_difficulty(
                frame,
                ContentViewport.full_frame(frame),
                self._backend,
            )
        except OcrBackendUnavailableError as error:
            self._status = LiveEncounterPreviewStatus.OCR_UNAVAILABLE
            self._reason = str(error)
            return self.snapshot()
        except OcrBackendError:
            self._operation_state = OperationDifficultyState.UNRESOLVED
            self._status = LiveEncounterPreviewStatus.RUNNING
            self._reason = None
            return self.snapshot()
        self.apply_operation_observation(observation)
        self._status = LiveEncounterPreviewStatus.RUNNING
        self._reason = None
        return self.snapshot()

    def apply_operation_observation(
        self,
        observation: OperationDifficultyObservation,
    ) -> EncounterSessionUpdate:
        """Apply an already observed fact; public for deterministic caller-owned replay tests."""

        self._operation_state = observation.state
        update = apply_operation_difficulty_observation(self._session, observation, self._catalog)
        self._session = update.session
        self._update_status = update.status
        return update

    def apply_outside_run_observations(
        self,
        observations: tuple[OutsideRunPageObservation, ...],
    ) -> LiveEncounterPreviewSnapshot:
        """Reuse existing semantic outside-run evidence to end, never restart, this encounter."""

        self._end_watcher = self._end_watcher.apply(observations)
        if self._end_watcher.ended:
            self._status = LiveEncounterPreviewStatus.ENDED_WAITING_NEXT
            self._reason = None
        return self.snapshot()

    def set_locale(self, locale_id: str) -> LiveEncounterPreviewSnapshot:
        self._locale_id = locale_id
        return self.snapshot()

    def capture_failed(self, reason: str) -> LiveEncounterPreviewSnapshot:
        self._status = LiveEncounterPreviewStatus.CAPTURE_UNAVAILABLE
        self._reason = reason
        return self.snapshot()

    def ocr_unavailable(self, reason: str) -> LiveEncounterPreviewSnapshot:
        self._status = LiveEncounterPreviewStatus.OCR_UNAVAILABLE
        self._reason = reason
        return self.snapshot()

    def stop(self) -> LiveEncounterPreviewSnapshot:
        self._status = LiveEncounterPreviewStatus.STOPPED
        return self.snapshot()

    def diagnostic_json(self) -> str:
        """Return compact local-only feedback data with no player identity or frame payload."""

        snapshot = self.snapshot()
        return json.dumps(
            {
                "build": LIVE_ENCOUNTER_PREVIEW_BUILD,
                "profile": "jp_mumu_fullscreen_1920x1080.operation_difficulty.v1",
                "monitor_index": snapshot.monitor_index,
                "capture_dimensions": snapshot.frame_size,
                "capture_status": snapshot.status.value,
                "capture_reason": snapshot.reason,
                "ocr_language": "ja-JP",
                "ocr_available": snapshot.status is not LiveEncounterPreviewStatus.OCR_UNAVAILABLE,
                "operation_state": (
                    snapshot.operation_state.value if snapshot.operation_state is not None else None
                ),
                "map_id": snapshot.latest_map_id,
                "difficulty_id": snapshot.latest_difficulty_id,
                "simulation_code": snapshot.latest_simulation_code,
                "observed_difficulty": snapshot.latest_observed_difficulty,
                "encounter_update_status": (
                    snapshot.update_status.value if snapshot.update_status is not None else None
                ),
                "progress": snapshot.presentation.progress_label,
                "encounter_ended": snapshot.encounter_ended,
            },
            ensure_ascii=False,
            indent=2,
        )


def run_live_encounter_loop(
    source: FrameSource,
    controller: LiveEncounterPreviewController,
    on_snapshot: Callable[[LiveEncounterPreviewSnapshot], None],
) -> None:
    """Run a bounded-cadence source until it ends/stops, keeping per-frame failures non-fatal."""

    try:
        for frame in source:
            on_snapshot(asyncio.run(controller.process_frame(frame)))
            if controller.snapshot().status in {
                LiveEncounterPreviewStatus.OCR_UNAVAILABLE,
                LiveEncounterPreviewStatus.ENDED_WAITING_NEXT,
                LiveEncounterPreviewStatus.STOPPED,
            }:
                break
    except WindowsDisplayCaptureError as error:
        on_snapshot(controller.capture_failed(str(error)))
    finally:
        if controller.snapshot().status not in {
            LiveEncounterPreviewStatus.CAPTURE_UNAVAILABLE,
            LiveEncounterPreviewStatus.OCR_UNAVAILABLE,
            LiveEncounterPreviewStatus.ENDED_WAITING_NEXT,
            LiveEncounterPreviewStatus.ENDED_WAITING_NEXT,
        }:
            on_snapshot(controller.stop())


def write_live_preview_diagnostic(controller: LiveEncounterPreviewController, path: Path) -> None:
    """Write only explicit local diagnostic metadata; never capture or upload gameplay."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(controller.diagnostic_json() + "\n", encoding="utf-8")


def run_windows_live_encounter_preview(
    *,
    monitor_index: int,
    locale_id: str,
    always_on_top: bool,
    ocr_unavailable_reason: str | None = None,
    diagnostic_path: Path | None = None,
) -> None:
    """Run the optional Windows/Tk shell while the source worker owns physical-display capture."""

    from sentry_copilot.encounter.desktop import LiveEncounterPreviewWindow

    source = WindowsDisplayFrameSource(monitor_index=monitor_index, target_fps=2.0)
    controller = LiveEncounterPreviewController(
        WindowsOcrBackend(),
        locale_id=locale_id,
        monitor_index=monitor_index,
    )
    initial = (
        controller.ocr_unavailable(ocr_unavailable_reason)
        if ocr_unavailable_reason is not None
        else controller.snapshot()
    )

    def close() -> None:
        source.stop()
        controller.stop()

    window = LiveEncounterPreviewWindow(
        initial,
        on_locale=controller.set_locale,
        diagnostic_text=controller.diagnostic_json,
        on_close=close,
        always_on_top=always_on_top,
    )
    worker: Thread | None = None
    if ocr_unavailable_reason is None:
        worker = Thread(
            target=run_live_encounter_loop,
            args=(source, controller, window.publish),
            daemon=True,
            name="sentry-live-encounter-capture",
        )
        worker.start()
    window.run()
    if worker is not None:
        worker.join(timeout=1.0)
    if diagnostic_path is not None:
        write_live_preview_diagnostic(controller, diagnostic_path)


def _status_message(status: LiveEncounterPreviewStatus, locale_id: str) -> str:
    messages = {
        "zh_CN": {
            LiveEncounterPreviewStatus.WAITING_FOR_SUPPORTED_FRAME: (
                "等待受支持的 1920×1080 游戏画面"
            ),
            LiveEncounterPreviewStatus.RUNNING: "正在监测游戏画面",
            LiveEncounterPreviewStatus.CAPTURE_UNAVAILABLE: "无法初始化显示捕获",
            LiveEncounterPreviewStatus.OCR_UNAVAILABLE: "所需的日文 OCR 不可用",
            LiveEncounterPreviewStatus.ENDED_WAITING_NEXT: "上一局已结束，等待下一局",
            LiveEncounterPreviewStatus.STOPPED: "已停止",
        },
        "en": {
            LiveEncounterPreviewStatus.WAITING_FOR_SUPPORTED_FRAME: (
                "Waiting for a supported 1920×1080 game frame"
            ),
            LiveEncounterPreviewStatus.RUNNING: "Monitoring the game frame",
            LiveEncounterPreviewStatus.CAPTURE_UNAVAILABLE: "Display capture could not start",
            LiveEncounterPreviewStatus.OCR_UNAVAILABLE: "Required Japanese OCR is unavailable",
            LiveEncounterPreviewStatus.ENDED_WAITING_NEXT: (
                "Previous encounter ended. Waiting for next encounter."
            ),
            LiveEncounterPreviewStatus.STOPPED: "Stopped",
        },
    }
    return messages.get(locale_id, messages["en"])[status]


@dataclass(frozen=True)
class _OutsideRunEndWatcher:
    """Minimal adapter over existing outside-run semantic evidence and its two-frame debounce."""

    pending_count: int = 0
    ended: bool = False
    confirmation_count: int = 2

    def apply(self, observations: tuple[OutsideRunPageObservation, ...]) -> _OutsideRunEndWatcher:
        if self.ended:
            return self
        count = self.pending_count + 1 if has_definite_outside_run_evidence(observations) else 0
        return _OutsideRunEndWatcher(
            pending_count=count,
            ended=count >= self.confirmation_count,
            confirmation_count=self.confirmation_count,
        )
