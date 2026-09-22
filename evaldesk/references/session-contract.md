# Session Contract

The local session is the boundary between Feishu, the browser UI, and write-back.

## Files

| File | Owner | Purpose |
| --- | --- | --- |
| `manifest.json` | `prepare_session.py` | Source URL, sheet ID, revision, parsed schema, validation options, and write allowlist |
| `tasks.json` | `prepare_session.py` | Read-only task rows and original values |
| `results.json` | Browser UI | Editable structured annotations keyed by physical sheet row |
| `status.json` | Local server and commit step | Current local workflow state and last error |
| `commit-preview.json` | `commit_results.py` | Exact proposed or applied cell changes |

## Invariants

- `manifest.version`, `tasks.version`, and `results.version` must be supported by the scripts.
- Every `results.rows` key must exist in `tasks.rows`.
- Every task uses its physical sheet row number, not its displayed index.
- `manifest.assignment` records the selected annotator scope.
- `tasks.rows` contains only exact task-person matches (`仲裁人` preferred when
  present, otherwise `标注人`), or only blank assignments
  when `--include-unassigned` was explicitly selected.
- Every dimension key in results must exist in the manifest schema.
- Edited `human_score` and `mos` arrays require one slot per generated output.
  Preserve irregular historical arrays unchanged, with warnings. Array index N
  maps to `tasks.rows[].outputs[N]`.
- Version 1 scalar score values remain readable for old sessions. The browser
  upgrades them to version 2 arrays before saving.
- Scores and labels must be members of the options captured during preparation.
- The write allowlist is derived during preparation and must not be expanded by browser data.
- Session JSON is UTF-8 and is replaced atomically.
- `saved_at` is local registration metadata. Successful “保存并下一条” makes a
  row green; later editing clears registration until it is saved again.
- `blind_snapshot` preserves the initial independent scores before Review.
  It is local and immutable after persistence.
- Requests are serialized in the browser and merged under a server lock. Capture
  dirty physical rows before navigation; a failed save does not advance a case.

## Browser Boundary

The browser loads:

- manifest metadata and options;
- task prompts and media URLs;
- current local results.

The browser posts only structured result rows to `/api/results`. It does not receive Feishu credentials and does not call Feishu APIs.

Do not recover annotations by parsing HTML, browser local storage, screenshots, or visible text.

## Refreshing A Session

Running `prepare_session.py --force` replaces the source snapshot and local results, and removes a stale commit preview.

Do not use `--force` after a user has annotated cases unless those local results have been exported or reconciled.

## Storage

Default session location:

```text
~/.evaldesk/sessions/<sheet-id>-<timestamp>/
```

Session directories are private runtime data. Do not include them in the
application package or source control.
