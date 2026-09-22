# EvalDesk 飞书审阅台

飞书托管的静态评测前端。它不使用 Base、不连接源表，也不需要审阅者安装
Python、Node.js 或 `lark-cli`。

## 数据边界

- 管理员在本地通过 EvalDesk 只读生成会话。
- `make_bundle.py build` 生成脱敏任务包，不包含源表 URL、物理列映射或写入白名单。
- 审阅者导入任务包；进度自动保存在当前浏览器。
- 审阅者导出 `results.json`，管理员使用 `make_bundle.py import` 校验包 ID、源表 ID、
  `source_revision` 和任务行集合。
- 后续 EvalDesk 回写仍会再次检查源表实时 revision。

## 管理员流程

```bash
python3 -m evaldesk prepare \
  --url '<飞书表格链接>' \
  --include-unassigned \
  --range A1:BD200 \
  --session .private/session

python3 make_bundle.py build \
  --session .private/session \
  --output .private/review-bundle.json
```

将 `review-bundle.json` 发给审阅者。收到导出的结果后：

```bash
python3 make_bundle.py import \
  --session .private/session \
  --input ~/Downloads/results-<package-id>.json
```

导入只更新本地会话的 `results.json`，不会直接修改飞书原表。之后使用 EvalDesk
正常的 preview/commit 流程回写。

## 本地检查

```bash
python3 -m unittest test_make_bundle.py

python3 /Users/bytedance/.trae-cn/skills/webapp-testing/scripts/with_server.py \
  --server "python3 -m http.server 8765 --bind 127.0.0.1" \
  --port 8765 \
  -- python3 test_browser.py http://127.0.0.1:8765
```
