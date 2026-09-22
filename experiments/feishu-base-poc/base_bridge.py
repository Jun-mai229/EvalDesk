#!/usr/bin/env python3
"""Convert an EvalDesk session to and from a Base-friendly record package."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class BridgeError(ValueError):
    pass


STATUS_OPTIONS = [
    {"name": "未开始", "hue": "Gray"},
    {"name": "进行中", "hue": "Blue"},
    {"name": "已提交", "hue": "Green"},
    {"name": "已退回", "hue": "Orange"},
]


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeError(f"无法读取 JSON：{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BridgeError(f"JSON 顶层必须是对象：{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def text_field(name: str, *, url: bool = False) -> dict[str, Any]:
    field: dict[str, Any] = {"type": "text", "name": name}
    if url:
        field["style"] = {"type": "url"}
    return field


def number_field(name: str) -> dict[str, Any]:
    return {
        "type": "number",
        "name": name,
        "style": {
            "type": "plain",
            "precision": 2,
            "percentage": False,
            "thousands_separator": False,
        },
    }


def select_field(
    name: str, options: list[str], *, multiple: bool = False
) -> dict[str, Any]:
    return {
        "type": "select",
        "name": name,
        "multiple": multiple,
        "options": [{"name": option} for option in options],
    }


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def package_id(manifest: dict[str, Any], tasks: dict[str, Any]) -> str:
    identity = {
        "sheet_id": manifest["source"]["sheet_id"],
        "revision": manifest["source"]["revision"],
        "target_group": manifest["schema"]["target_group"],
        "annotator": manifest["assignment"].get("annotator"),
        "rows": [row["row"] for row in tasks["rows"]],
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"edb-{digest}"


def field_name(index: int, dimension: dict[str, Any], suffix: str) -> str:
    return f"D{index} {dimension['name']} {suffix}"


def validate_session(
    manifest: dict[str, Any],
    tasks: dict[str, Any],
    results: dict[str, Any],
) -> None:
    if manifest.get("version") != 2:
        raise BridgeError("PoC 只支持 manifest version 2")
    if tasks.get("version") != 2 or results.get("version") != 2:
        raise BridgeError("PoC 只支持 tasks/results version 2")
    if not manifest.get("schema", {}).get("supported"):
        raise BridgeError("模板未通过 EvalDesk 诊断")
    if manifest["schema"].get("blind"):
        raise BridgeError("PoC 暂不支持盲评；需要先落实 Base 行级权限和快照锁定")
    task_rows = {str(row["row"]) for row in tasks.get("rows", [])}
    result_rows = set(results.get("rows", {}))
    if task_rows != result_rows:
        raise BridgeError("tasks 与 results 的物理行集合不一致")


def build_fields(manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    dimensions = manifest["schema"]["dimensions"]
    options = manifest["options"]
    task_fields = [
        text_field("任务ID"),
        text_field("批次ID"),
        number_field("源行号"),
        text_field("案例ID"),
        text_field("Prompt"),
        text_field("Prompt原文"),
        text_field("参考素材JSON"),
        text_field("标注人原文"),
        select_field("状态", [item["name"] for item in STATUS_OPTIONS]),
        text_field("历史对比JSON"),
        text_field("提交时间"),
    ]
    output_fields = [
        text_field("输出评分ID"),
        text_field("任务ID"),
        number_field("输出序号"),
        select_field("媒体类型", ["image", "video"]),
        text_field("输出地址", url=True),
    ]
    for index, dimension in enumerate(dimensions, start=1):
        key = dimension["key"]
        editable = set(dimension["editable_fields"])
        dimension_options = options[key]
        if "tags" in editable:
            task_fields.append(
                select_field(
                    field_name(index, dimension, "标签"),
                    dimension_options["tags"],
                    multiple=True,
                )
            )
        if "reason" in editable:
            task_fields.append(text_field(field_name(index, dimension, "归因")))
        if "review_label" in editable:
            task_fields.append(
                select_field(
                    field_name(index, dimension, "Review标签"),
                    dimension_options["review_labels"],
                )
            )
        if "review_reason" in editable:
            task_fields.append(
                text_field(field_name(index, dimension, "Review归因"))
            )
        if "arbitration_label" in editable:
            task_fields.append(
                select_field(
                    field_name(index, dimension, "仲裁标签"),
                    dimension_options.get("arbitration_labels", []),
                )
            )
        output_fields.append(
            select_field(
                field_name(index, dimension, "人评分"),
                dimension_options["scores"],
            )
        )
        output_fields.append(
            text_field(field_name(index, dimension, "机评分"))
        )
    overall = manifest["schema"].get("overall_columns", {})
    overall_options = options.get("overall", {})
    if "tags" in overall:
        task_fields.append(
            select_field("整体标签", overall_options.get("tags", []), multiple=True)
        )
    if "reason" in overall:
        task_fields.append(text_field("整体归因"))
    if "review_label" in overall:
        task_fields.append(
            select_field(
                "整体Review标签", overall_options.get("review_labels", [])
            )
        )
    if "review_reason" in overall:
        task_fields.append(text_field("整体Review归因"))
    if manifest["schema"].get("arbitration_columns"):
        task_fields.extend(
            [
                select_field(
                    "整体仲裁标签",
                    options.get("overall_arbitration_labels", []),
                ),
                text_field("整体仲裁原因"),
            ]
        )
    output_fields.append(number_field("MOS"))
    return {
        "批次": [
            text_field("批次ID"),
            text_field("源表ID"),
            text_field("源版本"),
            text_field("模板"),
            text_field("目标评分组"),
            text_field("标注人原文"),
            select_field("状态", ["准备中", "标注中", "待回写", "已回写"]),
            text_field("创建时间"),
        ],
        "任务": task_fields,
        "输出评分": output_fields,
    }


def result_status(result: dict[str, Any]) -> str:
    if result.get("saved_at"):
        return "已提交"
    changed = bool(result.get("updated_at"))
    return "进行中" if changed else "未开始"


def build_package(
    manifest: dict[str, Any],
    tasks: dict[str, Any],
    results: dict[str, Any],
) -> dict[str, Any]:
    validate_session(manifest, tasks, results)
    package = package_id(manifest, tasks)
    dimensions = manifest["schema"]["dimensions"]
    fields = build_fields(manifest)
    result_rows = results["rows"]
    task_records = []
    output_records = []
    mapping: dict[str, Any] = {"task_rows": {}, "dimensions": {}}
    for index, dimension in enumerate(dimensions, start=1):
        mapping["dimensions"][dimension["key"]] = {
            "index": index,
            "name": dimension["name"],
        }

    for task in tasks["rows"]:
        row_key = str(task["row"])
        task_id = f"{package}:row:{row_key}"
        result = result_rows[row_key]
        mapping["task_rows"][task_id] = task["row"]
        record = {
            "任务ID": task_id,
            "批次ID": package,
            "源行号": task["row"],
            "案例ID": str(task["id"]),
            "Prompt": task.get("prompt", ""),
            "Prompt原文": task.get("prompt_original", ""),
            "参考素材JSON": json_text(
                [
                    {"url": url, "kind": kind}
                    for url, kind in zip(
                        task.get("references", []),
                        task.get("reference_kinds", []),
                    )
                ]
            ),
            "标注人原文": task.get("annotator", ""),
            "状态": [result_status(result)],
            "历史对比JSON": json_text(
                {
                    "dimensions": {
                        key: value.get("comparisons", [])
                        for key, value in task.get("dimensions", {}).items()
                    },
                    "mos": task.get("comparison_mos", []),
                }
            ),
            "提交时间": result.get("saved_at") or "",
        }
        for dimension_index, dimension in enumerate(dimensions, start=1):
            key = dimension["key"]
            values = result["dimensions"][key]
            editable = set(dimension["editable_fields"])
            if "tags" in editable:
                record[field_name(dimension_index, dimension, "标签")] = values["tags"]
            if "reason" in editable:
                record[field_name(dimension_index, dimension, "归因")] = values["reason"]
            if "review_label" in editable:
                label = values["review_label"]
                record[field_name(dimension_index, dimension, "Review标签")] = (
                    [label] if label else []
                )
            if "review_reason" in editable:
                record[field_name(dimension_index, dimension, "Review归因")] = values[
                    "review_reason"
                ]
            if "arbitration_label" in editable:
                label = values["arbitration_label"]
                record[field_name(dimension_index, dimension, "仲裁标签")] = (
                    [label] if label else []
                )
        overall = result.get("overall", {})
        for source, target in (
            ("tags", "整体标签"),
            ("reason", "整体归因"),
            ("review_reason", "整体Review归因"),
        ):
            if source in overall:
                record[target] = overall[source]
        if "review_label" in overall:
            record["整体Review标签"] = (
                [overall["review_label"]] if overall["review_label"] else []
            )
        if "arbitration" in result:
            record["整体仲裁标签"] = (
                [result["arbitration"]["label"]]
                if result["arbitration"]["label"]
                else []
            )
            record["整体仲裁原因"] = result["arbitration"]["reason"]
        task_records.append(record)

        for output_index, output_url in enumerate(task.get("outputs", []), start=1):
            output_record = {
                "输出评分ID": f"{task_id}:output:{output_index}",
                "任务ID": task_id,
                "输出序号": output_index,
                "媒体类型": [
                    task.get("output_kinds", ["image"] * len(task["outputs"]))[
                        output_index - 1
                    ]
                ],
                "输出地址": output_url,
                "MOS": score_number(result["mos"][output_index - 1]),
            }
            for dimension_index, dimension in enumerate(dimensions, start=1):
                key = dimension["key"]
                output_record[
                    field_name(dimension_index, dimension, "人评分")
                ] = score_select(
                    result["dimensions"][key]["human_score"][output_index - 1]
                )
                machine_scores = task["dimensions"][key].get("machine_score", [])
                output_record[
                    field_name(dimension_index, dimension, "机评分")
                ] = (
                    str(machine_scores[output_index - 1])
                    if output_index <= len(machine_scores)
                    else ""
                )
            output_records.append(output_record)

    source = manifest["source"]
    return {
        "version": 1,
        "package_id": package,
        "generated_at": utc_now(),
        "source_snapshot": {
            "sheet_id": source["sheet_id"],
            "revision": source["revision"],
            "target_group": manifest["schema"]["target_group"],
        },
        "tables": {
            "批次": {
                "fields": fields["批次"],
                "records": [
                    {
                        "批次ID": package,
                        "源表ID": source["sheet_id"],
                        "源版本": str(source["revision"]),
                        "模板": manifest["schema"]["template_layout"],
                        "目标评分组": manifest["schema"]["target_group"],
                        "标注人原文": manifest["assignment"].get("annotator") or "",
                        "状态": ["准备中"],
                        "创建时间": manifest.get("created_at", ""),
                    }
                ],
            },
            "任务": {
                "fields": fields["任务"],
                "records": task_records,
            },
            "输出评分": {
                "fields": fields["输出评分"],
                "records": output_records,
            },
        },
        "mapping": mapping,
    }


def score_number(value: Any) -> int | float | None:
    text = str(value or "").strip()
    if not text:
        return None
    number = float(text)
    return int(number) if number.is_integer() else number


def score_select(value: Any) -> list[str]:
    text = str(value or "").strip()
    return [text] if text else []


def select_scalar(value: Any, location: str) -> str:
    if value in (None, "", []):
        return ""
    if not isinstance(value, list) or len(value) != 1:
        raise BridgeError(f"{location} 必须是零个或一个选项")
    return str(value[0])


def import_results(
    manifest: dict[str, Any],
    tasks: dict[str, Any],
    baseline_results: dict[str, Any],
    package: dict[str, Any],
) -> dict[str, Any]:
    validate_session(manifest, tasks, baseline_results)
    expected_id = package_id(manifest, tasks)
    if package.get("package_id") != expected_id:
        raise BridgeError("Base 数据包与当前 EvalDesk 会话不匹配")
    snapshot = package.get("source_snapshot", {})
    expected_snapshot = {
        "sheet_id": manifest["source"]["sheet_id"],
        "revision": manifest["source"]["revision"],
        "target_group": manifest["schema"]["target_group"],
    }
    if any(
        str(snapshot.get(key)) != str(value)
        for key, value in expected_snapshot.items()
    ):
        raise BridgeError("Base 数据包的源表快照与当前会话不一致")

    task_records = package.get("tables", {}).get("任务", {}).get("records", [])
    output_records = (
        package.get("tables", {}).get("输出评分", {}).get("records", [])
    )
    task_by_id = {}
    for record in task_records:
        task_id = record.get("任务ID")
        if not task_id or task_id in task_by_id:
            raise BridgeError("任务表存在空任务ID或重复任务ID")
        task_by_id[task_id] = record
    outputs_by_task: dict[str, dict[int, dict[str, Any]]] = {}
    for record in output_records:
        task_id = record.get("任务ID")
        try:
            output_index = int(record.get("输出序号"))
        except (TypeError, ValueError) as exc:
            raise BridgeError("输出评分表存在非法输出序号") from exc
        indexed = outputs_by_task.setdefault(task_id, {})
        if output_index in indexed:
            raise BridgeError(f"{task_id} 存在重复输出序号 {output_index}")
        indexed[output_index] = record

    converted = copy.deepcopy(baseline_results)
    dimensions = manifest["schema"]["dimensions"]
    expected_task_ids = {
        f"{expected_id}:row:{task['row']}" for task in tasks["rows"]
    }
    if set(task_by_id) != expected_task_ids:
        raise BridgeError("任务表中的任务集合与当前会话不一致")
    if set(outputs_by_task) != expected_task_ids:
        raise BridgeError("输出评分表中的任务集合与当前会话不一致")
    for task in tasks["rows"]:
        row_key = str(task["row"])
        task_id = f"{expected_id}:row:{row_key}"
        task_record = task_by_id[task_id]
        output_map = outputs_by_task.get(task_id, {})
        expected_indices = set(range(1, len(task["outputs"]) + 1))
        if set(output_map) != expected_indices:
            raise BridgeError(f"第 {row_key} 行输出评分记录不完整")
        result = converted["rows"][row_key]
        result["mos"] = [
            "" if output_map[index].get("MOS") is None else str(output_map[index]["MOS"])
            for index in sorted(output_map)
        ]
        for dimension_index, dimension in enumerate(dimensions, start=1):
            key = dimension["key"]
            values = result["dimensions"][key]
            editable = set(dimension["editable_fields"])
            values["human_score"] = [
                select_scalar(
                    output_map[index].get(
                        field_name(dimension_index, dimension, "人评分"), []
                    ),
                    f"第 {row_key} 行输出 {index} {dimension['name']}人评分",
                )
                for index in sorted(output_map)
            ]
            if "tags" in editable:
                tags = task_record.get(
                    field_name(dimension_index, dimension, "标签"), []
                )
                if not isinstance(tags, list):
                    raise BridgeError(f"第 {row_key} 行 {dimension['name']}标签必须是数组")
                values["tags"] = [str(item) for item in tags]
            if "reason" in editable:
                values["reason"] = str(
                    task_record.get(
                        field_name(dimension_index, dimension, "归因"), ""
                    )
                    or ""
                )
            if "review_label" in editable:
                values["review_label"] = select_scalar(
                    task_record.get(
                        field_name(dimension_index, dimension, "Review标签"), []
                    ),
                    f"第 {row_key} 行 {dimension['name']}Review标签",
                )
            if "review_reason" in editable:
                values["review_reason"] = str(
                    task_record.get(
                        field_name(dimension_index, dimension, "Review归因"), ""
                    )
                    or ""
                )
            if "arbitration_label" in editable:
                values["arbitration_label"] = select_scalar(
                    task_record.get(
                        field_name(dimension_index, dimension, "仲裁标签"), []
                    ),
                    f"第 {row_key} 行 {dimension['name']}仲裁标签",
                )
        overall = result.get("overall", {})
        for source, target in (
            ("tags", "整体标签"),
            ("reason", "整体归因"),
            ("review_reason", "整体Review归因"),
        ):
            if source in overall:
                raw = task_record.get(target, [] if source == "tags" else "")
                overall[source] = (
                    [str(item) for item in raw]
                    if source == "tags" and isinstance(raw, list)
                    else str(raw or "")
                )
        if "review_label" in overall:
            overall["review_label"] = select_scalar(
                task_record.get("整体Review标签", []),
                f"第 {row_key} 行整体Review标签",
            )
        if "arbitration" in result:
            result["arbitration"] = {
                "label": select_scalar(
                    task_record.get("整体仲裁标签", []),
                    f"第 {row_key} 行整体仲裁标签",
                ),
                "reason": str(task_record.get("整体仲裁原因", "") or ""),
            }
        if select_scalar(task_record.get("状态", []), f"第 {row_key} 行状态") == "已提交":
            result["saved_at"] = task_record.get("提交时间") or utc_now()
        result["updated_at"] = utc_now()
    converted["updated_at"] = utc_now()
    return converted


def load_session(directory: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        read_json(directory / "manifest.json"),
        read_json(directory / "tasks.json"),
        read_json(directory / "results.json"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="生成 Base 字段与记录数据包")
    export.add_argument("--session", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    collect = commands.add_parser("import", help="把 Base 数据包还原为 results.json")
    collect.add_argument("--session", type=Path, required=True)
    collect.add_argument("--package", type=Path, required=True)
    collect.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        manifest, tasks, results = load_session(args.session)
        if args.command == "export":
            value = build_package(manifest, tasks, results)
        else:
            value = import_results(
                manifest, tasks, results, read_json(args.package)
            )
        write_json(args.output, value)
    except BridgeError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
