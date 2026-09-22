"""Runtime preflight checks for the local workbench."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import webbrowser
from pathlib import Path
from typing import Any

from .common import (
    APP_ROOT,
    WorkbenchError,
    find_available_port,
    find_lark_cli,
    parse_sheet_id,
    run_lark,
)

MINIMUM_PYTHON = (3, 9)
REQUIRED_ASSETS = ("index.html", "styles.css", "app.js")
CHECK_LABELS = {
    "python": "Python",
    "lark_cli": "lark-cli",
    "assets": "界面资源",
    "session_directory": "会话目录",
    "local_port": "本地端口",
    "browser": "浏览器",
    "feishu_access": "飞书访问",
}


def check_environment(
    url: str | None = None,
    sheet_id: str | None = None,
    session_root: str | None = None,
    port: int = 4180,
    check_browser: bool = True,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    python_ok = sys.version_info >= MINIMUM_PYTHON
    checks.append(
        {
            "name": "python",
            "ok": python_ok,
            "detail": ".".join(str(item) for item in sys.version_info[:3]),
            "required": ">=3.9",
        }
    )

    cli_path = find_lark_cli()
    cli_detail = cli_path or "not found"
    cli_ok = cli_path is not None
    if cli_path:
        try:
            completed = subprocess.run(
                [cli_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            cli_ok = completed.returncode == 0
            cli_detail = (completed.stdout or completed.stderr).strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            cli_ok = False
            cli_detail = str(exc)
    checks.append({"name": "lark_cli", "ok": cli_ok, "detail": cli_detail})

    asset_dir = APP_ROOT / "assets" / "workbench"
    missing_assets = [
        name for name in REQUIRED_ASSETS if not (asset_dir / name).is_file()
    ]
    checks.append(
        {
            "name": "assets",
            "ok": not missing_assets,
            "detail": "ok" if not missing_assets else f"missing: {missing_assets}",
        }
    )

    target_root = (
        Path(session_root).expanduser().resolve()
        if session_root
        else Path.home() / ".evaldesk" / "sessions"
    )
    writable = True
    writable_detail = str(target_root)
    try:
        target_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target_root):
            pass
    except OSError as exc:
        writable = False
        writable_detail = str(exc)
    checks.append(
        {"name": "session_directory", "ok": writable, "detail": writable_detail}
    )

    selected_port = None
    try:
        selected_port = find_available_port(port)
        port_detail = str(selected_port)
        port_ok = True
    except WorkbenchError as exc:
        port_detail = str(exc)
        port_ok = False
    checks.append({"name": "local_port", "ok": port_ok, "detail": port_detail})

    browser_ok = True
    browser_detail = "not checked"
    if check_browser:
        try:
            browser_detail = webbrowser.get().name
        except webbrowser.Error as exc:
            browser_ok = False
            browser_detail = str(exc)
    checks.append(
        {
            "name": "browser",
            "ok": browser_ok,
            "blocking": False,
            "detail": browser_detail,
        }
    )

    source_detail = "not checked; pass --url to verify login and access"
    source_ok = True
    if url and cli_ok:
        try:
            resolved_sheet_id = parse_sheet_id(url, sheet_id)
            payload = run_lark(
                ["sheets", "+workbook-info", "--url", url, "--as", "user"]
            )
            sheets = payload.get("data", {}).get("sheets", [])
            match = next(
                (
                    item
                    for item in sheets
                    if str(item.get("sheet_id")) == resolved_sheet_id
                ),
                None,
            )
            if match is None:
                source_ok = False
                source_detail = f"工作簿中不存在子表 {resolved_sheet_id}"
            elif match.get("resource_type") != "sheet":
                source_ok = False
                source_detail = f"子表类型不受支持: {match.get('resource_type')}"
            else:
                title = match.get("title") or match.get("sheet_name") or resolved_sheet_id
                source_detail = f"可访问: {title} ({resolved_sheet_id})"
        except WorkbenchError as exc:
            source_ok = False
            source_detail = str(exc)
    checks.append(
        {
            "name": "feishu_access",
            "ok": source_ok,
            "detail": source_detail,
        }
    )

    blocking_failures = [
        item["name"]
        for item in checks
        if not item["ok"] and item.get("blocking", True)
    ]
    return {
        "ok": not blocking_failures,
        "checks": checks,
        "selected_port": selected_port,
        "blocking_failures": blocking_failures,
    }


def command_doctor(args: argparse.Namespace) -> int:
    report = check_environment(
        url=args.url,
        sheet_id=args.sheet_id,
        session_root=args.session_root,
        port=args.port,
        check_browser=not args.no_browser_check,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def setup_next_steps(
    report: dict[str, Any], url: str | None = None
) -> list[str]:
    checks = {item["name"]: item for item in report["checks"]}
    steps: list[str] = []
    if not checks["python"]["ok"]:
        steps.append("安装 Python 3.9 或更高版本，然后重新运行 evaldesk setup。")
    if not checks["lark_cli"]["ok"]:
        steps.append("安装 lark-cli，并确认在终端执行 lark-cli --version 能成功。")
    if not checks["session_directory"]["ok"]:
        steps.append(
            "选择可写目录，并用 evaldesk setup --session-root '<目录>' 重新检查。"
        )
    if not checks["local_port"]["ok"]:
        steps.append("通过 --port 指定其他本地端口。")
    if not checks["feishu_access"]["ok"]:
        steps.append(
            "运行 lark-cli auth status --json --verify 检查登录，再按错误提示补齐权限。"
        )
    if not checks["browser"]["ok"]:
        steps.append("安装或设置默认浏览器；也可以在启动时使用 --no-open。")
    if report["ok"] and not url:
        steps.extend(
            [
                "运行 lark-cli auth status --json --verify 检查当前用户身份。",
                "运行 evaldesk setup --url '<飞书表格链接>' --no-browser-check 验证表格访问。",
            ]
        )
    elif report["ok"]:
        steps.append(
            "运行 evaldesk diagnose --url '<飞书表格链接>' 检查模板兼容性。"
        )
    return steps


def command_setup(args: argparse.Namespace) -> int:
    report = check_environment(
        url=args.url,
        sheet_id=args.sheet_id,
        session_root=args.session_root,
        port=args.port,
        check_browser=not args.no_browser_check,
    )
    report["next_steps"] = setup_next_steps(report, args.url)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1

    print("EvalDesk 环境检查")
    for item in report["checks"]:
        skipped = str(item["detail"]).startswith("not checked")
        marker = "跳过" if skipped else ("通过" if item["ok"] else "失败")
        label = CHECK_LABELS.get(item["name"], item["name"])
        print(f"[{marker}] {label}: {item['detail']}")
    print()
    print("下一步")
    for index, step in enumerate(report["next_steps"], start=1):
        print(f"{index}. {step}")
    return 0 if report["ok"] else 1
