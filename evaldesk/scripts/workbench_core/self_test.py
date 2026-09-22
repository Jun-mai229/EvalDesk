"""Offline contract smoke test."""
from __future__ import annotations

import argparse
import csv
import io
import json
import tempfile
from pathlib import Path
from typing import Any

from .common import (
    ARBITRATION_DIMENSIONS, DIMENSION_FIELDS, EXPECTED_DIMENSIONS, atomic_json,
    read_json,
)
from .server import validate_browser_payload
from .template import (
    ARBITRATION_DIMENSION_FIELDS, LEGACY_DIMENSION_FIELDS, build_session,
)
from .writeback import build_writes


def column_letters(column_count: int) -> list[str]:
    columns = []
    for number in range(1, column_count + 1):
        current = number
        letters = ""
        while current:
            current, remainder = divmod(current - 1, 26)
            letters = chr(65 + remainder) + letters
        columns.append(letters)
    return columns


def fake_payloads(
    layout: str = "standard-56", output_count: int = 1
) -> tuple[dict[str, Any], dict[str, Any]]:
    if layout == "standard-56":
        dimension_fields = DIMENSION_FIELDS
    elif layout == "legacy-48":
        dimension_fields = LEGACY_DIMENSION_FIELDS
    else:
        raise ValueError(f"unknown layout: {layout}")
    column_count = 7 + len(EXPECTED_DIMENSIONS) * len(dimension_fields) + 1
    columns = column_letters(column_count)
    row1 = [""] * column_count
    row2 = ["index", "prompt", "prompt_中文翻译", "用户素材", "video_url_baseline", "标注人", "review人"]
    row3 = [""] * 7
    for name in EXPECTED_DIMENSIONS:
        row2.extend([name] + [""] * (len(dimension_fields) - 1))
        row3.extend(dimension_fields)
    row2.append("mos分")
    row3.append("")
    row4 = [
        "case-1",
        "draw a product",
        "生成产品图",
        "",
        json.dumps(
            [f"https://example.test/output-{index + 1}.jpg" for index in range(output_count)]
        ),
        "@测试员",
        "",
    ]
    for _ in EXPECTED_DIMENSIONS:
        if layout == "standard-56":
            row4.extend(["", "", "", "4.2", "", ""])
        else:
            row4.extend(["", "", "", "", ""])
    row4.append("")
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    for number, row in ((1, row1), (2, row2), (3, row3), (4, row4)):
        line = io.StringIO()
        csv.writer(line, lineterminator="").writerow(row)
        stream.write(f"[row={number}] {line.getvalue()}\n")
    csv_payload = {
        "ok": True,
        "data": {
            "actual_range": f"A1:{columns[-1]}4",
            "annotated_csv": stream.getvalue(),
            "col_indices": columns,
            "has_more": False,
            "revision": 42,
        },
    }
    validation_ranges = []
    for _ in EXPECTED_DIMENSIONS:
        width = len(dimension_fields)
        start = 7 + len(validation_ranges) * width
        cells = [
            {
                "data_validation": {
                    "items": ["5", "4", "3", "2", "1", "-1"]
                }
            },
            {
                "data_validation": {
                    "items": ["问题 A", "问题 B"],
                    "support_multiple_values": True,
                }
            },
            {},
        ]
        if layout == "standard-56":
            cells.append({})
        cells.extend(
            [
                {
                    "data_validation": {
                        "items": ["人评错误", "机评错误"]
                    }
                },
                {},
            ]
        )
        validation_ranges.append(
            {
                "col_indices": columns[start : start + width],
                "cells": [cells],
            }
        )
    validation_payload = {
        "ok": True,
        "data": {
            "has_more": False,
            "ranges": validation_ranges,
        },
    }
    return csv_payload, validation_payload


def fake_arbitration_payloads(
    output_count: int = 4,
    row_count: int = 1,
    reference_count: int = 0,
    first_row_output_count: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    columns = column_letters(107)
    row1 = [""] * 107
    row2 = [
        "index", "prompt", "prompt翻译", "垫图", "结果图_baseline", "标注人",
        "review人",
    ]
    row3 = [""] * 7
    row4 = [
        "case-arbitration",
        "draw four products",
        "生成四张产品图",
        json.dumps(
            [
                f"https://example.test/reference-{index + 1}.jpg"
                for index in range(reference_count)
            ]
        ),
        json.dumps(
            [f"https://example.test/output-{index + 1}.jpg" for index in range(output_count)]
        ),
        "@测试员",
        "@复核员",
    ]
    for round_index, start in enumerate((7, 38)):
        row1[start] = f"baseline（第{round_index + 1}轮）"
        for name in ARBITRATION_DIMENSIONS:
            row2.extend([name] + [""] * (len(DIMENSION_FIELDS) - 1))
            row3.extend(DIMENSION_FIELDS)
            score = json.dumps([4 - round_index] * output_count)
            row4.extend([score, "", f"第{round_index + 1}轮归因", "4", "", ""])
        row2.append("mos分")
        row3.append("人评打分")
        row4.append(json.dumps([4 - round_index] * output_count))
    row1[69] = "baseline（三轮仲裁）"
    for name in ARBITRATION_DIMENSIONS:
        row2.extend([name] + [""] * (len(ARBITRATION_DIMENSION_FIELDS) - 1))
        row3.extend(ARBITRATION_DIMENSION_FIELDS)
        row4.extend(["", "", "", "", "4", "", ""])
    row2.extend(["mos分", "", ""])
    row3.extend(["人评打分", "仲裁标签（针对两轮diff）", "对三轮都不一致的进行"])
    row4.extend(["", "", ""])

    data_rows = []
    for index in range(row_count):
        row = list(row4)
        current_output_count = (
            first_row_output_count
            if index == 0 and first_row_output_count is not None
            else output_count
        )
        row[0] = f"case-arbitration-{index + 1}"
        row[1] = f"draw product set {index + 1}"
        row[2] = f"生成第 {index + 1} 组产品图"
        row[4] = json.dumps(
            [
                f"https://example.test/output-{item + 1}.jpg"
                for item in range(current_output_count)
            ]
        )
        if current_output_count != output_count:
            for position, value in enumerate(row):
                if value == json.dumps([4] * output_count):
                    row[position] = json.dumps([4] * current_output_count)
                elif value == json.dumps([3] * output_count):
                    row[position] = json.dumps([3] * current_output_count)
        data_rows.append((index + 4, row))

    stream = io.StringIO()
    for number, row in [(1, row1), (2, row2), (3, row3), *data_rows]:
        line = io.StringIO()
        csv.writer(line, lineterminator="").writerow(row)
        stream.write(f"[row={number}] {line.getvalue()}\n")
    csv_payload = {
        "ok": True,
        "data": {
            "actual_range": f"A1:DC{row_count + 3}",
            "annotated_csv": stream.getvalue(),
            "col_indices": columns,
            "has_more": False,
            "revision": 77,
        },
    }
    validation_ranges = []
    for dimension_index in range(len(ARBITRATION_DIMENSIONS)):
        start = 69 + dimension_index * len(ARBITRATION_DIMENSION_FIELDS)
        validation_ranges.append(
            {
                "col_indices": columns[start : start + len(ARBITRATION_DIMENSION_FIELDS)],
                "cells": [[
                    {"data_validation": {"items": ["5", "4", "3", "2", "1", "-1"]}},
                    {
                        "data_validation": {
                            "items": ["问题 A", "问题 B"],
                            "support_multiple_values": True,
                        }
                    },
                    {
                        "data_validation": {
                            "items": ["认同一轮", "认同二轮", "都不认同"]
                        }
                    },
                    {},
                    {},
                    {"data_validation": {"items": ["人评错误", "机评错误"]}},
                    {},
                ]],
            }
        )
    validation_ranges.append(
        {
            "col_indices": ["DB"],
            "cells": [[
                {
                    "data_validation": {
                        "items": ["认同一轮", "认同二轮", "都不认同"]
                    }
                }
            ]],
        }
    )
    return csv_payload, {
        "ok": True,
        "data": {"has_more": False, "ranges": validation_ranges},
    }


def command_self_test(_: argparse.Namespace) -> int:
    for layout, mos_column in (("standard-56", "BD"), ("legacy-48", "AV")):
        csv_payload, validation_payload = fake_payloads(layout)
        manifest, tasks, results = build_session(
            "https://example.test/sheets/x?sheet=sheet1",
            "sheet1",
            csv_payload,
            validation_payload,
            annotator="测试员",
        )
        assert manifest["schema"]["supported"], manifest["schema"]["problems"]
        assert manifest["schema"]["template_layout"] == layout
        assert len(manifest["schema"]["dimensions"]) == 8
        assert manifest["assignment"]["annotator"] == "测试员"
        assert tasks["rows"][0]["annotator"] == "@测试员"
        assert tasks["rows"][0]["dimensions"]["d1"]["machine_score"] == (
            ["4.2"] if layout == "standard-56" else [""]
        )
        assert tasks["rows"][0]["dimensions"]["d1"]["human_score"] == [""]
        assert tasks["rows"][0]["mos"] == [""]
        assert manifest["write_allowlist"][-1] == mos_column
        results["rows"]["4"]["dimensions"]["d1"]["human_score"] = ["3"]
        results["rows"]["4"]["dimensions"]["d1"]["tags"] = ["问题 A"]
        results["rows"]["4"]["mos"] = ["4"]
        writes, preview = build_writes(manifest, tasks, results)
        assert len(writes) == 3
        assert {item["column"] for item in preview} == {"H", "I", mos_column}
        assert next(item for item in writes if item["range"] == "H4")["cells"] == [
            [{"value": 3}]
        ]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.json"
            atomic_json(target, results)
            assert read_json(target)["rows"]["4"]["mos"] == ["4"]

    csv_payload, validation_payload = fake_payloads("standard-56", output_count=4)
    manifest, tasks, results = build_session(
        "https://example.test/sheets/x?sheet=sheet1",
        "sheet1",
        csv_payload,
        validation_payload,
        annotator="测试员",
    )
    assert len(tasks["rows"][0]["outputs"]) == 4
    results["rows"]["4"]["dimensions"]["d1"]["human_score"] = ["2"] * 4
    results["rows"]["4"]["mos"] = ["4", "3.5", "4", "5"]
    writes, preview = build_writes(manifest, tasks, results)
    assert len(writes) == 2
    assert next(item for item in writes if item["range"] == "H4")["cells"] == [
        [{"value": "[2,2,2,2]"}]
    ]
    assert next(item for item in writes if item["range"] == "BD4")["cells"] == [
        [{"value": "[4,3.5,4,5]"}]
    ]
    assert all(item["output_count"] == 4 for item in preview)

    legacy_results = {
        **results,
        "version": 1,
        "rows": {
            "4": {
                **results["rows"]["4"],
                "dimensions": {
                    **results["rows"]["4"]["dimensions"],
                    "d1": {
                        **results["rows"]["4"]["dimensions"]["d1"],
                        "human_score": "2，2，2，2",
                    },
                },
                "mos": "[4,3.5,4,5]",
            }
        },
    }
    legacy_writes, _ = build_writes(manifest, tasks, legacy_results)
    assert len(legacy_writes) == 2
    browser_saved = validate_browser_payload(
        {"rows": {"4": results["rows"]["4"]}},
        tasks,
        {**results, "version": 1},
    )
    assert browser_saved["version"] == 2

    csv_payload, validation_payload = fake_arbitration_payloads()
    manifest, tasks, results = build_session(
        "https://example.test/sheets/x?sheet=arbitration",
        "arbitration",
        csv_payload,
        validation_payload,
        annotator="测试员",
    )
    assert manifest["schema"]["supported"], manifest["schema"]["problems"]
    assert manifest["schema"]["template_layout"] == "image-arbitration-107"
    assert len(manifest["schema"]["dimensions"]) == 5
    assert manifest["schema"]["mos_column"] == "DA"
    assert manifest["schema"]["arbitration_columns"] == {
        "label": "DB",
        "reason": "DC",
    }
    assert "H" not in manifest["write_allowlist"]
    assert "AM" not in manifest["write_allowlist"]
    assert tasks["rows"][0]["dimensions"]["d1"]["comparisons"][0][
        "human_score"
    ] == ["4"] * 4
    assert tasks["rows"][0]["dimensions"]["d1"]["comparisons"][1][
        "human_score"
    ] == ["3"] * 4
    row_result = results["rows"]["4"]
    row_result["dimensions"]["d1"]["human_score"] = ["2"] * 4
    row_result["dimensions"]["d1"]["arbitration_label"] = "认同二轮"
    row_result["mos"] = ["4"] * 4
    row_result["arbitration"]["label"] = "都不认同"
    writes, preview = build_writes(manifest, tasks, results)
    assert {item["column"] for item in preview} == {"BR", "BT", "DA", "DB"}
    assert next(item for item in writes if item["range"] == "BR4")["cells"] == [
        [{"value": "[2,2,2,2]"}]
    ]
    browser_saved = validate_browser_payload(
        {"rows": {"4": row_result}},
        tasks,
        results,
    )
    assert browser_saved["rows"]["4"]["arbitration"]["label"] == "都不认同"
    print("self-test: ok")
    return 0
