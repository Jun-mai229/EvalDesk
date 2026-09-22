# Template Compatibility

EvalDesk resolves evaluation fields by header meaning. It does not depend on a
workbook name, a fixed column count, or a fixed first column.

## Supported

- Five-dimension image and eight-dimension video scoring
- Single-output and multi-output scoring
- Zero, one, or multiple historical comparison rounds
- Per-dimension and overall arbitration
- Standard evaluation and blind-review workflows
- Standard six-field and legacy five-field layouts
- JSON, ASCII comma, full-width comma, and ideographic comma score sequences
- Custom JSON field aliases with conflict validation
- Read-only template diagnosis
- Physical-row and write-allowlist based write-back previews

## New Templates

Run a read-only diagnosis before launching:

```bash
evaldesk diagnose --url '<feishu-sheet-url>'
```

If multiple output or score groups are present, pass the exact reported group
label with `--target-group`. If only field names differ, create a minimal JSON
alias file and pass the same `--aliases` option to `diagnose` and `launch`.

## Not Yet Supported

- Automatic machine-score joins across sheets
- Workbook-level sheet navigation
- Expert-field editing
- Automatic pagination beyond 1,000 rows

For a new template, verify header parsing, session generation, browser display,
local saving, write-back preview, and confirmed write-back in that order.
