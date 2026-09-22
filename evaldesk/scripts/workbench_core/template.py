"""Feishu template discovery and local session preparation."""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .aliases import load_aliases
from .schema import parse_schema

from .common import (
    ARBITRATION_DIMENSIONS, ARBITRATION_EDITABLE_FIELDS, DEFAULT_RANGE,
    DIMENSION_FIELDS, EDITABLE_FIELDS, EXPECTED_DIMENSIONS, FIELD_KEYS,
    WorkbenchError, atomic_json, column_number, parse_sheet_id, run_lark,
    utc_now,
)

LEGACY_DIMENSION_FIELDS = [
    "打分",
    "打分标签",
    "打分归因",
    "人机review打签",
    "review归因",
]
LEGACY_FIELD_KEYS = [
    "human_score",
    "tags",
    "reason",
    "review_label",
    "review_reason",
]
ARBITRATION_DIMENSION_FIELDS = [
    "人评打分",
    "打分标签",
    "仲裁标签",
    "打分归因",
    "机评分数",
    "人机review打签",
    "review归因",
]
ARBITRATION_FIELD_KEYS = [
    "human_score",
    "tags",
    "arbitration_label",
    "reason",
    "machine_score",
    "review_label",
    "review_reason",
]

def extract_urls(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, dict):
        return [url for key, part in value.items() if key in ("url", "link", "text", "value", "href", "content")
                for url in extract_urls(part)]
    if isinstance(value, list):
        return [url for part in value for url in extract_urls(part)]
    text = str(value).strip()
    try:
        decoded = json.loads(text)
        if isinstance(decoded, (dict, list)):
            return extract_urls(decoded)
    except (ValueError, TypeError):
        pass
    return [
        item.rstrip("')]}，。;；")
        for item in re.findall(r"https?://[^\s'\"<>\[\]，、]+", text)
    ]


def parse_annotated_csv(text: str, columns: list[str]) -> dict[int, list[str]]:
    normalized = re.sub(r"(?m)^\[row=(\d+)\] ", r"\1,", text)
    parsed: dict[int, list[str]] = {}
    for record in csv.reader(io.StringIO(normalized)):
        if not record:
            continue
        try:
            row_number = int(record[0])
        except ValueError as exc:
            raise WorkbenchError(f"无法解析真实行号: {record[0]!r}") from exc
        values = record[1:]
        values.extend([""] * (len(columns) - len(values)))
        parsed[row_number] = values[: len(columns)]
    return parsed


def nonempty(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def split_multi(value: Any) -> list[str]:
    if not nonempty(value):
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def decode_score_sequence(value: Any) -> list[str]:
    """Decode JSON arrays, legacy comma lists, and scalar scores."""
    if isinstance(value, list):
        return [str(item).strip() if item is not None else "" for item in value]
    text = str(value if value is not None else "").strip()
    if not text:
        return []
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, list):
        return [str(item).strip() if item is not None else "" for item in decoded]
    stripped = text.removeprefix("[").removesuffix("]")
    return [item.strip() for item in re.split(r"[,，、]", stripped)]


def parse_score_sequence(value: Any, output_count: int) -> list[str]:
    """Normalize a score value to exactly one slot per output."""
    items = decode_score_sequence(value)
    return items + [""] * max(0, output_count - len(items))


def cell_value(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index]


def locate_basic_column(row2: list[str], *names: str) -> int | None:
    lowered = {name.strip().lower(): index for index, name in enumerate(row2)}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def mapped_columns(
    columns: list[str], start: int, keys: list[str]
) -> dict[str, str | None]:
    return {
        key: columns[start + offset]
        for offset, key in enumerate(keys)
    }


def parse_arbitration_schema(
    columns: list[str],
    row1: list[str],
    row2: list[str],
    row3: list[str],
) -> tuple[list[dict[str, Any]], int, list[str], dict[str, Any]]:
    problems: list[str] = []
    group_starts = [
        index
        for index, value in enumerate(row1)
        if str(value).strip()
    ]
    expected_groups = ["baseline（第1轮）", "baseline（第2轮）", "baseline（三轮仲裁）"]
    actual_groups = [row1[index].strip() for index in group_starts]
    if actual_groups != expected_groups:
        problems.append(
            "三轮表头分组不匹配，实际为 " + "、".join(actual_groups)
        )
        group_starts = [7, 38, 69]

    comparison_rounds: list[dict[str, Any]] = []
    comparison_dimensions: list[list[dict[str, str | None]]] = []
    for round_index, (label, start) in enumerate(
        zip(("第1轮", "第2轮"), group_starts[:2])
    ):
        mappings: list[dict[str, str | None]] = []
        for dimension_index, name in enumerate(ARBITRATION_DIMENSIONS):
            cursor = start + dimension_index * len(DIMENSION_FIELDS)
            actual_name = row2[cursor].strip() if cursor < len(row2) else ""
            actual_fields = row3[cursor : cursor + len(DIMENSION_FIELDS)]
            if actual_name != name or actual_fields != DIMENSION_FIELDS:
                problems.append(
                    f"{label} {name} 表头不匹配: {actual_name!r} / {actual_fields}"
                )
            mappings.append(mapped_columns(columns, cursor, FIELD_KEYS))
        mos_index = start + len(ARBITRATION_DIMENSIONS) * len(DIMENSION_FIELDS)
        if mos_index >= len(row2) or row2[mos_index].strip().lower() != "mos分":
            problems.append(f"{label} 未在预期位置找到 mos分")
        comparison_dimensions.append(mappings)
        comparison_rounds.append(
            {
                "label": label,
                "mos_column": columns[mos_index],
            }
        )

    active_start = group_starts[2]
    dimensions: list[dict[str, Any]] = []
    for dimension_index, name in enumerate(ARBITRATION_DIMENSIONS):
        cursor = active_start + dimension_index * len(ARBITRATION_DIMENSION_FIELDS)
        actual_name = row2[cursor].strip() if cursor < len(row2) else ""
        actual_fields = row3[cursor : cursor + len(ARBITRATION_DIMENSION_FIELDS)]
        if actual_name != name or actual_fields != ARBITRATION_DIMENSION_FIELDS:
            problems.append(
                f"三轮仲裁 {name} 表头不匹配: {actual_name!r} / {actual_fields}"
            )
        dimensions.append(
            {
                "key": f"d{dimension_index + 1}",
                "name": name,
                "columns": mapped_columns(
                    columns, cursor, ARBITRATION_FIELD_KEYS
                ),
                "editable_fields": ARBITRATION_EDITABLE_FIELDS,
                "comparison_columns": [
                    {
                        "label": comparison_rounds[round_index]["label"],
                        "columns": comparison_dimensions[round_index][dimension_index],
                    }
                    for round_index in range(2)
                ],
            }
        )

    mos_index = (
        active_start
        + len(ARBITRATION_DIMENSIONS) * len(ARBITRATION_DIMENSION_FIELDS)
    )
    if mos_index >= len(row2) or row2[mos_index].strip().lower() != "mos分":
        problems.append("三轮仲裁未在预期位置找到 mos分")
    overall_label_index = mos_index + 1
    overall_reason_index = mos_index + 2
    if (
        overall_label_index >= len(row3)
        or "仲裁标签" not in row3[overall_label_index]
    ):
        problems.append("未找到整体仲裁标签列")
    if overall_reason_index >= len(row3):
        problems.append("未找到整体仲裁原因列")
    extras = {
        "comparison_rounds": comparison_rounds,
        "arbitration_columns": {
            "label": columns[overall_label_index],
            "reason": columns[overall_reason_index],
        },
    }
    return dimensions, mos_index, problems, extras


def _legacy_parse_schema(
    columns: list[str], rows: dict[int, list[str]]
) -> tuple[
    list[dict[str, Any]], dict[str, int | None], int, str, list[str],
    dict[str, Any],
]:
    row1 = rows.get(1)
    row2 = rows.get(2)
    row3 = rows.get(3)
    if row1 is None or row2 is None or row3 is None:
        raise WorkbenchError("模板必须包含第 1、2、3 行表头")

    is_arbitration = any("三轮仲裁" in value for value in row1)
    if is_arbitration:
        dimensions, mos_index, problems, extras = parse_arbitration_schema(
            columns, row1, row2, row3
        )
        template_layout = "image-arbitration-107"
        expected_dimensions = ARBITRATION_DIMENSIONS
    else:
        mos_index = locate_basic_column(row2, "mos分", "MOS分")
        if mos_index is None:
            raise WorkbenchError("未找到 mos分 列")

        dimensions = []
        layouts: set[str] = set()
        cursor = 7
        while cursor < mos_index:
            title = row2[cursor].strip()
            if not title:
                cursor += 1
                continue
            standard_fields = row3[cursor : cursor + len(DIMENSION_FIELDS)]
            legacy_fields = row3[cursor : cursor + len(LEGACY_DIMENSION_FIELDS)]
            if standard_fields == DIMENSION_FIELDS:
                width = len(DIMENSION_FIELDS)
                layout = "standard-56"
                mapping = mapped_columns(columns, cursor, FIELD_KEYS)
            elif legacy_fields == LEGACY_DIMENSION_FIELDS:
                width = len(LEGACY_DIMENSION_FIELDS)
                layout = "legacy-48"
                mapping = mapped_columns(columns, cursor, LEGACY_FIELD_KEYS)
                mapping["machine_score"] = None
            else:
                raise WorkbenchError(
                    f"{columns[cursor]} 列的维度 {title!r} 不是支持的五列或六列结构: "
                    f"{standard_fields}"
                )
            layouts.add(layout)
            dimensions.append(
                {
                    "key": f"d{len(dimensions) + 1}",
                    "name": title,
                    "columns": mapping,
                    "editable_fields": EDITABLE_FIELDS,
                    "comparison_columns": [],
                }
            )
            cursor += width
        problems = []
        if len(layouts) > 1:
            problems.append("同一张表混用了五列和六列维度结构")
        template_layout = next(iter(layouts), "unknown")
        expected_dimensions = EXPECTED_DIMENSIONS
        extras = {
            "comparison_rounds": [],
            "arbitration_columns": None,
        }

    names = [item["name"] for item in dimensions]
    if names != expected_dimensions:
        problems.append(
            "维度顺序不匹配，预期 "
            + "、".join(expected_dimensions)
            + "，实际 "
            + "、".join(names)
        )

    basic = {
        "id": locate_basic_column(row2, "index", "id"),
        "prompt": locate_basic_column(row2, "prompt"),
        "prompt_zh": locate_basic_column(row2, "prompt_中文翻译", "prompt翻译"),
        "references": locate_basic_column(row2, "用户素材", "垫图", "参考图"),
        "outputs": locate_basic_column(
            row2, "video_url_baseline", "结果图_baseline", "结果图", "输出"
        ),
        "annotator": locate_basic_column(row2, "标注人"),
        "reviewer": locate_basic_column(row2, "review人"),
    }
    if basic["id"] is None:
        problems.append("未找到 index/id 列")
    if basic["prompt"] is None and basic["prompt_zh"] is None:
        problems.append("未找到 prompt 列")
    if basic["outputs"] is None:
        problems.append("未找到结果图或视频列")
    return dimensions, basic, mos_index, template_layout, problems, extras


def validation_by_column(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    data = payload.get("data", {})
    if data.get("has_more"):
        raise WorkbenchError("数据验证读取被截断，不能生成会话")
    found: dict[str, dict[str, Any]] = {}
    for region in data.get("ranges", []):
        columns = region.get("col_indices", [])
        for row in region.get("cells", []):
            for index, cell in enumerate(row):
                if index >= len(columns):
                    continue
                validation = cell.get("data_validation")
                if validation:
                    entry = {
                        "items": [str(item) for item in validation.get("items", [])],
                        "multiple": bool(validation.get("support_multiple_values")),
                    }
                    if columns[index] in found and found[columns[index]] != entry:
                        raise WorkbenchError(f"{columns[index]} 列不同任务行的选项不一致，请缩小任务范围")
                    found[columns[index]] = entry
    return found


def read_validation_payload(
    url: str,
    sheet_id: str,
    csv_payload: dict[str, Any],
    end_row: int,
    target_group: str | None = None,
    aliases: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = csv_payload["data"]
    columns = data.get("col_indices", [])
    rows = parse_annotated_csv(data.get("annotated_csv", ""), columns)
    dimensions, _, mos_index, _, _, extras = parse_schema(
        columns, rows, target_group, aliases
    )
    ranges: list[dict[str, Any]] = []
    for dimension in dimensions:
        dimension_columns = dimension["columns"]
        start = dimension_columns["human_score"]
        end = max((c for c in dimension_columns.values() if c), key=column_number)
        payload = run_lark(
            [
                "sheets",
                "+dropdown-get",
                "--url",
                url,
                "--sheet-id",
                sheet_id,
                "--range",
                f"{start}{extras['header_rows'] + 1}:{end}{end_row}",
                "--as",
                "user",
            ]
        )
        dimension_data = payload.get("data", {})
        if dimension_data.get("has_more"):
            raise WorkbenchError(
                f"维度 {dimension['name']} 的数据验证读取被截断，不能生成会话"
            )
        ranges.extend(dimension_data.get("ranges", []))
    extra_columns = {**extras.get("overall_columns", {}), **(extras.get("arbitration_columns") or {}), "mos": columns[mos_index]}
    for column in set(extra_columns.values()):
        payload = run_lark(
            [
                "sheets",
                "+dropdown-get",
                "--url",
                url,
                "--sheet-id",
                sheet_id,
                "--range",
                f"{column}{extras['header_rows'] + 1}:{column}{end_row}",
                "--as",
                "user",
            ]
        )
        ranges.extend(payload.get("data", {}).get("ranges", []))
    return {"ok": True, "data": {"has_more": False, "ranges": ranges}}


def source_dimension(
    row: list[str],
    column_lookup: dict[str, int],
    dimension: dict[str, Any],
    output_count: int,
) -> dict[str, Any]:
    cols = dimension["columns"]
    def value(field: str) -> str:
        column = cols.get(field)
        return "" if column is None else cell_value(row, column_lookup.get(column))

    values = {
        "human_score": parse_score_sequence(value("human_score"), output_count),
        "tags": split_multi(value("tags")),
        "reason": value("reason"),
        "machine_score": parse_score_sequence(value("machine_score"), output_count),
        "review_label": value("review_label"),
        "review_reason": value("review_reason"),
    }
    if cols.get("arbitration_label"):
        values["arbitration_label"] = value("arbitration_label")
    values["raw_scores"] = {key: value(key) for key in ("human_score", "machine_score")}
    values["warnings"] = [
        f"{'历史人评' if key == 'human_score' else '机评'}原始分数有 {len(decode_score_sequence(value(key)))} 项，当前结果 {output_count} 项；原值：{value(key)}"
        for key in ("human_score", "machine_score")
        if decode_score_sequence(value(key)) and len(decode_score_sequence(value(key))) != output_count
    ]
    values["comparisons"] = [
        {
            "label": comparison["label"],
            **source_dimension(
                row,
                column_lookup,
                {
                    "columns": comparison["columns"],
                    "comparison_columns": [],
                },
                output_count,
            ),
        }
        for comparison in dimension.get("comparison_columns", [])
    ]
    return values


def build_session(
    url: str,
    sheet_id: str,
    csv_payload: dict[str, Any],
    validation_payload: dict[str, Any],
    annotator: str | None = None,
    include_unassigned: bool = False,
    target_group: str | None = None,
    aliases: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if bool(annotator) == include_unassigned:
        raise WorkbenchError("必须且只能选择 --annotator 或 --include-unassigned")
    data = csv_payload["data"]
    if data.get("has_more"):
        raise WorkbenchError("表格读取被截断，请缩小范围或提高读取上限")
    columns = data.get("col_indices", [])
    rows = parse_annotated_csv(data.get("annotated_csv", ""), columns)
    dimensions, basic, mos_index, template_layout, problems, extras = parse_schema(
        columns, rows, target_group, aliases
    )
    validations = validation_by_column(validation_payload)
    column_lookup = {column: index for index, column in enumerate(columns)}

    options: dict[str, Any] = {}
    allowlist = [columns[mos_index]]
    for dimension in dimensions:
        cols = dimension["columns"]
        options[dimension["key"]] = {
            "scores": validations.get(cols["human_score"], {}).get(
                "items", []
            ),
            "tags": validations.get(cols["tags"], {}).get("items", []),
            "review_labels": validations.get(cols["review_label"], {}).get(
                "items", []
            ),
            "arbitration_labels": validations.get(
                cols.get("arbitration_label", ""), {}
            ).get("items", []),
        }
        allowlist.extend(
            cols[key] for key in dimension["editable_fields"] if cols.get(key)
        )
    arbitration_columns = extras.get("arbitration_columns")
    overall_arbitration_labels: list[str] = []
    if arbitration_columns:
        allowlist.extend(arbitration_columns.values())
        overall_arbitration_labels = validations.get(
            arbitration_columns["label"], {}
        ).get("items", [])
    overall_columns = extras.get("overall_columns", {})
    allowlist.extend(overall_columns.values())
    overall_options = {
        "tags": validations.get(overall_columns.get("tags"), {}).get("items", []),
        "review_labels": validations.get(overall_columns.get("review_label"), {}).get("items", []),
    }

    task_rows: list[dict[str, Any]] = []
    result_rows: dict[str, Any] = {}
    for row_number in sorted(number for number in rows if number > extras["header_rows"]):
        row = rows[row_number]
        assigned_to = cell_value(row, basic["annotator"]).strip()
        if annotator and assigned_to.lstrip("@") != annotator.strip().lstrip("@"):
            continue
        if include_unassigned and assigned_to:
            continue
        task_id = cell_value(row, basic["id"])
        prompt = cell_value(row, basic["prompt_zh"]) or cell_value(row, basic["prompt"])
        outputs = extract_urls(cell_value(row, basic["outputs"]))
        references = extract_urls(cell_value(row, basic["references"]))
        if not task_id or not prompt or not outputs:
            continue
        kind = "video" if any(
            urlparse(item).path.lower().endswith((".mp4", ".mov", ".webm"))
            for item in outputs
        ) else "image"
        output_kinds = [
            "video"
            if urlparse(item).path.lower().endswith((".mp4", ".mov", ".webm"))
            else "image"
            for item in outputs
        ]
        dimension_values = {
            dimension["key"]: source_dimension(
                row, column_lookup, dimension, len(outputs)
            )
            for dimension in dimensions
        }
        mos = parse_score_sequence(cell_value(row, mos_index), len(outputs))
        comparison_mos = [
            {
                "label": comparison["label"],
                "scores": parse_score_sequence(
                    cell_value(
                        row,
                        column_lookup.get(comparison["mos_column"]),
                    ),
                    len(outputs),
                ),
            }
            for comparison in extras["comparison_rounds"]
        ]
        arbitration = (
            {
                "label": cell_value(
                    row, column_lookup.get(arbitration_columns["label"])
                ),
                "reason": cell_value(
                    row, column_lookup.get(arbitration_columns.get("reason"))
                ),
            }
            if arbitration_columns
            else None
        )
        task = {
            "row": row_number,
            "id": task_id,
            "kind": kind,
            "prompt": prompt,
            "prompt_original": cell_value(row, basic["prompt"]),
            "references": references,
            "reference_kinds": [
                "video" if urlparse(item).path.lower().endswith((".mp4", ".mov", ".webm", ".m4v"))
                else "image" for item in references
            ],
            "outputs": outputs,
            "output_kinds": output_kinds,
            "annotator": assigned_to,
            "reviewer": cell_value(row, basic["reviewer"]),
            "dimensions": dimension_values,
            "mos": mos,
            "comparison_mos": comparison_mos,
            "expert_values": {label: cell_value(row, column_lookup[column])
                              for column, label in extras.get("expert_columns", {}).items()},
            "overall": {field: split_multi(cell_value(row, column_lookup[column])) if field == "tags"
                        else cell_value(row, column_lookup[column])
                        for field, column in overall_columns.items()},
        }
        if arbitration is not None:
            task["arbitration"] = arbitration
        task_rows.append(task)
        result_row = {
            "dimensions": {
                dimension["key"]: {
                    field: deepcopy(dimension_values[dimension["key"]][field])
                    for field in dimension["editable_fields"]
                }
                for dimension in dimensions
            },
            "mos": mos,
            "updated_at": None,
            "saved_at": None,
            "overall": deepcopy(task["overall"]),
        }
        if arbitration is not None:
            result_row["arbitration"] = deepcopy(arbitration)
        result_rows[str(row_number)] = result_row

    if not task_rows:
        assignment = f"标注人 {annotator}" if annotator else "未分配"
        problems.append(f"读取范围内没有属于{assignment}的有效任务行")
    if not all(options[item["key"]]["tags"] for item in dimensions if item["columns"].get("tags")):
        problems.append("至少一个维度没有读到打分标签的数据验证")
    if not all(options[item["key"]]["scores"] for item in dimensions):
        problems.append("至少一个维度没有评分选项；需明确该列评分规则后再加载")
    for field, option_key in (("tags", "tags"), ("review_label", "review_labels")):
        if overall_columns.get(field) and not overall_options[option_key]:
            problems.append(f"MOS 的 {field} 列缺少模板选项")
    if arbitration_columns:
        if not all(options[item["key"]]["arbitration_labels"] for item in dimensions if item["columns"].get("arbitration_label")):
            problems.append("至少一个维度没有读到仲裁标签的数据验证")
        if not overall_arbitration_labels:
            problems.append("没有读到整体仲裁标签的数据验证")

    manifest = {
        "version": 2,
        "created_at": utc_now(),
        "source": {
            "url": url,
            "sheet_id": sheet_id,
            "revision": data.get("revision"),
            "range": data.get("actual_range"),
        },
        "assignment": {
            "annotator": annotator,
            "include_unassigned": include_unassigned,
        },
        "schema": {
            "supported": not problems,
            "problems": problems,
            "template_layout": template_layout,
            "dimensions": dimensions,
            "mos_column": columns[mos_index],
            "comparison_rounds": extras["comparison_rounds"],
            "arbitration_columns": arbitration_columns,
            "overall_columns": overall_columns,
            "header_rows": extras["header_rows"],
            "target_group": extras["target_group"],
            "available_groups": extras["available_groups"],
            "model": extras["model"],
            "alias_source": (aliases or {}).get("source", "default"),
        },
        "options": {
            **options,
            "overall_arbitration_labels": overall_arbitration_labels,
            "overall": overall_options,
        },
        "write_allowlist": sorted(set(allowlist), key=column_number),
        "task_count": len(task_rows),
    }
    tasks = {"version": 2, "rows": task_rows}
    results = {"version": 2, "updated_at": utc_now(), "rows": result_rows}
    return manifest, tasks, results


def default_session_dir(sheet_id: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path.home() / ".evaldesk" / "sessions" / f"{sheet_id}-{stamp}"


def resolve_read_range(sheet: dict[str, Any], requested: str) -> str:
    if requested != "auto":
        return requested
    last = ""
    number = int(sheet["column_count"])
    while number:
        number, remainder = divmod(number - 1, 26)
        last = chr(65 + remainder) + last
    return f"A1:{last}{min(int(sheet['row_count']), 1000)}"


def read_sheet_csv(
    url: str,
    sheet_id: str,
    requested_range: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    workbook = run_lark(
        ["sheets", "+workbook-info", "--url", url, "--as", "user"]
    )
    sheet = next(
        (
            item
            for item in workbook["data"].get("sheets", [])
            if item["sheet_id"] == sheet_id
        ),
        None,
    )
    if not sheet:
        raise WorkbenchError(f"未找到子表 {sheet_id}")
    read_range = resolve_read_range(sheet, requested_range)
    payload = run_lark(
        [
            "sheets",
            "+csv-get",
            "--url",
            url,
            "--sheet-id",
            sheet_id,
            "--range",
            read_range,
            "--max-chars",
            "20000000",
            "--as",
            "user",
        ]
    )
    return sheet, payload


def _diagnostic_suggestions(problems: list[str]) -> list[str]:
    suggestions = []
    joined = "\n".join(problems).lower()
    if "mos" in joined:
        suggestions.append("确认表头包含 MOS 分，或在别名文件的 mos 中追加实际名称")
    if "评分组" in joined or "评分目标" in joined:
        suggestions.append("使用 --target-group 指定需要编辑的模型或评分轮次")
    if "人员" in joined or "标注人" in joined or "仲裁人" in joined:
        suggestions.append("增加标注人/仲裁人列，或在 basic_fields 中配置别名")
    if "输出" in joined or "结果图" in joined:
        suggestions.append("增加结果图/输出列，或在 basic_fields.outputs 中配置列名前缀")
    if "未知" in joined or "重复" in joined:
        suggestions.append("检查评分块中的字段名称和重复列，再补充 score_fields 别名")
    if not suggestions:
        suggestions.append("根据 problems 修正表头后重新运行 diagnose")
    return suggestions


def command_diagnose(args: argparse.Namespace) -> int:
    sheet_id = parse_sheet_id(args.url, args.sheet_id)
    aliases = load_aliases(getattr(args, "aliases", None))
    sheet, csv_payload = read_sheet_csv(args.url, sheet_id, args.range)
    data = csv_payload.get("data", {})
    columns = data.get("col_indices", [])
    rows = parse_annotated_csv(data.get("annotated_csv", ""), columns)
    header_cells = [
        {
            "column": column,
            "row1": cell_value(rows.get(1, []), index),
            "row2": cell_value(rows.get(2, []), index),
            "row3": cell_value(rows.get(3, []), index),
        }
        for index, column in enumerate(columns)
        if any(cell_value(rows.get(row, []), index) for row in (1, 2, 3))
    ]
    try:
        dimensions, basic, mos_index, layout, problems, extras = parse_schema(
            columns,
            rows,
            getattr(args, "target_group", None),
            aliases,
        )
        report = {
            "supported": not problems,
            "sheet": {
                "id": sheet_id,
                "name": sheet.get("sheet_name", sheet_id),
                "range": data.get("actual_range"),
                "rows": sheet.get("row_count"),
                "columns": sheet.get("column_count"),
            },
            "alias_source": aliases["source"],
            "layout": layout,
            "target_group": extras["target_group"],
            "available_groups": extras["available_groups"],
            "basic_fields": {
                key: columns[index] if index is not None else None
                for key, index in basic.items()
            },
            "dimensions": [
                {
                    "name": item["name"],
                    "columns": item["columns"],
                    "editable_fields": item["editable_fields"],
                }
                for item in dimensions
            ],
            "mos_column": columns[mos_index],
            "read_only": {
                "comparison_rounds": extras["comparison_rounds"],
                "expert_columns": extras["expert_columns"],
            },
            "problems": problems,
            "suggestions": _diagnostic_suggestions(problems) if problems else [],
        }
    except WorkbenchError as exc:
        problems = [str(exc)]
        report = {
            "supported": False,
            "sheet": {
                "id": sheet_id,
                "name": sheet.get("sheet_name", sheet_id),
                "range": data.get("actual_range"),
                "rows": sheet.get("row_count"),
                "columns": sheet.get("column_count"),
            },
            "alias_source": aliases["source"],
            "problems": problems,
            "suggestions": _diagnostic_suggestions(problems),
            "detected_headers": header_cells,
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["supported"] else 2


def command_prepare(args: argparse.Namespace) -> int:
    sheet_id = parse_sheet_id(args.url, args.sheet_id)
    aliases = load_aliases(getattr(args, "aliases", None))
    sheet, csv_payload = read_sheet_csv(args.url, sheet_id, args.range)
    validation_payload = read_validation_payload(
        args.url,
        sheet_id,
        csv_payload,
        args.validation_end_row,
        getattr(args, "target_group", None),
        aliases,
    )
    manifest, tasks, results = build_session(
        args.url,
        sheet_id,
        csv_payload,
        validation_payload,
        annotator=args.annotator,
        include_unassigned=args.include_unassigned,
        target_group=getattr(args, "target_group", None),
        aliases=aliases,
    )
    manifest["schema"]["blind"] = bool(getattr(args, "blind", False) or "盲评" in sheet.get("sheet_name", ""))
    manifest["source"]["sheet_name"] = sheet.get("sheet_name", sheet_id)
    session = Path(args.session).resolve() if args.session else default_session_dir(sheet_id)
    if session.exists() and any(session.iterdir()) and not args.force:
        raise WorkbenchError(f"会话目录已存在且非空: {session}；如需覆盖请使用 --force")
    session.mkdir(parents=True, exist_ok=True)
    if args.force:
        (session / "commit-preview.json").unlink(missing_ok=True)
    atomic_json(session / "manifest.json", manifest)
    atomic_json(session / "tasks.json", tasks)
    atomic_json(session / "results.json", results)
    atomic_json(
        session / "status.json",
        {"state": "prepared", "updated_at": utc_now(), "last_error": None},
    )
    print(
        json.dumps(
            {
                "session": str(session),
                "supported": manifest["schema"]["supported"],
                "problems": manifest["schema"]["problems"],
                "tasks": manifest["task_count"],
                "dimensions": [
                    item["name"] for item in manifest["schema"]["dimensions"]
                ],
                "template_layout": manifest["schema"]["template_layout"],
                "revision": manifest["source"]["revision"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if manifest["schema"]["supported"] else 2
