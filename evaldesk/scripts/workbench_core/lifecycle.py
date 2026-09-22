"""Safe local server lifecycle operations."""
from __future__ import annotations

import argparse
import json
import os
import signal
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from .common import WorkbenchError, read_json


def command_stop(args: argparse.Namespace) -> int:
    session = Path(args.session).expanduser().resolve()
    state_path = session / "server.json"
    state = read_json(state_path)
    manifest = read_json(session / "manifest.json")
    pid = state.get("pid")
    url = state.get("url")
    if not isinstance(pid, int) or not isinstance(url, str):
        raise WorkbenchError("server.json 缺少有效的 pid 或 url")

    try:
        with urlopen(f"{url}/api/session", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        live_sheet = payload["manifest"]["source"]["sheet_id"]
        expected_sheet = manifest["source"]["sheet_id"]
        if str(live_sheet) != str(expected_sheet):
            raise WorkbenchError("端口上的服务不属于该会话，拒绝停止")
    except (URLError, TimeoutError, KeyError, json.JSONDecodeError):
        try:
            os.kill(pid, 0)
        except OSError:
            state_path.unlink(missing_ok=True)
            print(json.dumps({"stopped": True, "already_stopped": True}))
            return 0
        raise WorkbenchError("无法验证正在运行的服务，拒绝按 PID 停止")

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        raise WorkbenchError(f"停止服务失败: {exc}") from exc
    print(json.dumps({"stopped": True, "pid": pid, "url": url}, ensure_ascii=False))
    return 0
