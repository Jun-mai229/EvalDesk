# Write-back Safety

Read this reference before running `commit_results.py --apply`.

## Approval Gate

`commit_results.py` without `--apply` is the required first step. It validates local results and creates `commit-preview.json` without changing Feishu.

Before applying, show the user:

- source sheet;
- source revision;
- affected physical rows;
- cell count;
- each target column and field type;
- before and after values, with long reasons summarized when necessary.

An earlier request to build, test, or demonstrate EvalDesk is not approval to write.

## Validation Gate

Reject the write when:

- the template was marked unsupported;
- a result contains an unknown physical row;
- a field or column is outside the manifest allowlist;
- a score or label is outside the captured validation options;
- MOS is non-numeric or outside 1 through 5;
- a reason exceeds the supported length;
- the current Feishu revision differs from the revision captured during preparation.

Do not add a force flag for revision conflicts. Prepare a fresh session and reconcile intentionally.

## Write Semantics

- Write only values that differ from the source snapshot.
- Send multi-select labels through `multiple_values`, not a comma-joined scalar.
- Require one human score and one MOS slot per generated output whenever that
  field is non-empty; reject partially filled arrays.
- Write multi-output scores as compact JSON array text such as `[2,2,2,2]`.
  Read-back verification also accepts legacy full-width comma lists.
- Keep single-output scores numeric for compatibility with existing sheets.
- Keep machine-score columns read-only.
- Keep expert fields, earlier rounds, other models, and local registration/Blind
  Review metadata out of the write allowlist.
- Compare with the source first. Unchanged irregular historical values must not
  block unrelated edits; newly edited scores still require full validation.
- Keep unrelated values, formulas, styles, merges, dimensions, and sheet metadata unchanged.
- Use one batched `+cells-set --writes` request for the validated changes.

## Verification

After writing:

1. Read every affected row range with `+cells-get`.
2. Compare each intended scalar or multi-select value.
3. Set `verified: true` only when every comparison matches.
4. Record mismatches in `commit-preview.json`.
5. Report a verification failure even when the write API returned `ok`.

Do not automatically retry a partial or mismatched write. Read the current state and reconcile first.
