#!/usr/bin/env python3
"""Run the offline template and write-preview contract checks."""

from workbench_core.cli import run_subcommand


if __name__ == "__main__":
    raise SystemExit(run_subcommand("self-test"))
