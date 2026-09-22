"""Distribution and first-run regression tests."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from evaldesk.scripts.workbench_core.environment import (
    check_environment,
    setup_next_steps,
)


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install_skill.py"


def load_installer():
    spec = importlib.util.spec_from_file_location("install_skill", INSTALLER)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load install_skill.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Distribution(unittest.TestCase):
    def test_cli_uses_utf8_with_legacy_console_encoding(self):
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "cp1252"
        result = subprocess.run(
            [sys.executable, "-m", "evaldesk", "--help"],
            cwd=ROOT,
            capture_output=True,
            env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("飞书", result.stdout.decode("utf-8"))

    def test_skill_is_self_contained(self):
        installer = load_installer()
        source = ROOT / "skill" / "evaldesk"
        self.assertEqual(installer.validate_skill(source), "evaldesk")
        self.assertTrue((source / "references" / "installation.md").is_file())
        self.assertTrue((source / "references" / "compatibility.md").is_file())
        self.assertTrue((source / "references" / "windows.md").is_file())
        self.assertTrue((source / "references" / "writeback-safety.md").is_file())

    def test_installer_requires_explicit_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "skills"
            command = [
                sys.executable,
                str(INSTALLER),
                "--target-root",
                str(target),
            ]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertTrue((target / "evaldesk" / "SKILL.md").is_file())

            second = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(second.returncode, 1)
            self.assertIn("--force", second.stdout)

            replaced = subprocess.run(
                [*command, "--force"], capture_output=True, text=True
            )
            self.assertEqual(
                replaced.returncode, 0, replaced.stdout + replaced.stderr
            )

    def test_setup_guidance_for_clean_machine(self):
        report = {
            "ok": False,
            "checks": [
                {"name": "python", "ok": True},
                {"name": "lark_cli", "ok": False},
                {"name": "assets", "ok": True},
                {"name": "session_directory", "ok": True},
                {"name": "local_port", "ok": True},
                {"name": "browser", "ok": True},
                {"name": "feishu_access", "ok": True},
            ],
        }
        steps = setup_next_steps(report)
        self.assertTrue(any("lark-cli" in step for step in steps))

    def test_setup_guidance_after_preflight(self):
        report = {
            "ok": True,
            "checks": [
                {"name": "python", "ok": True},
                {"name": "lark_cli", "ok": True},
                {"name": "assets", "ok": True},
                {"name": "session_directory", "ok": True},
                {"name": "local_port", "ok": True},
                {"name": "browser", "ok": True},
                {"name": "feishu_access", "ok": True},
            ],
        }
        steps = setup_next_steps(report)
        self.assertTrue(any("auth status" in step for step in steps))
        self.assertTrue(any("setup --url" in step for step in steps))

    def test_windows_expectation_rejects_linux_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch(
                "evaldesk.scripts.workbench_core.environment.current_runtime",
                return_value="linux",
            ), mock.patch(
                "evaldesk.scripts.workbench_core.environment.find_lark_cli",
                return_value=None,
            ):
                report = check_environment(
                    check_browser=False,
                    expected_runtime="windows",
                    session_root=directory,
                    port=0,
                )
        runtime = next(
            item for item in report["checks"] if item["name"] == "runtime"
        )
        self.assertFalse(runtime["ok"])
        self.assertEqual(runtime["required"], "windows")
        self.assertIn("runtime", report["blocking_failures"])

    def test_server_stops_through_authenticated_http_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            fixtures = {
                "manifest.json": {
                    "schema": {"supported": True},
                    "source": {"sheet_id": "test-sheet"},
                },
                "tasks.json": {"rows": []},
                "results.json": {"version": 2, "rows": {}},
            }
            for name, payload in fixtures.items():
                (session / name).write_text(
                    json.dumps(payload), encoding="utf-8"
                )
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "evaldesk",
                    "serve",
                    "--session",
                    str(session),
                    "--port",
                    "0",
                    "--no-open",
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                state_path = session / "server.json"
                deadline = time.monotonic() + 30
                while not state_path.exists() and time.monotonic() < deadline:
                    if server.poll() is not None:
                        break
                    time.sleep(0.05)
                if not state_path.exists():
                    server.terminate()
                    stdout, stderr = server.communicate(timeout=5)
                    self.fail(
                        "server did not become ready; "
                        f"returncode={server.returncode}; "
                        f"stdout={stdout!r}; stderr={stderr!r}"
                    )
                stopped = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "evaldesk",
                        "stop",
                        "--session",
                        str(session),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(
                    stopped.returncode, 0, stopped.stdout + stopped.stderr
                )
                stdout, stderr = server.communicate(timeout=5)
                self.assertEqual(server.returncode, 0, stdout + stderr)
                self.assertFalse(state_path.exists())
            finally:
                if server.poll() is None:
                    server.terminate()
                    server.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
