# Local Installation

EvalDesk has two independent parts:

- the `evaldesk` command-line application;
- this optional Agent skill.

The command-line application is required. The skill only teaches a compatible
Agent how to operate it.

## Requirements

- Python 3.9 or newer
- `pipx`
- Node.js (used to install the official `lark-cli`)
- a modern browser
- `lark-cli` on `PATH`
- a Feishu user identity that can read the source sheet

On Windows, use native PowerShell and read `windows.md`. Do not run EvalDesk
inside WSL, a container, or a remote Agent sandbox when the browser is on the
Windows host.

## External Users And lark-cli

`lark-cli` is the official open-source Lark/Feishu command-line tool. It does
not require TRAE and is not limited to ByteDance employees. After installing
Node.js, install and verify it with:

```bash
npx @larksuite/cli@latest install
lark-cli --version
```

Each recipient must configure and authorize `lark-cli` with their own
Lark/Feishu identity:

```bash
lark-cli config init --new
lark-cli auth login --domain docs --no-wait --json
lark-cli auth status --json --verify
```

Complete the authorization URL returned by `auth login`.

The recipient's identity must be able to read the source sheet. Their tenant
must also allow the required Open Platform application and document scopes. If
application creation or scopes require administrator approval, the recipient
must ask their organization administrator to approve them.

Never distribute another person's `lark-cli` configuration, token, or cookie.

Install the EvalDesk wheel supplied with the release:

```bash
pipx install ./evaldesk-<version>-py3-none-any.whl
evaldesk self-test
evaldesk setup --no-browser-check
```

On native Windows PowerShell, use:

```powershell
py -m pipx install .\evaldesk-<version>-py3-none-any.whl
evaldesk self-test
evaldesk setup --expect-runtime windows --no-browser-check
```

## Skill Installation

Install the entire `evaldesk` skill directory into the local Agent product's
skills root. Keep `SKILL.md` and `references/` together. When using the source
release, run:

```bash
python3 scripts/install_skill.py --target-root '<agent-skills-root>'
```

On Windows PowerShell, replace `python3` with `py`:

```powershell
py .\scripts\install_skill.py --target-root '<agent-skills-root>'
```

The script refuses to replace an existing installation unless `--force` is
explicitly supplied.

## Verification

Run these checks on the recipient's machine:

```bash
evaldesk self-test
evaldesk setup --no-browser-check
evaldesk setup --url '<feishu-sheet-url>' --no-browser-check
```

For Windows verification and launch, include `--expect-runtime windows`. A
runtime report of `linux` or a session path below `/home/` means the service is
not running on the Windows host; do not return its `127.0.0.1` URL.

Do not distribute `~/.evaldesk/sessions/`. Session directories contain source
links, media URLs, task content, and local annotation results.
