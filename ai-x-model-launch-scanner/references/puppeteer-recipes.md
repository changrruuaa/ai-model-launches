# puppeteer-core 抓取 recipe(v2.0.0 主路径,xscan.mjs 工具级细则)

> 本文件是 SKILL.md Step 2/3/5 浏览器操作的工具级细则。执行器是 `scripts\xscan.mjs`
> (puppeteer-core 驱动真 Chrome,CDP 控制,**无需前台窗口、无需焦点、无逐次审批**)。
> 前身 cua-recipes.md 的通用经验已全部迁入本文;cua 专属内容(§0/§1/§4/§5)仅在
> browser_scheme=cua-driver 的 fallback 时参考 cua-recipes.md。

---

## 0. launch / connect 策略(xscan.mjs 内置,此处供诊断)

```
已有 CDP 端口(chrome_inspect.py exit 0)→ puppeteer.connect({browserURL: http://127.0.0.1:<port>})
否则 → puppeteer.launch({
  executablePath: <chrome.exe>,        # Step 0 探测的安装路径
  userDataDir: <shadow_profile>,       # Step 2 sync_cookies.py 建的 shadow profile(带 X cookie)
  headless: false,                     # 真 Chrome 有头——无头会被 X 反自动化 + 登录墙双杀
  defaultViewport: null,               # 跟随窗口实际尺寸
  args: ['--disable-backgrounding-occluded-windows',   # 被遮挡不停渲染(滚动加载依赖渲染)
         '--disable-renderer-backgrounding',           # 后台 tab 不降级
         '--window-size=1440,900', '--no-first-run', '--no-default-browser-check',
         '--disable-session-crashed-bubble']
})
```

- **窗口纪律**:shadow Chrome **无需在最上层、允许被遮挡**;唯一禁忌 = **最小化**(最小化 → 渲染节流 → IntersectionObserver 不触发 → 滚动不出新推文,exit 7)。启动后提示用户"可遮挡勿最小化"
- **Chrome ≥136 硬约束**:默认 user-data-dir 忽略 `--remote-debugging-port` → 一切 CDP 操作必须走 shadow profile(Step 2),**禁止直接 attach 日常 Chrome**
- shadow Chrome 由 xscan.mjs 拉起、用完保留(登录态在 profile 里,下次复用);用户可随时手关,下次自动重拉

## 1. Cookie 认证探查(Step 2,4 步验证)

1. `python "${HERMES_SKILL_DIR}\scripts\sync_cookies.py" --check` → 定位日常 profile(`%LOCALAPPDATA%\Google\Chrome\User Data`)、锁检测(Chrome 运行中 → Cookies DB 锁住)、shadow 存在性/新鲜度
2. `python "${HERMES_SKILL_DIR}\scripts\sync_cookies.py"` → 幂等复制 `Default\Network\Cookies` + `Local State` 到 shadow(两者必须同拷:cookie 走 app-bound encryption,密钥在 Local State,同机同用户由真 Chrome 自解密);Chrome 运行中 → 复用既有 shadow(exit 0 "reused",警示 cookie 时效)
3. `node "${HERMES_SKILL_DIR}\scripts\xscan.mjs" --mode login-check --profile <shadow>` → launch/connect + 导航
4. **登录态判定 = 只看跳转结果 URL**(与 v1.3.x 同规):`x.com/home` → 已登录;停在/弹回 `x.com`(登录墙)→ 未登录 → ①**先关闭 shadow Chrome 窗口**,再 `sync_cookies.py --force` 重拷重验一次(shadow 运行中会锁住 Cookies,exit 6)②仍失败 → 请用户在 shadow Chrome 窗口**手动登录 X 一次**(登录态持久在 shadow profile,此后不再需要;**不代登录**)

`sync_cookies.py` 退出码:0 ok/reused / 4 daily Chrome 锁住且无既有 shadow(关闭 daily Chrome 重试)/ 5 日常 profile 不存在 / 6 shadow Cookies 被**运行中的 shadow Chrome** 锁(非强制重拷可直接复用;`--force`/登录墙处置须先关 shadow 窗口)。`--force` 忽略 mtime 强制重拷。

## 2. 单账号时间线扫描(Step 3)

```
node "${HERMES_SKILL_DIR}\scripts\xscan.mjs" --mode timeline --handle <handle> \
  --out "<run_dir>\raw_<handle>.json" --since <YYYY-MM-DD> --max-rounds 4 [--profile <shadow>]
python "${HERMES_SKILL_DIR}\scripts\parse_account.py" --base-dir <base_dir> --run-id <run_id> <handle>
```

xscan.mjs 内部流程(诊断时参考):
1. `goto("https://x.com/<handle>")` —— **handle 无 @**(带 @ → `x.com/search?q=<handle>` 搜索 fallback;**禁用搜索框/搜索页定位账号**)。sleep 2-3s 渲染
2. **search fallback 判定**(@ 已在 xscan 入参剥离):结果 URL 是 `x.com/search?q=...` = X 拒绝解析该 handle。xscan 在搜索结果里找**精确同名 profile 链接**——有(瞬时竞态)→ re-navigate ≤2;无 → exit 8(handle 不可解析,检查 vendors 清单是否改名/typo,按 no-x-data 处理勿按导航超时重试)
3. 第 1 轮直读 DOM;第 R 轮(R=2..4)`scrollBy(0, 3000 + 随机 0-1000)` → sleep 1.5-2.5s(随机化,反自动化)→ 只提取新增 status_id
4. **终止**:本轮最老推文 `created_at < since`,或 R=4,或连续 3 轮零新增。**时间窗全覆盖是硬要求,宁可多滚不得提前收手**;窗内漏看 = 漏报
5. 落盘 `raw_<handle>.json`(UTF-8 无 BOM)——**schema 与 v1.3.x 完全一致**,parse_account.py 无感:
   ```json
   {"handle": "OpenAI", "company": "OpenAI", "rounds": 2,
    "tweets": [{"status_id": "1956...", "text": "...",
                "time_raw": "Wed Sep 03 10:12:33 +0000 2026",
                "engagement_raw": "81 replies, 328 reposts, 2448 likes, 215 bookmarks, 182331 views",
                "media": ["https://pbs.twimg.com/media/xxx.jpg"], "pinned": false}]}
   ```
   raw 落盘后 agent **不把推文正文读进上下文**(脚本落盘 + parse_account 一行 stdout 汇报,上下文保护)

**DOM 提取映射**(xscan.mjs 实现;snapshot 异常时人工诊断用):
| 字段 | 来源 |
|---|---|
| status_id | `article[data-testid=tweet]` 内 `a[href*="/status/"]` href 的纯数字段 |
| text | `[data-testid=tweetText]` innerText |
| time_raw | `time[datetime]`(ISO)转 X 标准串 `Wed Sep 03 10:12:33 +0000 2026` |
| engagement_raw | `[aria-label*="replies"]` 的 aria-label 原样存 |
| media | `img[src*="pbs.twimg.com/media"]` |
| pinned | article 内出现 "Pinned"/"置顶" 文案 |

**已知 trap(承自 v1.3.x,依然有效)**:
- 置顶带视频推文独占大量 viewport(X SPA 惰性加载)→ 不滚动永远看不到后续推文,xscan 已处理,勿手工"看起来到底了"就停
- 正文截断 → Step 3 详情页重抓(下节)
- 空 timeline ≠ 厂商没发布 → exit 4 → 标 no-x-data 记入报告
- `CDP DOM.getDocument timed out` → 重试 1 次 → 仍失败标 no-x-data,**不 web_search 补**

## 3. 详情页抓取(Step 3 候选深抓)

```
node "${HERMES_SKILL_DIR}\scripts\xscan.mjs" --mode detail --handle <handle> --status-id <id> \
  --out "<run_dir>\raw_detail_<id>.json" [--profile <shadow>]
```
`goto("https://x.com/<handle>/status/<id>")`(同样 handle 无 @)→ sleep 2-3s → 详情页不截断(解正文截断)→ 落盘 `{"status_id","text_full","media","external_links"}`。

## 4. xscan.mjs 退出码与处置

| 码 | 含义 | agent 处置 |
|---|---|---|
| 0 | ok | 继续 parse_account |
| 2 | 登录墙 | 走 Step 2 第 4 步(cookie 重拷→用户手动登录);同一账号标 no-x-data 前先试一次 |
| 3 | 导航超时 | 重试 1 次;再失败标 no-x-data |
| 4 | 空结果 | 标 no-x-data(空 timeline ≠ 没发布) |
| 5 | CDP 连接失败 | `sync_cookies.py --check` + chrome_inspect 诊断;重试 1 次 |
| 7 | 连续零新增疑后台节流 | 提示用户勿最小化 shadow 窗口后重试 1 次 |
| 8 | handle 不可解析(search fallback) | 检查 vendors 清单该 handle 是否改名/typo;标 no-x-data,**勿按导航超时重试** |

(cookie 失效无独立码:服务端会话过期一律表现为登录墙 exit 2。)

**通用纪律(承 v1.3.x)**:同一账号重试 ≤2 次(`--mark-failed <reason>` 入 run_report);**"cookie 彻底失效"= exit 2 在 `sync_cookies.py --force` 重拷 + 用户手动登录一次之后仍复现** → 整体中止;失败标 `empty / rate-limited / nav-timeout / session-expired / parse-failed / window-throttled / handle-unresolvable`。
