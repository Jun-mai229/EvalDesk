---
name: evaldesk
description: Operate a local Feishu image and video evaluation workbench. Use for template diagnosis, annotation, previews, or confirmed write-back. Do not use for non-Feishu data sources.
---

# EvalDesk

Before the first run, read `references/installation.md`. Use the `evaldesk`
executable when installed. In the EvalDesk source directory, use
`python3 -m evaldesk` as an equivalent command.

## Workflow

1. Run `evaldesk setup --no-browser-check`.
2. For a new or changed sheet template, run
   `evaldesk diagnose --url '<url>'` before creating a session.
3. If the report requires a target group, rerun with
   `--target-group '<exact group label>'`.
4. If only field names differ, create a minimal JSON alias file and pass the
   same `--aliases <path>` option to both `diagnose` and `launch`.
5. Start the workbench with
   `evaldesk launch --url '<url>' --annotator '<name>'`.
6. Keep the session directory private. It contains source links, media URLs,
   and annotation results.
7. Stop the local server with `evaldesk stop --session '<directory>'`.
8. Run `evaldesk commit --session '<directory>'` and inspect
   `commit-preview.json`.
9. Use `--apply` only after the user explicitly confirms the preview.

## Boundaries

- Treat `results.json` as the only annotation result source.
- Never recover scores from HTML, screenshots, browser storage, or visible text.
- Never edit machine scores, historical rounds, or expert fields.
- Never bypass the manifest write allowlist.
- Never package credentials or `~/.evaldesk/sessions/`.
- Stop when template diagnosis reports unsupported or ambiguous mappings.

Read `references/compatibility.md` for template coverage and
`references/writeback-safety.md` before changing write-back behavior.
