# Template Contract

Read this reference before preparing a session from a new sheet.

## Supported Layouts

The adapter maps named fields and group boundaries, not fixed column counts.
The original layouts remain compatible:

| Layout | Basic fields | Dimension blocks | Overall score |
| --- | --- | --- | --- |
| `standard-56` | `A:G` | `H:BC`, eight dimensions with six columns each | `BD` |
| `legacy-48` | `A:G` | `H:AU`, eight dimensions with five columns each | `AV` |
| `image-arbitration-107` | `A:G` | two read-only five-dimension rounds plus one editable five-dimension arbitration round | `DA` |

Common video dimensions (actual sheet names and ordering are preserved):

1. 指令跟随
2. 参考遵循
3. 一致性保持
4. 视觉质量
5. 文字质量
6. 音频质量
7. 剪辑质量
8. 创意实现

Each `standard-56` dimension contains:

1. 人评打分
2. 打分标签
3. 打分归因
4. 机评分数
5. 人机review打签
6. review归因

Each `legacy-48` dimension contains:

1. 打分
2. 打分标签
3. 打分归因
4. 人机review打签
5. review归因

The legacy layout has no machine score. Show it as unavailable in the UI and
do not synthesize or write a machine-score column.

The `image-arbitration-107` layout uses:

- first round `H:AL` and second round `AM:BQ` as read-only comparisons;
- arbitration dimensions in `BR:CZ`;
- arbitration MOS in `DA`;
- overall arbitration label and reason in `DB:DC`.

Common image dimensions are 指令跟随、参考遵循、画面质量、文字质量、视觉审美.
Each editable dimension adds 仲裁标签 between 打分标签 and 打分归因.

## Semantic Layouts

- One-row MOS-only headers preserve the physical data start at row 2 and include
  actual reason/arbitration fields.
- Three-row image/video headers may use five-, six-, or seven-field blocks,
  including mixed widths and “打分” / “人评打分” aliases.
- Zero, one, or more earlier groups are read-only comparisons when a uniquely
  labeled arbitration target is present. Otherwise require `--target-group`.
- For baseline/SFT1/SFT2, require explicit `--target-group`; each session binds
  only that model's output column and score columns. Separate model sessions
  can therefore have different output counts, such as 4/4/1.
- Preserve MOS labels/reasons/review fields where present. Keep expert fields
  read-only; never map “专家评估” or “专家裁定” into a writable reason field.
- Use `仲裁人` if present, otherwise `标注人`. Missing personnel columns block use.
- `auto` discovers the physical width from workbook metadata and reads up to
  1,000 rows. Explicit range selection is a bounded subset, not pagination.

## Parsing Rules

- Read enough columns to include `mos分`. Do not plan writes from a truncated read.
- Use `col_indices` returned by `lark-cli`; do not count column letters manually.
- Use the `[row=N]` prefix from `annotated_csv` as the physical row number.
- Read score, tag, and review choices from data validation.
- Preserve every dimension found in the selected group. Match comparisons by
  dimension name. Reject duplicate fields or ambiguous group boundaries.
- Detect media type from generated-output URLs. Treat `.mp4`, `.mov`, and `.webm` as video.
- Parse generated-output cells as ordered URL lists. Preserve their order because
  score position N belongs to output N.
- Normalize human scores, machine scores, and MOS to one score slot per output.
  Accept scalar values, JSON arrays such as `[2,2,2,2]`, and legacy comma lists
  such as `2，2，2，2` and `2、2、2、2` when reading. Preserve zero.
- Preserve excess historical score slots and show mismatch warnings. Pad missing
  slots with blanks without broadcasting values. Never rewrite an unchanged
  irregular historical field just because another field changed.
- Parse reference and output URLs from plain text, JSON arrays, and structured
  URL/text/link values. Detect video references separately. Keep reference
  materials and generated results visibly labeled in separate panels.
- Skip rows that do not contain all of ID, prompt, and generated output.

## Editable Fields

The adapter may write only:

- human score;
- scoring labels;
- scoring reason;
- review label;
- review reason;
- MOS.

For `image-arbitration-107`, the adapter may additionally write each
dimension's arbitration label and the overall arbitration label/reason.

Machine scores and all basic fields are read-only.

For a multi-output case, write human scores and MOS as compact JSON array text,
for example `[2,2,2,2]`. Keep single-output cells numeric for compatibility.
Tags and reasons remain shared at case/dimension level because the template has
one cell for each of those fields.

## Unsupported Templates

Stop before opening the UI when:

- the one-row or three-row header cannot be mapped unambiguously;
- a dimension contains unknown or duplicate fields;
- `mos分` is missing;
- any dimension's scoring labels cannot be read;
- the read is truncated;
- no valid task rows are found.

Do not guess a mapping for an unsupported template. Update the adapter deliberately and rerun its self-test.
Cross-sheet machine-score joins, a workbook navigation page, and expert editing
are not implemented. Do not infer cross-sheet links from row numbers or IDs alone.
