# Runtime Environment

Read this reference when installing, diagnosing, or launching EvalDesk on a
new machine.

## Required

| Dependency | Requirement |
| --- | --- |
| Python | 3.9 or newer |
| `lark-cli` | Available on `PATH` |
| Feishu identity | User credentials supplied to `lark-cli` |
| Permissions | The user can read the source sheet and edit write-back cells |
| Browser | A modern browser capable of opening localhost |
| Network | Access to Feishu and the media hosts referenced by the sheet |
| Filesystem | Write access to the session directory |

The browser and server must run on the same host. For a Windows browser, run
EvalDesk from native Windows Python and include `--expect-runtime windows`.
Do not launch it in WSL, a container, or a remote Agent sandbox.

The Python runtime uses only the standard library. Do not add a package manager
or virtual environment unless a future feature introduces a real dependency.

## Preflight

Run a local-only check:

```bash
evaldesk setup --no-browser-check
```

Include a source URL to verify the active user identity can access the workbook
and selected sheet:

```bash
evaldesk setup --url '<feishu-sheet-url>' --no-browser-check
```

The check reports the runtime platform, Python, `lark-cli`, packaged UI assets,
session-directory permissions, browser availability, a free local port, and
optional Feishu access. Browser discovery is advisory; all other failed checks
block launch.

## Authentication Boundary

Never package access tokens, cookies, app secrets, or another user's login
state with EvalDesk. `lark-cli` owns authentication. EvalDesk only invokes it
with user identity and consumes its structured JSON response.

If Feishu access fails, inspect the current user identity with
`lark-cli auth status --json --verify`, complete authentication through the
supported `lark-cli` authorization flow, then rerun `evaldesk setup` with the
target URL.

## Distribution

- Distribute the built wheel instead of selected Python source files.
- Keep the optional Agent Skill's `SKILL.md` and `references/` together.
- Do not distribute `~/.evaldesk/sessions/`; it contains source links, task
  content, media URLs, and local annotation results.
- Keep credentials under the user's own `lark-cli` configuration. Never copy
  authentication state into this project.
