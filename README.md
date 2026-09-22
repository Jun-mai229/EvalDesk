# EvalDesk

从飞书评测表创建本地图片或视频评分工作台。项目不绑定特定 IDE，
运行时只需要 Python 3.9+、浏览器，以及已登录且位于 `PATH` 中的
`lark-cli`。Python 运行时只使用标准库。

```text
evaldesk/
├── assets/workbench/       # 本地 Web 页面
├── config/                 # 可扩展字段别名
├── references/             # 数据契约与安全说明
└── scripts/                # 启动、停止、预览和回写命令
docs/                       # 通用开发文档
skill/evaldesk/             # 可移植 Skill 源文件
tests/                      # 仅使用匿名合成数据
```

## 安装

给其他人使用时，优先发送 `scripts/build_release.py` 生成的本地发布包。解压后
使用 `pipx` 安装其中的 wheel：

```bash
pipx install ./evaldesk-*-py3-none-any.whl
```

在源码目录开发或试用时，也可以直接安装当前目录：

```bash
pipx install .
```

也可以不安装，在项目根目录使用 `python3 -m evaldesk`。下文命令中的
`evaldesk` 均可替换为 `python3 -m evaldesk`。

## 使用

首次使用先运行新手检查：

```bash
evaldesk setup --no-browser-check
```

它会逐项检查 Python、`lark-cli`、界面资源、会话目录、端口和浏览器，并给出
下一步操作。需要机器读取结构化结果时，使用 `evaldesk setup --json`；
原有的 `evaldesk doctor` 仍保持 JSON 输出。

如果 `lark-cli` 尚未配置，按照所在组织提供的安装方式完成安装，再初始化并
验证当前用户身份：

```bash
lark-cli config init --new
lark-cli auth login --domain docs --no-wait --json
lark-cli auth status --json --verify
```

打开 `auth login` 返回的授权链接完成授权。不要复制其他人的 Token、Cookie
或 CLI 配置。

首次接入新模板时，先查看字段识别和兼容性报告：

```bash
evaldesk setup --url '<飞书链接>' --no-browser-check
evaldesk diagnose --url '<飞书链接>'
```

一键读取表格并启动本地工作台：

```bash
evaldesk launch --url '<飞书链接>' --annotator '<标注人>'
```

评测结束后，停止服务并生成回写预览：

```bash
evaldesk stop --session '<会话目录>'
evaldesk commit --session '<会话目录>'
```

`commit_results.py` 默认仅生成 `commit-preview.json`，不会修改飞书。只有在用户检查
预览并明确确认后，才可追加 `--apply`。

会话默认保存在 `~/.evaldesk/sessions/`，不进入源码目录。会话中包含飞书链接、
任务素材和本地评分结果，不应打包、提交或转发。

## 自定义模板字段

默认别名位于 `evaldesk/config/field-aliases.json`。团队模板使用其他列名时，
创建一个只包含新增别名的 JSON 文件：

```json
{
  "basic_fields": {
    "id": ["案例编号"],
    "annotator": ["执行人"],
    "outputs": ["生成物"]
  },
  "score_fields": {
    "human_score": ["人工打分"]
  },
  "mos": ["总分"]
}
```

通过 `--aliases` 同时用于诊断和启动：

```bash
evaldesk diagnose --url '<飞书链接>' --aliases team-aliases.json
evaldesk launch --url '<飞书链接>' --annotator '<标注人>' \
  --aliases team-aliases.json
```

自定义项追加到内置别名，不会改变写入白名单。未知配置项、空别名和语义冲突
会在读取表格前被拒绝。

## Skill 分发

`skill/evaldesk/` 是可安装到支持 `SKILL.md` 的 Agent 产品中的独立 Skill
源目录。项目本身不放置 `.trae` 等 IDE 专属目录；安装位置由使用者的 Agent
产品决定，EvalDesk 命令行工具可以独立运行。

将完整 Skill 安装到用户指定的 Agent Skill 根目录：

```bash
python3 scripts/install_skill.py --target-root '<agent-skills-root>'
```

安装脚本默认拒绝覆盖同名 Skill。确认升级时显式追加 `--force`。

## 构建本地发布包

```bash
python3 scripts/build_release.py
```

产物位于 `dist/evaldesk-<版本>-local.zip`，包含 wheel、独立 Skill、安装脚本、
安装说明和 SHA-256 文件清单。完整接收者流程见 `INSTALL.md`。
