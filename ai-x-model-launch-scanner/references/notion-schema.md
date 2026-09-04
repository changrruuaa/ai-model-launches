# Notion 数据库 Schema（AI Model Launches）

由 `notion_sync.py` 在首次 sync 时自动创建（parent = `skills.config.notion_parent_page_id` 指向的页面，该页面必须 Share 给 integration）。

## Properties

| Property | Type | 说明 |
|---|---|---|
| Name | title | one_line_cn 或 model_name |
| Tweet ID | rich_text | **去重键**（推文 ID 超过 JS 安全整数，不能用 number） |
| Company | select | 写入时自动建选项 |
| Author | rich_text | X handle |
| Model Name | rich_text | 无则空 |
| URL | url | 推文链接 |
| Created At | date | 推文时间（CST） |
| Confidence | number (percent) | 0-100 |
| Category | select | model_release / capability_update / benchmark / research_paper / product / other |
| Key Facts | rich_text | " · " 拼接 |
| Raw Text | rich_text | 截 1900 字符（Notion 上限 2000） |
| Metrics | rich_text | "likes=2448, ..." |
| Scanned At | date | 扫描日期 |
| Status | select | new / reviewed / archived |
| Verified | checkbox | Step 4b release_verified |

## 页面 children

- paragraph：Raw Text 前 1900 字符
- bookmark：推文 URL

## 写入行为

- 去重：按 Tweet ID query（run 开始可批量拉取窗口内已有 ID）；存在 → 只更新 Metrics/Confidence/Key Facts/Verified（`--no-update` 则跳过）
- 节流：每请求 sleep 0.35s（Notion ~3 rps）；429 退避重试 3 次
- 幂等：同 run_id 重跑 → "新增 0，更新 N"
- **顺序保证**：`write_local.py` 先于 `notion_sync.py`——Notion 失败不吃掉本地报告
- token：`~/.hermes/.env` 的 `NOTION_TOKEN`，hermes 透传进 terminal 沙箱，**绝不打印**
