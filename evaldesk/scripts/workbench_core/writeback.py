"""Result validation, write preview, conflict checks, and verification."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .common import (
    WorkbenchError, atomic_json, column_number, read_json, run_lark, utc_now,
)
from .template import decode_score_sequence, parse_score_sequence, split_multi


def validate_score_sequence(
    value: Any,
    output_count: int,
    allowed: list[str] | None,
    location: str,
) -> list[str]:
    decoded = decode_score_sequence(value)
    if not decoded:
        decoded = [""] * output_count
    if len(decoded) != output_count:
        raise WorkbenchError(
            f"{location} 应有 {output_count} 个分数，实际有 {len(decoded)} 个"
        )
    if any(not item for item in decoded) and any(decoded):
        raise WorkbenchError(f"{location} 必须为每个输出都填写分数，或全部留空")
    if allowed is not None:
        unknown = sorted({item for item in decoded if item} - set(allowed))
        if unknown:
            raise WorkbenchError(f"{location} 含模板选项外分数: {unknown}")
    return decoded

def validate_result_value(
    field: str,
    value: Any,
    option_set: dict[str, Any],
    location: str,
    output_count: int,
) -> Any:
    if field == "human_score":
        return validate_score_sequence(
            value, output_count, option_set["scores"], location
        )
    if field == "tags":
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise WorkbenchError(f"{location} 的标签必须是字符串数组")
        unknown = sorted(set(value) - set(option_set["tags"]))
        if unknown:
            raise WorkbenchError(f"{location} 含模板外标签: {unknown}")
        return value
    if value is None:
        value = ""
    if not isinstance(value, (str, int, float)):
        raise WorkbenchError(f"{location} 的值类型非法")
    text = str(value).strip()
    if field == "review_label" and text and text not in option_set["review_labels"]:
        raise WorkbenchError(f"{location} 的 review 标签 {text!r} 不在模板选项中")
    if (
        field == "arbitration_label"
        and text
        and text not in option_set.get("arbitration_labels", [])
    ):
        raise WorkbenchError(f"{location} 的仲裁标签 {text!r} 不在模板选项中")
    if field in ("reason", "review_reason") and len(str(value)) > 5000:
        raise WorkbenchError(f"{location} 超过 5000 字")
    return text if field not in ("reason", "review_reason") else str(value)


def scalar_equal(left: Any, right: Any) -> bool:
    return str(left if left is not None else "").strip() == str(right if right is not None else "").strip()


def numeric_score(value: str) -> int | float:
    number = float(value)
    return int(number) if number.is_integer() else number


def score_sequence_to_cell(value: list[str]) -> dict[str, Any]:
    if not any(value):
        return {"value": ""}
    numbers = [numeric_score(item) for item in value]
    if len(numbers) == 1:
        return {"value": numbers[0]}
    return {"value": json.dumps(numbers, ensure_ascii=False, separators=(",", ":"))}


def result_to_cell(field: str, value: Any) -> dict[str, Any]:
    if field == "tags":
        if value:
            return {"multiple_values": [{"value": item} for item in value]}
        return {"value": ""}
    if field == "human_score":
        return score_sequence_to_cell(value)
    return {"value": value}


def build_writes(
    manifest: dict[str, Any], tasks: dict[str, Any], results: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not manifest.get("schema", {}).get("supported"):
        raise WorkbenchError("manifest 标记模板不受支持，禁止回写")
    task_map = {str(item["row"]): item for item in tasks.get("rows", [])}
    result_map = results.get("rows")
    if not isinstance(result_map, dict):
        raise WorkbenchError("results.rows 必须是对象")
    unknown_rows = sorted(set(result_map) - set(task_map))
    if unknown_rows:
        raise WorkbenchError(f"results 中出现会话外行号: {unknown_rows}")

    allowlist = set(manifest["write_allowlist"])
    sheet_id = manifest["source"]["sheet_id"]
    writes: list[dict[str, Any]] = []
    preview: list[dict[str, Any]] = []
    dimensions = manifest["schema"]["dimensions"]
    options = manifest["options"]

    for row_key, source in task_map.items():
        local = result_map.get(row_key)
        if local is None:
            continue
        output_count = len(source.get("outputs", []))
        for dimension in dimensions:
            key = dimension["key"]
            source_values = source["dimensions"][key]
            local_dimensions = local.get("dimensions", {})
            if key not in local_dimensions:
                raise WorkbenchError(f"第 {row_key} 行缺少维度 {dimension['name']}")
            local_values = local_dimensions[key]
            for field in dimension["editable_fields"]:
                if field not in local_values:
                    raise WorkbenchError(
                        f"第 {row_key} 行 {dimension['name']} 缺少字段 {field}"
                    )
                # Historical invalid/partial values do not block unrelated edits.
                if local_values[field] == source_values[field]:
                    continue
                value = validate_result_value(
                    field,
                    local_values[field],
                    options[key],
                    f"第 {row_key} 行 {dimension['name']}",
                    output_count,
                )
                original = source_values[field]
                if field == "human_score":
                    original = parse_score_sequence(original, output_count)
                equal = (
                    list(value) == list(original)
                    if field in ("human_score", "tags")
                    else scalar_equal(value, original)
                )
                if equal:
                    continue
                column = dimension["columns"][field]
                if column not in allowlist:
                    raise WorkbenchError(f"列 {column} 不在写入白名单")
                cell = result_to_cell(field, value)
                writes.append(
                    {
                        "sheet_id": sheet_id,
                        "range": f"{column}{row_key}",
                        "cells": [[cell]],
                    }
                )
                preview.append(
                    {
                        "row": int(row_key),
                        "column": column,
                        "dimension": dimension["name"],
                        "field": field,
                        "before": original,
                        "after": value,
                        "output_count": output_count,
                    }
                )
        arbitration_columns = manifest["schema"].get("arbitration_columns")
        if arbitration_columns:
            local_arbitration = local.get("arbitration")
            if not isinstance(local_arbitration, dict) or set(
                local_arbitration
            ) != {"label", "reason"}:
                raise WorkbenchError(f"第 {row_key} 行整体仲裁结构非法")
            source_arbitration = source.get("arbitration", {})
            label = str(local_arbitration["label"] or "").strip()
            allowed_labels = options.get("overall_arbitration_labels", [])
            if label and label not in allowed_labels:
                raise WorkbenchError(
                    f"第 {row_key} 行整体仲裁标签 {label!r} 不在模板选项中"
                )
            reason = str(local_arbitration["reason"] or "")
            if len(reason) > 5000:
                raise WorkbenchError(f"第 {row_key} 行整体仲裁原因超过 5000 字")
            for field, value in (("label", label), ("reason", reason)):
                original = source_arbitration.get(field, "")
                if scalar_equal(value, original):
                    continue
                if field not in arbitration_columns:
                    raise WorkbenchError(f"整体仲裁没有可写的 {field} 列")
                column = arbitration_columns[field]
                if column not in allowlist:
                    raise WorkbenchError(f"列 {column} 不在写入白名单")
                writes.append(
                    {
                        "sheet_id": sheet_id,
                        "range": f"{column}{row_key}",
                        "cells": [[{"value": value}]],
                    }
                )
                preview.append(
                    {
                        "row": int(row_key),
                        "column": column,
                        "dimension": "整体仲裁",
                        "field": f"arbitration_{field}",
                        "before": original,
                        "after": value,
                        "output_count": output_count,
                    }
                )
        overall_columns = manifest["schema"].get("overall_columns", {})
        for field, column in overall_columns.items():
            raw = local.get("overall", {}).get(field, "")
            original = source.get("overall", {}).get(field, "")
            if raw == original:
                continue
            value = validate_result_value(field, raw, options.get("overall", {}), f"第 {row_key} 行 MOS {field}", output_count)
            if column not in allowlist:
                raise WorkbenchError(f"列 {column} 不在写入白名单")
            writes.append({"sheet_id": sheet_id, "range": f"{column}{row_key}", "cells": [[result_to_cell(field, value)]]})
            preview.append({"row": int(row_key), "column": column, "dimension": "MOS",
                            "field": field, "before": original, "after": value, "output_count": output_count})
        if local.get("mos", "") == source.get("mos", ""):
            continue
        mos_value = validate_score_sequence(
            local.get("mos", ""), output_count, None, f"第 {row_key} 行 MOS"
        )
        for item in mos_value:
            if item:
                try:
                    number = float(item)
                except ValueError as exc:
                    raise WorkbenchError(
                        f"第 {row_key} 行 MOS 含非数字分数 {item!r}"
                    ) from exc
                if not 1 <= number <= 5:
                    raise WorkbenchError(
                        f"第 {row_key} 行 MOS 分数 {item!r} 必须在 1 到 5 之间"
                    )
        source_mos = parse_score_sequence(source.get("mos", ""), output_count)
        if mos_value != source_mos:
            column = manifest["schema"]["mos_column"]
            if column not in allowlist:
                raise WorkbenchError(f"列 {column} 不在写入白名单")
            writes.append(
                {
                    "sheet_id": sheet_id,
                    "range": f"{column}{row_key}",
                    "cells": [[score_sequence_to_cell(mos_value)]],
                }
            )
            preview.append(
                {
                    "row": int(row_key),
                    "column": column,
                    "dimension": "MOS",
                    "field": "mos",
                    "before": source_mos,
                    "after": mos_value,
                    "output_count": output_count,
                }
            )
    order = sorted(
        range(len(writes)),
        key=lambda index: (
            preview[index]["row"],
            column_number(preview[index]["column"]),
        ),
    )
    return [writes[index] for index in order], [preview[index] for index in order]


def current_revision(url: str) -> Any:
    payload = run_lark(
        ["sheets", "+revision-get", "--url", url, "--as", "user"]
    )
    data = payload.get("data", {})
    for key in ("revision", "version"):
        if key in data:
            return data[key]
    raise WorkbenchError(f"无法从 revision-get 响应中取得版本号: {data}")


def normalize_read_cell(
    cell: dict[str, Any], field: str, output_count: int
) -> Any:
    if field == "tags":
        if "multiple_values" in cell:
            return [str(item.get("value", "")) for item in cell["multiple_values"]]
        return split_multi(cell.get("value", ""))
    if field in ("human_score", "mos"):
        return parse_score_sequence(cell.get("value", ""), output_count)
    return str(cell.get("value", "")).strip()


def verify_writes(
    manifest: dict[str, Any], preview: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_row: dict[int, list[dict[str, Any]]] = {}
    for item in preview:
        by_row.setdefault(item["row"], []).append(item)
    failures: list[dict[str, Any]] = []
    source = manifest["source"]
    for row, expected_items in by_row.items():
        start = min(expected_items, key=lambda item: column_number(item["column"]))["column"]
        end = max(expected_items, key=lambda item: column_number(item["column"]))["column"]
        payload = run_lark(
            [
                "sheets",
                "+cells-get",
                "--url",
                source["url"],
                "--sheet-id",
                source["sheet_id"],
                "--range",
                f"{start}{row}:{end}{row}",
                "--include",
                "value,data_validation",
                "--as",
                "user",
            ]
        )
        region = payload["data"]["ranges"][0]
        columns = region["col_indices"]
        cells = region.get("cells", [[]])[0]
        actual = {
            column: cells[index] if index < len(cells) else {}
            for index, column in enumerate(columns)
        }
        for item in expected_items:
            cell = actual.get(item["column"], {})
            observed = normalize_read_cell(
                cell, item["field"], item.get("output_count", 1)
            )
            intended = item["after"]
            equal = (
                list(observed) == list(intended)
                if item["field"] in ("human_score", "tags", "mos")
                else scalar_equal(observed, intended)
            )
            if not equal:
                failures.append({**item, "observed": observed})
    return failures


def command_commit(args: argparse.Namespace) -> int:
    session = Path(args.session).resolve()
    manifest = read_json(session / "manifest.json")
    tasks = read_json(session / "tasks.json")
    results = read_json(session / "results.json")
    writes, preview = build_writes(manifest, tasks, results)
    preview_doc = {
        "created_at": utc_now(),
        "apply_requested": bool(args.apply),
        "source_revision": manifest["source"]["revision"],
        "write_count": len(writes),
        "changes": preview,
        "verified": None,
    }
    atomic_json(session / "commit-preview.json", preview_doc)
    if not args.apply:
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "write_count": len(writes),
                    "rows": sorted({item["row"] for item in preview}),
                    "preview": str(session / "commit-preview.json"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if not writes:
        preview_doc["verified"] = True
        atomic_json(session / "commit-preview.json", preview_doc)
        print(json.dumps({"mode": "apply", "write_count": 0, "verified": True}))
        return 0

    actual_revision = current_revision(manifest["source"]["url"])
    if str(actual_revision) != str(manifest["source"]["revision"]):
        raise WorkbenchError(
            "飞书表格版本已变化，禁止覆盖。"
            f" prepare={manifest['source']['revision']} current={actual_revision}"
        )
    run_lark(
        [
            "sheets",
            "+cells-set",
            "--url",
            manifest["source"]["url"],
            "--writes",
            json.dumps(writes, ensure_ascii=False, separators=(",", ":")),
            "--as",
            "user",
        ]
    )
    failures = verify_writes(manifest, preview)
    preview_doc["verified"] = not failures
    preview_doc["verification_failures"] = failures
    preview_doc["applied_at"] = utc_now()
    atomic_json(session / "commit-preview.json", preview_doc)
    atomic_json(
        session / "status.json",
        {
            "state": "committed" if not failures else "verification_failed",
            "updated_at": utc_now(),
            "last_error": failures or None,
        },
    )
    if failures:
        raise WorkbenchError(
            f"已发起写入，但有 {len(failures)} 个单元格回读不一致；请检查 commit-preview.json"
        )
    print(
        json.dumps(
            {
                "mode": "apply",
                "write_count": len(writes),
                "rows": sorted({item["row"] for item in preview}),
                "verified": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0
