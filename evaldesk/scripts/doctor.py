#!/usr/bin/env python3
"""Check local runtime requirements and optional Feishu access."""

from workbench_core.cli import run_subcommand


if __name__ == "__main__":
    raise SystemExit(run_subcommand("doctor"))
