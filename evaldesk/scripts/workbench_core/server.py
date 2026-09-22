"""Local HTTP server for a prepared scoring session."""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import signal
import sys
import threading
import webbrowser
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .common import (
    APP_ROOT,
    WorkbenchError,
    atomic_json,
    find_available_port,
    read_json,
    utc_now,
)

ASSET_DIR = APP_ROOT / "assets" / "workbench"

def validate_browser_payload(
    payload: Any,
    tasks: dict[str, Any],
    existing: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), dict):
        raise WorkbenchError("浏览器结果格式非法")
    task_map = {str(item["row"]): item for item in tasks.get("rows", [])}
    allowed_rows = set(task_map)
    if set(payload["rows"]) - allowed_rows:
        raise WorkbenchError("浏览器提交了会话外行号")
    merged = deepcopy(existing)
    for row, value in payload["rows"].items():
        if not isinstance(value, dict):
            raise WorkbenchError(f"第 {row} 行结果格式非法")
        expected = existing.get("rows", {}).get(row)
        if not isinstance(expected, dict):
            raise WorkbenchError(f"第 {row} 行缺少本地结果基线")
        expected_fields = set(expected) | {"saved_at", "blind_snapshot"}
        if set(value) - expected_fields:
            raise WorkbenchError(f"第 {row} 行包含未知结果字段")
        missing_fields = expected_fields - {"updated_at", "saved_at", "blind_snapshot"} - set(value)
        if missing_fields:
            raise WorkbenchError(f"第 {row} 行缺少结果字段: {sorted(missing_fields)}")
        saved_at = value.get("saved_at")
        if saved_at is not None and not isinstance(saved_at, str):
            raise WorkbenchError(f"第 {row} 行保存标记格式非法")
        if expected.get("blind_snapshot") and value.get("blind_snapshot") != expected["blind_snapshot"]:
            raise WorkbenchError(f"第 {row} 行已留档的独立评分不可删除或覆盖")
        if "blind_snapshot" in value:
            snapshot = value["blind_snapshot"]
            if not isinstance(snapshot, dict) or set(snapshot) != {"dimensions", "mos", "saved_at"}:
                raise WorkbenchError(f"第 {row} 行盲评快照结构非法")
        dimensions = value.get("dimensions")
        if not isinstance(dimensions, dict) or set(dimensions) != set(
            expected.get("dimensions", {})
        ):
            raise WorkbenchError(f"第 {row} 行维度结构非法")
        output_count = len(task_map[row].get("outputs", []))
        if not isinstance(value.get("mos"), list) or (len(value["mos"]) != output_count and value["mos"] != expected["mos"]):
            raise WorkbenchError(f"第 {row} 行 MOS 数量与输出数量不一致")
        for key, dimension in dimensions.items():
            expected_fields = set(expected["dimensions"][key])
            if not isinstance(dimension, dict) or set(dimension) != expected_fields:
                raise WorkbenchError(f"第 {row} 行维度 {key} 字段结构非法")
            scores = dimension.get("human_score")
            if not isinstance(scores, list) or (len(scores) != output_count and scores != expected["dimensions"][key]["human_score"]):
                raise WorkbenchError(
                    f"第 {row} 行维度 {key} 的分数数量与输出数量不一致"
                )
        if "overall" in expected and (
            not isinstance(value.get("overall"), dict)
            or set(value["overall"]) != set(expected["overall"])
        ):
            raise WorkbenchError(f"第 {row} 行 MOS 附加字段结构非法")
        if "arbitration" in expected:
            arbitration = value.get("arbitration")
            if not isinstance(arbitration, dict) or set(arbitration) != {
                "label",
                "reason",
            }:
                raise WorkbenchError(f"第 {row} 行整体仲裁结构非法")
        merged["rows"][row] = value
        merged["rows"][row]["updated_at"] = utc_now()
    merged["version"] = 2
    merged["updated_at"] = utc_now()
    return merged


def make_handler(session: Path):
    write_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format_string: str, *args: Any) -> None:
            sys.stdout.write(
                "%s - - [%s] %s\n"
                % (self.address_string(), self.log_date_time_string(), format_string % args)
            )

        def send_bytes(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, status: int, payload: Any) -> None:
            self.send_bytes(
                status,
                "application/json; charset=utf-8",
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            static_files = {
                "/": "index.html",
                "/index.html": "index.html",
                "/styles.css": "styles.css",
                "/app.js": "app.js",
            }
            asset_name = static_files.get(path)
            if asset_name:
                asset = ASSET_DIR / asset_name
                content_type = (
                    mimetypes.guess_type(asset.name)[0]
                    or "application/octet-stream"
                )
                if content_type.startswith("text/") or content_type == (
                    "application/javascript"
                ):
                    content_type += "; charset=utf-8"
                self.send_bytes(200, content_type, asset.read_bytes())
                return
            if path == "/api/session":
                try:
                    self.send_json(
                        200,
                        {
                            "manifest": read_json(session / "manifest.json"),
                            "tasks": read_json(session / "tasks.json"),
                            "results": read_json(session / "results.json"),
                        },
                    )
                except WorkbenchError as exc:
                    self.send_json(500, {"error": str(exc)})
                return
            self.send_json(404, {"error": "Not found"})

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/results":
                self.send_json(404, {"error": "Not found"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size > 5_000_000:
                    raise WorkbenchError("请求体过大")
                payload = json.loads(self.rfile.read(size))
                with write_lock:
                    tasks = read_json(session / "tasks.json")
                    existing = read_json(session / "results.json")
                    merged = validate_browser_payload(payload, tasks, existing)
                    atomic_json(session / "results.json", merged)
                    atomic_json(
                        session / "status.json",
                        {"state": "scoring", "updated_at": utc_now(), "last_error": None},
                    )
                self.send_json(200, {"saved": True, "updated_at": merged["updated_at"]})
            except (WorkbenchError, json.JSONDecodeError, ValueError) as exc:
                self.send_json(400, {"error": str(exc)})

    return Handler


def command_serve(args: argparse.Namespace) -> int:
    session = Path(args.session).resolve()
    manifest = read_json(session / "manifest.json")
    read_json(session / "tasks.json")
    read_json(session / "results.json")
    if not manifest.get("schema", {}).get("supported"):
        raise WorkbenchError("该会话模板校验未通过，不能启动评分工作台")
    missing_assets = [
        name
        for name in ("index.html", "styles.css", "app.js")
        if not (ASSET_DIR / name).exists()
    ]
    if missing_assets:
        raise WorkbenchError(f"缺少 UI 资产: {missing_assets}")
    selected_port = find_available_port(args.port)
    server = ThreadingHTTPServer(
        ("127.0.0.1", selected_port), make_handler(session)
    )
    url = f"http://127.0.0.1:{server.server_port}"
    server_state = session / "server.json"
    atomic_json(
        server_state,
        {
            "pid": os.getpid(),
            "port": server.server_port,
            "url": url,
            "started_at": utc_now(),
        },
    )
    if selected_port != args.port:
        print(f"端口 {args.port} 已占用，自动使用 {selected_port}", flush=True)
    print(f"EvalDesk: {url}", flush=True)
    print(f"本地结果: {session / 'results.json'}", flush=True)
    if not args.no_open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def stop_server(_signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_server)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        server.server_close()
        server_state.unlink(missing_ok=True)
    return 0
