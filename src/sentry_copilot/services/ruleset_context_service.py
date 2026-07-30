from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Never

from pydantic import ValidationError

from sentry_copilot.catalogs.repository import (
    CatalogLookupError,
    StrategyCatalogRepository,
)
from sentry_copilot.domain.commands import (
    CorrectSessionRulesetRevision,
    RulesetContextCommand,
    SelectSessionRulesetContext,
)
from sentry_copilot.domain.events import (
    SessionRulesetContextSelected,
    SessionRulesetRevisionCorrected,
)
from sentry_copilot.domain.identifiers import (
    CatalogVersion,
    LocaleId,
    RulesetId,
    RulesetRevisionId,
)
from sentry_copilot.domain.models import SessionState
from sentry_copilot.domain.reducer import InvalidObservationError, reduce_session


class RulesetContextErrorCode(StrEnum):
    SESSION_MISMATCH = "session_mismatch"
    RULESET_CONTEXT_ALREADY_SELECTED = "ruleset_context_already_selected"
    RULESET_CONTEXT_NOT_SELECTED = "ruleset_context_not_selected"
    RULESET_REVISION_UNKNOWN = "ruleset_revision_unknown"
    RULESET_MISMATCH = "ruleset_mismatch"
    RULESET_REVISION_MISMATCH = "ruleset_revision_mismatch"
    LOCALE_MISMATCH = "locale_mismatch"
    CATALOG_MISMATCH = "catalog_mismatch"
    CATALOG_VERSION_MISMATCH = "catalog_version_mismatch"
    IDENTICAL_CONTEXT = "identical_context"
    INVALID_REVISION_FOR_RULESET = "invalid_revision_for_ruleset"
    INVALID_SELECTION_TIME = "invalid_selection_time"
    INVALID_CONTEXT = "invalid_context"


class RulesetContextCommandError(ValueError):
    """Typed rejection for a ruleset-context command or mismatch check."""

    def __init__(self, code: RulesetContextErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class RulesetContextService:
    """Validate context commands against catalogs, then apply accepted facts."""

    def __init__(self, catalog_repository: StrategyCatalogRepository) -> None:
        self._catalog_repository = catalog_repository

    def select(
        self,
        state: SessionState,
        command: SelectSessionRulesetContext,
    ) -> SessionState:
        """Perform initial manual or replay-metadata revision selection."""

        self._require_session(state, command)
        current = state.ruleset_context
        if current is not None and current.ruleset_revision_id is not None:
            self._reject(
                RulesetContextErrorCode.RULESET_CONTEXT_ALREADY_SELECTED,
                "a concrete ruleset context already exists; use explicit correction",
            )
        if current is not None:
            self._require_ruleset(current.ruleset_id, command.ruleset_id)
            self._require_locale(current.locale_id, command.locale_id)
            self._require_selection_time(current.selected_at, command.selected_at)

        self._require_snapshot_ruleset(state, command.ruleset_id)
        self._validate_catalog_target(command)
        event = SessionRulesetContextSelected(
            session_id=command.session_id,
            ruleset_id=command.ruleset_id,
            ruleset_revision_id=command.ruleset_revision_id,
            locale_id=command.locale_id,
            catalog_version=command.catalog_version,
            selection_method=command.selection_method,
            selected_at=command.selected_at,
            selection_evidence=command.selection_evidence,
            reason=command.reason,
        )
        return self._apply_accepted_event(state, event)

    def correct(
        self,
        state: SessionState,
        command: CorrectSessionRulesetRevision,
    ) -> SessionState:
        """Perform one explicit revision or catalog-version correction."""

        self._require_session(state, command)
        current = state.ruleset_context
        if current is None:
            self._reject(
                RulesetContextErrorCode.RULESET_CONTEXT_NOT_SELECTED,
                "ruleset context must be selected before correction",
            )
        if current.ruleset_revision_id is None:
            self._reject(
                RulesetContextErrorCode.RULESET_REVISION_UNKNOWN,
                "an unknown revision must use initial selection, not correction",
            )

        self._require_ruleset(current.ruleset_id, command.ruleset_id)
        self._require_locale(current.locale_id, command.locale_id)
        if (
            current.ruleset_revision_id == command.ruleset_revision_id
            and current.catalog_version == command.catalog_version
        ):
            self._reject(
                RulesetContextErrorCode.IDENTICAL_CONTEXT,
                "the requested ruleset context is identical to the current context",
            )
        self._require_selection_time(current.selected_at, command.selected_at)
        self._validate_catalog_target(command)

        event = SessionRulesetRevisionCorrected(
            session_id=command.session_id,
            ruleset_id=command.ruleset_id,
            ruleset_revision_id=command.ruleset_revision_id,
            locale_id=command.locale_id,
            catalog_version=command.catalog_version,
            selected_at=command.selected_at,
            selection_evidence=command.selection_evidence,
            reason=command.reason,
        )
        return self._apply_accepted_event(state, event)

    def validate_current_context(
        self,
        state: SessionState,
        *,
        ruleset_id: RulesetId,
        ruleset_revision_id: RulesetRevisionId,
        locale_id: LocaleId,
        catalog_version: CatalogVersion,
    ) -> None:
        """Reject mismatched evidence without changing or auto-switching context."""

        current = state.ruleset_context
        if current is None:
            self._reject(
                RulesetContextErrorCode.RULESET_CONTEXT_NOT_SELECTED,
                "session has no current ruleset context",
            )
        if current.ruleset_revision_id is None:
            self._reject(
                RulesetContextErrorCode.RULESET_REVISION_UNKNOWN,
                "session revision is still unknown",
            )
        self._require_ruleset(current.ruleset_id, ruleset_id)
        self._require_locale(current.locale_id, locale_id)
        if current.ruleset_revision_id != ruleset_revision_id:
            self._reject(
                RulesetContextErrorCode.RULESET_REVISION_MISMATCH,
                "observed revision does not match the current session revision",
            )
        if current.catalog_version != catalog_version:
            self._reject(
                RulesetContextErrorCode.CATALOG_VERSION_MISMATCH,
                "observed catalog version does not match the current session catalog",
            )

    def _validate_catalog_target(self, command: RulesetContextCommand) -> None:
        try:
            self._catalog_repository.catalog(command.catalog_version)
        except CatalogLookupError:
            self._reject(
                RulesetContextErrorCode.CATALOG_VERSION_MISMATCH,
                f"unknown catalog version: {command.catalog_version}",
            )

        try:
            ruleset = self._catalog_repository.get_ruleset(
                catalog_version=command.catalog_version,
                ruleset_id=command.ruleset_id,
            )
        except CatalogLookupError:
            self._reject(
                RulesetContextErrorCode.CATALOG_MISMATCH,
                "catalog does not contain the requested ruleset",
            )

        try:
            revision = self._catalog_repository.get_revision(
                catalog_version=command.catalog_version,
                ruleset_revision_id=command.ruleset_revision_id,
            )
        except CatalogLookupError:
            self._reject(
                RulesetContextErrorCode.RULESET_REVISION_UNKNOWN,
                "catalog does not contain the requested revision",
            )

        if (
            revision.ruleset_id != command.ruleset_id
            or revision.ruleset_revision_id not in ruleset.revision_ids
        ):
            self._reject(
                RulesetContextErrorCode.INVALID_REVISION_FOR_RULESET,
                "requested revision does not belong to the requested ruleset",
            )
        if command.locale_id not in ruleset.supported_locales:
            self._reject(
                RulesetContextErrorCode.CATALOG_MISMATCH,
                "catalog does not support the requested locale for this ruleset",
            )

    @staticmethod
    def _require_session(
        state: SessionState,
        command: RulesetContextCommand,
    ) -> None:
        if state.session_id != command.session_id:
            RulesetContextService._reject(
                RulesetContextErrorCode.SESSION_MISMATCH,
                "command session_id does not match SessionState",
            )

    @staticmethod
    def _require_snapshot_ruleset(
        state: SessionState,
        ruleset_id: RulesetId,
    ) -> None:
        if (
            state.strategy_selection is not None
            and state.strategy_selection.ruleset_id != ruleset_id
        ):
            RulesetContextService._reject(
                RulesetContextErrorCode.RULESET_MISMATCH,
                "prebattle snapshot ruleset does not match the selected context",
            )

    @staticmethod
    def _require_ruleset(
        current_ruleset_id: RulesetId,
        requested_ruleset_id: RulesetId,
    ) -> None:
        if current_ruleset_id != requested_ruleset_id:
            RulesetContextService._reject(
                RulesetContextErrorCode.RULESET_MISMATCH,
                "ruleset correction cannot change ruleset_id",
            )

    @staticmethod
    def _require_locale(
        current_locale_id: LocaleId,
        requested_locale_id: LocaleId,
    ) -> None:
        if current_locale_id != requested_locale_id:
            RulesetContextService._reject(
                RulesetContextErrorCode.LOCALE_MISMATCH,
                "ruleset revision correction cannot change locale_id",
            )

    @staticmethod
    def _require_selection_time(
        current_selected_at: datetime,
        selected_at: datetime,
    ) -> None:
        if selected_at < current_selected_at:
            RulesetContextService._reject(
                RulesetContextErrorCode.INVALID_SELECTION_TIME,
                "new selection time cannot precede the current selection time",
            )

    @staticmethod
    def _apply_accepted_event(
        state: SessionState,
        event: SessionRulesetContextSelected | SessionRulesetRevisionCorrected,
    ) -> SessionState:
        try:
            candidate = reduce_session(state, event)
            return SessionState.model_validate(candidate.model_dump())
        except (InvalidObservationError, ValidationError) as exc:
            raise RulesetContextCommandError(
                RulesetContextErrorCode.INVALID_CONTEXT,
                "accepted ruleset context event failed whole-state validation",
            ) from exc

    @staticmethod
    def _reject(code: RulesetContextErrorCode, message: str) -> Never:
        raise RulesetContextCommandError(code, message)
