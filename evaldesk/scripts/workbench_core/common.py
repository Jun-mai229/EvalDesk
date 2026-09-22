"""Shared filesystem, CLI, and Feishu helpers."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RANGE = "auto"
DIMENSION_FIELDS = [
    "人评打分",
    "打分标签",
    "打分归因",
    "机评分数",
    "人机review打签",
    "review归因",
]
FIELD_KEYS = [
    "human_score",
    "tags",
    "reason",
    "machine_score",
    "review_label",
    "review_reason",
]
EDITABLE_FIELDS = [
    "human_score",
    "tags",
    "reason",
    "review_label",
    "review_reason",
]
ARBITRATION_EDITABLE_FIELDS = [
    "human_score",
    "tags",
    "arbitration_label",
    "reason",
    "review_label",
    "review_reason",
]
EXPECTED_DIMENSIONS = [
    "指令跟随",
    "参考遵循",
    "一致性保持",
    "视觉质量",
    "文字质量",
    "音频质量",
    "剪辑质量",
    "创意实现",
]
ARBITRATION_DIMENSIONS = [
    "指令跟随",
    "参考遵循",
    "画面质量",
    "文字质量",
    "视觉审美",
]

class WorkbenchError(RuntimeError):
    pass


def find_lark_cli() -> str | None:
    return shutil.which("lark-cli")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkbenchError(f"缺少文件: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkbenchError(f"JSON 文件损坏: {path}: {exc}") from exc


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def run_lark(args: list[str]) -> dict[str, Any]:
    executable = find_lark_cli()
    if executable is None:
        raise WorkbenchError("未找到 lark-cli，请先安装并登录")
    env = os.environ.copy()
    env["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
    env["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
    try:
        result = subprocess.run(
            [executable, *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except FileNotFoundError as exc:
        raise WorkbenchError("未找到 lark-cli，请先安装并登录") from exc
    except subprocess.TimeoutExpired as exc:
        raise WorkbenchError("lark-cli 请求超时") from exc
    if result.returncode != 0:
        raise WorkbenchError(result.stderr.strip() or result.stdout.strip())
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise WorkbenchError(f"lark-cli 返回了非 JSON 内容: {result.stdout[:300]}") from exc
    if not payload.get("ok"):
        error = payload.get("error", {})
        raise WorkbenchError(error.get("message") or json.dumps(error, ensure_ascii=False))
    return payload


def parse_sheet_id(url: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    values = parse_qs(urlparse(url).query).get("sheet", [])
    if values and values[0]:
        return values[0]
    raise WorkbenchError("链接中没有 sheet 参数，请传入 --sheet-id")


def column_number(column: str) -> int:
    value = 0
    for char in column.upper():
        if not "A" <= char <= "Z":
            raise WorkbenchError(f"非法列字母: {column}")
        value = value * 26 + ord(char) - 64
    return value


def find_available_port(start: int = 4180, attempts: int = 100) -> int:
    if not 0 <= start <= 65535:
        raise WorkbenchError(f"端口超出范围: {start}")
    candidates = [0] if start == 0 else range(start, min(start + attempts, 65536))
    for port in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return int(sock.getsockname()[1])
    raise WorkbenchError(f"从端口 {start} 开始未找到可用端口")
