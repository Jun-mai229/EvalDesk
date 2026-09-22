"""Offline regression using anonymous synthetic templates."""
import argparse
import copy
import json
import sys
import unittest
import tempfile
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evaldesk/scripts"))
from workbench_core.aliases import load_aliases
from workbench_core.common import WorkbenchError
from workbench_core.schema import parse_schema
from workbench_core.self_test import fake_arbitration_payloads, fake_payloads, column_letters
from workbench_core.template import (
    _diagnostic_suggestions,
    build_session,
    decode_score_sequence,
    extract_urls,
    parse_annotated_csv,
)
from workbench_core.server import validate_browser_payload
from workbench_core.writeback import build_writes

class Regression(unittest.TestCase):
    def test_synthetic_sessions_and_write_allowlist(self):
        cases = [
            fake_payloads("standard-56", output_count=2),
            fake_payloads("legacy-48", output_count=2),
            fake_arbitration_payloads(output_count=2),
        ]
        for index, (data, options) in enumerate(cases):
            with self.subTest(case=index):
                manifest, tasks, results = build_session(
                    "https://example.test/sheets/demo?sheet=sample",
                    "sample",
                    data,
                    options,
                    annotator="测试员",
                )
                self.assertTrue(
                    manifest["schema"]["supported"],
                    manifest["schema"]["problems"],
                )
                self.assertEqual(build_writes(manifest, tasks, results), ([], []))
                validate_browser_payload({"rows": results["rows"]}, tasks, results)
                self.assertTrue(manifest["write_allowlist"])

    def test_auto_range_and_blind_detection(self):
        from workbench_core.template import command_prepare
        data, validation = fake_arbitration_payloads()
        calls = []
        def lark(args):
            calls.append(args)
            if "+workbook-info" in args:
                return {"data": {"sheets": [{"sheet_id": "x", "column_count": 164,
                                             "row_count": 2300, "sheet_name": "盲评测试"}]}}
            return data
        with tempfile.TemporaryDirectory() as directory, patch("workbench_core.template.run_lark", side_effect=lark), patch("workbench_core.template.read_validation_payload", return_value=validation):
            args = argparse.Namespace(url="x", sheet_id="x", range="auto", validation_end_row=20,
                                      annotator="测试员", include_unassigned=False, target_group=None,
                                      session=directory, force=False, blind=False)
            self.assertEqual(command_prepare(args), 0)
            self.assertIn("A1:FH1000", calls[1])
            manifest = json.loads((Path(directory) / "manifest.json").read_text())
            self.assertTrue(manifest["schema"]["blind"])

    def test_zero_one_three_history_rounds(self):
        base, validation = fake_arbitration_payloads()
        cols = base["data"]["col_indices"]
        original = parse_annotated_csv(base["data"]["annotated_csv"], cols)
        for count in (0, 1, 2, 3):
            rows = {}
            for n, row in original.items():
                rows[n] = row[:7] + row[7:38] * count + row[69:]
            for i in range(count):
                rows[1][7 + 31*i] = f"baseline（第{i+1}轮）"
            newcols = column_letters(len(rows[2]))
            out = parse_schema(newcols, rows)
            self.assertEqual(len(out[5]["comparison_rounds"]), count)
            self.assertEqual(len(out[0]), 5)
            self.assertFalse(out[4])
            self.assertEqual(out[0][0]["columns"]["human_score"], newcols[7 + count*31])

    def test_reference_structures_and_zero(self):
        self.assertEqual(extract_urls('[{"url":"https://example.test/a.jpg"},{"text":"https://example.test/b.mp4"}]'),
                         ["https://example.test/a.jpg", "https://example.test/b.mp4"])
        self.assertEqual(decode_score_sequence(0), ["0"])
        self.assertEqual(decode_score_sequence("3、4、4、3"), ["3", "4", "4", "3"])

    def test_saved_marker_roundtrip_and_unknown_fields(self):
        data, options = fake_payloads()
        manifest, tasks, results = build_session("x", "x", data, options, annotator="测试员")
        local = copy.deepcopy(results)
        local["rows"]["4"]["saved_at"] = "2026-09-21T12:00:00Z"
        saved = validate_browser_payload({"rows": local["rows"]}, tasks, results)
        self.assertTrue(saved["rows"]["4"]["saved_at"])
        self.assertEqual(build_writes(manifest, tasks, saved), ([], []))
        local["rows"]["4"]["unknown"] = "x"
        with self.assertRaises(WorkbenchError):
            validate_browser_payload({"rows": local["rows"]}, tasks, results)

    def test_unchanged_invalid_history_does_not_block(self):
        data, options = fake_payloads(output_count=4)
        manifest, tasks, results = build_session("x", "x", data, options, annotator="测试员")
        for obj in (tasks["rows"][0], results["rows"]["4"]):
            obj["dimensions"]["d1"]["human_score"] = ["2", "", "", ""]
        results["rows"]["4"]["dimensions"]["d2"]["reason"] = "只改另一维度归因"
        writes, _ = build_writes(manifest, tasks, results)
        self.assertEqual(len(writes), 1)
        results["rows"]["4"]["dimensions"]["d1"]["human_score"] = ["3", "", "", ""]
        with self.assertRaises(WorkbenchError):
            build_writes(manifest, tasks, results)

    def test_custom_field_aliases_and_conflict_validation(self):
        data, _ = fake_payloads()
        columns = data["data"]["col_indices"]
        rows = parse_annotated_csv(data["data"]["annotated_csv"], columns)
        rows[2][0] = "案例编号"
        rows[2][1] = "原始提示"
        rows[2][4] = "生成物_baseline"
        rows[2][5] = "执行人"
        rows[2][-1] = "总分"
        for index, value in enumerate(rows[3]):
            if value == "人评打分":
                rows[3][index] = "人工打分"

        custom = {
            "basic_fields": {
                "id": ["案例编号"],
                "prompt": ["原始提示"],
                "outputs": ["生成物"],
                "annotator": ["执行人"],
            },
            "score_fields": {"human_score": ["人工打分"]},
            "mos": ["总分"],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aliases.json"
            path.write_text(json.dumps(custom, ensure_ascii=False), encoding="utf-8")
            aliases = load_aliases(str(path))
            parsed = parse_schema(columns, rows, aliases=aliases)
            self.assertEqual(parsed[1]["id"], 0)
            self.assertEqual(parsed[1]["outputs"], 4)
            self.assertEqual(parsed[2], len(columns) - 1)

            custom["score_fields"]["tags"] = ["人工打分"]
            path.write_text(json.dumps(custom, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(WorkbenchError, "字段别名冲突"):
                load_aliases(str(path))

    def test_template_diagnostic_suggestions(self):
        suggestions = _diagnostic_suggestions(
            ["未找到人工 MOS 评分区", "找不到所选评分组对应的输出列"]
        )
        self.assertTrue(any("mos" in item.lower() for item in suggestions))
        self.assertTrue(any("输出" in item for item in suggestions))


if __name__ == "__main__":
    unittest.main()
