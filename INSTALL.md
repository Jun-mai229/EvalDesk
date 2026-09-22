# EvalDesk 本地安装

发布包同时包含 EvalDesk 命令行程序和可选的 Agent Skill。普通用户只安装
命令行程序即可；需要让 Agent 代为操作时，再安装 Skill。

## 1. 准备环境

- Python 3.9 或更高版本
- `pipx`
- 现代浏览器
- 已安装并位于 `PATH` 中的 `lark-cli`
- 对目标飞书表格具有读取权限的用户身份

不要复制其他人的 Token、Cookie、`lark-cli` 配置或 EvalDesk 会话目录。

## 2. 安装程序

在解压后的发布目录中执行：

```bash
pipx install ./evaldesk-*-py3-none-any.whl
evaldesk self-test
evaldesk setup --no-browser-check
```

升级已有版本时执行：

```bash
pipx install --force ./evaldesk-*-py3-none-any.whl
```

## 3. 配置飞书身份

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

## 4. 安装可选 Skill

先找到当前 Agent 产品的用户级 Skill 根目录，再执行：

```bash
python3 scripts/install_skill.py --target-root '<agent-skills-root>'
```

安装脚本不会猜测 Agent 产品，也不会默认覆盖已有版本。确认需要升级时使用：

```bash
python3 scripts/install_skill.py \
  --target-root '<agent-skills-root>' \
  --force
```

## 5. 开始使用

首次使用一个模板时：

```bash
evaldesk diagnose --url '<飞书表格链接>'
evaldesk launch --url '<飞书表格链接>' --annotator '<标注人>'
```

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
