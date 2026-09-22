#!/usr/bin/env python3
"""Stop the local server associated with a prepared session."""

from workbench_core.cli import run_subcommand


if __name__ == "__main__":
    raise SystemExit(run_subcommand("stop"))
