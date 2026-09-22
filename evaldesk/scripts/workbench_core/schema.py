"""Semantic header mapping; model groups and review rounds are distinct."""
from __future__ import annotations

from typing import Any

from .aliases import alias_key, is_mos, load_aliases, normalize, output_model
from .common import WorkbenchError


def norm(value: Any) -> str:
    return normalize(value)


ALL_FIELDS = [
    "human_score",
    "tags",
    "reason",
    "machine_score",
    "review_label",
    "review_reason",
    "arbitration_label",
]


def parse_schema(columns, rows, target_group=None, aliases=None):
    aliases = aliases or load_aliases()
    width = len(columns)
    padded = {n: list(rows.get(n, [])) + [""] * max(0, width - len(rows.get(n, [])))
              for n in (1, 2, 3)}
    single = any(
        alias_key(value, aliases, "basic_fields") == "id"
        for value in padded[1]
    )
    header = padded[1] if single else padded[2]
    fields = [""] * width if single else padded[3]
    problems = []

    def locate(key):
        matches = [
            index
            for index, value in enumerate(header)
            if alias_key(value, aliases, "basic_fields") == key
        ]
        if len(matches) > 1:
            raise WorkbenchError(f"基本字段重复: {key}")
        return matches[0] if matches else None

    basic = {
        "id": locate("id"),
        "prompt": locate("prompt"),
        "prompt_zh": locate("prompt_zh"),
        "references": locate("references"),
        "annotator": (
            locate("arbitrator")
            if locate("arbitrator") is not None
            else locate("annotator")
        ),
        "reviewer": locate("reviewer"),
    }
    for key in ("id", "annotator"):
        if basic[key] is None:
            problems.append(f"缺少{'任务人员（标注人/仲裁人）' if key == 'annotator' else 'index/id'}列")
    if basic["prompt"] is None and basic["prompt_zh"] is None:
        problems.append("缺少 prompt 列")
    output_columns = {
        model: index
        for index, value in enumerate(header)
        if (model := output_model(value, aliases)) is not None
    }
    basic["outputs"] = output_columns.get("baseline")
    mos_indices = [
        index for index, value in enumerate(header) if is_mos(value, aliases)
    ]
    if not mos_indices:
        raise WorkbenchError("未找到人工 MOS 评分区；该表可能是素材、机评或统计来源")

    groups = []
    if single:
        for n, start in enumerate(mos_indices):
            end = mos_indices[n + 1] if n + 1 < len(mos_indices) else width
            label = header[start] if len(mos_indices) == 1 else f"第{n + 1}轮"
            if norm(header[start]).startswith(("3轮", "第3轮")):
                label = "三轮仲裁"
            mapping = {"human_score": columns[start]}
            for i in range(start + 1, end):
                key = alias_key(header[i], aliases, "score_fields")
                if key and key != "human_score":
                    if key in mapping:
                        raise WorkbenchError(f"{label} 重复字段 {header[i]}")
                    mapping[key] = columns[i]
            groups.append({"label": label, "start": start, "mos": start,
                           "dimensions": [], "overall": mapping, "end": end})
    else:
        starts = [i for i, v in enumerate(padded[1])
                  if norm(v) and any(i <= m for m in mos_indices)
                  and alias_key(fields[i], aliases, "score_fields") == "human_score"]
        if not starts:
            starts = [next(
                (
                    i
                    for i, value in enumerate(fields)
                    if alias_key(value, aliases, "score_fields") == "human_score"
                ),
                mos_indices[0],
            )]
        for n, start in enumerate(starts):
            end = starts[n + 1] if n + 1 < len(starts) else width
            mos = [i for i in mos_indices if start <= i < end]
            if len(mos) != 1:
                raise WorkbenchError("评分分组边界不明确，请显式映射表头")
            label = padded[1][start] or "当前评分"
            dimensions = []
            titles = [i for i in range(start, mos[0]) if norm(header[i])]
            for position, cursor in enumerate(titles):
                stop = titles[position + 1] if position + 1 < len(titles) else mos[0]
                mapping = {}
                for i in range(cursor, stop):
                    title = norm(fields[i])
                    if not title:
                        continue
                    key = alias_key(fields[i], aliases, "score_fields")
                    if not key or key in mapping:
                        raise WorkbenchError(f"{columns[i]} 未知或重复评分字段: {fields[i]}")
                    mapping[key] = columns[i]
                if "human_score" not in mapping:
                    raise WorkbenchError(f"{header[cursor]} 缺少人评分数")
                if any(d["name"] == header[cursor].strip() for d in dimensions):
                    raise WorkbenchError(f"{label} 重复维度 {header[cursor]}")
                dimensions.append({"name": header[cursor].strip(), "columns": mapping})
            overall = {"human_score": columns[mos[0]]}
            for i in range(mos[0] + 1, end):
                key = alias_key(fields[i], aliases, "score_fields")
                if key:
                    if key in overall:
                        raise WorkbenchError(f"{label} MOS 字段重复")
                    overall[key] = columns[i]
                elif "仲裁标签" in norm(fields[i]):
                    overall["arbitration_label"] = columns[i]
                elif norm(fields[i]).startswith("对三轮都不一致"):
                    overall["reason"] = columns[i]
                elif norm(fields[i]) and "专家" not in fields[i]:
                    raise WorkbenchError(f"{columns[i]} MOS 附加字段不明确: {fields[i]}")
            groups.append({"label": label, "start": start, "mos": mos[0],
                           "dimensions": dimensions, "overall": overall, "end": end})

    # An explicit model selection never turns other models into previous rounds.
    model_groups = len(output_columns) > 1
    candidates = [g for g in groups if target_group and norm(g["label"]) == norm(target_group)]
    if target_group and not candidates:
        raise WorkbenchError(f"未找到评分组 {target_group}；可选: {[g['label'] for g in groups]}")
    if not target_group:
        candidates = [g for g in groups if "仲裁" in g["label"]]
        if len(groups) == 1:
            candidates = groups
    if len(candidates) != 1:
        raise WorkbenchError("请用 --target-group 明确评分目标: " + "、".join(g["label"] for g in groups))
    active = candidates[0]
    history = [] if model_groups else [g for g in groups if g["start"] < active["start"]]
    model = norm(active["label"]).split("(", 1)[0]
    if model_groups:
        basic["outputs"] = output_columns.get(model)
    elif len(output_columns) == 1:
        basic["outputs"] = next(iter(output_columns.values()))
    if basic["outputs"] is None:
        problems.append("找不到所选评分组对应的输出列")

    dimensions = []
    for n, dimension in enumerate(active["dimensions"]):
        mapping = dimension["columns"]
        comparisons = []
        for group in history:
            match = next((d for d in group["dimensions"] if norm(d["name"]) == norm(dimension["name"])), None)
            if match:
                comparisons.append({"label": group["label"], "columns": match["columns"]})
        dimensions.append({**dimension, "key": f"d{n+1}",
                           "columns": {key: mapping.get(key) for key in ALL_FIELDS},
                           "editable_fields": [key for key in mapping if key != "machine_score"],
                           "comparison_columns": comparisons})

    overall = active["overall"]
    extras = {
        "header_rows": 1 if single else 3,
        "target_group": active["label"],
        "available_groups": [g["label"] for g in groups],
        "model": model if model_groups else "baseline",
        "comparison_rounds": [{"label": g["label"], "mos_column": columns[g["mos"]],
                               "columns": g["overall"]} for g in history],
        "arbitration_columns": None,
        "overall_columns": {k: v for k, v in overall.items() if k != "human_score"},
        "expert_columns": {columns[i]: header[i] if single else fields[i]
                           for i in range(active["start"], active["end"])
                           if "专家" in (header[i] if single else fields[i])},
    }
    # Keep v2 arbitration sessions compatible; expert columns are always excluded.
    if "arbitration_label" in overall:
        extras["arbitration_columns"] = {"label": overall["arbitration_label"]}
        if "reason" in overall:
            extras["arbitration_columns"]["reason"] = overall["reason"]
        extras["overall_columns"] = {k: v for k, v in extras["overall_columns"].items()
                                    if k not in ("arbitration_label", "reason")}
    layout = "semantic-rounds" if history else "semantic-dimensions"
    if single:
        layout = "mos-only"
    elif len(dimensions) == 8 and not history and not model_groups:
        layout = "standard-56" if all(d["columns"].get("machine_score") for d in dimensions) else "legacy-48"
    elif len(dimensions) == 5 and len(history) == 2 and len(columns) == 107:
        layout = "image-arbitration-107"
    return dimensions, basic, active["mos"], layout, problems, extras
