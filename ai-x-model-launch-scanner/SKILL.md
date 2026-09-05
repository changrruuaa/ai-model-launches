---
name: ai-x-model-launch-scanner
description: >-
  用 cua-driver 驱动用户 Chrome 扫描 16 个 AI 厂商 X 账号在时间窗口内的推文，
  关键词预筛 + LLM 分类识别模型发布，web_search 交叉验证后写入本地 Markdown/JSON
  与 Notion。触发词：扫描 AI 模型发布 / 抓取 AI 公司推文 / 按厂家清单扫一遍 /
  跑模型扫描 / "scan AI model launches" / "近 N 天有什么新模型"。
version: 1.2.1
author: chang
license: MIT
platforms: [windows]
# 🚨 不要在 frontmatter 声明 required_environment_variables：
#    实测 hermes desktop 对声明的缺失变量强制提示且无法跳过，会卡死整个 skill 加载。
#    Notion token 改为运行时探测（Step 0 --check-auth，无 token 静默降级为仅本地）。
metadata:
  hermes:
    tags: [ai, research, twitter, monitoring]
    requires_tools: [computer_use]
    fallback_for_tools: []
    config:
      - key: base_dir
        description: 扫描数据与报告落地根目录（Windows 路径）
        default: ""
        prompt: 请输入扫描结果保存目录（如 D:\obs-mind\work\active\AI扫描）
      - key: default_days
        description: 默认时间窗口（自然日）
        default: 7
      - key: classify_mode
        description: 分类模式：inline=会话内免费分类 / api=脚本调 Haiku（无人值守）
        default: inline
      - key: notion_enabled
        description: 是否写入 Notion 数据库
        default: true
      - key: notion_parent_page_id
        description: Notion 父页面 ID（32 位 hex；页面需 Share 给 integration）
        default: ""
        prompt: 请提供 Notion 父页面 URL 或 32 位 page id（用于自动建库）
      - key: session_batch_size
        description: 每个扫描会话处理的账号数（上下文保护；内存或上下文偏小时调低到 2）
        default: 3
      - key: verify_web_search
        description: 是否对 launch 条目做 web_search release date 验证
        default: true
---

# AI X Model Launch Scanner（数字员工 · X 模型发布扫描）

## When to Use

用户要求"扫描 AI 模型发布 / 抓取 AI 公司推文 / 按厂家清单扫一遍 / 跑模型扫描 / 近 N 天有什么新模型 / scan AI model launches"时加载本 skill。定时任务触发时同样适用。

**约束声明**（首次对话须告知用户）：
- 扫描期间请保持 Chrome 在**主屏幕最上层**，不要最小化/遮挡；被切走会自动前置恢复（流程 W），持续遮挡会中止报错
- 建议用户**最大化 Chrome**（增大 pointer viewport 预算）并**关闭浏览器自动翻译**（弹窗会挡住 X tab）
- 需要用户 Chrome 已登录 X（本 skill 不导 cookie、不代登录）
- 上下文保护：每个扫描会话只扫 3 个账号（config `session_batch_size`），批次结束换新会话 `--resume` 续扫

**🚨 三禁硬规则（违反 = 本 run 无效）**：
- 扫描被任何原因阻断（consent / 未登录 / 超时 / 窗口丢失）→ 该账号标 `no-x-data` 即 STOP
- **任何 web/搜索来源的内容禁止写入 `data/raw/`**（raw 只含 X timeline 直读数据）
- web_search 仅允许出现在 Step 4b，且只针对 `classified.json` 中 `is_launch=true` 的条目
- 不替代扫描、不发现新推文、不补"扫不到"的账号

## Quick Reference

| Step | 内容 | 执行者 |
|---|---|---|
| 0 | 环境检查 + cua attach + 登录态检查 | agent + 1 Bash |
| 1 | 14 大厂 timeline 扫描（分批会话） | agent（cua）+ parse_account.py |
| 2 | launch 候选详情页深度抓取 | agent（cua）+ merge_detail.py |
| 3 | @arena + @ArtificialAnlys 扫描 | agent（cua） |
| 4a | LLM 分类（inline / --api） | agent 或 classify.py |
| 4b | web_search 验证 release date | agent（web_search/web_extract） |
| 5 | 第三方交叉验证 | cross_check.py |
| 6 | 下载 benchmark 图片 | grab_images.py |
| 7 | 本地报告 + Notion | write_local.py + notion_sync.py |

**命令约定**：`${HERMES_SKILL_DIR}` 由 hermes 加载时替换。工具级细则见 `${HERMES_SKILL_DIR}\references\cua-recipes.md`；失败诊断见 `references\scan-failure-modes.md`。

**API 前台分类**（2026-09-04 实测，详见 cua-recipes.md）：
- **CDP 免前台组（首选）**：`cua_browser_click(ref=...)`、`cua_browser_pointer`（scroll/click/drag）、`cua_browser_navigate`、`cua_browser_state`
- **SendInput 前台组（慎用）**：`computer_use key`（**禁止**用于 timeline 操作，Chrome `Chrome_WidgetWin_1` 拒绝 background keystroke）；`computer_use click coordinate`（仅无 ref 时）；`computer_use focus_app`（启动/恢复时切焦点）
- **调用顺序铁律**：prepare 后**不得**立即 navigate（`browser_mutation_unproven`）→ 中间插一次 `cua_browser_state`；navigate 后先 fresh snapshot 再 mutation（`browser_verification_required`）；**每次 mutation 前必须 fresh `cua_browser_state`**

**厂商清单**：以 `assets\vendors.main.json`（14 大厂）+ `assets\vendors.thirdparty.json`（@arena、@ArtificialAnlys）为唯一依据，见 `references\vendors.md`。

## Procedure

### Step 0 — 启动准备（≤ 30s）

1. 读 config 注入值。`base_dir` 为空 → 追问用户（Windows 路径），并提示写入 `~/.hermes/config.yaml` 的 `skills.config.base_dir` 持久化（否则产物落临时目录且每次都问）。`notion_enabled=true` 且 `notion_parent_page_id` 为空 → 同样追问
2. `python "${HERMES_SKILL_DIR}\scripts\check_env.py"` → 退出码 12 → 按提示 `python -m pip install <缺失包>` 后重试
3. Notion 启用时：`python "${HERMES_SKILL_DIR}\scripts\notion_sync.py" --check-auth` → exit 3 = 未配置 token → **静默降级为仅本地**（notion_sync 全程跳过，不提示不阻塞）。配置方法（一次性，用户手动）：管理员/普通终端执行 `setx NOTION_TOKEN "ntn_你的token"` 后**重启 Hermes desktop**（子进程继承用户环境变量）
4. Chrome 实例巡检（工具级细则见 `references\scan-failure-modes.md` H 章）：
   ```
   python "%USERPROFILE%\.hermes\tools\chrome_inspect.py"     # 机器级工具，未部署则跳过本步
   ```
   - 未部署判据：stdout 无 JSON 且 stderr 报 can't open file → 跳过本步直接第 5 步（不阻塞；亦可用第 2 步 check_env 输出的 `chrome_inspector` 字段预判。工具自身 exit 0/1/2 均带 stdout JSON，不会与未部署混淆）
   - exit 0 → 记录 `summary.cdp_ready`（pid/port）作 attach 佐证，继续第 5 步
   - exit 1 / 2 → 🛑 STOP：把 `summary.action_hint` 原样报告用户；**禁止自行拉起/重启浏览器、禁止启动无头 Chrome**
   - exit 3 → 报告 stderr 错误内容；跳过巡检继续主流程（不重试巡检）
5. cua attach + 登录态检查（**先导航、后验登录态**——cua_driver 在非 x.com 页面无法返回登录状态；实测工具名，细则见 cua-recipes.md）：
   ```
   computer_use list_apps                                        # 找 chrome.exe pid
   computer_use list_windows(pid)                                # cheap：is_on_screen && !minimized
   computer_use cua_browser_prepare(strategy="existing_profile", pid=<pid>, window_id=<hwnd>)
   computer_use cua_browser_state(pid, window_id)                # ⚠️ prepare 后必须先 state（bind + tab_id）
   computer_use cua_browser_navigate(url="https://x.com/home", ...)   # ⚠️ 先跳 x.com（无论当前在哪个页面）
   # terminal sleep 2-3
   computer_use cua_browser_state(...)                           # ⚠️ 之后才判登录态
   ```
6. **登录态判定 = 只看跳转结果 URL**：`x.com/home` → 已登录；强制停在/跳回 `x.com`（登录页）→ 🛑 STOP，请用户在 Chrome 登录 X 后重跑。**不代登录**
7. **错误分支（硬规则，错误码为 2026-09-04 实测名）**：
   - `browser_requires_setup: no owned endpoint` → 🛑 STOP，不 fallback 不重试
   - `browser_existing_profile_not_granted` / `browser_consent_required` → **征得用户明确同意后**可代写 `~/.hermes/config.yaml` 的 `computer_use.grant_existing_profile: true`（或用户手改）；**改完必须重启 Hermes desktop 才生效**；重启后 daemon 不会被自动拉起 → 可按 `references\scan-failure-modes.md` G8 自启带 `--grant` 的 daemon（进程级授权，一键脚本 `%USERPROFILE%\cua-attach-chrome.ps1`）
   - `wrong_target_refused` → `focus_app` 切焦点后重试 1 次；仍失败 → 建议用户只保留单一 X home 标签页后重跑
   - `browser_mutation_unproven` / `browser_verification_required` → 先做一次 fresh `cua_browser_state` 再重试原操作
   - `this session has ended` / 跨会话 MCP 断连 → 每个新 agent process 都要走一遍第 5 步完整 re-attach
   - 窗口不在最上层/被遮挡/Chrome 休眠 → **流程 W**（见下）
   - 巡检 `summary.headless_instances` 非空 → 提示用户自行关闭残留无头实例（**不自动杀进程**）
   - Chrome 实例/端口状态拿不准 → 先巡检（第 4 步，H 章）再裁决；**禁开 Chrome 内置任务管理器、禁无头 fallback**
   - ⚠️ cua-driver 升级（`hermes computer-use install --upgrade`）会断当前 MCP session → 只允许在无扫描进行时升级，升级后重启 Hermes desktop

### Step 1 — 厂商主账号扫描（分批会话）

1. `python "${HERMES_SKILL_DIR}\scripts\plan_scan.py" --stage main --days <N> --base-dir <base_dir> [--run-id <id>] [--resume] [--batch-size <3>]`
   → 输出 `RUN>{...}` JSON 行：run_id、本会话批次（batch 字段）、companies、ctx_hint。新 run 会创建 `<base_dir>\data\raw\<run_id>\`
2. 对批次内每账号执行 recipe（细则与 trap 见 `references\cua-recipes.md`）：
   ```
   computer_use focus_app(pid)                                            # 失败 → 流程 W
   computer_use cua_browser_navigate(url="https://x.com/<handle>", ...)   # 等 terminal sleep 2-3
   computer_use cua_browser_state(...)   # snapshot：AX tree（status_id href / engagement aria-label / photo link / time）+ 可读文本 + "Pinned"/"置顶"标记
   # 时间窗未覆盖 → 滚动一轮再来：
   computer_use cua_browser_pointer(x, y, delta_y=2000~4000)   # ⚠️ 唯一滚动路径；mutation 前必须 fresh state
   # terminal sleep 2-4 → cua_browser_state(...)（只提取新增 status_id）
   ```
   - **时间窗全覆盖是硬要求**：终止条件 = 本轮最老一条推文 `created_at < since`，或 R=4 轮上限。宁可多滚，不得提前收手
   - **增量提取**：维护已见 status_id 集合，每轮只提取新增，追加进 raw JSON——也是流程 W 恢复后续扫的幂等基础
   - **滚动注意**：`delta_y` 建议 2000-4000（太小 X 不触发 IntersectionObserver 加载下一批）；`to_x/to_y` 仅用于 drag；置顶带视频推文会独占 ~300 节点 viewport 预算，必须滚动才能触发后续加载
   - 每账号 1-4 轮：稀疏 1 轮，高密度（@OpenAI 类）3-4 轮；单账号总调用 **≤15**（实测基线 12-15）
3. **每账号完成后立即落盘**（她的体量只进磁盘不进上下文）：写 `<run_dir>\raw_<handle>.json`（UTF-8 无 BOM）：
   ```json
   {"handle": "OpenAI", "company": "OpenAI", "rounds": 2,
    "tweets": [{"status_id": "...", "text": "...", "time_raw": "Wed Sep 03 10:12:33 +0000 2026",
                "engagement_raw": "81 replies, 328 reposts, 2448 likes, 215 bookmarks, 182331 views",
                "media": ["https://pbs.twimg.com/media/xxx.jpg"], "pinned": false}]}
   ```
   然后 `python "${HERMES_SKILL_DIR}\scripts\parse_account.py" --base-dir <base_dir> --run-id <run_id> <handle>`
   → stdout 一行 `@OpenAI ok rounds=2 fetched=12 in_window=3 pinned=1`。exit 2 → 按提示修 raw 文件一次重跑；再失败 → `--mark-failed parse-failed`
4. 失败标 `empty / rate-limited / nav-timeout / session-expired / parse-failed / window-lost-fatal` 入 run_report；每账号 ≤2 次重试；任一 `session-expired` → 整体中止
5. **批次纪律**：每会话 ≤ `session_batch_size`（默认 3）账号且累计滚动轮数 ≤6；达到即收尾本会话，换新会话从第 1 步 `--resume` 续扫

### Step 2 — 详情页深度抓取（≤ 5 min）

1. `python "${HERMES_SKILL_DIR}\scripts\prefilter.py" --base-dir <base_dir> --run-id <run_id>` → `candidates.json`
2. 逐候选（每会话 ≤15 个）：`cua_browser_navigate("https://x.com/<handle>/status/<id>")` + fresh `cua_browser_state`（详情页不截断，解 B2）→ 落盘 `raw_detail_<id>.json`：`{"status_id","text_full","media","external_links"}`；浏览器异常 → 流程 W
3. `python "${HERMES_SKILL_DIR}\scripts\merge_detail.py" --base-dir <base_dir> --run-id <run_id>` → `detail_tweets.json`
4. 预算用尽 → 跳过剩余，不阻塞

### Step 3 — 小厂模型发现（≤ 3 min）

`python "${HERMES_SKILL_DIR}\scripts\plan_scan.py" --stage thirdparty --base-dir <base_dir> --run-id <run_id>`
然后对 @arena、@ArtificialAnlys 复用 Step 1 recipe（同会话同 tab，切账号 ≈3 calls）。标记 `is_third_party=true`（parse_account 自动）。
### Step 4a — LLM 分类（先于 4b/5/6）

`python "${HERMES_SKILL_DIR}\scripts\classify.py" --base-dir <base_dir> --run-id <run_id>`
→ 产出 `to_classify.json`（仅 id/handle/text/links 精简字段）。

- **inline（classify_mode=inline，默认）**：本会话**不读** candidates/raw 大文件；只读 `to_classify.json` → 按 `${HERMES_SKILL_DIR}\templates\classify_prompt.txt` 规则逐条判 → 写 `classified.json`（UTF-8，schema 同 --api）→ `python ... classify.py ... --validate` 校验
- **>120 条 → 强制改 --api**（上下文保护硬规则）：`python ... classify.py ... --api`（需 `ANTHROPIC_API_KEY` / `ant auth login`；调 claude-haiku-4-5，成本 <$0.05）
- `--slice 50` / `--merge` 为分片应急路径
- 分类规则要点：launch=首次发布/正式可用/重大版本升级/新能力上线；排除招聘、活动预告、纯 benchmark 转发、营销、财务；"coming soon"=false；`confidence<0.6` → false；**只依据文本，不补外部知识**

### Step 4b — web_search 真实性验证（仅交互模式；`verify_web_search=false` 或无人值守跳过，记 `release_verified=null`）

- ✅ 允许：对 `is_launch=true` 条目 `web_search("<model_name> <company> release date")` / `web_extract` 官方博客
- ❌ **三禁**：替代 timeline 扫描 / 发现新推文 / 补"扫不到"的账号
- 每条 ≤2 次搜索，超出标"待人工核实"；结果逐条追加落盘 `verified.json`：`[{"id","release_verified",true/false,"external_refs":[...]}]`

### Step 5 — 第三方交叉验证（< 1 min）

`python "${HERMES_SKILL_DIR}\scripts\cross_check.py" --base-dir <base_dir> --run-id <run_id>`
→ launch 条目 × @arena/@ArtificialAnlys 推文模型名匹配 → `cross_verified`；第三方 benchmark 类保留为"第三方信号"。输出 `cross_checked.json`。

### Step 6 — 下载 benchmark 图片（≤ 2 min）

`python "${HERMES_SKILL_DIR}\scripts\grab_images.py" --base-dir <base_dir> --run-id <run_id>`
→ requests 直下 pbs.twimg.com 附图到 `<run_dir>\images\`（无需浏览器）。失败不阻塞。可选 `--todo` 生成截图候选清单，benchmark 推文可由 agent 用 cua 截推文卡片。

### Step 7 — 生成报告 + Notion（≤ 2 min）

```
python "${HERMES_SKILL_DIR}\scripts\write_local.py" --base-dir <base_dir> --run-id <run_id>
python "${HERMES_SKILL_DIR}\scripts\notion_sync.py" --base-dir <base_dir> --run-id <run_id> --parent-id <notion_parent_page_id>
```
- **write_local 必须先于 notion_sync**——Notion 失败不吃掉本地结果
- 报告：`<base_dir>\reports\YYYY-MM-DD-model-launches.md`（同日重跑 -2 后缀不覆盖）
- Notion 自动建库/去重/更新（细则 `references\notion-schema.md`）；`object_not_found` → 用户在父页面 Connections 添加 integration
- 最后按 Verification 模板汇报

### 流程 W — 窗口丢失容错（Steps 1/2/3 所有浏览器调用的错误路径）

**触发信号**：调用报错（ref stale / target not found / window not found / "not a live binding" / CDP timeout / **Chrome 后台或低功耗休眠导致 CDP 断开**）；snapshot 的 title/URL 与预期 x.com/<handle> 不符；连续 2 次调用返回空。

**恢复（≤2 次，每次）**：
1. `computer_use list_apps` → 重新确认 chrome.exe pid
2. `computer_use list_windows(pid)` → title 含 x.com 窗口；`is_on_screen && !minimized`（cheap check）
3. `computer_use focus_app(pid)` → 把 Chrome 调到主屏幕最上层
4. title 不含 x.com（tab 被挪用）→ `cua_browser_navigate` 回目标 URL → fresh `cua_browser_state` 后再继续

**复验**：`terminal sleep 2` → `list_windows` 复验；通过但下个实际调用仍失败 → 升级 `cua_browser_state` 复验。

**裁决**：通过 → 记 incident **继续当前账号**（增量去重幂等）；2 次失败 → **立即停**：标 `window-lost-fatal`、结束会话、报错"请将 Chrome 置于主屏幕最上层后重跑，自动 --resume 续扫"；不做第 3 次。会话内 ≥2 账号 fatal → run 中止。

## Pitfalls

1. **`computer_use key` 禁用于 timeline 操作**：Chrome `Chrome_WidgetWin_1` GUI 类拒绝 background keystroke（`background_unavailable`，与窗口大小/最大化无关，2026-09-04 zoomed 实验证实）；foreground 偷焦点且 X viewport 惰性加载不触发。**滚动/翻页一律 `cua_browser_pointer`（CDP 路径，免前台）**
2. **mutation 前置条件**：prepare 后直接 navigate → `browser_mutation_unproven`；navigate 后直接 mutation → `browser_verification_required`。一律先 fresh `cua_browser_state`
3. **`cua_browser_pointer` 三坑**：`to_x/to_y` 仅用于 drag（滚动用 `x`+`y`+`delta_x`+`delta_y`）；`delta_y` ≥2000（太小不触发加载）；调用前必须 fresh `cua_browser_state`（不带 pid/window_id 一次）
4. **跨会话 MCP session 必断**：每个新 agent process 重新走 Step 0 完整 re-attach；cua-driver 升级也会断——只在无扫描时升级，升级后重启 Hermes desktop
5. `CDP DOM.getDocument timed out`（@deepseek_ai 已知）→ 先流程 W；窗口正常仍超时 → 重试 1 次 → 标 no-x-data，**不 web_search 补**
6. 空 timeline ≠ 厂商没发布 → 标 no-x-data 记入报告
7. 正文截断 → Step 2 详情页重抓
8. **web_search 三禁**：不替代扫描、不发现新推文、不补扫不到的账号；任何 web 来源内容禁止写入 data/raw（parse_account 会拒收）
9. 同一账号重试 ≤2 次；任一 session-expired → 整体中止
10. Notion `object_not_found` → 父页面没 Share 给 integration → Connections 添加
11. **Windows 编码**：落盘 JSON 强制 UTF-8 无 BOM；脚本读写显式 `encoding="utf-8"`；终端中文先 `PYTHONIOENCODING=utf-8`
12. **上下文保护**：分批会话（默认 3 账号/会话、滚动 ≤6 轮）、即扫即弃、分类不混入扫描会话、>120 条切 --api、每条验证 ≤2 次搜索；压缩/中断后 `plan_scan.py --status --resume` 重新定位
13. **窗口焦点**：cua_driver 对非主屏幕最上层窗口不可用 → 流程 W；恢复 ≤2 次，失败**立即报错**，绝不无限重试；复验用 `list_windows`（cheap）不用 `get_window_state`
14. **登录态检查顺序**：非 x.com 页面拿不到登录态 → attach 后、W 恢复后**先导航到 x.com 再判登录态**；只看跳转 URL（`x.com/home`=已登录，`x.com` 登录页=未登录 → STOP，不代登录）
15. **Chrome 自动翻译弹窗**会挡住 X tab → 引导用户关闭自动翻译或先手动关掉弹窗
16. **置顶带视频推文独占 ~300 节点 viewport 预算**（X SPA 惰性加载）→ 不滚动就永远看不到后续推文，必须 scroll

## Verification

- Step 1 每账号 stdout 一行汇总（ok/rounds/fetched/in_window/pinned）
- Step 7 后向用户汇报模板：
```
✅ 扫描完成 · <窗口>（近 N 天）
   16 个账号 · 抓取 X 条 · 命中 launch Y 条 · 第三方信号 Z 条
发现的模型发布：
  1. ...（公司）— 一句话 [95%] ✓验证 ✓第三方确认
⚠️ @deepseek_ai no-x-data —— 不代表该厂商没发布
📄 报告：<base_dir>\reports\...  🖼️ images\（N 张）  🗃️ Notion：新增 a，更新 b
```
- 断言：报告存在且含"无数据不等于没发布"段；`cross_checked.json` 的 launch 均带 `release_verified`（true/false/null）；本会话账号数 ≤ `session_batch_size`；**单账号总调用 ≤15**；raw 文件不含任何 web 来源字段
