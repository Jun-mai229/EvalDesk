"""One-command environment check, session preparation, and server launch."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .common import WorkbenchError, parse_sheet_id
from .environment import check_environment
from .server import command_serve
from .template import command_prepare, default_session_dir


def command_launch(args: argparse.Namespace) -> int:
    sheet_id = parse_sheet_id(args.url, args.sheet_id)
    session = (
        Path(args.session).expanduser().resolve()
        if args.session
        else default_session_dir(sheet_id)
    )
    report = check_environment(
        url=args.url,
        sheet_id=sheet_id,
        session_root=str(session.parent),
        port=args.port,
        check_browser=not args.no_open,
    )
    print(
        json.dumps(
            {
                "preflight": "passed" if report["ok"] else "failed",
                "checks": report["checks"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not report["ok"]:
        raise WorkbenchError(
            "环境检查未通过: " + ", ".join(report["blocking_failures"])
        )

    prepare_args = argparse.Namespace(
        url=args.url,
        sheet_id=sheet_id,
        annotator=args.annotator,
        include_unassigned=args.include_unassigned,
        range=args.range,
        validation_end_row=args.validation_end_row,
        session=str(session),
        force=args.force,
        target_group=args.target_group,
        blind=args.blind,
        aliases=args.aliases,
    )
    prepared = command_prepare(prepare_args)
    if prepared != 0:
        return prepared

    serve_args = argparse.Namespace(
        session=str(session),
        port=report["selected_port"],
        no_open=args.no_open,
    )
    return command_serve(serve_args)
