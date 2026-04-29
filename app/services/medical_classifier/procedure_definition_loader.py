from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CategoryDefinition:
    key: str
    title: str
    description: str
    scope: str = "full"
    positive_signals: list[str] = field(default_factory=list)
    negative_signals: list[str] = field(default_factory=list)
    examples_positive: list[str] = field(default_factory=list)
    examples_negative: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProcedureDefinition:
    treatment_code: str
    procedure_name: str
    procedure_aliases: list[str] = field(default_factory=list)
    source: str = "manual"
    current_hospitalization_only: bool = True
    require_actual_performance: bool = True
    priority_sections: list[str] = field(default_factory=list)
    global_positive_signals: list[str] = field(default_factory=list)
    global_negative_signals: list[str] = field(default_factory=list)
    categories: list[CategoryDefinition] = field(default_factory=list)


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes"}:
            return True
        if normalized in {"0", "false", "no"}:
            return False
    return bool(value)


def _category_from_dict(data: dict[str, Any]) -> CategoryDefinition:
    return CategoryDefinition(
        key=str(data.get("key", "")).strip(),
        title=str(data.get("title", "")).strip(),
        description=str(data.get("description", "")).strip(),
        scope=str(data.get("scope", "full")).strip() or "full",
        positive_signals=_as_str_list(data.get("positive_signals")),
        negative_signals=_as_str_list(data.get("negative_signals")),
        examples_positive=_as_str_list(data.get("examples_positive")),
        examples_negative=_as_str_list(data.get("examples_negative")),
    )


def _procedure_from_dict(data: dict[str, Any]) -> ProcedureDefinition:
    categories = [_category_from_dict(item) for item in data.get("categories", []) if isinstance(item, dict)]
    categories = [category for category in categories if category.key]

    return ProcedureDefinition(
        treatment_code=str(data.get("treatment_code", "")).strip(),
        procedure_name=str(data.get("procedure_name", "")).strip(),
        procedure_aliases=_as_str_list(data.get("procedure_aliases")),
        source=str(data.get("source", "manual")).strip() or "manual",
        current_hospitalization_only=_as_bool(data.get("current_hospitalization_only"), True),
        require_actual_performance=_as_bool(data.get("require_actual_performance"), True),
        priority_sections=_as_str_list(data.get("priority_sections")),
        global_positive_signals=_as_str_list(data.get("global_positive_signals")),
        global_negative_signals=_as_str_list(data.get("global_negative_signals")),
        categories=categories,
    )


class ProcedureDefinitionLoader:
    def __init__(self, definitions_path: str | None = None) -> None:
        self.definitions_path = definitions_path
        self._cache: dict[str, ProcedureDefinition] = {}

    def load(self) -> dict[str, ProcedureDefinition]:
        if not self.definitions_path:
            return {}

        path = Path(self.definitions_path)
        if not path.exists():
            logger.warning("Procedure definitions path does not exist: %s", path)
            return {}

        files = sorted(path.glob("*.json")) if path.is_dir() else [path]
        loaded: dict[str, ProcedureDefinition] = {}

        for file_path in files:
            try:
                raw = json.loads(file_path.read_text(encoding="utf-8"))
                items = raw if isinstance(raw, list) else [raw]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    definition = _procedure_from_dict(item)
                    if not definition.treatment_code:
                        logger.warning("Skipping definition without treatment_code: %s", file_path)
                        continue
                    loaded[definition.treatment_code] = definition
            except Exception as exc:  # pragma: no cover
                logger.exception("Failed loading procedure definition from %s: %s", file_path, exc)

        self._cache = loaded
        return loaded

    def get(self, treatment_code: Any) -> ProcedureDefinition | None:
        if not self._cache:
            self.load()
        return self._cache.get(str(treatment_code))
