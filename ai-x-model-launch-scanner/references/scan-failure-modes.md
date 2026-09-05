# AI X-scan failure modes & workarounds（cua-driver 版继承）

> **继承关系**：本文件源自 x-cua-driver-scanner（deleted 2026-09-02）→ ai-x-model-launch-scanner 旧版 → 本 skill。
> 原 WSL/hermes 环境经验改写为 hermes desktop（Windows 原生）语境；**排除**所有"web_search 回退"路径（与本 skill"web_search 三禁"原则冲突），仅保留验证用途。
> 实战来源：2026-09-01~03 三轮 run 实测（详见旧文件 provenance）。

## A. cua-driver / CDP failures

### A1. `CDP DOM.getDocument timed out after 20s`
特定 X profile（如 @deepseek_ai）触发，页面已加载但 CDP 序列化超时。
**workaround**：先触发流程 W 确认窗口正常 → 仍超时则重试 1 次 → 标 `no-x-data` 记入报告。**不 web_search 补**。

### A2. `the browser operation requires an explicit session`
新 label `start_session` 后调用 browser_* 报此错。
**workaround**：`browser_prepare(strategy=existing_profile, pid, window_id)` → 收到 attach 确认 → `get_browser_state` 拿新 target/tab。

### A3. `target_id is not a live binding`
用旧 session 的 target/tab 调 navigate。
**workaround**：`get_browser_state` 重拿。每个 lifecycle session 有自己的 target/tab namespace。

## B. X.com content failures

### B1. Blank sub-account timeline
snapshot ~100 元素 0 article（@ChatGPTapp Sep 2 触发）。可能是 X 限流或子账号特殊状态。
**workaround**：流程 W → 仍空 → 标 no-data 记入报告。**不假设厂商没发布**。

### B2. Truncated tweet body on profile timeline
长推文在 timeline 上总被截断（"Show more"）。**本 skill 由 Step 2 详情页机制系统性解决**：`x.com/<handle>/status/<id>` 详情页不截断。

### B3. og:description via curl（历史 workaround）
`curl -A "Mozilla/5.0..." "https://x.com/<handle>/status/<id>"` 拉 og:description（截 ~280 字符）。仅作诊断备用；主路径是详情页 get_text。

## C. Anonymous-access X data sources that DO NOT work

- `syndication.twitter.com/...` → 429 per-IP 限流。不重试、不加 sleep 硬扛
- Nitter instances → TLS/CF challenge 全挂。别浪费时间
- **本 skill 原则**：不引入任何匿名抓取源，抓不到就标 no-x-data

## D. Reliability tactics

- **Per-vendor retries ≤ 2**：超出走 no-data 路径
- **Window discipline**：默认 7 天。窄窗口会漏边缘 release（Tencent Hy4 Aug 28 曾卡在 2 天窗口外）
- **Vendor audit trail**：报告必须区分"扫了没发布"（cite X URL）与"没抓到"（no-x-data）

## E. Browser attach refusal taxonomy

| 症状 | 编码 | 首选动作 |
|---|---|---|
| `no owned endpoint is available` + allow_launch hint | E1 | 🛑 STOP，不 fallback、不 isolated browser |
| `browser_existing_profile_not_granted` / isolated 要求 | E2 | **征得同意后代写** `grant_existing_profile: true` + 重启 Hermes（见 G4）；或重启后按 G8 自启带 grant daemon |
| `this session has ended` mid-batch | A2 | `start_session` 新 label → `browser_prepare` 重绑 |
| `CDP DOM.getDocument timed out` mid-batch | A1 | 流程 W → 重试 1 次 → no-data |
| 窗口被遮挡/最小化/切后台 | W | 流程 W（恢复 ≤2 次，2s 复验，失败立即报错） |

## F. Cheap before expensive

`list_windows(pid)` 返 flat record（title/window_id/bounds/is_on_screen/minimized），无 UIA walk；`get_window_state` 触发完整 UIA walk（几百元素 + screenshot）。
**窗口复验一律用 `list_windows`**；仅在 list_windows 通过但实际调用仍失败时升级 `cua_browser_state`。

## G. 2026-09-04 hermes desktop 实测（runs 142109/145545/153150，cua-driver 0.21.0→0.23.2）

> 三轮 @OpenAI 单账号冒烟 + hermes 端发现清单（D1-D16/R1-R4）。本节为实测新增；A-F 为历史继承。

### G1. 滚动路径定论（D1/D2/D5/D7）
- `computer_use key PageDown`：background 被 Chrome `Chrome_WidgetWin_1` 类拒绝（`background_unavailable`），**与窗口大小无关**（zoomed=True 仍被拒）；foreground 偷焦点且 viewport 惰性加载不触发
- **唯一正解 `cua_browser_pointer`**（CDP `Input.dispatchMouseEvent`，route: trusted_input）：免前台、不偷焦点、连发稳定
- pointer：滚动用 `x/y/delta_x/delta_y`（`to_x/to_y` 仅 drag）；`delta_y` 2000-4000，太小 X 不触发 IntersectionObserver

### G2. 调用顺序约束（R2/D8/D11）
- prepare → 立即 navigate = `browser_mutation_unproven`；中间必须 `cua_browser_state`（bind）
- navigate → 直接 mutation = `browser_verification_required`；先 fresh snapshot
- 每次 mutation 前 fresh `cua_browser_state`（hard rule）

### G3. 升级与 session（R1/D3/D10/D16）
- driver 0.21.0 的 "no exact New Tab button" heuristic bug（`wrong_target_refused`）在 0.23.2 修复 → 保持 0.23.2+
- `hermes computer-use install --upgrade` 会**断当前 MCP session**（Connection closed），本会话 computer_use 全失联，仅新会话恢复 → 只在无扫描时升级；升级后重启 Hermes desktop
- config.yaml 改动（如 grant_existing_profile）也需重启 Hermes desktop 生效
- 跨会话 MCP session 必断 → 每个新 agent process 重新 prepare

### G4. consent 分支实测（修正旧 E2 规则）
- 实测错误名 `browser_existing_profile_not_granted`（非旧文档的 `browser_consent_required`）
- run1 中 agent 自行写 config.yaml 成功解锁（not_granted → 错误码变化确认生效）→ 现行规则：**征得用户明确同意后可代写**，写后提示重启 Hermes
- 替代路径（2026-09-05）：重启 Hermes desktop 后 daemon 不会自动拉起 → 按 G8 `Start-Process` 自启带 `--grant existing-profile` 的 daemon（进程级授权，不依赖 config.yaml；同样须先征得用户同意）
- `wrong_target_refused`（X SPA heuristic）缓解：`focus_app` 先行 + 单一 X home 标签页

### G5. 登录态与内容形态
- run1 时 Chrome X tab 为**登出状态**（中文登录页）→ 先导航后验登录态规则生效；登出状态下后续 prepare/滚动可能"成功"但内容是登录墙 → 登录判定必须在 navigate 后立刻做
- 置顶带视频推文独占 ~300 节点 viewport 预算（R4）→ 必须滚动触发 IntersectionObserver
- Chrome 自动翻译弹窗挡 X tab（D12）→ 关闭自动翻译
- Chrome 后台/低功耗休眠会断 CDP（R3）→ 作为流程 W 触发信号

### G6. 违规案例存档（三禁）
run 20260904-142109：consent 未授权 → timeline SKIPPED → agent 用 web_search 回填 `external_sources` 进 raw_OpenAI.json——**违反三禁**。修复：SKILL.md 三禁硬化框 + parse_account.py 对含 web 来源字段的 raw 拒收（exit 2）。fixtures：`tests/fixtures/raw_openai_run1_reject.json`（拒收样例）、`raw_openai_run3_real.json`（合规样例）。

### G7. 错误码速查（2026-09-04 实测汇总）

| 错误码 | 触发 | 首选动作 |
|---|---|---|
| `browser_requires_setup: no owned endpoint` | 无 owned endpoint | 🛑 STOP |
| `browser_existing_profile_not_granted` | grant_existing_profile 未配 | 同意后代写 config + 重启 Hermes |
| `wrong_target_refused` | X SPA heuristic | focus_app + 重试 1 次 + 单 X tab |
| `browser_mutation_unproven` | prepare 后直接 navigate | 先 `cua_browser_state` |
| `browser_verification_required` | navigate 后直接 mutation | 先 fresh snapshot |
| `background_unavailable` | key 后台投递被 Chrome 拒 | 换 `cua_browser_pointer` |
| `Connection closed`（MCP） | driver 升级/会话过期 | 重启 Hermes desktop / 新会话 re-attach |
| 巡检 exit 1 / 2 | Chrome 无可用 CDP 端口 / 未运行 | 🛑 STOP + `action_hint` 报告用户（H 章） |
| 巡检 exit 3 | 巡检脚本内部错误 | 报告 stderr 内容；跳过巡检不阻塞主流程 |
| daemon 不在（重启后空窗） | daemon 未被自动拉起；若 daemon 存活但未带 grant → mid-session 原地无解（G8），须先重启 Hermes desktop | **征得同意后**按 G8 `Start-Process` 自启带 `--grant` 的 daemon |

### G8. cua-driver daemon 生命周期与手动 grant attach（2026-09-05 实测）

> 背景：hermes 拉起的 daemon **默认不传 `--grant`**，attach 用户日常 Chrome 会被 `browser_existing_profile_not_granted` 拒。要换成带 grant 的 daemon 无法原地替换（杀不死），只能在重启 Hermes desktop 后的空窗手动拉起。

- **hermes 拉起的 daemon 杀不死**：`Stop-Process -Name cua-driver -Force` → hermes 立刻拉起新的；`taskkill /F /PID` → 权限不足（进程 token 在不同 session）；`psutil.Process(pid).kill()` → 调用方卡死 300s（复活机制死循环/死锁）。任何"stop + restart daemon"路径都不可行
- **唯一换血窗口**：重启 Hermes desktop → daemon **不会**被自动拉起 → 此刻手动拉起（见下）
- **手动启动唯一正解 = `Start-Process -WindowStyle Hidden`**：`subprocess.Popen` + `DETACHED_PROCESS`/`CREATE_NEW_PROCESS_GROUP` 在 MSYS bash 下常立刻挂掉或被父进程杀；Python subprocess 起的 daemon 起不来且 CommandLine 不可见；`Start-Process` 启动的在 PowerShell 进程空间存活、`Get-CimInstance` 能看到完整 CommandLine

**四步流程**（一键脚本：仓库 `tools\cua-attach-chrome.ps1` → 部署 `copy tools\cua-attach-chrome.ps1 "%USERPROFILE%\cua-attach-chrome.ps1"`）：

1. 起 daemon（`--grant` 是 **daemon 进程级 flag，不经过 config.yaml 检查**）：
   ```
   Start-Process -FilePath "$env:USERPROFILE\.cua-driver\packages\current\cua-driver.exe" -ArgumentList "serve","--grant","existing-profile","--permission-mode","standard" -WindowStyle Hidden
   # 等 3-4s daemon listening
   ```
2. 验证带 grant：`Get-CimInstance Win32_Process` 查 cua-driver CommandLine，应含 `serve --grant existing-profile --permission-mode standard`
3. 找已登录 Chrome（必须有可见窗口）：`Get-Process chrome | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1` → PID/HWND
4. attach 直调 CLI（python stdin 发 JSON，避开 PowerShell 转义坑）：`cua-driver.exe call browser_prepare`，stdin `{"pid":<pid>,"window_id":<hwnd>,"strategy":{"kind":"existing_profile"}}` → 预期 `{"status":"ok","action":"attached_existing_profile",...,"endpoint_ownership":{"method":"devtools_active_ports_file",...}}`

与 G4 的关系：G4 的 config.yaml 路径（同意 → 写 config → 重启）之外，重启后 daemon 未自动拉起时按本节自启带 grant daemon——不依赖 config.yaml 的替代授权路径（**仍须先征得用户同意**）。

## H. Chrome 进程/端口巡检（chrome_inspect.py，机器级工具）

> 背景：任务管理器/PowerShell 进程列表看不到 CDP 端口与 profile 归属；Chrome 内置任务管理器窗口在进程/窗口枚举中与普通 Chrome 无差别、无法识别——两条路都不可用。唯一正解 = 巡检脚本（工具细则与输出 schema 见 `%USERPROFILE%\.hermes\tools\chrome_inspect_README.md`，部署时随脚本一并复制）。

**🚫 两条禁令（违反 = 本 run 无效）**：
1. 禁止打开 Chrome 内置任务管理器（Shift+Esc）查进程/端口
2. 禁止 fallback 启动无头 Chrome 获取用户 cookie/登录态（headless 必无用户登录态）

**调用**：`python "%USERPROFILE%\.hermes\tools\chrome_inspect.py"`（机器级路径；未部署判据：stdout 无 JSON 且 stderr 报 can't open file——工具自身 exit 0/1/2 均带 stdout JSON，可区分——此时跳过巡检，不阻塞）

**裁决表**：

| 巡检结果 | 判定 | 动作 |
|---|---|---|
| exit 0 + `summary.cdp_ready` | 存在 CDP 就绪、非 headless 实例 | 继续正常 attach 流程；pid/port 作佐证 |
| exit 1 | 有 Chrome 但无可用非 headless CDP 端口（用户日常 Chrome 默认无调试端口，属预期） | 🛑 STOP，把 `action_hint` 报告用户 |
| exit 1 + `headless_instances` 非空 | 存在残留无头实例 | 提示用户自行关闭（**不自动杀进程**）；仍 STOP |
| exit 2 | 无 chrome.exe 运行 | 🛑 STOP，请用户先打开 Chrome；**不自行拉起浏览器** |
| exit 3 | 脚本内部错误 | 报告 stderr 内容；跳过巡检不阻塞主流程 |

**已知死路（2026-09 实查，不试）**：`--load-extension`（Chrome 137 起 branded 版移除）、CDP `Extensions.loadUnpacked`（仅会话级，重启失效）、本地 CRX 注册表 path（Chrome 33 起移除）、自托管 update_url 强装（Windows 需域加入/Chrome Enterprise Core）。巡检脚本也拿不到 cookie 内容——登录态只来自用户日常 Chrome 的 attach 主路径。
