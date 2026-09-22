"""Load and validate configurable template field aliases."""
from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from .common import APP_ROOT, WorkbenchError

DEFAULT_ALIAS_PATH = APP_ROOT / "config" / "field-aliases.json"
ALLOWED_KEYS = {
    "basic_fields": {
        "id",
        "prompt",
        "prompt_zh",
        "references",
        "annotator",
        "arbitrator",
        "reviewer",
        "outputs",
    },
    "score_fields": {
        "human_score",
        "tags",
        "reason",
        "machine_score",
        "review_label",
        "review_reason",
        "arbitration_label",
    },
}


def normalize(value: Any) -> str:
    return (
        re.sub(r"\s+", "", str(value))
        .lower()
        .replace("（", "(")
        .replace("）", ")")
    )


def _read_alias_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkbenchError(f"字段别名文件不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkbenchError(f"字段别名文件不是有效 JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise WorkbenchError(f"字段别名文件顶层必须是对象: {path}")
    return payload


def _validate_aliases(payload: dict[str, Any], source: Path) -> None:
    unknown_sections = set(payload) - {"basic_fields", "score_fields", "mos"}
    if unknown_sections:
        raise WorkbenchError(
            f"字段别名文件包含未知分组: {sorted(unknown_sections)}"
        )
    for section, allowed in ALLOWED_KEYS.items():
        values = payload.get(section, {})
        if not isinstance(values, dict):
            raise WorkbenchError(f"{source} 中 {section} 必须是对象")
        unknown_keys = set(values) - allowed
        if unknown_keys:
            raise WorkbenchError(
                f"{source} 中 {section} 包含未知字段: {sorted(unknown_keys)}"
            )
        for key, aliases in values.items():
            if (
                not isinstance(aliases, list)
                or not aliases
                or not all(isinstance(item, str) and item.strip() for item in aliases)
            ):
                raise WorkbenchError(
                    f"{source} 中 {section}.{key} 必须是非空字符串数组"
                )
    mos = payload.get("mos", [])
    if not isinstance(mos, list) or not all(
        isinstance(item, str) and item.strip() for item in mos
    ):
        raise WorkbenchError(f"{source} 中 mos 必须是字符串数组")


def _check_collisions(payload: dict[str, Any]) -> None:
    for section in ("basic_fields", "score_fields"):
        owners: dict[str, str] = {}
        for key, aliases in payload[section].items():
            for alias in aliases:
                normalized = normalize(alias)
                previous = owners.get(normalized)
                if previous and previous != key:
                    raise WorkbenchError(
                        f"字段别名冲突: {alias!r} 同时属于 {previous} 和 {key}"
                    )
                owners[normalized] = key


def load_aliases(path: str | None = None) -> dict[str, Any]:
    defaults = _read_alias_file(DEFAULT_ALIAS_PATH)
    _validate_aliases(defaults, DEFAULT_ALIAS_PATH)
    merged = deepcopy(defaults)
    source = "default"
    if path:
        custom_path = Path(path).expanduser().resolve()
        custom = _read_alias_file(custom_path)
        _validate_aliases(custom, custom_path)
        for section in ("basic_fields", "score_fields"):
            for key, aliases in custom.get(section, {}).items():
                merged[section][key] = list(
                    dict.fromkeys([*merged[section][key], *aliases])
                )
        merged["mos"] = list(dict.fromkeys([*merged["mos"], *custom.get("mos", [])]))
        source = str(custom_path)
    _check_collisions(merged)
    merged["source"] = source
    return merged


def alias_key(value: Any, aliases: dict[str, Any], section: str) -> str | None:
    normalized = normalize(value)
    for key, values in aliases[section].items():
        if normalized in {normalize(item) for item in values}:
            return key
    return None


def output_model(value: Any, aliases: dict[str, Any]) -> str | None:
    normalized = normalize(value)
    output_aliases = sorted(
        (normalize(item) for item in aliases["basic_fields"]["outputs"]),
        key=len,
        reverse=True,
    )
    for alias in output_aliases:
        if normalized == alias:
            return "baseline"
        if normalized.startswith(alias):
            suffix = normalized[len(alias) :].strip("_-()")
            if suffix:
                return suffix
    return None


def is_mos(value: Any, aliases: dict[str, Any]) -> bool:
    normalized = normalize(value)
    return any(
        re.fullmatch(rf"(?:第?\d+轮)?{re.escape(normalize(alias))}", normalized)
        for alias in aliases["mos"]
    )
