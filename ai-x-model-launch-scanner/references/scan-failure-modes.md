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
| `browser_existing_profile_not_granted` / isolated 要求 | E2 | **征得同意后代写** `grant_existing_profile: true` + 重启 Hermes（见 G4） |
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
