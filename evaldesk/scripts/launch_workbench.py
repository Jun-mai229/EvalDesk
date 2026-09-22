#!/usr/bin/env python3
"""Check the environment, prepare a session, and launch the workbench."""

from workbench_core.cli import run_subcommand


if __name__ == "__main__":
    raise SystemExit(run_subcommand("launch"))
