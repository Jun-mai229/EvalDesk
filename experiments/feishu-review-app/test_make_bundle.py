#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
MODULE_PATH = Path(__file__).with_name("make_bundle.py")
SPEC = importlib.util.spec_from_file_location("make_bundle", MODULE_PATH)
assert SPEC and SPEC.loader
make_bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(make_bundle)

from evaldesk.scripts.workbench_core.self_test import fake_payloads  # noqa: E402
from evaldesk.scripts.workbench_core.template import build_session  # noqa: E402
from evaldesk.scripts.workbench_core.writeback import build_writes  # noqa: E402


def session():
    payload, validation = fake_payloads("standard-56", output_count=2)
    return build_session(
        "https://example.test/private-source?sheet=sample",
        "sample",
        payload,
        validation,
        annotator="测试员",
    )


class ReviewBundleTest(unittest.TestCase):
    def test_bundle_omits_write_authority_and_source_url(self):
        manifest, tasks, results = session()
        bundle = make_bundle.build_bundle(manifest, tasks, results)
        encoded = str(bundle)
        self.assertNotIn(manifest["source"]["url"], encoded)
        self.assertNotIn("write_allowlist", encoded)
        self.assertNotIn("mos_column", encoded)
        self.assertNotIn("'columns'", encoded)
        self.assertEqual(
            bundle["source_snapshot"]["revision"],
            manifest["source"]["revision"],
        )
        self.assertEqual(len(bundle["tasks"]), 1)

    def test_export_round_trip_remains_valid_for_writeback(self):
        manifest, tasks, results = session()
        bundle = make_bundle.build_bundle(manifest, tasks, results)
        exported = copy.deepcopy(bundle["baseline_results"])
        exported["review_package"] = {
            "package_id": bundle["package_id"],
            "sheet_id": bundle["source_snapshot"]["sheet_id"],
            "source_revision": bundle["source_snapshot"]["revision"],
        }
        row = exported["rows"]["4"]
        row["dimensions"]["d1"]["human_score"] = ["2", "3"]
        row["mos"] = ["4", "3.5"]
        merged = make_bundle.validate_export(manifest, tasks, exported)
        writes, preview = build_writes(manifest, tasks, merged)
        self.assertEqual(len(writes), 2)
        self.assertEqual({item["field"] for item in preview}, {"human_score", "mos"})

    def test_revision_mismatch_is_rejected(self):
        manifest, tasks, results = session()
        bundle = make_bundle.build_bundle(manifest, tasks, results)
        exported = copy.deepcopy(bundle["baseline_results"])
        exported["review_package"] = {
            "package_id": bundle["package_id"],
            "sheet_id": bundle["source_snapshot"]["sheet_id"],
            "source_revision": 999,
        }
        with self.assertRaisesRegex(make_bundle.BundleError, "版本"):
            make_bundle.validate_export(manifest, tasks, exported)

    def test_row_injection_is_rejected(self):
        manifest, tasks, results = session()
        bundle = make_bundle.build_bundle(manifest, tasks, results)
        exported = copy.deepcopy(bundle["baseline_results"])
        exported["review_package"] = {
            "package_id": bundle["package_id"],
            "sheet_id": bundle["source_snapshot"]["sheet_id"],
            "source_revision": bundle["source_snapshot"]["revision"],
        }
        exported["rows"]["999"] = copy.deepcopy(exported["rows"]["4"])
        with self.assertRaisesRegex(make_bundle.BundleError, "任务行集合"):
            make_bundle.validate_export(manifest, tasks, exported)


if __name__ == "__main__":
    unittest.main()
