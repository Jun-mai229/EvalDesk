# EvalDesk

从飞书评测表创建本地图片或视频评分工作台。项目不绑定特定 IDE，
运行时只需要 Python 3.9+、浏览器，以及已登录且位于 `PATH` 中的
`lark-cli`。

```text
evaldesk/
├── assets/workbench/       # 本地 Web 页面
├── references/             # 数据契约与安全说明
└── scripts/                # 启动、停止、预览和回写命令
docs/                       # 通用开发文档
tests/                      # 仅使用匿名合成数据
```

先检查环境：

```bash
python3 evaldesk/scripts/doctor.py --no-browser-check
```

一键读取表格并启动本地工作台：

```bash
python3 evaldesk/scripts/launch_workbench.py \
  --url '<飞书链接>' --annotator '<标注人>'
```

评测结束后，停止服务并生成回写预览：

```bash
python3 evaldesk/scripts/stop_session.py --session '<会话目录>'
python3 evaldesk/scripts/commit_results.py --session '<会话目录>'
```

`commit_results.py` 默认仅生成 `commit-preview.json`，不会修改飞书。只有在用户检查
预览并明确确认后，才可追加 `--apply`。

会话默认保存在 `~/.evaldesk/sessions/`，不进入源码目录。会话中包含飞书链接、
任务素材和本地评分结果，不应打包、提交或转发。
