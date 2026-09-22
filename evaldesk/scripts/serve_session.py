#!/usr/bin/env python3
"""Serve a prepared evaluation session on localhost."""

from workbench_core.cli import run_subcommand


if __name__ == "__main__":
    raise SystemExit(run_subcommand("serve"))
