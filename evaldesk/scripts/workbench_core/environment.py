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
