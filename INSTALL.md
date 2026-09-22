# EvalDesk 本地安装

发布包同时包含 EvalDesk 命令行程序和可选的 Agent Skill。普通用户只安装
命令行程序即可；需要让 Agent 代为操作时，再安装 Skill。

## 1. 准备环境

- Python 3.9 或更高版本
- `pipx`
- Node.js（用于安装官方 `lark-cli`）
- 现代浏览器
- 已安装并位于 `PATH` 中的 `lark-cli`
- 对目标飞书表格具有读取权限的用户身份

Windows 用户必须在原生 PowerShell 或命令提示符中运行 EvalDesk。不要在
WSL、容器或远程 Agent 沙箱中启动，否则服务所在环境的 `127.0.0.1` 无法被
Windows 浏览器访问。

不要复制其他人的 Token、Cookie、`lark-cli` 配置或 EvalDesk 会话目录。

## 2. 外部人员安装飞书 CLI

`lark-cli` 是飞书/Lark 官方开源命令行工具，不依赖 TRAE，也不只面向字节
员工。安装 Node.js 后，可以通过 npm 独立安装：

```bash
npx @larksuite/cli@latest install
lark-cli --version
```

首次使用时，每位用户都应使用自己的飞书身份完成应用配置和授权：

```bash
lark-cli config init --new
lark-cli auth login --domain docs --no-wait --json
lark-cli auth status --json --verify
```

打开命令返回的授权链接完成登录。外部用户还必须满足以下条件：

- 其飞书账号能够访问目标表格；
- 所在租户允许创建或使用飞书开放平台应用；
- 所需文档权限已经获得租户管理员批准。

如果租户禁止创建应用或需要管理员审批，用户应联系其组织管理员处理。
不得将发起人的 `lark-cli` 配置目录、Token 或 Cookie 发给外部用户共用。

## 3. 安装程序

在解压后的发布目录中执行：

```bash
pipx install ./evaldesk-*-py3-none-any.whl
evaldesk self-test
evaldesk setup --no-browser-check
```

Windows PowerShell 使用：

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
py -m pipx install .\evaldesk-*-py3-none-any.whl
evaldesk self-test
evaldesk setup --expect-runtime windows --no-browser-check
```

如果最后一条命令报告运行平台为 `linux`，或会话路径以 `/home/` 开头，请停止。
这说明命令没有在 Windows 本机运行，生成的本地链接无法由 Windows 浏览器打开。

升级已有版本时执行：

```bash
pipx install --force ./evaldesk-*-py3-none-any.whl
```

## 4. 配置飞书身份

如果 `setup` 提示 `lark-cli` 未配置或未登录，按照所在组织提供的
`lark-cli` 安装方式完成安装，然后执行：

```bash
lark-cli config init --new
lark-cli auth login --domain docs --no-wait --json
lark-cli auth status --json --verify
```

打开 `auth login` 返回的授权链接并完成授权。随后验证目标表格：

```bash
evaldesk setup --url '<飞书表格链接>' --no-browser-check
```

## 5. 安装可选 Skill

先找到当前 Agent 产品的用户级 Skill 根目录，再执行：

```bash
python3 scripts/install_skill.py --target-root '<agent-skills-root>'
```

Windows PowerShell 使用：

```powershell
py .\scripts\install_skill.py --target-root '<agent-skills-root>'
```

安装脚本不会猜测 Agent 产品，也不会默认覆盖已有版本。确认需要升级时使用：

```bash
python3 scripts/install_skill.py \
  --target-root '<agent-skills-root>' \
  --force
```

## 6. 开始使用

首次使用一个模板时：

```bash
evaldesk diagnose --url '<飞书表格链接>'
evaldesk launch --url '<飞书表格链接>' --annotator '<标注人>'
```

Windows 上的启动命令必须附带运行平台校验：

```powershell
evaldesk launch --expect-runtime windows --url '<飞书表格链接>' --annotator '<标注人>'
```

命令输出的 `http://127.0.0.1:<端口>` 只能在运行 EvalDesk 的同一台电脑上打开，
不能发送给其他人使用。

评测后先生成回写预览：

```bash
evaldesk stop --session '<会话目录>'
evaldesk commit --session '<会话目录>'
```

只有检查 `commit-preview.json` 并明确确认后，才能执行：

```bash
evaldesk commit --session '<会话目录>' --apply
```

会话默认位于 `~/.evaldesk/sessions/`，包含源链接、素材地址和评测结果，不应
提交、打包或转发。
