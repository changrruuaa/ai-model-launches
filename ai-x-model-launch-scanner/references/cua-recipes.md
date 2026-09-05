# cua-driver 调用 recipe（2026-09-04 hermes desktop 实测版，cua-driver 0.23.2）

> 本文件是 SKILL.md Procedure 的工具级细则。所有签名与结论来自 2026-09-04 三轮 hermes 实测
>（runs 20260904-142109 / 145545 / 153150，@OpenAI 单账号冒烟）+ hermes 端发现清单 D1-D16 / R1-R4。
> **三条硬约束**：① cua_driver 要求目标窗口在**主屏幕最上层**；② cua_driver 在**非 x.com 页面无法返回登录状态**；
> ③ **抢焦点必还**——扫描结束/中止时把焦点归还 hermes desktop（§5）。

---

## 0. API 前台分类速查（按"是否需要前台窗口"）

| API | 底层路径 | 需前台？ | 适用场景 |
|---|---|---|---|
| `cua_browser_click(ref=...)` | CDP | ❌ | 点击按钮/链接（**首选**，比坐标点击可靠） |
| `cua_browser_pointer`（scroll/click/drag） | CDP `Input.dispatchMouseEvent`（route: trusted_input） | ❌ | 鼠标操作（**滚动唯一正解**） |
| `cua_browser_navigate` | CDP | ❌ | URL 跳转 |
| `cua_browser_state` | CDP | ❌ | 抓取 snapshot / 重新 bind |
| `computer_use click coordinate=...` | SendInput | ⚠️ 部分要 | 仅当没有 ref 时 |
| `computer_use key` | SendInput | ✅ 强制前台 | **禁用于 timeline 操作**（Chrome 拒绝） |
| `computer_use focus_app` | 切窗口焦点 | ✅ | 启动/恢复时把焦点给 Chrome |

**为什么 key 被拒**：Chrome 的 `Chrome_WidgetWin_1` GUI 类主动拒绝 background keystroke
（`background_unavailable`），与窗口是否最大化无关（zoomed=True 实验证实）；foreground 按键偷焦点
且 X viewport 惰性加载不触发。`cua_browser_pointer` 走 CDP，不依赖 SendInput、不偷焦点、不受窗口状态影响。

---

## 1. attach + 登录态检查（Step 0，顺序不可颠倒）

前置：`python "%USERPROFILE%\.hermes\tools\chrome_inspect.py"` 巡检 Chrome 实例（细则见 scan-failure-modes.md H 章；工具未部署则跳过）。

**pid/hwnd 浮动（2026-09-05 实测）**：Chrome 每次启动 pid 与 MainWindowHandle 都会变（实测 pid 7504→16308→20088→8872），必须每次实查、**绝不缓存**；窗口过滤只认 `MainWindowHandle != 0`（Chrome 一次会启 8-10 个子进程，句柄全为 0——`!= 0` 即隐藏/后台窗口过滤器）。

```
computer_use list_apps                                     # 找 chrome.exe pid
computer_use list_windows(pid)                             # cheap：{title, window_id, bounds, is_on_screen, minimized}
computer_use cua_browser_prepare(strategy="existing_profile", pid=<pid>, window_id=<hwnd>)
# → attached_existing_profile
computer_use cua_browser_state(pid, window_id)             # ⚠️ prepare 后必须先 state：native bind + tab_id
computer_use cua_browser_navigate(url="https://x.com/home", ...)   # ① 先导航（无论当前在哪个页面）
# terminal sleep 2-3
computer_use cua_browser_state(...)                        # ② 再判登录态（snapshot）
```

**登录态判定 = 只看跳转结果 URL**：
- `https://x.com/home` → 已登录，继续
- 强制停在 `https://x.com`（登录页/登录墙）→ 未登录 → 🛑 STOP，请用户在 Chrome 登录后重跑（**不代登录**）

**调用顺序铁律**：
- prepare 后**不得**立即 navigate → `browser_mutation_unproven`；中间必须插一次 `cua_browser_state`
- navigate 后直接 mutation → `browser_verification_required`；先 fresh snapshot
- **每次 mutation 前必须 fresh `cua_browser_state`**（不带 pid/window_id 调一次拿最新 ref/binding）

错误分支（实测错误码）：
- `browser_requires_setup: no owned endpoint` → 🛑 STOP（不 fallback、不重试）
- `browser_existing_profile_not_granted` → **征得用户同意后**写 `~/.hermes/config.yaml` 的 `computer_use.grant_existing_profile: true`（或用户手改）；**必须重启 Hermes desktop 才生效**（实测 2026-09-04：写后错误从 not_granted 变为可继续）；或重启后按 scan-failure-modes.md G8 `Start-Process` 自启带 `--grant` 的 daemon（进程级授权，不依赖 config）
- `wrong_target_refused` → cua-driver 对 X SPA 的窗口 heuristic（"no exact New Tab button" 过严，0.23.2 已修部分）→ `focus_app` 后重试 1 次；仍失败建议用户只留单一 X home 标签页
- 跨会话 MCP session 必断（R1/D10）→ 每个新 agent process 重走本节完整流程
- cua-driver 升级断当前 MCP session（R1/D3）→ 只在无扫描时升级（`hermes computer-use install --upgrade`），升级后重启 Hermes desktop

---

## 2. 单账号扫描（滚动逐轮，时间窗全覆盖）

```
computer_use focus_app(pid)                                          # 失败 → 流程 W
computer_use cua_browser_navigate(url="https://x.com/<handle>", ...) # terminal sleep 2-3（实测 X 渲染需 2-3s）
# 第 1 轮（无需滚动）：
computer_use cua_browser_state(...)   # snapshot：AX tree（status_id href / engagement aria-label / photo link / time）+ 可读文本 + "Pinned"/"置顶"
# 第 R 轮（R=2..4）：
computer_use cua_browser_state       # ⚠️ mutation 前先 fresh（不带 pid/window_id）
computer_use cua_browser_pointer(x, y, delta_y=2000~4000)   # 唯一滚动路径
# terminal sleep 2-4 → cua_browser_state(...)（只提取新增 status_id）
```

**pointer 参数**：
- 滚动用 `x` + `y` + `delta_x` + `delta_y`；**`to_x/to_y` 仅用于 drag action**
- `delta_y` 建议 **2000-4000**：太小 X 不触发 IntersectionObserver 加载下一批（D5）
- 最大化 Chrome 窗口（zoomed）→ pointer viewport 预算更大 → 每轮覆盖更多节点（间接收益，非根治）

**终止**：本轮最老一条 `created_at < since`，或 R=4。窗内推文漏看 = 漏报，不得提前收手
**增量提取**：维护已见 status_id 集合，只追加新条目到 raw_<handle>.json
**预算**：稀疏账号 R=1，高密度（@OpenAI 类）R=3-4；单账号总调用 **≤15**（实测新基线 12-15，旧 key 路径 17-25）

**每轮从 snapshot 提取**：
- status_id：`href="/<handle>/status/<id>"` 中的 `<id>`
- engagement：`aria-label="81 replies, 328 reposts, 2448 likes, 215 bookmarks, 182331 views"` 原样保存（`engagement_raw`）；或 slash 快记 `"798/1754/14966/4084763"`（`engagement`，parse_account 归一化，两者都支持）
- media：`href="/status/<id>/photo/1"` 意味有图（pbs.twimg.com URL 从 snapshot 文本/详情页补）
- time：优先 X 标准格式 `Wed Sep 03 10:12:33 +0000 2026`（`time_raw`，秒级）；只有相对/显示时间时记 `time_display`（须含绝对 UTC，如 `"11h ago / 2026-09-04 03:32 UTC"`，parse_account 按分钟精度归一化）

**pinned 判定**："Pinned" / "置顶" 标题下方第一条 article。
**R4 注意**：置顶带视频推文独占 ~300 节点 viewport 预算——不滚动永远看不到后续推文。

**raw_<handle>.json 格式**（agent 每账号落盘一次，UTF-8 无 BOM；**禁止任何 web/搜索来源字段**，parse_account 会拒收）：
```json
{"handle": "OpenAI", "company": "OpenAI", "rounds": 2,
 "tweets": [{"status_id": "1956...", "text": "...",
             "time_raw": "Wed Sep 03 10:12:33 +0000 2026",
             "engagement_raw": "81 replies, 328 reposts, 2448 likes, 215 bookmarks, 182331 views",
             "media": ["https://pbs.twimg.com/media/xxx.jpg"], "pinned": false}]}
```

---

## 3. 详情页抓取（Step 2）

```
computer_use cua_browser_navigate(url="https://x.com/<handle>/status/<id>", ...)   # terminal sleep 2-3
computer_use cua_browser_state(...)    # 详情页不截断（解 B2）；提取全文 + 图片 URL + 外链
```
落盘 `raw_detail_<id>.json`：`{"status_id": "...", "text_full": "...", "media": [...], "external_links": [...]}`

---

## 4. 流程 W — 窗口丢失容错

**触发信号**：调用报错（ref stale / target not found / window not found / "not a live binding" / CDP timeout / **Chrome 后台或低功耗休眠导致 CDP 断开**（R3））；snapshot 的 title/URL 与预期不符；连续 2 次调用返回空。

**恢复（≤2 次，每次）**：
1. `computer_use list_apps` → 重新确认 pid
2. `computer_use list_windows(pid)` → title 含 x.com 的窗口；`is_on_screen && !minimized`
3. `computer_use focus_app(pid)` → Chrome 调到主屏幕最上层
4. title 不含 x.com → `cua_browser_navigate` 回目标 URL → fresh `cua_browser_state`

**复验**：`terminal sleep 2` → `list_windows` 复验；通过但下个实际调用仍失败 → 升级 `cua_browser_state` 复验。

**裁决**：通过 → 记 incident 续扫（增量去重保证幂等）；2 次失败 → **立即**标 `window-lost-fatal`，结束会话，报错指引"Chrome 置于主屏幕最上层后重跑 --resume"；会话内 ≥2 账号 fatal → run 中止。结束会话/run 中止时执行**焦点归还**（§5）。

---

## 5. 焦点归还（扫描结束/中止时把焦点还给 hermes desktop）

操控 Chrome 需要抢焦点（Chrome 置主屏幕最上层）；**错误或工作结束时必须把焦点归还 hermes desktop**（硬约束③）。
`focus_app` 是通用窗口焦点 API（非 Chrome 专属）；hermes desktop 自己在 `list_apps` 中可见（2026-09-05 用户确认）。

```
computer_use list_apps                        # 重新实查 hermes desktop pid（不缓存，同 pid/hwnd 浮动原则）
computer_use focus_app(<hermes_desktop_pid>)
```

守则：
- 归还失败 → 记一句"焦点归还失败 <原因>"，**不阻塞**收尾/中止流程本身
- computer_use MCP 不可用（session 过期/驱动升级断连）→ **跳过归还**，报告如实说明"焦点未归还"——Chrome 多进程 + 焦点返还延迟，无可靠终端兜底（2026-09-05 用户确认）
- 从未抢过焦点的中止点（如巡检 STOP，Chrome 未被前置）→ 归还 = 聚焦 hermes desktop 本身，无害
- 焦点归还调用不计入单账号 ≤15 扫描调用预算（会话级 1-2 次）
- 归还后中途再需要浏览器 → `focus_app(chrome_pid)` 重新前置即可（CDP 免前台组不依赖焦点，cua 会话不受影响）

**触发点**：①Step 0 任何 🛑 STOP（巡检 exit 1/2、browser_requires_setup、登录墙、grant 拒绝）②Step 1 批次纪律收尾 ③session-expired 整体中止 / window-lost-fatal 会话结束（§4 裁决）④Step 3 末（浏览器阶段结束、进 Step 4a 前）⑤Step 7 报告完成。

---

## 6. 已知 trap（不试）

- `computer_use key` 做 timeline 翻页/滚动 → `background_unavailable`（Chrome_WidgetWin_1 拒绝，无解，绕开）
- prepare 后直接 navigate → `browser_mutation_unproven`；navigate 后直接 mutation → `browser_verification_required`
- pointer `to_x/to_y` 用于滚动 → 无效（仅 drag）；`delta_y` <2000 → X 不加载下一批
- Chrome 自动翻译弹窗挡住 X tab（D12）→ 引导用户关闭自动翻译
- 置顶视频推文占满 viewport 预算（R4）→ 必须滚动
- 旧工具集遗留（hermes/WSL 时代）：`page query_dom` 的 `[data-testid=...]` 在 Windows UIA 不可达、`page execute_javascript` 被 standard daemon 拒——新 API（cua_browser_*）已无这些路径，但不要混用旧名
- 同一账号重试 ≤2 次；任一 session-expired → 整体中止
