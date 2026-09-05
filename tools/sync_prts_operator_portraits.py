"""Boundedly verify PRTS Elite-0 operator portraits and cache image bytes privately.

This developer tool never uses seasonal tier, Covenant membership, or Ban data as portrait
identity.  It reads the current roster only to establish requested coverage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import cv2
import numpy as np
import yaml

from sentry_copilot.catalogs.operator_portrait_sources import OperatorPortraitSourceCatalog

_API_URL = "https://prts.wiki/api.php"
_USER_AGENT = "SentryCopilot/0.1 (private portrait source validation; contact: local developer)"
_REQUEST_DELAY_SECONDS = 0.12
_MAX_ATTEMPTS = 3
_API_TITLE_BATCH_SIZE = 20


@dataclass(frozen=True)
class _ResolvedSource:
    current_operator_id: str
    name_zh_CN: str
    default_file_title: str
    verified_file_title: str
    source_page: str
    image_url: str
    default_mapping: bool
    override_note: str | None


def main() -> None:
    arguments = _arguments()
    roster = _ordinary_roster(arguments.operator_catalog)
    cache_root = arguments.cache_root
    cache_root.mkdir(parents=True, exist_ok=True)
    print(f"resolving {len(roster)} exact PRTS portrait titles", flush=True)
    resolved, failures = _resolve_sources(roster)
    source_collisions = _source_collisions(resolved)
    if source_collisions:
        failures.extend(
            {
                "name_zh_CN": ", ".join(names),
                "reason": f"multiple operators resolved to one PRTS file: {file_title}",
            }
            for file_title, names in source_collisions.items()
        )
    records: list[dict[str, Any]] = []
    for index, item in enumerate(resolved, start=1):
        try:
            records.append(_cache_record(item, cache_root))
            print(f"cached {index}/{len(resolved)}: {item.name_zh_CN}", flush=True)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            failures.append(
                {
                    "current_operator_id": item.current_operator_id,
                    "name_zh_CN": item.name_zh_CN,
                    "reason": str(error),
                }
            )
    audit = _audit_payload(roster, records, failures, source_collisions)
    arguments.audit_report.parent.mkdir(parents=True, exist_ok=True)
    arguments.audit_report.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if failures:
        raise SystemExit(f"portrait coverage incomplete; see {arguments.audit_report}")
    _write_public_manifest(records, arguments.manifest)
    print(f"verified {len(records)}/{len(roster)} portraits")


def _arguments() -> argparse.Namespace:
    repository_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--operator-catalog",
        type=Path,
        default=repository_root / "data/catalogs/covenant_latter/operator_catalog.yaml",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=repository_root / "data/catalogs/operator_portrait_sources.yaml",
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=repository_root / "data/private/assets/operator_portraits/prts",
    )
    parser.add_argument(
        "--audit-report",
        type=Path,
        default=repository_root
        / "data/private/assets/operator_portraits/prts/portrait_coverage_audit.json",
    )
    return parser.parse_args()


def _ordinary_roster(path: Path) -> tuple[tuple[str, str], ...]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("operators"), list):
        raise ValueError("operator catalog is missing records")
    roster = tuple(
        (str(item["operator_id"]), str(item["name_zh_CN"]))
        for item in raw["operators"]
        if isinstance(item, dict) and item.get("special_entry") is not True
    )
    if len(roster) != 112 or len({name for _, name in roster}) != len(roster):
        raise ValueError("current ordinary operator roster must contain 112 uniquely named records")
    return roster


def _resolve_sources(
    roster: tuple[tuple[str, str], ...],
) -> tuple[list[_ResolvedSource], list[dict[str, str]]]:
    resolved: list[_ResolvedSource] = []
    failures: list[dict[str, str]] = []
    defaults = tuple(f"头像_{name}.png" for _, name in roster)
    default_pages = _query_file_batches(defaults)
    for operator_id, name in roster:
        default = f"头像_{name}.png"
        page = next(
            (
                candidate
                for candidate in default_pages
                if _matches_expected_identity(candidate[0], name)
            ),
            None,
        )
        default_mapping = page is not None
        if page is None:
            page = _search_exact_portrait(name)
        if page is None:
            failures.append({"name_zh_CN": name, "reason": "PRTS base portrait file not found"})
            continue
        file_title, source_page, image_url = page
        if not _matches_expected_identity(file_title, name):
            failures.append(
                {"name_zh_CN": name, "reason": "PRTS file title does not match expected identity"}
            )
            continue
        override_note = None if default_mapping else "PRTS exact-name file search override"
        resolved.append(
            _ResolvedSource(
                current_operator_id=operator_id,
                name_zh_CN=name,
                default_file_title=default,
                verified_file_title=file_title,
                source_page=source_page,
                image_url=image_url,
                default_mapping=default_mapping,
                override_note=override_note,
            )
        )
    return resolved, failures


def _source_collisions(resolved: list[_ResolvedSource]) -> dict[str, list[str]]:
    """Report accidental source reuse; never accept an unreviewed identity collision."""

    names_by_file_title: dict[str, list[str]] = {}
    for source in resolved:
        names_by_file_title.setdefault(source.verified_file_title, []).append(source.name_zh_CN)
    return {
        file_title: names
        for file_title, names in names_by_file_title.items()
        if len(names) > 1
    }


def _query_file(file_title: str) -> tuple[str, str, str] | None:
    pages = _query_file_batches((file_title,))
    return pages[0] if pages else None


def _query_file_batches(file_titles: tuple[str, ...]) -> tuple[tuple[str, str, str], ...]:
    pages: list[tuple[str, str, str]] = []
    for start in range(0, len(file_titles), _API_TITLE_BATCH_SIZE):
        pages.extend(_query_files(file_titles[start : start + _API_TITLE_BATCH_SIZE]))
    return tuple(pages)


def _query_files(file_titles: tuple[str, ...]) -> tuple[tuple[str, str, str], ...]:
    payload = _request_json(
        {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "titles": "|".join(f"File:{file_title}" for file_title in file_titles),
            "prop": "imageinfo",
            "iiprop": "url|mime|size",
        }
    )
    raw_pages = payload.get("query", {}).get("pages", [])
    if not isinstance(raw_pages, list):
        return ()
    verified: list[tuple[str, str, str]] = []
    for page in raw_pages:
        if not isinstance(page, dict) or page.get("missing") is True:
            continue
        info = page.get("imageinfo")
        if not isinstance(info, list) or len(info) != 1 or not isinstance(info[0], dict):
            continue
        image_info = info[0]
        if image_info.get("mime") != "image/png":
            continue
        title = page.get("title")
        source_page = image_info.get("descriptionurl")
        image_url = image_info.get("url")
        if all(isinstance(item, str) and item for item in (title, source_page, image_url)):
            verified.append((_file_title_from_api_title(title), source_page, image_url))
    return tuple(verified)


def _search_exact_portrait(name: str) -> tuple[str, str, str] | None:
    payload = _request_json(
        {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "list": "search",
            "srnamespace": "6",
            "srlimit": "10",
            "srsearch": f"头像 {name}",
        }
    )
    results = payload.get("query", {}).get("search", [])
    if not isinstance(results, list):
        return None
    for item in results:
        title = item.get("title") if isinstance(item, dict) else None
        if isinstance(title, str):
            file_title = _file_title_from_api_title(title)
            if _matches_expected_identity(file_title, name):
                return _query_file(file_title)
    return None


def _request_json(params: dict[str, str]) -> dict[str, Any]:
    url = f"{_API_URL}?{urlencode(params)}"
    for attempt in range(_MAX_ATTEMPTS):
        try:
            payload = json.loads(_curl_get(url, "application/json").decode("utf-8"))
            if isinstance(payload, dict):
                time.sleep(_REQUEST_DELAY_SECONDS)
                return payload
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError, json.JSONDecodeError):
            if attempt + 1 == _MAX_ATTEMPTS:
                raise
            time.sleep(1.0 * (attempt + 1))
    raise ValueError("PRTS API response was not a mapping")


def _cache_record(source: _ResolvedSource, cache_root: Path) -> dict[str, Any]:
    portrait_key = f"prts:{source.name_zh_CN}"
    path = OperatorPortraitSourceCatalog.private_cache_path(cache_root, portrait_key)
    if path.is_file():
        payload = path.read_bytes()
    else:
        payload = _download_png(source.image_url)
        if path.exists() and path.read_bytes() != payload:
            raise ValueError(f"refusing to overwrite different portrait cache file: {path.name}")
        temporary = path.with_suffix(".part")
        temporary.write_bytes(payload)
        temporary.replace(path)
    width, height, channels = _validate_png(payload)
    return {
        "current_operator_id": source.current_operator_id,
        "portrait_key": portrait_key,
        "name_zh_CN": source.name_zh_CN,
        "default_attempted_file_title": source.default_file_title,
        "verified_file_title": source.verified_file_title,
        "resolution": "default" if source.default_mapping else "override",
        "explicit_override_note": source.override_note,
        "source_page": source.source_page,
        "validation_status": "verified",
        "width": width,
        "height": height,
        "channels": channels,
        "byte_size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "local_cache_path": str(path),
    }


def _download_png(url: str) -> bytes:
    for attempt in range(_MAX_ATTEMPTS):
        try:
            payload = _curl_get(url, "image/png")
            if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("PRTS response was not a PNG image")
            time.sleep(_REQUEST_DELAY_SECONDS)
            return payload
        except (OSError, subprocess.SubprocessError):
            if attempt + 1 == _MAX_ATTEMPTS:
                raise
            time.sleep(1.0 * (attempt + 1))
    raise ValueError("PRTS image response was unavailable")


def _curl_get(url: str, accept: str) -> bytes:
    """Use the Windows-provided transport that reaches PRTS on this workstation."""

    completed = subprocess.run(
        [
            "curl.exe",
            "--fail",
            "--silent",
            "--show-error",
            "--max-time",
            "30",
            "--header",
            f"User-Agent: {_USER_AGENT}",
            "--header",
            f"Accept: {accept}",
            url,
        ],
        check=True,
        capture_output=True,
    )
    return completed.stdout


def _validate_png(payload: bytes) -> tuple[int, int, int]:
    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim not in {2, 3} or image.shape[0] <= 0 or image.shape[1] <= 0:
        raise ValueError("cached PRTS portrait could not be decoded")
    channels = 1 if image.ndim == 2 else int(image.shape[2])
    return int(image.shape[1]), int(image.shape[0]), channels


def _write_public_manifest(records: list[dict[str, Any]], path: Path) -> None:
    payload = {
        "schema_version": "0.1",
        "catalog_kind": "operator_portrait_sources",
        "portrait_sources": [
            {
                "portrait_key": item["portrait_key"],
                "name_zh_CN": item["name_zh_CN"],
                "provider": "PRTS",
                "file_title": item["verified_file_title"],
                "source_page": item["source_page"],
                "base_variant": "elite_0",
                **(
                    {"explicit_override_note": item["explicit_override_note"]}
                    if item["explicit_override_note"] is not None
                    else {}
                ),
            }
            for item in records
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _audit_payload(
    roster: tuple[tuple[str, str], ...],
    records: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    source_collisions: dict[str, list[str]],
) -> dict[str, Any]:
    hashes: dict[str, list[str]] = {}
    for item in records:
        hashes.setdefault(str(item["sha256"]), []).append(str(item["name_zh_CN"]))
    return {
        "schema_version": "0.1",
        "required_ordinary_roster_count": len(roster),
        "verified_portrait_count": len(records),
        "default_name_hits": sum(item["resolution"] == "default" for item in records),
        "explicit_override_count": sum(item["resolution"] == "override" for item in records),
        "failure_count": len(failures),
        "failures": failures,
        "source_file_collisions": source_collisions,
        "duplicate_sha256_groups": {
            digest: names for digest, names in hashes.items() if len(names) > 1
        },
        "unexpected_dimension_records": [
            item for item in records if (item["width"], item["height"]) != (180, 180)
        ],
        "total_cached_bytes": sum(int(item["byte_size"]) for item in records),
        "records": records,
    }


def _file_title_from_api_title(title: str) -> str:
    for prefix in ("File:", "文件:"):
        if title.startswith(prefix):
            return title.removeprefix(prefix)
    return title


def _matches_expected_identity(file_title: str, name: str) -> bool:
    normalized = file_title.replace("_", "").replace(" ", "")
    return normalized == f"头像{name}.png"


if __name__ == "__main__":
    main()
