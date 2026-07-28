from __future__ import annotations

from pathlib import Path

import yaml

from .models import MapDefinition


def load_map_definition(path: str | Path) -> MapDefinition:
    with Path(path).open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    return MapDefinition.model_validate(raw)


class MapRepository:
    def __init__(self, maps: dict[str, MapDefinition]) -> None:
        self._maps = maps

    @classmethod
    def from_directory(cls, directory: str | Path) -> MapRepository:
        maps: dict[str, MapDefinition] = {}
        for path in sorted(Path(directory).glob("*.yaml")):
            map_definition = load_map_definition(path)
            if map_definition.map_id in maps:
                raise ValueError(f"duplicate map_id: {map_definition.map_id}")
            maps[map_definition.map_id] = map_definition
        return cls(maps)

    def get(self, map_id: str) -> MapDefinition:
        try:
            return self._maps[map_id]
        except KeyError as exc:
            raise KeyError(f"unknown map_id: {map_id}") from exc

    def list_ids(self) -> list[str]:
        return sorted(self._maps)
