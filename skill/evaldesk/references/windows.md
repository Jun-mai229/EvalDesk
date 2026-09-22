# Native Windows Operation

EvalDesk must run as a native Windows process when its browser runs on Windows.
PowerShell should report `win32`:

```powershell
py -c "import sys; print(sys.platform)"
```

If the result is `linux`, or paths begin with `/home/`, the command is running
inside WSL, a container, or a remote Agent sandbox. Stop. That environment's
`127.0.0.1` is not the Windows browser's loopback interface.

## Install

Install Python 3.9 or newer and Node.js LTS. Then use PowerShell:

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
npx @larksuite/cli@latest install
lark-cli --version
```

Restart PowerShell if `pipx` or `lark-cli` is not found. Install the supplied
wheel and verify the native runtime:

```powershell
py -m pipx install .\evaldesk-<version>-py3-none-any.whl
evaldesk self-test
evaldesk setup --expect-runtime windows --no-browser-check
```

Authorize with the user's own Feishu identity:

```powershell
lark-cli config init --new
lark-cli auth login --domain docs --no-wait --json
lark-cli auth status --json --verify
```

## Launch

Run this in native PowerShell:

```powershell
evaldesk launch --expect-runtime windows --url '<feishu-sheet-url>' --annotator '<name>'
```

Keep that PowerShell window open while scoring. Open the reported
`http://127.0.0.1:<port>` URL on the same Windows computer. Do not send it to
another person or device.

Sessions are stored below `%USERPROFILE%\.evaldesk\sessions`. Stop a session
with:

```powershell
evaldesk stop --session "$env:USERPROFILE\.evaldesk\sessions\<session-name>"
```

If an Agent cannot execute native Windows processes, it cannot launch this
local workbench. The user must run the command in PowerShell, or use a hosted
evaluation application instead.
