#!/usr/bin/env node
/**
 * xscan.mjs — v2.0.0 主路径抓取器:puppeteer-core 驱动真 Chrome(shadow profile),CDP 控制。
 *
 * 模式:
 *   --mode timeline --handle <H> --out <raw_H.json> --since <YYYY-MM-DD> [--max-rounds 4]
 *   --mode detail   --handle <H> --status-id <ID> --out <raw_detail_ID.json>
 *   --mode login-check [--screenshot <path.png>]
 *   --doctor                          9 级 fallback 链探测(SKILL.md Step 1)
 *
 * 通用: [--profile <shadow_dir>] [--chrome <path>] [--close] [--company <C>] [--timeout <ms>]
 *
 * 落盘 schema 与 v1.3.x raw_<handle>.json 严格一致(parse_account.py 无感)。
 * 退出码:0 ok / 2 登录墙(cookie 失效也表现为登录墙) / 3 导航超时 / 4 空结果(含限流页,no-x-data)
 * / 5 CDP 连接失败 / 7 疑后台节流 / 8 handle 不可解析(search fallback,标 no-x-data 勿重试)
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";

const EXIT = { OK: 0, LOGIN: 2, NAV: 3, EMPTY: 4, CDP: 5, THROTTLE: 7, HANDLE: 8 };

const args = parseArgs(process.argv.slice(2));
const log = (...a) => process.stderr.write(`[xscan] ${a.join(" ")}\n`);
const outLine = (obj) => process.stdout.write(`XSCAN>${JSON.stringify(obj)}\n`);

function parseArgs(argv) {
  const a = { maxRounds: 4, timeout: 45000, close: false };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    if (k === "--mode") a.mode = argv[++i];
    else if (k === "--handle") a.handle = argv[++i].replace(/^@/, "");
    else if (k === "--company") a.company = argv[++i];
    else if (k === "--out") a.out = argv[++i];
    else if (k === "--since") a.since = argv[++i];
    else if (k === "--status-id") a.statusId = argv[++i];
    else if (k === "--max-rounds") a.maxRounds = parseInt(argv[++i], 10);
    else if (k === "--profile") a.profile = argv[++i];
    else if (k === "--chrome") a.chrome = argv[++i];
    else if (k === "--timeout") a.timeout = parseInt(argv[++i], 10);
    else if (k === "--screenshot") a.screenshot = argv[++i];
    else if (k === "--close") a.close = true;
    else if (k === "--doctor") a.doctor = true;
  }
  return a;
}

function fail(code, reason, extra = {}) {
  outLine({ ok: false, exit: code, reason, ...extra });
  process.exit(code);
}

function findChrome() {
  const candidates = [
    args.chrome,
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    path.join(process.env.LOCALAPPDATA || "", "Google\\Chrome\\Application\\chrome.exe"),
  ].filter(Boolean);
  for (const c of candidates) if (fs.existsSync(c)) return c;
  return null;
}

function shadowDir() {
  return args.profile || path.join(process.env.LOCALAPPDATA || "", "xscan-shadow");
}

/** Connect to a live shadow Chrome via DevToolsActivePort, else launch a new one. */
async function getBrowser(puppeteer) {
  const profile = shadowDir();
  const datFile = path.join(profile, "DevToolsActivePort");
  if (fs.existsSync(datFile)) {
    try {
      const [port] = fs.readFileSync(datFile, "utf8").split(/\r?\n/);
      const browser = await puppeteer.connect({
        browserURL: `http://127.0.0.1:${port}`,
        defaultViewport: null,
        protocolTimeout: args.timeout,
      });
      log(`connected to live shadow Chrome on :${port}`);
      return { browser, reused: true };
    } catch (e) {
      log(`stale DevToolsActivePort (${e.message.split("\n")[0]}), launching fresh`);
    }
  }
  const chrome = findChrome();
  if (!chrome) fail(EXIT.CDP, "chrome.exe not found (set --chrome or install Google Chrome)");
  fs.mkdirSync(profile, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: chrome,
    userDataDir: profile,
    headless: false,
    defaultViewport: null,
    args: [
      "--disable-backgrounding-occluded-windows",
      "--disable-renderer-backgrounding",
      "--disable-background-timer-throttling",
      `--window-size=1440,900`,
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-session-crashed-bubble",
    ],
  });
  log(`launched shadow Chrome pid=${browser.process()?.pid ?? "?"} profile=${profile}`);
  return { browser, reused: false };
}

/** Reuse an existing x.com tab or open a new page. */
async function getPage(browser) {
  const pages = await browser.pages();
  const existing = pages.find((p) => p.url().startsWith("https://x.com"));
  return existing || (await browser.newPage());
}

async function goto(page, url) {
  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: args.timeout });
  } catch (e) {
    return `goto-failed: ${e.message.split("\n")[0]}`;
  }
  await sleep(2000 + Math.random() * 1000); // X SPA 渲染窗口(承 v1.3.x 实测 2-3s)
  return null;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 登录态判定 = 只看跳转结果 URL(承 v1.3.x)。返回 null=已登录, 'login-wall'=未登录 */
function loginWallOf(url) {
  const u = new URL(url);
  if (u.pathname === "/" || u.pathname.startsWith("/login") || u.pathname === "/i/flow/login") {
    return "login-wall";
  }
  return null;
}

/** ISO datetime -> X created_at 标准串 "Wed Sep 03 10:12:33 +0000 2026" */
function toXTime(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return null;
  const D = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const M = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const p = (n) => String(n).padStart(2, "0");
  return `${D[d.getUTCDay()]} ${M[d.getUTCMonth()]} ${p(d.getUTCDate())} ` +
         `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())} +0000 ${d.getUTCFullYear()}`;
}

/** DOM -> raw tweets(在页面上下文执行)。与 cua snapshot 提取规则逐字段对齐。 */
async function extractTweets(page) {
  return page.$$eval('article[data-testid="tweet"]', (arts) => {
    return arts.map((a) => {
      const timeEl = a.querySelector("time");
      const iso = timeEl ? timeEl.getAttribute("datetime") : null;
      const link = timeEl && timeEl.closest("a") ? timeEl.closest("a").getAttribute("href") : null;
      let statusId = null;
      if (link) {
        const m = link.match(/\/status\/(\d+)/);
        if (m) statusId = m[1];
      }
      if (!statusId) {
        for (const x of a.querySelectorAll('a[href*="/status/"]')) {
          const m = (x.getAttribute("href") || "").match(/\/status\/(\d+)/);
          if (m) { statusId = m[1]; break; }
        }
      }
      const textEl = a.querySelector('[data-testid="tweetText"]');
      const engEl = a.querySelector('[role="group"][aria-label], [aria-label*="replies" i]');
      const media = Array.from(a.querySelectorAll(
        'img[src*="pbs.twimg.com/media"], img[src*="pbs.twimg.com/ext_tw_video_thumb"], img[src*="pbs.twimg.com/amplify_video_thumb"]'))
        .map((i) => i.src);
      const txt = a.textContent || "";
      return {
        status_id: statusId,
        iso,
        text: textEl ? textEl.innerText : "",
        engagement_raw: engEl ? engEl.getAttribute("aria-label") : null,
        media,
        pinned: /(^|\s)(Pinned|置顶)(\s|·|$)/.test(txt.slice(0, 200)),
      };
    }).filter((t) => t.status_id);
  });
}

/* ---------------- mode: timeline ---------------- */
async function modeTimeline(puppeteer) {
  if (!args.handle || !args.out || !args.since) fail(EXIT.NAV, "timeline 需要 --handle/--out/--since");
  const since = new Date(`${args.since}T00:00:00Z`);
  if (isNaN(since)) fail(EXIT.NAV, `--since 无法解析: ${args.since}`);

  const { browser } = await getBrowser(puppeteer);
  const page = await getPage(browser);
  try {
    // search fallback 自愈(@ 已在 parseArgs 剥离,落到 search 只会是 X 拒绝解析或瞬时竞态):
    // 搜索结果含精确同名 profile → 竞态,重试;否则 handle 不可解析,立即失败勿重试
    let urlOk = false;
    for (let attempt = 0; attempt <= 2 && !urlOk; attempt++) {
      const err = await goto(page, `https://x.com/${args.handle}`);
      if (err) fail(EXIT.NAV, err, { handle: args.handle });
      const url = page.url();
      const wall = loginWallOf(url);
      if (wall) {
        if (args.screenshot) await page.screenshot({ path: args.screenshot }).catch(() => {});
        fail(EXIT.LOGIN, `登录墙(结果 URL ${url})——Step 2 第 4 步:cookie 重拷或用户在 shadow 窗口手动登录`, { handle: args.handle });
      }
      if (url.includes("/search?q=")) {
        const exact = await page.$$eval('a[href^="/"]', (as, h) =>
          as.some((a) => (a.getAttribute("href") || "").toLowerCase() === `/${h.toLowerCase()}`), args.handle);
        if (!exact) {
          fail(EXIT.HANDLE,
            `handle 未被 X 解析(落到 search fallback,非导航超时):检查 vendors 清单该 handle 是否改名/typo;按 no-x-data 处理勿重试`,
            { handle: args.handle });
        }
        log(`search fallback with exact profile link (${url}), re-navigate #${attempt + 1}`);
        continue;
      }
      if (!url.toLowerCase().includes(`/${args.handle.toLowerCase()}`)) {
        log(`unexpected URL ${url}, re-navigate #${attempt + 1}`);
        continue;
      }
      urlOk = true;
    }
    if (!urlOk) fail(EXIT.NAV, "3 次 re-navigate 后仍未落到目标 profile 页", { handle: args.handle });

    let rounds = 0;
    const seen = new Map(); // status_id -> tweet
    let staleRounds = 0; // 连续零新增轮数

    for (let r = 1; r <= args.maxRounds; r++) {
      rounds = r;
      const fresh = await extractTweets(page);
      let added = 0;
      let oldestIso = null;
      for (const t of fresh) {
        if (!seen.has(t.status_id)) {
          seen.set(t.status_id, t);
          added++;
        }
        if (!oldestIso || t.iso < oldestIso) oldestIso = t.iso;
      }
      const covered = oldestIso ? new Date(oldestIso) < since : false;
      log(`round ${r}: dom=${fresh.length} added=${added} total=${seen.size} oldest=${oldestIso} covered=${covered}`);
      if (covered) break;
      if (added === 0) {
        staleRounds++;
        if (staleRounds >= 3) {
          // 全程零提取(0 article)→ 落到 EMPTY 分支区分限流页/真空 timeline(no-x-data);
          // 有 DOM 但零新增 = 最小化节流;零 DOM 但已有存量 = 时间窗未覆盖,均按 THROTTLE 失败
          if (fresh.length === 0 && seen.size === 0) break;
          fail(EXIT.THROTTLE,
            "连续 3 轮零新增且时间窗未覆盖——shadow 窗口可能被最小化(渲染节流),请保持窗口开启(可遮挡勿最小化)后重试",
            { handle: args.handle, rounds, fetched: seen.size });
        }
      } else {
        staleRounds = 0;
      }
      if (r === args.maxRounds) break;
      await page.evaluate(() => window.scrollBy({ top: 3000 + Math.random() * 1000, behavior: "instant" }));
      await sleep(1500 + Math.random() * 1000); // 随机化,反自动化
    }

    const all = [...seen.values()].filter((t) => t.iso && !isNaN(new Date(t.iso)));
    const inWindow = all.filter((t) => new Date(t.iso) >= since).length;
    const tweets = all.map((t) => ({
      status_id: t.status_id,
      text: t.text,
      time_raw: toXTime(t.iso),
      engagement_raw: t.engagement_raw || undefined,
      media: t.media,
      pinned: t.pinned,
    }));
    if (!tweets.length) {
      // 区分限流页与真空 timeline
      const bodyText = (await page.evaluate(() => document.body?.innerText || "")).slice(0, 2000);
      const rateLimited = /rate limit|瓶颈|try again|something went wrong/i.test(bodyText);
      fail(EXIT.EMPTY, rateLimited ? "页面为限流/错误页(按 no-x-data 处理,不 web_search 补)" : "空 timeline(按 no-x-data 处理)", { handle: args.handle });
    }

    const payload = {
      handle: args.handle,
      company: args.company || args.handle,
      rounds,
      tweets,
    };
    fs.mkdirSync(path.dirname(path.resolve(args.out)), { recursive: true });
    fs.writeFileSync(path.resolve(args.out), JSON.stringify(payload, null, 2), "utf8");
    outLine({ ok: true, handle: args.handle, rounds, fetched: tweets.length, in_window: inWindow, out: path.resolve(args.out) });
    return EXIT.OK;
  } finally {
    if (args.close) await browser.close().catch(() => {});
  }
}

/* ---------------- mode: detail ---------------- */
async function modeDetail(puppeteer) {
  if (!args.handle || !args.statusId || !args.out) fail(EXIT.NAV, "detail 需要 --handle/--status-id/--out");
  const { browser } = await getBrowser(puppeteer);
  const page = await getPage(browser);
  try {
    const err = await goto(page, `https://x.com/${args.handle}/status/${args.statusId}`);
    if (err) fail(EXIT.NAV, err, { status_id: args.statusId });
    const wall = loginWallOf(page.url());
    if (wall) fail(EXIT.LOGIN, `登录墙(${page.url()})`, { status_id: args.statusId });
    const data = await page.evaluate(() => {
      const art = document.querySelector('article[data-testid="tweet"]');
      if (!art) return null;
      const text = art.querySelector('[data-testid="tweetText"]');
      const media = Array.from(art.querySelectorAll(
        'img[src*="pbs.twimg.com/media"], img[src*="pbs.twimg.com/ext_tw_video_thumb"], img[src*="pbs.twimg.com/amplify_video_thumb"]')).map((i) => i.src);
      const links = Array.from(art.querySelectorAll('a[href^="http"]'))
        .map((a) => a.href)
        .filter((h) => !h.includes("x.com") && !h.includes("twitter.com") && !h.includes("help.twitter"));
      return { text_full: text ? text.innerText : "", media, external_links: [...new Set(links)] };
    });
    if (!data) fail(EXIT.EMPTY, "详情页未找到推文 article", { status_id: args.statusId });
    const payload = { status_id: args.statusId, ...data };
    fs.mkdirSync(path.dirname(path.resolve(args.out)), { recursive: true });
    fs.writeFileSync(path.resolve(args.out), JSON.stringify(payload, null, 2), "utf8");
    outLine({ ok: true, status_id: args.statusId, text_chars: data.text_full.length, media: data.media.length, out: path.resolve(args.out) });
    return EXIT.OK;
  } finally {
    if (args.close) await browser.close().catch(() => {});
  }
}

/* ---------------- mode: login-check ---------------- */
async function modeLoginCheck(puppeteer) {
  const { browser } = await getBrowser(puppeteer);
  const page = await getPage(browser);
  try {
    const err = await goto(page, "https://x.com/home");
    if (err) fail(EXIT.NAV, err);
    const url = page.url();
    const wall = loginWallOf(url);
    if (args.screenshot) await page.screenshot({ path: args.screenshot }).catch(() => {});
    outLine({ ok: !wall, logged_in: !wall, url, screenshot: args.screenshot || null });
    return wall ? EXIT.LOGIN : EXIT.OK;
  } finally {
    if (args.close) await browser.close().catch(() => {});
  }
}

/* ---------------- mode: doctor(9 级 fallback 链) ---------------- */
function probePs(command) {
  try {
    const out = execFileSync("powershell.exe", ["-NoProfile", "-Command", command],
      { timeout: 15000, encoding: "utf8", windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"] });
    return { ok: true, detail: out.trim().split("\n")[0].slice(0, 120) };
  } catch (e) {
    return { ok: false, detail: (e.message || "").split("\n")[0].slice(0, 120) };
  }
}

async function modeDoctor() {
  const ranks = [];
  // rank 0: puppeteer-core + Chrome CDP(主路径,完整实现)
  let puppeteer = null;
  try {
    puppeteer = (await import("puppeteer-core")).default;
    ranks.push({ rank: 0, scheme: "puppeteer-core+CDP", available: true, detail: "puppeteer-core importable" });
  } catch {
    ranks.push({ rank: 0, scheme: "puppeteer-core+CDP", available: false, detail: "puppeteer-core 未安装: cd scripts && npm install" });
  }
  const chrome = findChrome();
  ranks.push({ rank: -1, scheme: "chrome-binary", available: !!chrome, detail: chrome || "chrome.exe 未找到" });
  const profile = shadowDir();
  const cookie = path.join(profile, "Default", "Network", "Cookies");
  ranks.push({ rank: -1, scheme: "shadow-cookies", available: fs.existsSync(cookie), detail: cookie });

  // rank 1: cua-driver(hermes MCP——Node 侧只能探部署痕迹,可用性最终由 agent 会话判断)
  const hermesCfg = path.join(os.homedir(), ".hermes", "config.yaml");
  ranks.push({ rank: 1, scheme: "cua-driver", available: fs.existsSync(hermesCfg), detail: `hermes config ${fs.existsSync(hermesCfg) ? "存在" : "不存在"};MCP 可用性以 agent 会话为准` });

  // rank 2: playwright
  ranks.push({ rank: 2, scheme: "playwright", ...probePs("python -m pip show playwright") });
  // rank 3: chrome-devtools-mcp
  ranks.push({ rank: 3, scheme: "chrome-devtools-mcp", ...probePs("npx --no-install chrome-devtools-mcp --version") });
  // rank 4: chrome --headless(警示:登录墙/反自动化,末选)
  ranks.push({ rank: 4, scheme: "chrome-headless", available: !!chrome, detail: chrome ? "可行但登录墙风险高,仅降级用" : "无 chrome.exe" });
  // rank 5: nitter 镜像(历史全挂,快速探活)
  const nitter = probePs("(Invoke-WebRequest -Uri 'https://nitter.net' -TimeoutSec 5 -UseBasicParsing).StatusCode -eq 200");
  ranks.push({ rank: 5, scheme: "nitter-mirror", ...nitter, detail: nitter.detail + " | 历史记录:TLS/CF 全挂,勿抱期望" });
  // rank 6: apify(需 key)
  ranks.push({ rank: 6, scheme: "apify", available: !!process.env.APIFY_TOKEN, detail: process.env.APIFY_TOKEN ? "APIFY_TOKEN 已设" : "无 APIFY_TOKEN" });
  // rank 7: openai operator(地区限定)
  ranks.push({ rank: 7, scheme: "openai-operator", available: false, detail: "地区限定,默认不可用" });
  // rank 8: X API v2 官方(需付费)
  ranks.push({ rank: 8, scheme: "x-api-v2", available: !!(process.env.X_BEARER_TOKEN || process.env.TWITTER_BEARER_TOKEN), detail: "需 bearer token(付费)" });

  const available = ranks.filter((r) => r.rank >= 0 && r.available).sort((a, b) => a.rank - b.rank);
  outLine({ ok: available.length > 0, selected: available[0]?.scheme ?? null, available_ranks: available.map((r) => r.rank), ranks });
  return available.length > 0 ? EXIT.OK : EXIT.CDP;
}

/* ---------------- main ---------------- */
async function main() {
  if (args.doctor) return modeDoctor();
  let puppeteer;
  try {
    puppeteer = (await import("puppeteer-core")).default;
  } catch {
    process.stderr.write("puppeteer-core 未安装。先执行: cd scripts && npm install\n");
    return EXIT.CDP;
  }
  try {
    if (args.mode === "timeline") return await modeTimeline(puppeteer);
    if (args.mode === "detail") return await modeDetail(puppeteer);
    if (args.mode === "login-check") return await modeLoginCheck(puppeteer);
    process.stderr.write("未知模式。用法见文件头注释。\n");
    return EXIT.NAV;
  } catch (e) {
    const msg = (e.message || String(e)).split("\n")[0];
    if (/Target closed|Browser closed|Session closed|Disconnected/i.test(msg)) fail(EXIT.CDP, `CDP 连接断开: ${msg}`);
    if (/ENOTFOUND|ECONNREFUSED|timeout.*Navigation/i.test(msg)) fail(EXIT.NAV, `导航/网络失败: ${msg}`);
    fail(EXIT.CDP, `未分类错误: ${msg}`);
  }
}

process.exit(await main());
