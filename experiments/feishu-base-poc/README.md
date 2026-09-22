# 飞书多维表格评测 PoC

这个目录用于验证“管理员使用 EvalDesk，外部人员只使用飞书多维表格”的方案。
它与现有 `evaldesk/` 和 `skill/evaldesk/` 隔离，不修改现有会话和回写逻辑。

## 验证目标

1. 把 EvalDesk 会话转换成适合 Base 的字段和记录。
2. 在 Base 中按“案例”和“输出”分别填写评分。
3. 把 Base 记录还原为现有 `results.json`。
4. 继续复用 EvalDesk 的校验、预览和批量回写能力。

当前 PoC 只处理本地 JSON，不创建真实 Base，也不访问飞书。

## 数据模型

| Base 表 | 一行代表什么 | 主要内容 |
| --- | --- | --- |
| `批次` | 一次源表快照 | 批次 ID、源版本、模板、状态 |
| `任务` | 一个评测 Case | Prompt、参考素材、标签、归因、Review、提交状态 |
| `输出评分` | Case 的一个生成结果 | 输出地址、各维度人评分/机评分、MOS |

分数放在 `输出评分` 表，因为一个 Case 可能有多个输出；标签和归因留在
`任务` 表，因为当前 EvalDesk 模板中它们是 Case 级共享字段。

## 本地试验

从已有 EvalDesk 会话生成 Base 数据包：

```bash
python3 experiments/feishu-base-poc/base_bridge.py export \
  --session ~/.evaldesk/sessions/<session> \
  --output /tmp/base-package.json
```

生成文件中的 `tables.*.fields` 是 Base 建表字段定义，
`tables.*.records` 是待导入记录。模拟在 Base 中完成评分后，将编辑后的数据包
还原为新的结果文件：

```bash
python3 experiments/feishu-base-poc/base_bridge.py import \
  --session ~/.evaldesk/sessions/<session> \
  --package /tmp/base-package.json \
  --output /tmp/results.from-base.json
```

PoC 不会直接覆盖会话中的 `results.json`。人工比较并确认后，才应将结果纳入
现有 `evaldesk commit` 流程。

## Base 应用模式草图

建议在真实 Base 上配置以下页面：

| 页面 | 组件 | 用途 |
| --- | --- | --- |
| 我的任务 | 卡片列表 | 按标注人和状态筛选任务 |
| 任务详情 | 详情列表 | 查看 Prompt、参考素材、标签和归因 |
| 输出评分 | 标准列表 | 每个输出填写各维度分数和 MOS |
| 已提交 | 折叠列表 | 查看本人已完成任务 |
| 管理看板 | 统计图、列表 | 查看批次进度、缺失和退回任务 |

创建 AppMode 时，列表组件引用同一 Workspace 内的 Base。CLI 可以创建 Page
和列表组件，但组件位置、大小和最终排版仍需在飞书 UI 中调整。

## 上真实 Base 前必须解决

1. **人员映射**：源表中的名称需要转换为飞书 `open_id`，再使用 Base 的人员
   字段。PoC 暂时保留为 `标注人原文`。
2. **权限隔离**：筛选视图不等于权限。必须启用高级权限，确保标注人只能看到
   自己的任务和结果。
3. **媒体验证**：用真实外部账号检查图片、视频链接能否打开以及是否过期。
4. **盲评**：当前 PoC 主动拒绝盲评会话。需要先实现行级隔离和不可修改的独立
   评分快照。
5. **关系字段**：正式版本应在创建任务记录后取得 `record_id`，再把
   `输出评分` 通过 Link 字段关联到任务。PoC 使用稳定文本 `任务ID`。
6. **提交锁定**：状态变为 `已提交` 后，应通过高级权限或 Workflow 禁止继续
   编辑；不能只依赖界面提示。

## 安全边界

导出的 Base 数据包不包含：

- 飞书源表 URL；
- 目标列号；
- EvalDesk 写入白名单；
- 飞书 Token、Cookie 或 CLI 配置。

回写权限仍只存在于管理员本地的原始 EvalDesk 会话中。导入时会检查数据包 ID
和源表 revision，拒绝跨会话或过期结果。

## 测试

```bash
python3 experiments/feishu-base-poc/test_base_bridge.py
```

测试覆盖普通多输出评分、仲裁字段、源版本冲突、重复输出和盲评阻断。
