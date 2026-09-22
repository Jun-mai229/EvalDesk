#!/usr/bin/env python3
"""Build and safely import portable review packages for the Feishu-hosted UI."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class BundleError(ValueError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError(f"无法读取 JSON：{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BundleError(f"JSON 顶层必须是对象：{path}")
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


def validate_session(
    manifest: dict[str, Any],
    tasks: dict[str, Any],
    results: dict[str, Any],
) -> None:
    if manifest.get("version") != 2:
        raise BundleError("只支持 manifest version 2")
    if tasks.get("version") != 2 or results.get("version") != 2:
        raise BundleError("只支持 tasks/results version 2")
    if not manifest.get("schema", {}).get("supported"):
        raise BundleError("模板未通过 EvalDesk 诊断")
    task_rows = {str(item["row"]) for item in tasks.get("rows", [])}
    if task_rows != set(results.get("rows", {})):
        raise BundleError("tasks 与 results 的物理行集合不一致")


def package_id(manifest: dict[str, Any], tasks: dict[str, Any]) -> str:
    identity = {
        "sheet_id": manifest["source"]["sheet_id"],
        "revision": manifest["source"]["revision"],
        "target_group": manifest["schema"].get("target_group"),
        "rows": [item["row"] for item in tasks["rows"]],
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"edr-{digest}"


def public_dimension(dimension: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": dimension["key"],
        "name": dimension["name"],
        "editable_fields": list(dimension["editable_fields"]),
    }


def public_task(task: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "row",
        "id",
        "kind",
        "prompt",
        "prompt_original",
        "references",
        "reference_kinds",
        "outputs",
        "output_kinds",
        "dimensions",
        "mos",
        "comparison_mos",
        "expert_values",
        "overall",
        "arbitration",
    )
    return {key: copy.deepcopy(task[key]) for key in keys if key in task}


def build_bundle(
    manifest: dict[str, Any],
    tasks: dict[str, Any],
    results: dict[str, Any],
) -> dict[str, Any]:
    validate_session(manifest, tasks, results)
    schema = manifest["schema"]
    source = manifest["source"]
    bundle_id = package_id(manifest, tasks)
    return {
        "bundle_version": 1,
        "package_id": bundle_id,
        "created_at": utc_now(),
        "source_snapshot": {
            "sheet_id": source["sheet_id"],
            "revision": source["revision"],
            "sheet_name": source.get("sheet_name", "评测任务"),
        },
        "schema": {
            "template_layout": schema["template_layout"],
            "dimensions": [
                public_dimension(item) for item in schema["dimensions"]
            ],
            "blind": bool(schema.get("blind")),
            "has_arbitration": bool(schema.get("arbitration_columns")),
            "overall_fields": list(schema.get("overall_columns", {})),
        },
        "options": copy.deepcopy(manifest["options"]),
        "tasks": [public_task(item) for item in tasks["rows"]],
        "baseline_results": copy.deepcopy(results),
    }


def validate_export(
    manifest: dict[str, Any],
    tasks: dict[str, Any],
    exported: dict[str, Any],
) -> dict[str, Any]:
    if exported.get("version") != 2 or not isinstance(exported.get("rows"), dict):
        raise BundleError("导出文件不是 EvalDesk results version 2")
    expected_id = package_id(manifest, tasks)
    export_meta = exported.get("review_package", {})
    if export_meta.get("package_id") != expected_id:
        raise BundleError("任务包 ID 不匹配，拒绝合并")
    source = manifest["source"]
    if str(export_meta.get("source_revision")) != str(source["revision"]):
        raise BundleError("源表快照版本不匹配，拒绝合并")
    if export_meta.get("sheet_id") != source["sheet_id"]:
        raise BundleError("源表 ID 不匹配，拒绝合并")
    expected_rows = {str(item["row"]) for item in tasks["rows"]}
    if set(exported["rows"]) != expected_rows:
        raise BundleError("导出结果的任务行集合不匹配")
    return {
        "version": 2,
        "updated_at": exported.get("updated_at") or utc_now(),
        "rows": copy.deepcopy(exported["rows"]),
    }


def load_session(session: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        read_json(session / "manifest.json"),
        read_json(session / "tasks.json"),
        read_json(session / "results.json"),
    )


def command_build(args: argparse.Namespace) -> None:
    manifest, tasks, results = load_session(args.session)
    bundle = build_bundle(manifest, tasks, results)
    write_json(args.output, bundle)
    print(json.dumps({
        "output": str(args.output),
        "package_id": bundle["package_id"],
        "tasks": len(bundle["tasks"]),
        "source_revision": bundle["source_snapshot"]["revision"],
    }, ensure_ascii=False, indent=2))


def command_import(args: argparse.Namespace) -> None:
    manifest, tasks, _results = load_session(args.session)
    exported = read_json(args.input)
    merged = validate_export(manifest, tasks, exported)
    output = args.output or args.session / "results.json"
    write_json(output, merged)
    print(json.dumps({
        "output": str(output),
        "rows": len(merged["rows"]),
        "source_revision": manifest["source"]["revision"],
    }, ensure_ascii=False, indent=2))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="从 EvalDesk 会话生成脱敏任务包")
    build.add_argument("--session", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.set_defaults(handler=command_build)
    load = commands.add_parser("import", help="校验并导入前端导出的 results.json")
    load.add_argument("--session", type=Path, required=True)
    load.add_argument("--input", type=Path, required=True)
    load.add_argument("--output", type=Path)
    load.set_defaults(handler=command_import)
    return root


def main() -> None:
    args = parser().parse_args()
    try:
        args.handler(args)
    except BundleError as exc:
        raise SystemExit(f"错误：{exc}") from exc


if __name__ == "__main__":
    main()
