"""Safe local server lifecycle operations."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from .common import WorkbenchError, read_json


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return ctypes.get_last_error() == 5
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def command_stop(args: argparse.Namespace) -> int:
    session = Path(args.session).expanduser().resolve()
    state_path = session / "server.json"
    state = read_json(state_path)
    manifest = read_json(session / "manifest.json")
    pid = state.get("pid")
    url = state.get("url")
    stop_token = state.get("stop_token")
    if (
        not isinstance(pid, int)
        or not isinstance(url, str)
        or not isinstance(stop_token, str)
    ):
        raise WorkbenchError(
            "server.json 来自旧版本或格式无效；请在原启动终端按 Ctrl+C 停止服务"
        )

    try:
        with urlopen(f"{url}/api/session", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        live_sheet = payload["manifest"]["source"]["sheet_id"]
        expected_sheet = manifest["source"]["sheet_id"]
        if str(live_sheet) != str(expected_sheet):
            raise WorkbenchError("端口上的服务不属于该会话，拒绝停止")
    except (URLError, TimeoutError, KeyError, json.JSONDecodeError):
        if not process_exists(pid):
            state_path.unlink(missing_ok=True)
            print(json.dumps({"stopped": True, "already_stopped": True}))
            return 0
        raise WorkbenchError("无法验证正在运行的服务，拒绝按 PID 停止")

    try:
        body = json.dumps({"token": stop_token}).encode("utf-8")
        request = Request(
            f"{url}/api/stop",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            stopped = json.loads(response.read().decode("utf-8"))
        if stopped.get("stopped") is not True:
            raise WorkbenchError("服务未确认停止")
    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise WorkbenchError(f"停止服务失败: {exc}") from exc
    print(json.dumps({"stopped": True, "pid": pid, "url": url}, ensure_ascii=False))
    return 0
