"""Small in-memory live encounter preview orchestration over existing capture and vision seams."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from threading import Thread
from time import sleep

from sentry_copilot.capture.frame_source import (
    Frame,
    FrameSource,
    FrameSourceMetadata,
    FrameSourceType,
)
from sentry_copilot.capture.mumu_ipc import MuMuIpcCaptureError
from sentry_copilot.capture.windows_display import (
    WindowsDisplayCaptureError,
    WindowsDisplayFrameSource,
)
from sentry_copilot.encounter.catalog import JP_MUMU_ENCOUNTER_MAP_CATALOG, EncounterMapCatalog
from sentry_copilot.encounter.confirmed_banned_operators import (
    ConfirmedBannedOperator,
    ConfirmedBannedOperatorCatalog,
    ConfirmedBannedOperatorRow,
    project_confirmed_banned_operator_rows,
    resolve_confirmed_banned_operators,
)
from sentry_copilot.encounter.lifecycle import begin_encounter
from sentry_copilot.encounter.major_covenant_ban_catalog import (
    MajorCovenantPresentationCatalog,
)
from sentry_copilot.encounter.models import (
    BossCaptureSource,
    DifficultyCaptureSource,
    EncounterSession,
    EnemyTypeCaptureSource,
    MajorCovenantBanSnapshot,
    MajorCovenantBanStateEntry,
)
from sentry_copilot.encounter.presentation import EncounterPanelView, present_encounter
from sentry_copilot.encounter.session import (
    EncounterSessionUpdate,
    EncounterUpdateStatus,
    apply_boss_capture,
    apply_enemy_type_capture,
    apply_info_difficulty_capture,
    apply_major_covenant_ban_capture,
    apply_operation_difficulty_observation,
    apply_visual_difficulty_capture,
)
from sentry_copilot.vision.difficulty_recovery import (
    DifficultyRecoveryObservation,
    DifficultyRecoveryReferencePack,
    DifficultyRecoverySource,
    observe_jp_mumu_operation_splash_difficulty,
    observe_jp_mumu_post_start_difficulty,
)
from sentry_copilot.vision.info_1_2 import (
    JP_MUMU_INFO_1_2_PROFILE_ID,
    EnemySlotLayout,
    Info12Observation,
    Info12ReferencePack,
    Info12State,
    RankedVisualCandidate,
    observe_jp_mumu_info_1_2,
)
from sentry_copilot.vision.info_recovery_pages import (
    InfoRecoveryPageObservation,
    InfoRecoveryPageReferencePack,
    InfoRecoveryPageState,
    observe_jp_mumu_info_2_2_phase,
    observe_jp_mumu_returned_info_page,
)
from sentry_copilot.vision.major_covenant_ban import (
    MajorCovenantBanObservation,
    MajorCovenantBanObserver,
    MajorCovenantIdentityObservation,
    MajorCovenantReferencePack,
    supports_returned_major_covenant_ban,
)
from sentry_copilot.vision.operation_difficulty import (
    OperationDifficultyObservation,
    OperationDifficultyState,
)
from sentry_copilot.vision.outside_run_pages import (
    OutsideRunPageObservation,
)
from sentry_copilot.vision.returned_info_recovery import (
    RETURNED_INFO_BOSS_CONFIRMATION_COUNT,
    RETURNED_INFO_ENEMY_CONFIRMATION_COUNT,
    ReturnedInfoBossObservation,
    ReturnedInfoEnemyObservation,
    observe_jp_mumu_returned_info_boss,
    observe_jp_mumu_returned_info_enemy,
)
from sentry_copilot.vision.selection_session_lifecycle import has_definite_outside_run_evidence
from sentry_copilot.vision.viewport import ContentViewport

LIVE_ENCOUNTER_PREVIEW_BUILD = "live-encounter-preview-v0.1"
SUPPORTED_FRAME_SIZE = (1920, 1080)


class LiveEncounterPreviewStatus(StrEnum):
    WAITING_FOR_SUPPORTED_FRAME = "waiting_for_supported_frame"
    WAITING_FOR_INITIAL_INFO = "waiting_for_initial_info"
    INFO_REFERENCES_UNAVAILABLE = "info_references_unavailable"
    RUNNING = "running"
    CAPTURE_UNAVAILABLE = "capture_unavailable"
    ENDED_WAITING_NEXT = "ended_waiting_next"
    STOPPED = "stopped"


class _InfoEncounterLifecycleState(StrEnum):
    """Track departure from initial INFO so later frames can be screened for the next run.

    ``ARMED_FOR_NEXT_INFO`` never means that the retained encounter ended or became stale.
    """

    WAITING_FOR_INITIAL_INFO = "waiting_for_initial_info"
    INITIAL_INFO = "initial_info"
    ARMED_FOR_NEXT_INFO = "armed_for_next_info"


class _RecoveryReminderState(StrEnum):
    """Reminder-only state that is intentionally independent from Encounter lifecycle."""

    INACTIVE = "inactive"
    OPEN = "open"
    CLOSED_FOR_RUN = "closed_for_run"


INFO_DEPARTURE_CONFIRMATION_COUNT = 3
# Generic INFO-like transition frames are rejected by the strict canonical classifier.
# Three consecutive canonical initial-INFO observations are sufficient for live re-entry.
INFO_REENTRY_CONFIRMATION_COUNT = 3
INFO_2_2_REMINDER_CONFIRMATION_COUNT = 2


@dataclass(frozen=True)
class InfoReferenceLoadFailure:
    """Sanitized, path-free reason why declared INFO references could not load."""

    category: str
    reason: str


@dataclass(frozen=True)
class _NextInitialInfoCandidate:
    """Internal, stricter-than-anchor evidence for replacing an existing encounter."""

    is_candidate: bool
    reason: str | None


@dataclass(frozen=True)
class _NextInitialInfoTracePresent:
    """Compact, normalized evidence retained after an ARMED INFO page leaves view."""

    frame_id: str
    anchor_score: float | None
    enemy_slot_layout: str
    enemy_ranking_slot_count: int
    difficulty_candidate_id: str | None
    reliable_boss_id: str | None
    reliable_enemy_ids: tuple[str, ...]
    returned_info_state_same_frame: str | None
    info_2_2_state_same_frame: str | None
    classified_candidate: bool
    classification_reason: str | None


@dataclass
class _NextInitialInfoTrace:
    """Bounded diagnostics for one attempted next-run initial INFO sequence."""

    present_frames: int = 0
    candidate_frames: int = 0
    max_candidate_streak: int = 0
    last_present_frame_id: str | None = None
    last_candidate_frame_id: str | None = None
    last_rejection_reason: str | None = None
    rejection_counts: dict[str, int] = field(default_factory=dict)
    last_present: _NextInitialInfoTracePresent | None = None


@dataclass(frozen=True)
class _LastNextEncounterPromotionTrace:
    """One compact previous-promotion summary; this is not a history log."""

    max_candidate_streak: int
    frame_id: str | None
    promotion_reason: str


@dataclass(frozen=True)
class LiveEncounterPreviewSnapshot:
    """UI-facing, personal-data-free view of one caller-owned live preview."""

    session: EncounterSession | None
    presentation: EncounterPanelView
    status: LiveEncounterPreviewStatus
    status_message: str
    locale_id: str
    monitor_index: int | None
    capture_source_type: FrameSourceType
    capture_source_id: str
    capture_source_reference: str
    frame_size: tuple[int, int] | None
    operation_state: OperationDifficultyState | None
    update_status: EncounterUpdateStatus | None
    latest_map_id: str | None
    latest_difficulty_id: str | None
    latest_simulation_code: str | None
    latest_observed_difficulty: str | None
    reason: str | None
    encounter_ended: bool
    recovery_state: str
    recovery_reminder_visible: bool
    recovery_reminder_text: str | None
    missing_recoverable_items: tuple[str, ...]


class LiveEncounterPreviewController:
    """Own one in-memory encounter and apply bounded, source-neutral live observations."""

    def __init__(
        self,
        backend: object | None = None,
        *,
        catalog: EncounterMapCatalog = JP_MUMU_ENCOUNTER_MAP_CATALOG,
        locale_id: str = "zh_CN",
        monitor_index: int | None = 1,
        capture_source_metadata: FrameSourceMetadata | None = None,
        info_1_2_references: Info12ReferencePack | None = None,
        info_reference_failure: InfoReferenceLoadFailure | None = None,
        difficulty_recovery_references: DifficultyRecoveryReferencePack | None = None,
        difficulty_recovery_failure: InfoReferenceLoadFailure | None = None,
        info_recovery_page_references: InfoRecoveryPageReferencePack | None = None,
        info_recovery_page_failure: InfoReferenceLoadFailure | None = None,
        major_covenant_references: MajorCovenantReferencePack | None = None,
        major_covenant_catalog: MajorCovenantPresentationCatalog | None = None,
        confirmed_banned_operator_catalog: ConfirmedBannedOperatorCatalog | None = None,
        confirmed_banned_operator_catalog_failure: InfoReferenceLoadFailure | None = None,
        major_covenant_reference_failure: InfoReferenceLoadFailure | None = None,
        debug_skip_initial_enemy_capture: bool = False,
    ) -> None:
        del (
            backend
        )  # Kept as a compatibility-only constructor argument; live preview no longer OCRs.
        if monitor_index is not None and monitor_index < 1:
            raise ValueError("monitor_index must select a physical monitor starting at 1")
        self._catalog = catalog
        self._debug_skip_initial_enemy_capture = debug_skip_initial_enemy_capture
        self._locale_id = locale_id
        if capture_source_metadata is None:
            assert monitor_index is not None
            capture_source_metadata = FrameSourceMetadata(
                source_id=f"windows-display:monitor-{monitor_index}",
                source_type=FrameSourceType.WINDOWS_DISPLAY,
                source_reference=f"physical-monitor:{monitor_index}",
                frame_rate=2.0,
            )
        self._capture_source_metadata = capture_source_metadata
        self._monitor_index = (
            monitor_index
            if capture_source_metadata.source_type is FrameSourceType.WINDOWS_DISPLAY
            else None
        )
        self._session: EncounterSession | None = None
        self._status = (
            LiveEncounterPreviewStatus.WAITING_FOR_SUPPORTED_FRAME
            if info_1_2_references is not None
            else LiveEncounterPreviewStatus.INFO_REFERENCES_UNAVAILABLE
        )
        self._frame_size: tuple[int, int] | None = None
        self._operation_state: OperationDifficultyState | None = None
        self._update_status: EncounterUpdateStatus | None = None
        self._reason: str | None = (
            info_reference_failure.reason
            if info_1_2_references is None and info_reference_failure is not None
            else "INFO 1/2 visual references unavailable"
            if info_1_2_references is None
            else None
        )
        self._end_watcher = _OutsideRunEndWatcher()
        self._info_1_2_references = info_1_2_references
        self._info_reference_failure = info_reference_failure
        self._difficulty_recovery_references = difficulty_recovery_references
        self._difficulty_recovery_failure = difficulty_recovery_failure
        self._info_recovery_page_references = info_recovery_page_references
        self._info_recovery_page_failure = info_recovery_page_failure
        self._major_covenant_catalog = major_covenant_catalog
        self._confirmed_banned_operator_catalog = confirmed_banned_operator_catalog
        self._confirmed_banned_operator_catalog_failure = confirmed_banned_operator_catalog_failure
        self._major_covenant_reference_failure = major_covenant_reference_failure
        self._major_covenant_observer = (
            MajorCovenantBanObserver(major_covenant_references)
            if major_covenant_references is not None
            else None
        )
        self._encounter_count = 0
        self._boss_pending_id: str | None = None
        self._boss_pending_count = 0
        self._latest_info_1_2: Info12Observation | None = None
        self._latest_next_initial_info_candidate: _NextInitialInfoCandidate | None = None
        self._next_initial_info_trace: _NextInitialInfoTrace | None = None
        self._last_next_encounter_promotion_trace: _LastNextEncounterPromotionTrace | None = None
        self._next_encounter_promotion_reason: str | None = None
        self._latest_major_covenant_ban: MajorCovenantBanObservation | None = None
        self._major_ban_pending_disabled_ids: tuple[str, ...] | None = None
        self._major_ban_pending_count = 0
        self._difficulty_pending_id: str | None = None
        self._difficulty_pending_count = 0
        self._info_lifecycle_state = _InfoEncounterLifecycleState.WAITING_FOR_INITIAL_INFO
        self._info_departure_count = 0
        self._info_reentry_count = 0
        self._latest_post_start_difficulty: DifficultyRecoveryObservation | None = None
        self._latest_operation_splash_difficulty: DifficultyRecoveryObservation | None = None
        self._post_start_difficulty_pending_id: str | None = None
        self._post_start_difficulty_pending_count = 0
        self._operation_splash_difficulty_pending_id: str | None = None
        self._operation_splash_difficulty_pending_count = 0
        self._recovery_state = _RecoveryReminderState.INACTIVE
        self._recovery_reminder_visible = False
        self._phase_2_2_present_streak = 0
        self._latest_info_2_2_phase: InfoRecoveryPageObservation | None = None
        self._latest_returned_info: InfoRecoveryPageObservation | None = None
        self._latest_returned_info_boss: ReturnedInfoBossObservation | None = None
        self._returned_info_boss_pending_id: str | None = None
        self._returned_info_boss_pending_count = 0
        self._latest_returned_info_enemy: ReturnedInfoEnemyObservation | None = None
        self._returned_info_enemy_pending_candidate: tuple[str, ...] | None = None
        self._returned_info_enemy_pending_count = 0
        self._latest_returned_info_major: MajorCovenantBanObservation | None = None
        self._returned_info_major_pending_disabled_ids: tuple[str, ...] | None = None
        self._returned_info_major_pending_count = 0
        self._returned_info_major_capture_attempted = False

    @property
    def session(self) -> EncounterSession | None:
        return self._session

    def snapshot(self) -> LiveEncounterPreviewSnapshot:
        session = self._session or begin_encounter("live-encounter:waiting")
        map_capture = session.captured_map
        difficulty_capture = session.captured_difficulty
        presentation = present_encounter(
            session,
            self._catalog,
            locale_id=self._locale_id,
            major_covenant_catalog=self._major_covenant_catalog,
            confirmed_banned_operator_catalog=self._confirmed_banned_operator_catalog,
        )
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
            capture_source_type=self._capture_source_metadata.source_type,
            capture_source_id=self._capture_source_metadata.source_id,
            capture_source_reference=self._capture_source_metadata.source_reference,
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
            recovery_state=self._recovery_state.value,
            recovery_reminder_visible=self._recovery_reminder_visible,
            recovery_reminder_text=(
                _recovery_reminder_text(self._locale_id, self._missing_recoverable_items())
                if self._recovery_reminder_visible
                else None
            ),
            missing_recoverable_items=self._missing_recoverable_items(),
        )

    async def process_frame(self, frame: Frame) -> LiveEncounterPreviewSnapshot:
        """Observe one frame; ordinary unresolved evidence never clears retained encounter facts."""

        self._frame_size = (frame.width, frame.height)
        if self._frame_size != SUPPORTED_FRAME_SIZE:
            self._status = LiveEncounterPreviewStatus.WAITING_FOR_SUPPORTED_FRAME
            self._reason = f"requires {SUPPORTED_FRAME_SIZE[0]}x{SUPPORTED_FRAME_SIZE[1]}"
            return self.snapshot()
        viewport = ContentViewport.full_frame(frame)
        if self._info_1_2_references is None:
            self._latest_info_1_2 = Info12Observation(Info12State.UNRESOLVED, frame.frame_id, None)
            self._status = LiveEncounterPreviewStatus.INFO_REFERENCES_UNAVAILABLE
            self._reason = (
                self._info_reference_failure.reason
                if self._info_reference_failure is not None
                else "INFO 1/2 visual references unavailable"
            )
            return self.snapshot()
        self._latest_info_1_2 = observe_jp_mumu_info_1_2(frame, viewport, self._info_1_2_references)
        self._observe_info_recovery_pages(frame, viewport)
        self.apply_info_1_2_observation(self._latest_info_1_2)
        self._observe_initial_info_major_ban(frame, viewport, self._latest_info_1_2)
        self._observe_missing_difficulty_recovery(frame, viewport, self._latest_info_1_2)
        self._update_recovery_reminder()
        self._observe_returned_info_boss_recovery(frame, viewport)
        self._observe_returned_info_enemy_recovery(frame, viewport)
        self._observe_returned_info_major_recovery(frame, viewport)
        if self._end_watcher.ended:
            return self.snapshot()
        if self._session is None:
            self._status = LiveEncounterPreviewStatus.WAITING_FOR_INITIAL_INFO
            self._reason = None
            return self.snapshot()
        self._status = LiveEncounterPreviewStatus.RUNNING
        self._reason = None
        return self.snapshot()

    def apply_operation_observation(
        self,
        observation: OperationDifficultyObservation,
    ) -> EncounterSessionUpdate:
        """Apply an already observed fact; public for deterministic caller-owned replay tests."""

        self._operation_state = observation.state
        if observation.state is OperationDifficultyState.OBSERVED:
            self._close_recovery_for_run()
        if self._session is None or self._end_watcher.ended:
            return EncounterSessionUpdate(
                self._session or begin_encounter("live-encounter:waiting"),
                EncounterUpdateStatus.UNRESOLVED,
            )
        update = apply_operation_difficulty_observation(self._session, observation, self._catalog)
        self._session = update.session
        self._update_status = update.status
        return update

    def apply_info_1_2_observation(self, observation: Info12Observation) -> None:
        """Apply initial INFO facts, replacing an existing encounter only after strict re-entry."""
        if self._session is None or self._end_watcher.ended:
            self._latest_next_initial_info_candidate = None
            if not self._is_genuine_initial_info(observation):
                self._reset_pending_info_recognition()
                return
            self._start_encounter(promotion_reason="first_initial_info")
            self._apply_current_info_facts(observation)
            return

        if self._info_lifecycle_state is _InfoEncounterLifecycleState.INITIAL_INFO:
            self._latest_next_initial_info_candidate = None
            if observation.state is Info12State.PRESENT:
                self._info_departure_count = 0
                if self._is_genuine_initial_info(observation):
                    self._apply_current_info_facts(observation)
                else:
                    self._reset_pending_info_recognition()
            elif observation.state is Info12State.ABSENT:
                self._reset_pending_info_recognition()
                self._info_departure_count += 1
                if self._info_departure_count >= INFO_DEPARTURE_CONFIRMATION_COUNT:
                    self._info_lifecycle_state = _InfoEncounterLifecycleState.ARMED_FOR_NEXT_INFO
                    self._info_reentry_count = 0
                    self._next_initial_info_trace = _NextInitialInfoTrace()
                    self._open_recovery_for_run()
            else:
                self._reset_pending_info_recognition()
                self._info_departure_count = 0
            return

        if self._info_lifecycle_state is _InfoEncounterLifecycleState.ARMED_FOR_NEXT_INFO:
            candidate = self._classify_next_initial_info_candidate(observation)
            self._latest_next_initial_info_candidate = candidate
            self._record_next_initial_info_trace(observation, candidate)
            if candidate.is_candidate:
                self._info_reentry_count += 1
                if self._info_reentry_count >= INFO_REENTRY_CONFIRMATION_COUNT:
                    self._start_encounter(promotion_reason="confirmed_next_initial_info")
                    self._apply_current_info_facts(observation)
            else:
                self._info_reentry_count = 0
            return

        # Test-only/controller-owned established sessions that predate INFO lifecycle state.
        self._latest_next_initial_info_candidate = None
        if self._is_genuine_initial_info(observation):
            self._info_lifecycle_state = _InfoEncounterLifecycleState.INITIAL_INFO
            self._info_departure_count = 0
            self._apply_current_info_facts(observation)
        else:
            self._reset_pending_info_recognition()

    def _classify_next_initial_info_candidate(
        self, observation: Info12Observation
    ) -> _NextInitialInfoCandidate:
        """Require canonical initial-INFO structure, not merely the generic INFO anchor."""

        if observation.state is not Info12State.PRESENT:
            return _NextInitialInfoCandidate(
                False,
                "unsupported_frame" if observation.state is Info12State.UNRESOLVED else None,
            )
        if self._page_is_present(self._latest_returned_info, observation.frame_id):
            return _NextInitialInfoCandidate(False, "returned_info")
        if self._page_is_present(self._latest_info_2_2_phase, observation.frame_id):
            return _NextInitialInfoCandidate(False, "info_2_2")
        expected_slots = (
            2
            if observation.enemy_slot_layout is EnemySlotLayout.TWO_SLOT
            else 3
            if observation.enemy_slot_layout is EnemySlotLayout.THREE_SLOT
            else 0
        )
        if expected_slots == 0 or len(observation.enemy_rankings) != expected_slots:
            return _NextInitialInfoCandidate(False, "insufficient_structure")
        if not self._has_reliable_initial_enemy(observation):
            return _NextInitialInfoCandidate(False, "no_reliable_enemy")
        return _NextInitialInfoCandidate(True, "canonical_initial_info")

    @staticmethod
    def _has_reliable_initial_enemy(observation: Info12Observation) -> bool:
        """Return the retained-evidence-backed semantic signal for genuine initial INFO."""

        return any(identity_id is not None for identity_id in observation.reliable_enemy_ids)

    @classmethod
    def _is_genuine_initial_info(cls, observation: Info12Observation) -> bool:
        """Keep first-start and primary INFO fact eligibility on one semantic rule."""

        return (
            observation.state is Info12State.PRESENT
            and cls._has_reliable_initial_enemy(observation)
        )

    def _record_next_initial_info_trace(
        self,
        observation: Info12Observation,
        candidate: _NextInitialInfoCandidate,
    ) -> None:
        """Retain only bounded normalized evidence while awaiting the next encounter."""

        trace = self._next_initial_info_trace
        if trace is None or observation.state is not Info12State.PRESENT:
            return
        trace.present_frames += 1
        trace.last_present_frame_id = observation.frame_id
        trace.last_present = _NextInitialInfoTracePresent(
            frame_id=observation.frame_id,
            anchor_score=observation.anchor_score,
            enemy_slot_layout=observation.enemy_slot_layout.value,
            enemy_ranking_slot_count=len(observation.enemy_rankings),
            difficulty_candidate_id=observation.difficulty_candidate_id,
            reliable_boss_id=observation.reliable_boss_id,
            reliable_enemy_ids=tuple(
                identity_id
                for identity_id in observation.reliable_enemy_ids
                if identity_id is not None
            ),
            returned_info_state_same_frame=(
                self._latest_returned_info.state.value
                if self._page_is_present(self._latest_returned_info, observation.frame_id)
                and self._latest_returned_info is not None
                else None
            ),
            info_2_2_state_same_frame=(
                self._latest_info_2_2_phase.state.value
                if self._page_is_present(self._latest_info_2_2_phase, observation.frame_id)
                and self._latest_info_2_2_phase is not None
                else None
            ),
            classified_candidate=candidate.is_candidate,
            classification_reason=candidate.reason,
        )
        if candidate.is_candidate:
            trace.candidate_frames += 1
            trace.last_candidate_frame_id = observation.frame_id
            trace.max_candidate_streak = max(
                trace.max_candidate_streak,
                self._info_reentry_count + 1,
            )
        elif candidate.reason is not None:
            trace.last_rejection_reason = candidate.reason
            trace.rejection_counts[candidate.reason] = (
                trace.rejection_counts.get(candidate.reason, 0) + 1
            )

    @staticmethod
    def _page_is_present(
        observation: InfoRecoveryPageObservation | None,
        frame_id: str,
    ) -> bool:
        return (
            observation is not None
            and observation.frame_id == frame_id
            and observation.state is InfoRecoveryPageState.PRESENT
        )

    def _start_encounter(self, *, promotion_reason: str | None = None) -> None:
        """Replace the old session only after an authoritative, debounced INFO start."""

        if (
            promotion_reason == "confirmed_next_initial_info"
            and self._next_initial_info_trace is not None
        ):
            self._last_next_encounter_promotion_trace = _LastNextEncounterPromotionTrace(
                max_candidate_streak=self._next_initial_info_trace.max_candidate_streak,
                frame_id=self._next_initial_info_trace.last_candidate_frame_id,
                promotion_reason=promotion_reason,
            )
        self._next_initial_info_trace = None
        self._encounter_count += 1
        self._next_encounter_promotion_reason = promotion_reason
        self._session = begin_encounter(f"live-encounter:{self._encounter_count}")
        self._end_watcher = _OutsideRunEndWatcher()
        self._info_lifecycle_state = _InfoEncounterLifecycleState.INITIAL_INFO
        self._info_departure_count = 0
        self._info_reentry_count = 0
        self._update_status = None
        self._operation_state = None
        self._reset_pending_info_recognition()
        self._reset_pending_difficulty_recovery()
        self._latest_post_start_difficulty = None
        self._latest_operation_splash_difficulty = None
        self._recovery_state = _RecoveryReminderState.INACTIVE
        self._recovery_reminder_visible = False
        self._phase_2_2_present_streak = 0
        self._latest_info_2_2_phase = None
        self._latest_returned_info = None
        self._latest_returned_info_boss = None
        self._latest_returned_info_enemy = None
        self._latest_returned_info_major = None
        self._returned_info_major_capture_attempted = False
        self._latest_major_covenant_ban = None
        self._reset_pending_major_covenant_ban()
        self._reset_pending_returned_info_recognition()

    def _reset_pending_info_recognition(self) -> None:
        self._boss_pending_id = None
        self._boss_pending_count = 0
        self._difficulty_pending_id = None
        self._difficulty_pending_count = 0

    def _reset_pending_major_covenant_ban(self) -> None:
        self._major_ban_pending_disabled_ids = None
        self._major_ban_pending_count = 0

    def _reset_pending_difficulty_recovery(self) -> None:
        self._reset_pending_post_start_difficulty_recovery()
        self._operation_splash_difficulty_pending_id = None
        self._operation_splash_difficulty_pending_count = 0

    def _reset_pending_post_start_difficulty_recovery(self) -> None:
        """Clear only post-start evidence when the current frame is not semantic INFO 2/2."""

        self._post_start_difficulty_pending_id = None
        self._post_start_difficulty_pending_count = 0

    def _reset_pending_returned_info_recognition(self) -> None:
        self._reset_pending_returned_info_boss_recognition()
        self._reset_pending_returned_info_enemy_recognition()
        self._reset_pending_returned_info_major_recognition()

    def _reset_pending_returned_info_boss_recognition(self) -> None:
        self._returned_info_boss_pending_id = None
        self._returned_info_boss_pending_count = 0

    def _reset_pending_returned_info_enemy_recognition(self) -> None:
        self._returned_info_enemy_pending_candidate = None
        self._returned_info_enemy_pending_count = 0

    def _reset_pending_returned_info_major_recognition(self) -> None:
        self._returned_info_major_pending_disabled_ids = None
        self._returned_info_major_pending_count = 0

    def _observe_missing_difficulty_recovery(
        self, frame: Frame, viewport: ContentViewport, info: Info12Observation
    ) -> None:
        """Fill a missing Difficulty only after confirmed departure from genuine INFO 1/2."""

        if (
            self._session is None
            or self._info_lifecycle_state is not _InfoEncounterLifecycleState.ARMED_FOR_NEXT_INFO
            or info.state is not Info12State.ABSENT
        ):
            self._latest_post_start_difficulty = None
            self._latest_operation_splash_difficulty = None
            self._reset_pending_difficulty_recovery()
            return
        post_start_allowed = (
            self._session.captured_difficulty is None
            and self._page_is_present(self._latest_info_2_2_phase, frame.frame_id)
            and not self._page_is_present(self._latest_returned_info, frame.frame_id)
        )
        if post_start_allowed:
            self._latest_post_start_difficulty = observe_jp_mumu_post_start_difficulty(
                frame, viewport, self._difficulty_recovery_references
            )
            self._apply_difficulty_recovery(self._latest_post_start_difficulty)
        else:
            self._latest_post_start_difficulty = None
            self._reset_pending_post_start_difficulty_recovery()
        self._latest_operation_splash_difficulty = observe_jp_mumu_operation_splash_difficulty(
            frame, viewport, self._difficulty_recovery_references
        )
        if self._session.captured_difficulty is None:
            self._apply_difficulty_recovery(self._latest_operation_splash_difficulty)
        if self._latest_operation_splash_difficulty.reliable_id is not None:
            self._close_recovery_for_run()

    def _open_recovery_for_run(self) -> None:
        self._recovery_state = _RecoveryReminderState.OPEN
        self._recovery_reminder_visible = False
        self._phase_2_2_present_streak = 0

    def _close_recovery_for_run(self) -> None:
        if self._recovery_state is _RecoveryReminderState.OPEN:
            self._recovery_state = _RecoveryReminderState.CLOSED_FOR_RUN
        self._recovery_reminder_visible = False
        self._phase_2_2_present_streak = 0

    def _missing_recoverable_items(self) -> tuple[str, ...]:
        if self._session is None:
            return ()
        missing = tuple(
            item
            for item, complete in (
                ("boss", self._session.boss_id is not None),
                ("enemy_types", self._session.enemy_type_ids is not None),
            )
            if not complete
        )
        difficulty_id = (
            self._session.captured_difficulty.difficulty_id
            if self._session.captured_difficulty is not None
            else None
        )
        if (
            self._major_covenant_observer is not None
            and supports_returned_major_covenant_ban(difficulty_id)
            and self._session.major_covenant_ban is None
        ):
            return (*missing, "major_covenants")
        return missing

    def _observe_info_recovery_pages(self, frame: Frame, viewport: ContentViewport) -> None:
        """Observe recovery pages once so lifecycle exclusion and recovery can reuse them."""

        self._latest_info_2_2_phase = observe_jp_mumu_info_2_2_phase(
            frame, viewport, self._info_recovery_page_references
        )
        self._latest_returned_info = observe_jp_mumu_returned_info_page(
            frame, viewport, self._info_recovery_page_references
        )

    def _update_recovery_reminder(self) -> None:
        """Apply recovery reminder behavior to the current frame's page observations."""

        if self._latest_info_2_2_phase is None or self._latest_returned_info is None:
            return
        if self._recovery_state is not _RecoveryReminderState.OPEN:
            self._phase_2_2_present_streak = 0
            return
        if self._latest_returned_info.state is InfoRecoveryPageState.PRESENT:
            self._recovery_reminder_visible = False
            self._phase_2_2_present_streak = 0
            return
        if not self._missing_recoverable_items():
            self._recovery_reminder_visible = False
            self._phase_2_2_present_streak = 0
            return
        if self._latest_info_2_2_phase.state is InfoRecoveryPageState.PRESENT:
            self._phase_2_2_present_streak += 1
            if self._phase_2_2_present_streak >= INFO_2_2_REMINDER_CONFIRMATION_COUNT:
                self._recovery_reminder_visible = True
            return
        self._phase_2_2_present_streak = 0

    def _observe_returned_info_boss_recovery(self, frame: Frame, viewport: ContentViewport) -> None:
        """Fill only a missing Boss after returned-info page evidence has already passed."""

        if (
            self._session is None
            or self._session.boss_id is not None
            or self._recovery_state is not _RecoveryReminderState.OPEN
            or self._latest_returned_info is None
            or self._latest_returned_info.state is not InfoRecoveryPageState.PRESENT
        ):
            self._latest_returned_info_boss = None
            self._reset_pending_returned_info_boss_recognition()
            return
        observation = observe_jp_mumu_returned_info_boss(frame, viewport, self._info_1_2_references)
        self._latest_returned_info_boss = observation
        candidate = observation.reliable_id
        if candidate is None:
            self._reset_pending_returned_info_boss_recognition()
            return
        if candidate == self._returned_info_boss_pending_id:
            self._returned_info_boss_pending_count += 1
        else:
            self._returned_info_boss_pending_id = candidate
            self._returned_info_boss_pending_count = 1
        if self._returned_info_boss_pending_count < RETURNED_INFO_BOSS_CONFIRMATION_COUNT:
            return
        update = apply_boss_capture(
            self._session,
            candidate,
            self._catalog,
            source=BossCaptureSource.RETURNED_INFO_VISUAL,
        )
        self._session, self._update_status = update.session, update.status

    def _observe_returned_info_enemy_recovery(
        self, frame: Frame, viewport: ContentViewport
    ) -> None:
        """Fill only a complete missing Enemy set from a confirmed returned-info page."""

        if (
            self._session is None
            or self._session.enemy_type_ids is not None
            or self._recovery_state is not _RecoveryReminderState.OPEN
            or self._latest_returned_info is None
            or self._latest_returned_info.state is not InfoRecoveryPageState.PRESENT
        ):
            self._latest_returned_info_enemy = None
            self._returned_info_enemy_pending_candidate = None
            self._returned_info_enemy_pending_count = 0
            return
        known_enemy_ids = frozenset(
            enemy.enemy_category_id for enemy in self._catalog.enemy_categories
        )
        observation = observe_jp_mumu_returned_info_enemy(
            frame, viewport, self._info_1_2_references, known_enemy_ids
        )
        self._latest_returned_info_enemy = observation
        candidate = observation.complete_candidate
        if candidate is None:
            self._returned_info_enemy_pending_candidate = None
            self._returned_info_enemy_pending_count = 0
            return
        if candidate == self._returned_info_enemy_pending_candidate:
            self._returned_info_enemy_pending_count += 1
        else:
            self._returned_info_enemy_pending_candidate = candidate
            self._returned_info_enemy_pending_count = 1
        if self._returned_info_enemy_pending_count < RETURNED_INFO_ENEMY_CONFIRMATION_COUNT:
            return
        update = apply_enemy_type_capture(
            self._session,
            candidate,
            self._catalog,
            source=EnemyTypeCaptureSource.RETURNED_INFO_VISUAL,
        )
        self._session, self._update_status = update.session, update.status

    def _observe_returned_info_major_recovery(
        self, frame: Frame, viewport: ContentViewport
    ) -> None:
        """Fill only missing supported Major/Core Ban evidence from returned INFO."""

        self._returned_info_major_capture_attempted = False
        if (
            self._major_covenant_observer is None
            or self._session is None
            or self._session.major_covenant_ban is not None
            or self._latest_returned_info is None
            or self._latest_returned_info.state is not InfoRecoveryPageState.PRESENT
        ):
            self._latest_returned_info_major = None
            self._reset_pending_returned_info_major_recognition()
            return
        difficulty_id = (
            self._session.captured_difficulty.difficulty_id
            if self._session.captured_difficulty is not None
            else None
        )
        if not supports_returned_major_covenant_ban(difficulty_id):
            self._latest_returned_info_major = None
            self._reset_pending_returned_info_major_recognition()
            return
        self._returned_info_major_capture_attempted = True
        observation = self._major_covenant_observer.observe_returned_info(
            frame,
            viewport,
            returned_info_state=self._latest_returned_info.state,
            difficulty_id=difficulty_id,
        )
        self._latest_returned_info_major = observation
        if not observation.complete_reliable:
            self._reset_pending_returned_info_major_recognition()
            return
        candidate = observation.disabled_major_covenant_ids
        if candidate == self._returned_info_major_pending_disabled_ids:
            self._returned_info_major_pending_count += 1
        else:
            self._returned_info_major_pending_disabled_ids = candidate
            self._returned_info_major_pending_count = 1
        if self._returned_info_major_pending_count < 2:
            return
        snapshot = _major_snapshot_from_observation(observation)
        update = apply_major_covenant_ban_capture(self._session, snapshot)
        self._session, self._update_status = update.session, update.status
        self._reset_pending_returned_info_major_recognition()

    def _apply_difficulty_recovery(self, observation: DifficultyRecoveryObservation) -> None:
        assert self._session is not None
        if observation.source is DifficultyRecoverySource.POST_START_VISUAL:
            pending_id = self._post_start_difficulty_pending_id
            pending_count = self._post_start_difficulty_pending_count
        else:
            pending_id = self._operation_splash_difficulty_pending_id
            pending_count = self._operation_splash_difficulty_pending_count
        candidate = (
            observation.candidate_id
            if observation.source is DifficultyRecoverySource.POST_START_VISUAL
            else observation.reliable_id
        )
        if candidate is None:
            pending_id, pending_count = None, 0
        elif candidate == pending_id:
            pending_count += 1
        else:
            pending_id, pending_count = candidate, 1
        if observation.source is DifficultyRecoverySource.POST_START_VISUAL:
            self._post_start_difficulty_pending_id = pending_id
            self._post_start_difficulty_pending_count = pending_count
        else:
            self._operation_splash_difficulty_pending_id = pending_id
            self._operation_splash_difficulty_pending_count = pending_count
        if pending_count < 2 or candidate is None:
            return
        source = (
            DifficultyCaptureSource.POST_START_VISUAL
            if observation.source is DifficultyRecoverySource.POST_START_VISUAL
            else DifficultyCaptureSource.OPERATION_SPLASH_VISUAL
        )
        update = apply_visual_difficulty_capture(self._session, candidate, self._catalog, source)
        self._session, self._update_status = update.session, update.status

    def _apply_current_info_facts(self, observation: Info12Observation) -> None:
        """Apply one genuine INFO observation only after its target session is known."""

        assert self._session is not None
        difficulty = observation.difficulty_candidate_id
        if difficulty == self._difficulty_pending_id and difficulty is not None:
            self._difficulty_pending_count += 1
        elif difficulty is not None:
            self._difficulty_pending_id, self._difficulty_pending_count = difficulty, 1
        else:
            self._difficulty_pending_id, self._difficulty_pending_count = None, 0
        if self._difficulty_pending_count >= 2:
            update = apply_info_difficulty_capture(self._session, difficulty, self._catalog)
            self._session, self._update_status = update.session, update.status
        candidate = observation.reliable_boss_id
        if candidate is None:
            self._boss_pending_id = None
            self._boss_pending_count = 0
        elif candidate == self._boss_pending_id:
            self._boss_pending_count += 1
        else:
            self._boss_pending_id, self._boss_pending_count = candidate, 1
        if self._boss_pending_count >= 3:
            update = apply_boss_capture(self._session, candidate, self._catalog)
            self._session, self._update_status = update.session, update.status
        candidates = observation.reliable_enemy_ids
        if (
            not self._debug_skip_initial_enemy_capture
            and candidates
            and observation.enemy_slot_layout is not EnemySlotLayout.UNRESOLVED
            and all(item is not None for item in candidates)
        ):
            update = apply_enemy_type_capture(self._session, candidates, self._catalog)  # type: ignore[arg-type]
            self._session, self._update_status = update.session, update.status

    def _observe_initial_info_major_ban(
        self,
        frame: Frame,
        viewport: ContentViewport,
        info: Info12Observation,
    ) -> None:
        """Observe Major/Core Ban only in the current canonical initial-INFO lifecycle phase."""

        if (
            self._major_covenant_observer is None
            or self._session is None
            or self._info_lifecycle_state is not _InfoEncounterLifecycleState.INITIAL_INFO
        ):
            self._latest_major_covenant_ban = None
            self._reset_pending_major_covenant_ban()
            return
        if self._session.major_covenant_ban is not None:
            self._reset_pending_major_covenant_ban()
            return
        difficulty_id = (
            self._session.captured_difficulty.difficulty_id
            if self._session.captured_difficulty is not None
            else None
        )
        observation = self._major_covenant_observer.observe(
            frame,
            viewport,
            info_state=info.state,
            difficulty_id=difficulty_id,
        )
        self._latest_major_covenant_ban = observation
        self.apply_major_covenant_ban_observation(observation)

    def apply_major_covenant_ban_observation(
        self, observation: MajorCovenantBanObservation
    ) -> None:
        """Debounce one complete Major/Core-only Ban set without granting full Ban completion."""

        if self._session is None or not observation.complete_reliable:
            self._reset_pending_major_covenant_ban()
            return
        candidate = observation.disabled_major_covenant_ids
        if candidate == self._major_ban_pending_disabled_ids:
            self._major_ban_pending_count += 1
        else:
            self._major_ban_pending_disabled_ids = candidate
            self._major_ban_pending_count = 1
        if self._major_ban_pending_count < 2:
            return
        snapshot = _major_snapshot_from_observation(observation)
        update = apply_major_covenant_ban_capture(self._session, snapshot)
        self._session, self._update_status = update.session, update.status

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

    def stop(self) -> LiveEncounterPreviewSnapshot:
        self._status = LiveEncounterPreviewStatus.STOPPED
        return self.snapshot()

    def diagnostic_json(self) -> str:
        """Return compact local-only feedback data with no player identity or frame payload."""

        snapshot = self.snapshot()
        info = self._latest_info_1_2
        major_ban = self._latest_major_covenant_ban
        confirmed_banned: tuple[ConfirmedBannedOperator, ...] = ()
        confirmed_banned_rows: tuple[ConfirmedBannedOperatorRow, ...] = ()
        if (
            snapshot.session is not None
            and snapshot.session.major_covenant_ban is not None
            and self._confirmed_banned_operator_catalog is not None
        ):
            known_states = {
                item.covenant_id: item.state
                for item in snapshot.session.major_covenant_ban.covenant_states
            }
            confirmed_banned = resolve_confirmed_banned_operators(
                known_states, self._confirmed_banned_operator_catalog
            )
            confirmed_banned_rows = project_confirmed_banned_operator_rows(
                known_states, self._confirmed_banned_operator_catalog
            )
        return json.dumps(
            {
                "build": LIVE_ENCOUNTER_PREVIEW_BUILD,
                "profile": JP_MUMU_INFO_1_2_PROFILE_ID,
                "monitor_index": snapshot.monitor_index,
                "capture_source_type": snapshot.capture_source_type.value,
                "capture_source_id": snapshot.capture_source_id,
                "capture_source_reference": snapshot.capture_source_reference,
                "capture_dimensions": snapshot.frame_size,
                "capture_status": snapshot.status.value,
                "capture_reason": snapshot.reason,
                "operation_ocr_enabled": False,
                "info_reference_status": (
                    "available" if self._info_1_2_references is not None else "unavailable"
                ),
                "info_reference_error_category": (
                    self._info_reference_failure.category
                    if self._info_reference_failure is not None
                    else None
                ),
                "info_reference_error_reason": (
                    self._info_reference_failure.reason
                    if self._info_reference_failure is not None
                    else None
                ),
                "difficulty_recovery_reference_status": (
                    "available"
                    if self._difficulty_recovery_references is not None
                    else "unavailable"
                ),
                "difficulty_recovery_reference_error": (
                    self._difficulty_recovery_failure.reason
                    if self._difficulty_recovery_failure is not None
                    else None
                ),
                "info_recovery_page_reference_status": (
                    "available"
                    if self._info_recovery_page_references is not None
                    else "unavailable"
                ),
                "info_recovery_page_reference_error": (
                    self._info_recovery_page_failure.reason
                    if self._info_recovery_page_failure is not None
                    else None
                ),
                "major_ban_reference_status": (
                    "available" if self._major_covenant_observer is not None else "unavailable"
                ),
                "major_ban_reference_error": (
                    self._major_covenant_reference_failure.reason
                    if self._major_covenant_reference_failure is not None
                    else None
                ),
                "confirmed_banned_operator_catalog_status": (
                    "available"
                    if self._confirmed_banned_operator_catalog is not None
                    else "unavailable"
                ),
                "confirmed_banned_operator_catalog_error": (
                    self._confirmed_banned_operator_catalog_failure.reason
                    if self._confirmed_banned_operator_catalog_failure is not None
                    else None
                ),
                "confirmed_banned_operator_count": len(confirmed_banned),
                "confirmed_banned_operator_rows": tuple(
                    {"covenant_id": row.covenant_id, "operator_count": len(row.operators)}
                    for row in confirmed_banned_rows
                ),
                "encounter_id": snapshot.session.encounter_id
                if snapshot.session is not None
                else None,
                "info_lifecycle_state": self._info_lifecycle_state.value,
                "info_departure_count": self._info_departure_count,
                "info_reentry_count": self._info_reentry_count,
                "next_initial_info_candidate": (
                    self._latest_next_initial_info_candidate.is_candidate
                    if self._latest_next_initial_info_candidate is not None
                    else None
                ),
                "next_initial_info_candidate_reason": (
                    self._latest_next_initial_info_candidate.reason
                    if self._latest_next_initial_info_candidate is not None
                    else None
                ),
                "next_initial_info_trace_present_frames": (
                    self._next_initial_info_trace.present_frames
                    if self._next_initial_info_trace is not None
                    else 0
                ),
                "next_initial_info_trace_candidate_frames": (
                    self._next_initial_info_trace.candidate_frames
                    if self._next_initial_info_trace is not None
                    else 0
                ),
                "next_initial_info_trace_max_candidate_streak": (
                    self._next_initial_info_trace.max_candidate_streak
                    if self._next_initial_info_trace is not None
                    else 0
                ),
                "next_initial_info_trace_last_present_frame_id": (
                    self._next_initial_info_trace.last_present_frame_id
                    if self._next_initial_info_trace is not None
                    else None
                ),
                "next_initial_info_trace_last_candidate_frame_id": (
                    self._next_initial_info_trace.last_candidate_frame_id
                    if self._next_initial_info_trace is not None
                    else None
                ),
                "next_initial_info_trace_last_rejection_reason": (
                    self._next_initial_info_trace.last_rejection_reason
                    if self._next_initial_info_trace is not None
                    else None
                ),
                "next_initial_info_trace_rejection_counts": (
                    dict(self._next_initial_info_trace.rejection_counts)
                    if self._next_initial_info_trace is not None
                    else {}
                ),
                "next_initial_info_trace_last_present": _next_initial_info_trace_present_summary(
                    self._next_initial_info_trace.last_present
                    if self._next_initial_info_trace is not None
                    else None
                ),
                "last_next_encounter_promotion_trace": _last_next_encounter_promotion_trace_summary(
                    self._last_next_encounter_promotion_trace
                ),
                "next_encounter_promotion_reason": self._next_encounter_promotion_reason,
                "info_state": info.state.value if info is not None else None,
                "info_frame_id": info.frame_id if info is not None else None,
                "info_anchor_score": info.anchor_score if info is not None else None,
                "info_third_slot_foreground_ratio": (
                    info.third_slot_foreground_ratio if info is not None else None
                ),
                "info_enemy_slot_layout": (
                    info.enemy_slot_layout.value if info is not None else None
                ),
                "info_difficulty_candidate_id": info.difficulty_candidate_id
                if info is not None
                else None,
                "info_reliable_boss_id": info.reliable_boss_id if info is not None else None,
                "info_reliable_enemy_ids": info.reliable_enemy_ids if info is not None else (),
                "major_ban_supported": major_ban.supported if major_ban is not None else False,
                "major_ban_state": major_ban.state.value if major_ban is not None else None,
                "major_ban_reason": major_ban.reason if major_ban is not None else None,
                "major_row_visible": major_ban.row_visible if major_ban is not None else False,
                "major_candidate_count": major_ban.candidate_count if major_ban is not None else 0,
                "major_identity_observations": (
                    tuple(_major_identity_summary(item) for item in major_ban.identity_observations)
                    if major_ban is not None
                    else ()
                ),
                "disabled_major_covenant_ids": (
                    major_ban.disabled_major_covenant_ids if major_ban is not None else ()
                ),
                "major_structural_validity": (
                    major_ban.structural_valid if major_ban is not None else False
                ),
                "major_pending_count": self._major_ban_pending_count,
                "major_ban_captured": (
                    snapshot.session.major_covenant_ban is not None
                    if snapshot.session is not None
                    else False
                ),
                "major_siracusa_disabled_directly_retained_validated": False,
                "debug_skip_initial_enemy_capture": self._debug_skip_initial_enemy_capture,
                "initial_enemy_capture_suppressed": (
                    self._debug_skip_initial_enemy_capture
                    and info is not None
                    and bool(info.reliable_enemy_ids)
                ),
                "info_difficulty_top_two": _top_two_summary(info.difficulty_ranking)
                if info is not None
                else None,
                "info_boss_top_two": _top_two_summary(info.boss_ranking)
                if info is not None
                else None,
                "info_enemy_top_two": (
                    tuple(_top_two_summary(ranking) for ranking in info.enemy_rankings)
                    if info is not None
                    else ()
                ),
                "pending_difficulty_id": self._difficulty_pending_id,
                "pending_difficulty_count": self._difficulty_pending_count,
                "post_start_difficulty_state": (
                    self._latest_post_start_difficulty.state.value
                    if self._latest_post_start_difficulty is not None
                    else None
                ),
                "post_start_difficulty_candidate_id": (
                    self._latest_post_start_difficulty.candidate_id
                    if self._latest_post_start_difficulty is not None
                    else None
                ),
                "post_start_difficulty_top_two": (
                    _top_two_summary(self._latest_post_start_difficulty.ranking)
                    if self._latest_post_start_difficulty is not None
                    else None
                ),
                "post_start_difficulty_pending_count": self._post_start_difficulty_pending_count,
                "operation_splash_difficulty_state": (
                    self._latest_operation_splash_difficulty.state.value
                    if self._latest_operation_splash_difficulty is not None
                    else None
                ),
                "operation_splash_difficulty_reliable_id": (
                    self._latest_operation_splash_difficulty.reliable_id
                    if self._latest_operation_splash_difficulty is not None
                    else None
                ),
                "operation_splash_difficulty_top_two": (
                    _top_two_summary(self._latest_operation_splash_difficulty.ranking)
                    if self._latest_operation_splash_difficulty is not None
                    else None
                ),
                "operation_splash_difficulty_pending_count": (
                    self._operation_splash_difficulty_pending_count
                ),
                "info_2_2_phase_state": (
                    self._latest_info_2_2_phase.state.value
                    if self._latest_info_2_2_phase is not None
                    else None
                ),
                "info_2_2_phase_score": (
                    self._latest_info_2_2_phase.score
                    if self._latest_info_2_2_phase is not None
                    else None
                ),
                "info_2_2_phase_present_streak": self._phase_2_2_present_streak,
                "returned_info_state": (
                    self._latest_returned_info.state.value
                    if self._latest_returned_info is not None
                    else None
                ),
                "returned_info_score": (
                    self._latest_returned_info.score
                    if self._latest_returned_info is not None
                    else None
                ),
                "returned_info_boss_state": (
                    self._latest_returned_info_boss.state.value
                    if self._latest_returned_info_boss is not None
                    else None
                ),
                "returned_info_boss_reliable_id": (
                    self._latest_returned_info_boss.reliable_id
                    if self._latest_returned_info_boss is not None
                    else None
                ),
                "returned_info_boss_top_two": (
                    _top_two_summary(self._latest_returned_info_boss.ranking)
                    if self._latest_returned_info_boss is not None
                    else None
                ),
                "returned_info_boss_pending_count": self._returned_info_boss_pending_count,
                "returned_info_enemy_state": (
                    self._latest_returned_info_enemy.state.value
                    if self._latest_returned_info_enemy is not None
                    else None
                ),
                "returned_info_enemy_slot_layout": (
                    self._latest_returned_info_enemy.slot_layout.value
                    if self._latest_returned_info_enemy is not None
                    else None
                ),
                "returned_info_enemy_third_slot_foreground_ratio": (
                    self._latest_returned_info_enemy.third_slot_foreground_ratio
                    if self._latest_returned_info_enemy is not None
                    else None
                ),
                "returned_info_enemy_slot_top_two": (
                    tuple(
                        _top_two_summary(ranking)
                        for ranking in self._latest_returned_info_enemy.slot_rankings
                    )
                    if self._latest_returned_info_enemy is not None
                    else ()
                ),
                "returned_info_enemy_reliable_ids": (
                    self._latest_returned_info_enemy.reliable_ids
                    if self._latest_returned_info_enemy is not None
                    else ()
                ),
                "returned_info_enemy_complete_candidate": (
                    self._latest_returned_info_enemy.complete_candidate
                    if self._latest_returned_info_enemy is not None
                    else None
                ),
                "returned_info_enemy_pending_candidate": (
                    self._returned_info_enemy_pending_candidate
                ),
                "returned_info_enemy_pending_count": self._returned_info_enemy_pending_count,
                "returned_info_major_state": (
                    self._latest_returned_info_major.state.value
                    if self._latest_returned_info_major is not None
                    else None
                ),
                "returned_info_major_candidate_count": (
                    self._latest_returned_info_major.candidate_count
                    if self._latest_returned_info_major is not None
                    else 0
                ),
                "returned_info_major_identity_observations": (
                    tuple(
                        _major_identity_summary(item)
                        for item in self._latest_returned_info_major.identity_observations
                    )
                    if self._latest_returned_info_major is not None
                    else ()
                ),
                "returned_info_major_disabled_ids": (
                    self._latest_returned_info_major.disabled_major_covenant_ids
                    if self._latest_returned_info_major is not None
                    else ()
                ),
                "returned_info_major_structural_validity": (
                    self._latest_returned_info_major.structural_valid
                    if self._latest_returned_info_major is not None
                    else False
                ),
                "returned_info_major_pending_count": self._returned_info_major_pending_count,
                "returned_info_major_capture_attempted": (
                    self._returned_info_major_capture_attempted
                ),
                "recovery_state": self._recovery_state.value,
                "recovery_reminder_visible": self._recovery_reminder_visible,
                "missing_recoverable_items": self._missing_recoverable_items(),
                "pending_boss_id": self._boss_pending_id,
                "pending_boss_count": self._boss_pending_count,
                "operation_state": (
                    snapshot.operation_state.value if snapshot.operation_state is not None else None
                ),
                "map_id": snapshot.latest_map_id,
                "boss_id": snapshot.session.boss_id if snapshot.session is not None else None,
                "boss_capture_source": (
                    snapshot.session.boss_capture_source.value
                    if snapshot.session is not None
                    and snapshot.session.boss_capture_source is not None
                    else None
                ),
                "enemy_type_ids": snapshot.session.enemy_type_ids
                if snapshot.session is not None
                else None,
                "enemy_type_capture_source": (
                    snapshot.session.enemy_type_capture_source.value
                    if snapshot.session is not None
                    and snapshot.session.enemy_type_capture_source is not None
                    else None
                ),
                "difficulty_id": snapshot.latest_difficulty_id,
                "difficulty_capture_source": (
                    snapshot.session.captured_difficulty.capture_source.value
                    if snapshot.session is not None
                    and snapshot.session.captured_difficulty is not None
                    else None
                ),
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
    *,
    reconnect_interval_seconds: float = 1.0,
    retry_sleep: Callable[[float], None] = sleep,
) -> None:
    """Run one live source, reconnecting only after transient MuMu IPC failures.

    A healthy source iterator owns one native IPC connection and yields many frames.  This loop
    deliberately creates a replacement iterator only after that connection has failed, keeping
    the caller-owned encounter controller (and its sticky captured facts) intact while retrying.
    """

    if reconnect_interval_seconds <= 0:
        raise ValueError("reconnect_interval_seconds must be positive")
    try:
        while controller.snapshot().status is not LiveEncounterPreviewStatus.STOPPED:
            try:
                for frame in source.frames():
                    on_snapshot(asyncio.run(controller.process_frame(frame)))
                    if controller.snapshot().status is LiveEncounterPreviewStatus.STOPPED:
                        break
                break
            except MuMuIpcCaptureError as error:
                on_snapshot(controller.capture_failed(str(error)))
                if not _wait_for_mumu_reconnect(
                    controller,
                    reconnect_interval_seconds,
                    retry_sleep,
                ):
                    break
            except WindowsDisplayCaptureError as error:
                on_snapshot(controller.capture_failed(str(error)))
                break
    finally:
        if controller.snapshot().status not in {
            LiveEncounterPreviewStatus.CAPTURE_UNAVAILABLE,
            LiveEncounterPreviewStatus.STOPPED,
        }:
            on_snapshot(controller.stop())


def _wait_for_mumu_reconnect(
    controller: LiveEncounterPreviewController,
    interval_seconds: float,
    retry_sleep: Callable[[float], None],
) -> bool:
    """Wait in short slices so preview shutdown interrupts an unavailable-MuMu retry."""

    remaining = interval_seconds
    while remaining > 0:
        if controller.snapshot().status is LiveEncounterPreviewStatus.STOPPED:
            return False
        wait_seconds = min(0.1, remaining)
        retry_sleep(wait_seconds)
        remaining -= wait_seconds
    return controller.snapshot().status is not LiveEncounterPreviewStatus.STOPPED


def write_live_preview_diagnostic(controller: LiveEncounterPreviewController, path: Path) -> None:
    """Write only explicit local diagnostic metadata; never capture or upload gameplay."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(controller.diagnostic_json() + "\n", encoding="utf-8")


def run_windows_live_encounter_preview(
    *,
    monitor_index: int | None,
    locale_id: str,
    always_on_top: bool,
    diagnostic_path: Path | None = None,
    source: FrameSource | None = None,
    debug_skip_initial_enemy_capture: bool = False,
) -> None:
    """Run the optional Windows/Tk shell with an explicit source-neutral capture source."""

    from sentry_copilot.encounter.desktop import LiveEncounterPreviewWindow

    if source is None:
        if monitor_index is None:
            raise ValueError("monitor_index is required for Windows physical-display capture")
        source = WindowsDisplayFrameSource(monitor_index=monitor_index, target_fps=2.0)
    catalog = JP_MUMU_ENCOUNTER_MAP_CATALOG
    references: Info12ReferencePack | None = None
    reference_failure: InfoReferenceLoadFailure | None = None
    try:
        from sentry_copilot.encounter.info_1_2_catalog import (
            load_default_private_info_1_2_resources,
        )

        catalog, references = load_default_private_info_1_2_resources(catalog)
    except (FileNotFoundError, OSError, ValueError) as error:
        reference_failure = _sanitize_reference_load_failure(error)
    difficulty_recovery_references: DifficultyRecoveryReferencePack | None = None
    difficulty_recovery_failure: InfoReferenceLoadFailure | None = None
    try:
        from sentry_copilot.encounter.difficulty_recovery_catalog import (
            load_default_private_difficulty_recovery_references,
        )

        difficulty_recovery_references = load_default_private_difficulty_recovery_references()
    except (FileNotFoundError, OSError, ValueError) as error:
        difficulty_recovery_failure = _sanitize_reference_load_failure(error)
    info_recovery_page_references: InfoRecoveryPageReferencePack | None = None
    info_recovery_page_failure: InfoReferenceLoadFailure | None = None
    try:
        from sentry_copilot.encounter.info_recovery_pages_catalog import (
            load_default_private_info_recovery_page_references,
        )

        info_recovery_page_references = load_default_private_info_recovery_page_references()
    except (FileNotFoundError, OSError, ValueError) as error:
        info_recovery_page_failure = _sanitize_reference_load_failure(error)
    major_covenant_catalog: MajorCovenantPresentationCatalog | None = None
    major_covenant_references: MajorCovenantReferencePack | None = None
    confirmed_banned_operator_catalog: ConfirmedBannedOperatorCatalog | None = None
    confirmed_banned_operator_catalog_failure: InfoReferenceLoadFailure | None = None
    major_covenant_reference_failure: InfoReferenceLoadFailure | None = None
    try:
        from sentry_copilot.encounter.major_covenant_ban_catalog import (
            load_default_private_major_covenant_ban_resources,
        )

        major_covenant_catalog, major_covenant_references = (
            load_default_private_major_covenant_ban_resources()
        )
    except (FileNotFoundError, OSError, ValueError) as error:
        major_covenant_reference_failure = _sanitize_reference_load_failure(error)
    try:
        from sentry_copilot.encounter.confirmed_banned_operators import (
            load_default_confirmed_banned_operator_catalog,
        )

        confirmed_banned_operator_catalog = load_default_confirmed_banned_operator_catalog()
    except (FileNotFoundError, OSError, ValueError) as error:
        # The partial derived rows are optional presentation only; Major capture remains usable.
        confirmed_banned_operator_catalog = None
        confirmed_banned_operator_catalog_failure = _sanitize_catalog_load_failure(error)
    controller = LiveEncounterPreviewController(
        catalog=catalog,
        locale_id=locale_id,
        monitor_index=monitor_index,
        capture_source_metadata=source.metadata,
        info_1_2_references=references,
        info_reference_failure=reference_failure,
        difficulty_recovery_references=difficulty_recovery_references,
        difficulty_recovery_failure=difficulty_recovery_failure,
        info_recovery_page_references=info_recovery_page_references,
        info_recovery_page_failure=info_recovery_page_failure,
        major_covenant_references=major_covenant_references,
        major_covenant_catalog=major_covenant_catalog,
        confirmed_banned_operator_catalog=confirmed_banned_operator_catalog,
        confirmed_banned_operator_catalog_failure=confirmed_banned_operator_catalog_failure,
        major_covenant_reference_failure=major_covenant_reference_failure,
        debug_skip_initial_enemy_capture=debug_skip_initial_enemy_capture,
    )
    initial = controller.snapshot()

    def close() -> None:
        _stop_frame_source(source)
        controller.stop()

    window = LiveEncounterPreviewWindow(
        initial,
        on_locale=controller.set_locale,
        diagnostic_text=controller.diagnostic_json,
        on_close=close,
        always_on_top=always_on_top,
    )
    worker = Thread(
        target=run_live_encounter_loop,
        args=(source, controller, window.publish),
        daemon=True,
        name="sentry-live-encounter-capture",
    )
    worker.start()
    window.run()
    worker.join(timeout=1.0)
    if diagnostic_path is not None:
        write_live_preview_diagnostic(controller, diagnostic_path)


def _stop_frame_source(source: FrameSource) -> None:
    """Request shutdown when a concrete live source exposes the optional stop seam."""

    stop = getattr(source, "stop", None)
    if callable(stop):
        stop()


def _status_message(status: LiveEncounterPreviewStatus, locale_id: str) -> str:
    messages = {
        "zh_CN": {
            LiveEncounterPreviewStatus.WAITING_FOR_SUPPORTED_FRAME: (
                "等待受支持的 1920×1080 游戏画面"
            ),
            LiveEncounterPreviewStatus.WAITING_FOR_INITIAL_INFO: (
                "已连接游戏画面，等待本局初始情報確認 1/2"
            ),
            LiveEncounterPreviewStatus.INFO_REFERENCES_UNAVAILABLE: "无法加载情報確認 1/2 识别参考",
            LiveEncounterPreviewStatus.RUNNING: "正在监测本局游戏画面",
            LiveEncounterPreviewStatus.CAPTURE_UNAVAILABLE: "无法获取游戏画面",
            LiveEncounterPreviewStatus.ENDED_WAITING_NEXT: "上一局已结束，等待下一局",
            LiveEncounterPreviewStatus.STOPPED: "已停止",
        },
        "en": {
            LiveEncounterPreviewStatus.WAITING_FOR_SUPPORTED_FRAME: (
                "Waiting for a supported 1920×1080 game frame"
            ),
            LiveEncounterPreviewStatus.WAITING_FOR_INITIAL_INFO: (
                "Game capture connected. Waiting for the initial INFO 1/2."
            ),
            LiveEncounterPreviewStatus.INFO_REFERENCES_UNAVAILABLE: (
                "INFO 1/2 recognition references could not be loaded"
            ),
            LiveEncounterPreviewStatus.RUNNING: "Monitoring the current encounter",
            LiveEncounterPreviewStatus.CAPTURE_UNAVAILABLE: "Game capture is unavailable",
            LiveEncounterPreviewStatus.ENDED_WAITING_NEXT: (
                "Previous encounter ended. Waiting for the next encounter."
            ),
            LiveEncounterPreviewStatus.STOPPED: "Stopped",
        },
    }
    return messages.get(locale_id, messages["en"])[status]


def _recovery_reminder_text(locale_id: str, missing_items: tuple[str, ...]) -> str:
    """Present the controller-derived recovery reminder without adding a Tk-owned flag."""

    labels = {
        "zh_CN": {"boss": "Boss", "enemy_types": "敌人类型"},
        "en": {"boss": "Boss", "enemy_types": "Enemy Types"},
    }
    if locale_id == "zh_CN":
        prefix = "⚠ 本局情报尚未完整，请点击游戏左上角「情報確認」重新扫描"
        missing = "待补充："
    else:
        prefix = "⚠ Encounter intel is incomplete. Open “INFO” in the game to scan again."
        missing = "Still needed: "
    values = [
        labels.get(locale_id, labels["en"])[item]
        for item in missing_items
        if item not in {"major_covenants", "additional_covenants"}
    ]
    covenant_label = _covenant_missing_label(
        major_missing="major_covenants" in missing_items,
        additional_missing="additional_covenants" in missing_items,
        locale_id=locale_id,
    )
    if covenant_label is not None:
        values.append(covenant_label)
    joined = " / ".join(values)
    return f"{prefix}\n{missing}{joined}" if joined else prefix


def _covenant_missing_label(
    major_missing: bool,
    additional_missing: bool,
    locale_id: str,
) -> str | None:
    """Present a future-proof Covenant recovery area without changing capture semantics."""

    labels = {
        "zh_CN": {
            (True, True): "盟约未识别",
            (True, False): "主盟约未识别",
            (False, True): "追加盟约未识别",
        },
        "en": {
            (True, True): "Covenants not captured",
            (True, False): "Major Covenants not captured",
            (False, True): "Additional Covenants not captured",
        },
    }
    return labels.get(locale_id, labels["en"]).get((major_missing, additional_missing))


def _next_initial_info_trace_present_summary(
    trace: _NextInitialInfoTracePresent | None,
) -> dict[str, object] | None:
    """Return the one retained normalized INFO-present record for local diagnostics."""

    if trace is None:
        return None
    return {
        "frame_id": trace.frame_id,
        "anchor_score": trace.anchor_score,
        "enemy_slot_layout": trace.enemy_slot_layout,
        "enemy_ranking_slot_count": trace.enemy_ranking_slot_count,
        "difficulty_candidate_id": trace.difficulty_candidate_id,
        "reliable_boss_id": trace.reliable_boss_id,
        "reliable_enemy_ids": trace.reliable_enemy_ids,
        "returned_info_state_same_frame": trace.returned_info_state_same_frame,
        "info_2_2_state_same_frame": trace.info_2_2_state_same_frame,
        "classified_candidate": trace.classified_candidate,
        "classification_reason": trace.classification_reason,
    }


def _last_next_encounter_promotion_trace_summary(
    trace: _LastNextEncounterPromotionTrace | None,
) -> dict[str, object] | None:
    if trace is None:
        return None
    return {
        "max_candidate_streak": trace.max_candidate_streak,
        "frame_id": trace.frame_id,
        "promotion_reason": trace.promotion_reason,
    }


def _top_two_summary(
    ranking: tuple[RankedVisualCandidate, ...],
) -> dict[str, float | str | None] | None:
    if not ranking:
        return None
    first = ranking[0]
    second = ranking[1] if len(ranking) > 1 else None
    return {
        "top_id": first.identity_id,
        "top_score": first.score,
        "second_id": second.identity_id if second is not None else None,
        "second_score": second.score if second is not None else None,
        "margin": first.score - second.score if second is not None else None,
    }


def _major_snapshot_from_observation(
    observation: MajorCovenantBanObservation,
) -> MajorCovenantBanSnapshot:
    """Materialize only an already complete reliable Major observation for capture services."""

    if not observation.complete_reliable:
        raise ValueError("Major Covenant snapshot requires a complete reliable observation")
    return MajorCovenantBanSnapshot(
        covenant_states=tuple(
            MajorCovenantBanStateEntry(
                covenant_id=covenant_id,
                state=item.state,
            )
            for covenant_id, item in sorted(
                (
                    (item.covenant_id, item)
                    for item in observation.identity_observations
                    if item.covenant_id is not None
                ),
                key=lambda item: item[0],
            )
        )
    )


def _major_identity_summary(
    item: MajorCovenantIdentityObservation,
) -> dict[str, float | int | str | None]:
    """Keep Major glyph diagnostics compact while preserving the calibrated score evidence."""

    return {
        "candidate_index_for_extraction_only": item.candidate_index_for_extraction_only,
        "covenant_id": item.covenant_id,
        "top_1_score": item.top_1_score,
        "margin": item.margin,
        "state": item.state.value,
        "state_saturation_median": item.state_saturation_median,
    }


def _sanitize_reference_load_failure(
    error: FileNotFoundError | OSError | ValueError,
) -> InfoReferenceLoadFailure:
    if isinstance(error, FileNotFoundError):
        filename = _asset_basename(error.filename)
        detail = (
            f"required reference asset unavailable: {filename}"
            if filename
            else "required reference asset unavailable"
        )
        return InfoReferenceLoadFailure("missing_file", detail)
    if isinstance(error, OSError):
        filename = _asset_basename(error.filename)
        detail = (
            f"reference asset could not be read: {filename}"
            if filename
            else "reference asset could not be read"
        )
        return InfoReferenceLoadFailure("io_error", detail)
    return InfoReferenceLoadFailure("invalid_resources", "INFO reference resources are invalid")


def _sanitize_catalog_load_failure(
    error: FileNotFoundError | OSError | ValueError,
) -> InfoReferenceLoadFailure:
    """Report optional public-catalog failures without exposing a local path."""

    if isinstance(error, FileNotFoundError):
        filename = _asset_basename(error.filename)
        detail = (
            f"required catalog unavailable: {filename}"
            if filename
            else "required catalog unavailable"
        )
        return InfoReferenceLoadFailure("missing_file", detail)
    if isinstance(error, OSError):
        filename = _asset_basename(error.filename)
        detail = (
            f"catalog could not be read: {filename}" if filename else "catalog could not be read"
        )
        return InfoReferenceLoadFailure("io_error", detail)
    return InfoReferenceLoadFailure(
        "invalid_resources", "confirmed-banned-operator catalog is invalid"
    )


def _asset_basename(filename: str | None) -> str | None:
    """Extract one safe basename from Windows, POSIX, or mixed-separator paths."""

    if filename is None:
        return None
    components = tuple(part for part in filename.replace("\\", "/").split("/") if part)
    return components[-1] if components else None


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
