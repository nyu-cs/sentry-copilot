"""Explicit local visual-reference catalogs and ambiguity-aware template matching."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from sentry_copilot.capture.frame_source import Frame, FrameSourceType, ImageArray
from sentry_copilot.domain.identifiers import RulesetRevisionId, StrategyId
from sentry_copilot.domain.strategy import StrategyCatalog
from sentry_copilot.image_io import ImageDecodeError, load_bgr_image
from sentry_copilot.vision.template_matching import TemplateImage, match_template
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi

_NORMALIZED_ID = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SUPPORTED_IMAGE_SUFFIXES = frozenset({".bmp", ".jpeg", ".jpg", ".png", ".webp"})


class VisualCatalogKind(StrEnum):
    """The finite visual identity set represented by a catalog."""

    STRATEGY = "strategy"
    AVATAR = "avatar"


class VisualReferenceKind(StrEnum):
    """Declared render context; metadata only, never a visual identity."""

    CANONICAL_WEB = "canonical_web"
    SELECTION_RENDER = "selection_render"
    SELECTION_GRID_RENDER = "selection_grid_render"
    BATTLE_RENDER = "battle_render"
    OTHER_EXPLICIT_RENDER_CONTEXT = "other_explicit_render_context"


class VisualMatchStatus(StrEnum):
    """Outcome of matching one explicit query image against loaded references."""

    MATCHED = "matched"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"
    NO_COMPARABLE_REFERENCE = "no_comparable_reference"


class VisualCatalogLoadError(ValueError):
    """An explicit catalog path could not be parsed or its declared assets cannot be loaded."""


class VisualCatalogValidationError(ValueError):
    """A visual catalog violates its local cross-record or asset invariants."""


class _VisualReferenceAssetSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    asset_id: str
    asset_reference: str
    sha256: str | None = None
    provenance: str | None = None

    @field_validator("asset_id")
    @classmethod
    def asset_id_must_be_normalized(cls, value: str) -> str:
        if not _NORMALIZED_ID.fullmatch(value):
            raise ValueError("asset_id must be a normalized identifier")
        return value

    @field_validator("asset_reference")
    @classmethod
    def asset_reference_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("asset_reference must not be blank")
        return value

    @field_validator("sha256")
    @classmethod
    def sha256_must_be_lowercase_hex(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256.fullmatch(value):
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        return value

    @field_validator("provenance")
    @classmethod
    def provenance_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("provenance must not be blank when supplied")
        return value


class _StrategyVisualReferenceSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: StrategyId
    asset_id: str
    ruleset_revision_id: RulesetRevisionId | None = None
    reference_kind: VisualReferenceKind = VisualReferenceKind.OTHER_EXPLICIT_RENDER_CONTEXT

    @field_validator("asset_id")
    @classmethod
    def asset_id_must_be_normalized(cls, value: str) -> str:
        if not _NORMALIZED_ID.fullmatch(value):
            raise ValueError("asset_id must be a normalized identifier")
        return value


class _AvatarVisualReferenceSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    avatar_id: str
    asset_id: str
    reference_kind: VisualReferenceKind = VisualReferenceKind.OTHER_EXPLICIT_RENDER_CONTEXT

    @field_validator("avatar_id", "asset_id")
    @classmethod
    def ids_must_be_normalized(cls, value: str) -> str:
        if not _NORMALIZED_ID.fullmatch(value):
            raise ValueError("avatar_id and asset_id must be normalized identifiers")
        return value


class _VisualCatalogDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = Field(ge=1)
    kind: VisualCatalogKind
    assets: tuple[_VisualReferenceAssetSpec, ...] = Field(min_length=1)
    strategy_references: tuple[_StrategyVisualReferenceSpec, ...] = ()
    avatar_references: tuple[_AvatarVisualReferenceSpec, ...] = ()

    def model_post_init(self, __context: Any) -> None:
        if self.kind is VisualCatalogKind.STRATEGY:
            if not self.strategy_references or self.avatar_references:
                raise ValueError("strategy catalog requires only strategy_references")
        elif not self.avatar_references or self.strategy_references:
            raise ValueError("avatar catalog requires only avatar_references")


@dataclass(frozen=True)
class VisualReferenceAsset:
    """An immutable decoded BGR asset declared by one explicit catalog entry."""

    asset_id: str
    asset_reference: str
    path: Path
    sha256: str
    width: int
    height: int
    provenance: str | None
    image: ImageArray

    def __post_init__(self) -> None:
        if not _NORMALIZED_ID.fullmatch(self.asset_id):
            raise ValueError("asset_id must be a normalized identifier")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("asset dimensions must be positive")
        if not _SHA256.fullmatch(self.sha256):
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        if self.image.dtype != np.uint8 or self.image.ndim != 3 or self.image.shape[2] != 3:
            raise ValueError("visual reference image must be a uint8 BGR image")
        if self.image.shape[:2] != (self.height, self.width):
            raise ValueError("asset dimensions must match the decoded image")
        image = np.array(self.image, dtype=np.uint8, copy=True)
        image.setflags(write=False)
        object.__setattr__(self, "image", image)


@dataclass(frozen=True)
class StrategyVisualReference:
    """One strategy ID linked to one asset and render context, without occupancy semantics."""

    strategy_id: str
    asset_id: str
    ruleset_revision_id: str | None = None
    reference_kind: VisualReferenceKind = VisualReferenceKind.OTHER_EXPLICIT_RENDER_CONTEXT


@dataclass(frozen=True)
class AvatarVisualReference:
    """One repeatable avatar visual identity linked to one loaded asset."""

    avatar_id: str
    asset_id: str
    reference_kind: VisualReferenceKind = VisualReferenceKind.OTHER_EXPLICIT_RENDER_CONTEXT


type VisualReference = StrategyVisualReference | AvatarVisualReference


@dataclass(frozen=True)
class VisualReferenceCatalog:
    """A validated finite, immutable, caller-loaded visual identity catalog."""

    kind: VisualCatalogKind
    catalog_path: Path
    schema_version: int
    fingerprint: str
    assets: tuple[VisualReferenceAsset, ...]
    references: tuple[VisualReference, ...]

    def asset(self, asset_id: str) -> VisualReferenceAsset:
        for asset in self.assets:
            if asset.asset_id == asset_id:
                return asset
        raise KeyError(f"unknown visual asset_id: {asset_id}")


@dataclass(frozen=True)
class VisualMatchCandidate:
    """One ranked template result with both visual identity and reference provenance."""

    identity_id: str
    asset_id: str
    asset_sha256: str
    score: float
    matched: bool
    pixel_bounds: PixelRoi | None


@dataclass(frozen=True)
class VisualMatchResult:
    """Immutable ambiguity-aware result for one explicit catalog/query match."""

    kind: VisualCatalogKind
    catalog_path: Path
    catalog_schema_version: int
    catalog_fingerprint: str
    query_path: Path
    query_sha256: str
    query_width: int
    query_height: int
    minimum_score: float
    ambiguity_margin: float
    status: VisualMatchStatus
    candidates: tuple[VisualMatchCandidate, ...]
    selected_candidate: VisualMatchCandidate | None


def load_visual_reference_catalog(
    path: str | Path,
    *,
    strategy_catalog: StrategyCatalog | None = None,
) -> VisualReferenceCatalog:
    """Load only explicitly declared local assets; never discover directories or other files."""

    catalog_path = Path(path)
    raw = _load_yaml_mapping(catalog_path)
    try:
        document = _VisualCatalogDocument.model_validate(raw)
    except ValidationError as error:
        raise VisualCatalogLoadError(f"invalid visual catalog: {catalog_path}") from error
    assets = tuple(_load_asset(spec, catalog_path.parent) for spec in document.assets)
    references = _references_for(document)
    _validate_catalog(document.kind, assets, references, strategy_catalog)
    return VisualReferenceCatalog(
        kind=document.kind,
        catalog_path=catalog_path,
        schema_version=document.schema_version,
        fingerprint=_catalog_fingerprint(document),
        assets=assets,
        references=references,
    )


def match_visual_catalog(
    *,
    catalog: VisualReferenceCatalog,
    query_path: str | Path,
    minimum_score: float = 0.9,
    ambiguity_margin: float = 0.02,
) -> VisualMatchResult:
    """Rank explicit query/template pairs and return unresolved or ambiguous outcomes safely."""

    if not -1.0 <= minimum_score <= 1.0:
        raise ValueError("minimum_score must be between -1.0 and 1.0")
    if ambiguity_margin < 0:
        raise ValueError("ambiguity_margin must be non-negative")
    path = Path(query_path)
    query = _load_bgr_image(path, "query image")
    query_hash = _file_sha256(path)
    height, width = query.shape[:2]
    frame = Frame(
        frame_id="visual-catalog-query:000000",
        frame_index=0,
        processed_at=datetime.now(UTC),
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="visual-catalog-query",
        width=width,
        height=height,
        image=query,
        source_reference=str(path),
    )
    viewport = ContentViewport.full_frame(frame)
    candidates: list[VisualMatchCandidate] = []
    for reference in catalog.references:
        asset = catalog.asset(reference.asset_id)
        if asset.width > width or asset.height > height:
            continue
        template = TemplateImage(asset.asset_id, asset.image)
        result = match_template(
            frame,
            viewport,
            PixelRoi(x=0, y=0, width=width, height=height),
            template,
            threshold=minimum_score,
        )
        candidates.append(
            VisualMatchCandidate(
                identity_id=_identity_id(reference),
                asset_id=asset.asset_id,
                asset_sha256=asset.sha256,
                score=result.score,
                matched=result.matched,
                pixel_bounds=result.match_bounds,
            )
        )
    ranked = tuple(
        sorted(candidates, key=lambda item: (-item.score, item.identity_id, item.asset_id))
    )
    status, selected = _resolve_match(ranked, minimum_score, ambiguity_margin)
    return VisualMatchResult(
        kind=catalog.kind,
        catalog_path=catalog.catalog_path,
        catalog_schema_version=catalog.schema_version,
        catalog_fingerprint=catalog.fingerprint,
        query_path=path,
        query_sha256=query_hash,
        query_width=width,
        query_height=height,
        minimum_score=minimum_score,
        ambiguity_margin=ambiguity_margin,
        status=status,
        candidates=ranked,
        selected_candidate=selected,
    )


def write_visual_match_report(result: VisualMatchResult, output_directory: str | Path) -> Path:
    """Write a structured caller-owned JSON report without creating diagnostic interpretation."""

    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    output_path = destination / "visual-catalog-match.json"
    output_path.write_text(
        json.dumps(_match_json(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def _load_asset(spec: _VisualReferenceAssetSpec, root: Path) -> VisualReferenceAsset:
    path = _resolve_asset_path(root, spec.asset_reference)
    image = _load_bgr_image(path, f"visual asset {spec.asset_id}")
    digest = _file_sha256(path)
    if spec.sha256 is not None and spec.sha256 != digest:
        raise VisualCatalogValidationError(f"asset hash mismatch: {spec.asset_id}")
    height, width = image.shape[:2]
    return VisualReferenceAsset(
        asset_id=spec.asset_id,
        asset_reference=spec.asset_reference,
        path=path,
        sha256=digest,
        width=width,
        height=height,
        provenance=spec.provenance,
        image=image,
    )


def _resolve_asset_path(root: Path, reference: str) -> Path:
    posix = PurePosixPath(reference)
    windows = PureWindowsPath(reference)
    if posix.is_absolute() or windows.is_absolute() or ".." in posix.parts or "\\" in reference:
        raise VisualCatalogValidationError("asset_reference must be a safe relative path")
    path = root.joinpath(*posix.parts).resolve()
    if not path.is_relative_to(root.resolve()):
        raise VisualCatalogValidationError("asset_reference escapes the catalog root")
    if path.suffix.lower() not in _SUPPORTED_IMAGE_SUFFIXES:
        raise VisualCatalogValidationError(f"unsupported visual asset format: {path.suffix}")
    if not path.is_file():
        raise VisualCatalogValidationError(f"declared visual asset does not exist: {reference}")
    return path


def _load_bgr_image(path: Path, label: str) -> ImageArray:
    try:
        return load_bgr_image(path)
    except ImageDecodeError as error:
        raise VisualCatalogValidationError(f"cannot decode {label}: {path}") from error


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _references_for(document: _VisualCatalogDocument) -> tuple[VisualReference, ...]:
    if document.kind is VisualCatalogKind.STRATEGY:
        return tuple(
            StrategyVisualReference(
                strategy_id=reference.strategy_id,
                asset_id=reference.asset_id,
                ruleset_revision_id=reference.ruleset_revision_id,
                reference_kind=reference.reference_kind,
            )
            for reference in document.strategy_references
        )
    return tuple(
        AvatarVisualReference(
            avatar_id=reference.avatar_id,
            asset_id=reference.asset_id,
            reference_kind=reference.reference_kind,
        )
        for reference in document.avatar_references
    )


def _validate_catalog(
    kind: VisualCatalogKind,
    assets: tuple[VisualReferenceAsset, ...],
    references: tuple[VisualReference, ...],
    strategy_catalog: StrategyCatalog | None,
) -> None:
    asset_ids = tuple(asset.asset_id for asset in assets)
    if len(asset_ids) != len(set(asset_ids)):
        raise VisualCatalogValidationError("duplicate visual asset_id")
    known_assets = set(asset_ids)
    keys = tuple((_identity_id(reference), reference.asset_id) for reference in references)
    if len(keys) != len(set(keys)):
        raise VisualCatalogValidationError("duplicate visual identity/asset reference")
    for reference in references:
        if reference.asset_id not in known_assets:
            raise VisualCatalogValidationError(
                f"visual reference declares unknown asset_id: {reference.asset_id}"
            )
    if kind is VisualCatalogKind.STRATEGY and strategy_catalog is not None:
        known_strategy_ids = {item.strategy_id for item in strategy_catalog.strategy_identities}
        valid_profile_keys = {
            (profile.ruleset_revision_id, profile.strategy_id)
            for profile in strategy_catalog.profiles
        }
        for reference in references:
            assert isinstance(reference, StrategyVisualReference)
            if reference.strategy_id not in known_strategy_ids:
                raise VisualCatalogValidationError(
                    f"visual reference has unknown strategy_id: {reference.strategy_id}"
                )
            if (
                reference.ruleset_revision_id is not None
                and (reference.ruleset_revision_id, reference.strategy_id) not in valid_profile_keys
            ):
                raise VisualCatalogValidationError(
                    "visual reference has no matching strategy profile for its revision"
                )


def _resolve_match(
    candidates: tuple[VisualMatchCandidate, ...],
    minimum_score: float,
    ambiguity_margin: float,
) -> tuple[VisualMatchStatus, VisualMatchCandidate | None]:
    if not candidates:
        return VisualMatchStatus.NO_COMPARABLE_REFERENCE, None
    top = candidates[0]
    if top.score < minimum_score:
        return VisualMatchStatus.UNRESOLVED, None
    best_per_identity: list[VisualMatchCandidate] = []
    seen_identities: set[str] = set()
    for candidate in candidates:
        if candidate.identity_id not in seen_identities:
            best_per_identity.append(candidate)
            seen_identities.add(candidate.identity_id)
    if len(best_per_identity) > 1 and top.score - best_per_identity[1].score <= ambiguity_margin:
        return VisualMatchStatus.AMBIGUOUS, None
    return VisualMatchStatus.MATCHED, top


def _identity_id(reference: VisualReference) -> str:
    return (
        reference.strategy_id
        if isinstance(reference, StrategyVisualReference)
        else reference.avatar_id
    )


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw: object = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as error:
        raise VisualCatalogLoadError(f"unable to read visual catalog: {path}") from error
    if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
        raise VisualCatalogLoadError("visual catalog root must be a string-keyed mapping")
    return raw



def _catalog_fingerprint(document: _VisualCatalogDocument) -> str:
    """Hash declared schema metadata deterministically; asset bytes remain separately hashed."""

    canonical = document.model_dump(mode="json")
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _match_json(result: VisualMatchResult) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": result.kind.value,
        "catalog_path": str(result.catalog_path),
        "catalog_schema_version": result.catalog_schema_version,
        "catalog_fingerprint": result.catalog_fingerprint,
        "query": {
            "path": str(result.query_path),
            "sha256": result.query_sha256,
            "width": result.query_width,
            "height": result.query_height,
        },
        "minimum_score": result.minimum_score,
        "ambiguity_margin": result.ambiguity_margin,
        "status": result.status.value,
        "selected_candidate": _candidate_json(result.selected_candidate)
        if result.selected_candidate is not None
        else None,
        "candidates": [_candidate_json(candidate) for candidate in result.candidates],
    }


def _candidate_json(candidate: VisualMatchCandidate | None) -> dict[str, object] | None:
    if candidate is None:
        return None
    return {
        "identity_id": candidate.identity_id,
        "asset_id": candidate.asset_id,
        "asset_sha256": candidate.asset_sha256,
        "score": candidate.score,
        "matched": candidate.matched,
        "pixel_bounds": {
            "x": candidate.pixel_bounds.x,
            "y": candidate.pixel_bounds.y,
            "width": candidate.pixel_bounds.width,
            "height": candidate.pixel_bounds.height,
        }
        if candidate.pixel_bounds is not None
        else None,
    }
