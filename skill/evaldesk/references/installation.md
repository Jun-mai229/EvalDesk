# Local Installation

EvalDesk has two independent parts:

- the `evaldesk` command-line application;
- this optional Agent skill.

The command-line application is required. The skill only teaches a compatible
Agent how to operate it.

## Requirements

- Python 3.9 or newer
- `pipx`
- a modern browser
- `lark-cli` on `PATH`
- a Feishu user identity that can read the source sheet

Install the EvalDesk wheel supplied with the release:

```bash
pipx install ./evaldesk-<version>-py3-none-any.whl
evaldesk self-test
evaldesk setup --no-browser-check
```

If `lark-cli` has not been configured, initialize it through the supported
organization or product flow:

```bash
lark-cli config init --new
lark-cli auth login --domain docs --no-wait --json
lark-cli auth status --json --verify
```

Complete the authorization URL returned by `auth login`. Never copy another
person's credentials, tokens, cookies, or CLI configuration.

## Skill Installation

Install the entire `evaldesk` skill directory into the local Agent product's
skills root. Keep `SKILL.md` and `references/` together. When using the source
release, run:

```bash
python3 scripts/install_skill.py --target-root '<agent-skills-root>'
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

Do not distribute `~/.evaldesk/sessions/`. Session directories contain source
links, media URLs, task content, and local annotation results.
