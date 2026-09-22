#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
MODULE_PATH = Path(__file__).with_name("base_bridge.py")
SPEC = importlib.util.spec_from_file_location("base_bridge", MODULE_PATH)
assert SPEC and SPEC.loader
base_bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base_bridge)

from evaldesk.scripts.workbench_core.self_test import (  # noqa: E402
    fake_arbitration_payloads,
    fake_payloads,
)
from evaldesk.scripts.workbench_core.template import build_session  # noqa: E402
from evaldesk.scripts.workbench_core.writeback import build_writes  # noqa: E402


def standard_session(output_count: int = 2):
    payload, validation = fake_payloads("standard-56", output_count=output_count)
    return build_session(
        "https://example.test/sheets/demo?sheet=sample",
        "sample",
        payload,
        validation,
        annotator="测试员",
    )


class BaseBridgeTest(unittest.TestCase):
    def test_package_omits_writeback_authority(self):
        manifest, tasks, results = standard_session()
        package = base_bridge.build_package(manifest, tasks, results)
        encoded = str(package)
        self.assertNotIn(manifest["source"]["url"], encoded)
        self.assertNotIn("write_allowlist", encoded)
        self.assertNotIn('"column"', encoded)
        self.assertEqual(len(package["tables"]["任务"]["records"]), 1)
        self.assertEqual(len(package["tables"]["输出评分"]["records"]), 2)

    def test_edited_base_records_round_trip_to_valid_results(self):
        manifest, tasks, results = standard_session()
        package = base_bridge.build_package(manifest, tasks, results)
        task = package["tables"]["任务"]["records"][0]
        output_a, output_b = package["tables"]["输出评分"]["records"]
        task["D1 指令跟随 标签"] = ["问题 A"]
        task["D1 指令跟随 归因"] = "主体遗漏"
        task["D1 指令跟随 Review标签"] = ["人评错误"]
        task["D1 指令跟随 Review归因"] = "复核后修正"
        task["状态"] = ["已提交"]
        task["提交时间"] = "2026-09-22T08:00:00+00:00"
        output_a["D1 指令跟随 人评分"] = ["2"]
        output_b["D1 指令跟随 人评分"] = ["3"]
        output_a["MOS"] = 4
        output_b["MOS"] = 3.5

        converted = base_bridge.import_results(
            manifest, tasks, results, package
        )
        row = converted["rows"]["4"]
        self.assertEqual(
            row["dimensions"]["d1"]["human_score"], ["2", "3"]
        )
        self.assertEqual(row["dimensions"]["d1"]["tags"], ["问题 A"])
        self.assertEqual(row["mos"], ["4", "3.5"])
        self.assertEqual(row["saved_at"], "2026-09-22T08:00:00+00:00")
        writes, preview = build_writes(manifest, tasks, converted)
        self.assertEqual(len(writes), 6)
        self.assertEqual(
            {item["field"] for item in preview},
            {
                "human_score",
                "tags",
                "reason",
                "review_label",
                "review_reason",
                "mos",
            },
        )

    def test_revision_mismatch_is_rejected(self):
        manifest, tasks, results = standard_session()
        package = base_bridge.build_package(manifest, tasks, results)
        package["source_snapshot"]["revision"] = 999
        with self.assertRaisesRegex(base_bridge.BridgeError, "源表快照"):
            base_bridge.import_results(manifest, tasks, results, package)

    def test_external_row_mapping_is_not_trusted(self):
        manifest, tasks, results = standard_session()
        package = base_bridge.build_package(manifest, tasks, results)
        original_id = package["tables"]["任务"]["records"][0]["任务ID"]
        forged_id = original_id.rsplit(":", 1)[0] + ":999"
        package["tables"]["任务"]["records"][0]["任务ID"] = forged_id
        for output in package["tables"]["输出评分"]["records"]:
            output["任务ID"] = forged_id
        package["mapping"]["task_rows"] = {forged_id: 4}
        with self.assertRaisesRegex(base_bridge.BridgeError, "任务集合"):
            base_bridge.import_results(manifest, tasks, results, package)

    def test_duplicate_output_is_rejected(self):
        manifest, tasks, results = standard_session()
        package = base_bridge.build_package(manifest, tasks, results)
        duplicate = copy.deepcopy(
            package["tables"]["输出评分"]["records"][0]
        )
        package["tables"]["输出评分"]["records"].append(duplicate)
        with self.assertRaisesRegex(base_bridge.BridgeError, "重复输出序号"):
            base_bridge.import_results(manifest, tasks, results, package)

    def test_blind_session_is_explicitly_blocked(self):
        manifest, tasks, results = standard_session()
        manifest["schema"]["blind"] = True
        with self.assertRaisesRegex(base_bridge.BridgeError, "盲评"):
            base_bridge.build_package(manifest, tasks, results)

    def test_arbitration_fields_round_trip(self):
        payload, validation = fake_arbitration_payloads(output_count=2)
        manifest, tasks, results = build_session(
            "https://example.test/sheets/demo?sheet=arb",
            "arb",
            payload,
            validation,
            annotator="测试员",
        )
        package = base_bridge.build_package(manifest, tasks, results)
        task = package["tables"]["任务"]["records"][0]
        task["D1 指令跟随 仲裁标签"] = ["认同一轮"]
        task["整体仲裁标签"] = ["都不认同"]
        task["整体仲裁原因"] = "两轮均有明显问题"
        converted = base_bridge.import_results(
            manifest, tasks, results, package
        )
        row = converted["rows"]["4"]
        self.assertEqual(
            row["dimensions"]["d1"]["arbitration_label"], "认同一轮"
        )
        self.assertEqual(row["arbitration"]["label"], "都不认同")
        self.assertEqual(row["arbitration"]["reason"], "两轮均有明显问题")


if __name__ == "__main__":
    unittest.main()
