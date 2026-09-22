"""Distribution and first-run regression tests."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from evaldesk.scripts.workbench_core.environment import setup_next_steps


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
    def test_skill_is_self_contained(self):
        installer = load_installer()
        source = ROOT / "skill" / "evaldesk"
        self.assertEqual(installer.validate_skill(source), "evaldesk")
        self.assertTrue((source / "references" / "installation.md").is_file())
        self.assertTrue((source / "references" / "compatibility.md").is_file())
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


if __name__ == "__main__":
    unittest.main()
