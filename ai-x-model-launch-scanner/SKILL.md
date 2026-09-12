---
name: ai-x-model-launch-scanner
description: >-
  puppeteer-core 驱动 shadow Chrome 扫描 16 个 AI 厂商 X 账号在时间窗口内的推文,关键词预筛 +
  LLM 分类识别模型发布,web_search 交叉验证后生成中文文稿与速报视频(卡片/配音/字幕),落本地
  Markdown/JSON 与 Notion。触发词:扫描 AI 模型发布 / 抓取 AI 公司推文 / 按厂家清单扫一遍 /
  跑模型扫描 / "scan AI model launches" / 近 N 天有什么新模型 / 做本期 AI 发布视频 / 出速报视频。
version: 2.0.0
author: chang
license: MIT
platforms: [windows]
# 🚨 不要在 frontmatter 声明 required_environment_variables(hermes 对缺失变量强制提示且无法跳过,
#    卡死 skill 加载)。Notion token 运行时探测(--check-auth,无 token 静默降级为仅本地)。
metadata:
  hermes:
    tags: [ai, research, twitter, monitoring, video]
    requires_tools: []   # computer_use 仅在 browser_scheme=cua-driver fallback 时使用
    fallback_for_tools: []
    config:              # hermes 原生注入通道(仅首跑引导);真源 = skill 目录 config.user.yaml
      - key: base_dir
        description: 扫描数据与报告落地根目录(Windows 路径)
        default: ""
        prompt: 请输入扫描结果保存目录(如 D:\obs-mind\work\active\AI扫描)
      - key: notion_parent_page_id
        description: Notion 父页面 ID(32 位 hex;页面需 Share 给 integration)
        default: ""
        prompt: 请提供 Notion 父页面 URL 或 32 位 page id(用于自动建库)
---

# AI X Model Launch Scanner(数字员工 · X 模型发布扫描 → 文稿 → 速报视频)

## When to Use

用户要求"扫描 AI 模型发布 / 抓取 AI 公司推文 / 跑模型扫描 / 近 N 天有什么新模型 / 做本期 AI 发布视频"时加载本 skill。定时任务触发时同样适用(`run.unattended=true`)。

**约束声明**(首次对话告知用户):
- v2 起浏览器层用 **puppeteer-core 驱动独立 shadow Chrome**(复用日常 Chrome 的 X 登录 cookie),**不碰用户日常 Chrome 窗口**;shadow 窗口可被遮挡、**勿最小化**(最小化会渲染节流导致扫不到)
- 全程约 15-40 分钟;Step 6/8 各有 **5 分钟倒计时**供用户查看/修改,Step 10 需用户回复"**继续**"才合成视频
- 建议用户日常 Chrome 保持已登录 X(本 skill 不导 cookie 内容、不代登录)
- 上下文保护:xscan 落盘不进上下文,分类不混扫描会话,>120 条强制 --api

**🚨 三禁硬规则(违反 = 本 run 无效)**:
- 扫描被任何原因阻断(登录墙 / 超时 / cookie 失效)→ 该账号标 `no-x-data` 即 STOP
- **任何 web/搜索来源的内容禁止写入 `data/raw/`**(raw 只含 X timeline 直读数据)
- web_search 仅允许出现在 Step 4,且只针对 `is_launch=true` 条目;不替代扫描、不发现新推文、不补"扫不到"的账号

**长期约束文件(单一真源)**:skill 同目录 `config.user.yaml`(首跑从 `config.user.example.yaml` 生成)。Step 0 只对文件中缺失的键追问,答案与探查结论**立即写回**;用户改偏好 = 直接编辑该文件,删键 = 恢复追问。frontmatter config 仅作 hermes 首跑引导,冲突以文件为准。

**默认环境全空原则**:任何依赖缺失不猜测、不假设已装——处置一律查 `references\environment-setup.md`(独立从零部署文件,每项含探测+安装命令)。

## Quick Reference

| Step | 内容 | 执行者与产物 |
|---|---|---|
| 0 | 环境确认(7 问 + 12 项检查 + 探查存档) | agent + check_env.py + config.user.yaml |
| 1 | 浏览器方案验证(9 级 fallback 链) | xscan.mjs --doctor → browser_scheme |
| 2 | Cookie 认证探查(4 步) | sync_cookies.py + xscan login-check |
| 3 | 14 大厂账号扫描 | plan_scan.py + xscan.mjs + parse_account.py |
| 4 | 分类 + 验证 + 返回信息(不暂停) | classify.py + web_search → 汇总表 |
| 5 | 交叉验证 + 小模型探查(仅 @arena/@ArtificialAnlys) | plan_scan thirdparty + cross_check.py |
| 6 | 5 分钟用户查看 + 倒计时 | agent(sleep 60×5) |
| 7 | 文稿撰写(SEG 分段) | manuscript.md(manuscript-format.md) |
| 8 | 输出文稿 + 5 分钟倒计时 | agent(sleep 60×5)→ 定稿 |
| 9 | 视频物料(5 子步:ppt-master 三级链/Grasai 生图/配音) | make_cards.py 等 → materials\ |
| 10 | 视频合成(需用户"继续") | compose_video.py → .mp4 |
| 11 | 物料归档 + 输出成品 + 结束 | 汇报模板 + Verification |

**命令约定**:`${HERMES_SKILL_DIR}` 由 hermes 替换。工具细则:`references\puppeteer-recipes.md`;失败诊断:`references\scan-failure-modes.md`;文稿/视频契约:`references\manuscript-format.md`、`references\video-spec.md`。

**厂商清单**:以 `assets\vendors.main.json`(14 大厂)+ `assets\vendors.thirdparty.json`(@arena、@ArtificialAnlys)为唯一依据,见 `references\vendors.md`。

## Procedure

### Step 0 — 环境确认(≤ 2 min)

1. 读 `config.user.yaml`(不存在 → 从模板复制生成,继续读)。**7 问**(仅对缺失键,答案写回文件):①`scan.base_dir`(Windows 路径,落临时目录会丢产物)②`scan.default_days` ③`scan.classify_mode` ④Notion(`notion.enabled`+`parent_page_id` 合一问)⑤视频/结构/生图:`video.enabled`+`aspect`+`manuscript.target_minutes`+`card_style`(未指定 → 默认 `ppt-reference`,基准 `assets\style-reference.png`);**文章结构限制(先于生图)**:问用户有无文稿结构硬约束 → 有则原文写 `manuscript.structure_rules`,无写 `false`,**默认留空=必问**;**生图探查**(video.enabled=true 时):问是否已有提示词优化 skill 及名称 → 探测存在性;没有 → `grsai skill download`(**只下 skill 本体,不下参考画廊**);读 `~/.grsai/config.json` imageModel 判定国内模型(豆包/seedream/kling/qwen 系)→ 国内则记 `imagegen.no_negative_prompts: true`(**提示词禁止负面提示词写法**)⑥音频:`audio.voice`(edge-tts 音色/无旁白)+`bgm_path` ⑦`run.unattended`
2. `python "${HERMES_SKILL_DIR}\scripts\check_env.py"` → exit 12 → 按 JSON `fatal_missing` 对照 environment-setup.md 逐项安装后重试
3. **附带 skill 联动适配**(凡本步下载/安装了 GPT-Image2-Skill 等):读其 SKILL.md 与依赖清单 → 装缺失依赖 → 最小冒烟(`grsai skill show`)→ 结果写 `probes:` 段(带日期);失败记降级不阻塞
4. `python "${HERMES_SKILL_DIR}\scripts\notion_sync.py" --check-auth` → exit 3 = 无 token → **静默降级仅本地**(全程跳过 notion,不提示不阻塞)。配置:`setx NOTION_TOKEN "ntn_..."` 后重启 Hermes desktop
5. `python "%USERPROFILE%\.hermes\tools\chrome_inspect.py"`(未部署跳过)→ exit 0 记 `cdp_ready` 佐证;exit 1/2 → 🛑 STOP 按 `summary.action_hint` 报告(**禁自行拉起浏览器、禁无头 Chrome**);exit 3 → 报 stderr 跳过巡检
6. 音频/生图探查结果写 `probes:` 段,Step 9/10 直接复用不再探

### Step 1 — 浏览器自动化方案验证(≤ 3 min)

`node "${HERMES_SKILL_DIR}\scripts\xscan.mjs" --doctor` → 按以下 9 级链输出 `available_ranks[]`:

```
0 puppeteer-core+Chrome CDP(主路径,完整实现)  1 cua-driver(复用 v1.3.2 cua-recipes.md)
2 Playwright   3 Chrome DevTools MCP   4 Chrome --headless(登录墙高风险,末选)
5 Nitter 镜像(历史全挂)   6 Apify/Bright Data(需 key)   7 OpenAI Operator(地区限定)   8 X API v2(付费)
```

- 选**首个可用级**写 run_report `browser_scheme`;**只有 rank 0/1 有可执行路径**:rank 0 走本 skill 全流程,rank 1 回退 cua-recipes.md(cua 专属:窗口须最上层/焦点归还/流程 W 在该文档)
- rank 2-8 = 探测+文档化路径(可用性如实写报告,执行按需人工);全不可用 → 🛑 STOP 报告
- doctor 同时报告 `chrome-binary`/`shadow-cookies` 基础项(rank -1,不参与选级)

### Step 2 — Cookie 认证探查(4 步验证,≤ 2 min;细则 puppeteer-recipes.md §1)

1. `python "${HERMES_SKILL_DIR}\scripts\sync_cookies.py" --check` → 定位日常 profile + Chrome 运行锁检测
2. `python "${HERMES_SKILL_DIR}\scripts\sync_cookies.py"` → 复制 `Cookies`+`Local State` 到 shadow(必须同拷,app-bound 同机自解密);Chrome 运行中 → 复用既有 shadow(exit 0 "reused",警示时效);exit 4 → 提示关 daily Chrome 重试;exit 6 → shadow 锁(复用或关 shadow 窗口后重拷)
3. `node "${HERMES_SKILL_DIR}\scripts\xscan.mjs" --mode login-check --screenshot "<run_dir>\login_check.png"` → launch/connect + 导航
4. **登录态 = 只看跳转结果 URL**:`x.com/home` → 已登录;登录墙 → 先**关闭 shadow Chrome 窗口**再 `sync_cookies.py --force` 重验一次(不关会 exit 6 shadow 锁)→ 仍失败请用户在 shadow 窗口**手动登录 X 一次**(持久,此后免维护;**不代登录**)→ 重跑本步

### Step 3 — 14 大厂账号扫描

1. `python "${HERMES_SKILL_DIR}\scripts\plan_scan.py" --stage main --days <N> --base-dir <base_dir> [--run-id <id>] [--resume]` → `RUN>{...}`(run_id/批次/companies)。新 run 创建 `<base_dir>\data\raw\<run_id>\`
2. 逐账号(batch ≤ `session_batch_size`):
   ```
   node "${HERMES_SKILL_DIR}\scripts\xscan.mjs" --mode timeline --handle <handle> \
     --out "<run_dir>\raw_<handle>.json" --since <since> --max-rounds 4 --screenshot "<run_dir>\err_<handle>.png"
   python "${HERMES_SKILL_DIR}\scripts\parse_account.py" --base-dir <base_dir> --run-id <run_id> <handle>
   ```
   - 内部已处理:handle **无 @**、search fallback 判定(精确同名 profile 才重试,否则 exit 8 no-x-data)、随机滚动间隔、时间窗全覆盖(最老推文 < since 或 4 轮)、增量去重;细则与 trap 见 `references\puppeteer-recipes.md` §2
   - 退出码处置见 puppeteer-recipes.md §4:重试 ≤2 次/账号,超限 `--mark-failed <reason>`(exit 8 勿重试);**cookie 彻底失效 = exit 2 在 --force 重拷+手动登录后仍复现 → 整体中止**
   - **raw 落盘即弃**:不把推文正文读进上下文,只看 xscan/parse_account 的 stdout 汇总行
3. 高价值候选详情页:prefilter.py → `xscan --mode detail`(URL `x.com/<handle>/status/<id>`,不截断)→ merge_detail.py(沿用 v1.3.x 流程,预算 ≤5 min / 15 候选,超预算跳过不阻塞)

### Step 4 — 分类 + 验证 + 返回信息(**不暂停**)

1. `python "${HERMES_SKILL_DIR}\scripts\classify.py" --base-dir <base_dir> --run-id <run_id>` → `to_classify.json`;**本会话不读** candidates/raw 大文件,只读 to_classify.json → 按 `templates\classify_prompt.txt` 逐条判 → 写 `classified.json` → `--validate` 校验;**>120 条强制 --api**(需 ANTHROPIC_API_KEY,调 claude-haiku-4-5)
2. `verify_web_search=true` 且交互模式:对 `is_launch=true` 条目 `web_search("<model> <company> release date")`,每条 ≤2 次,结果落 `verified.json`;三禁不变
3. 向用户贴汇总表(账号健康度 + launch 清单概览),**不等待**直接进 Step 5

### Step 5 — 交叉验证 + 小模型探查(≤ 4 min)

1. `python "${HERMES_SKILL_DIR}\scripts\plan_scan.py" --stage thirdparty --base-dir <base_dir> --run-id <run_id>` → xscan 扫 **@arena、@ArtificialAnlys(仅此 2 账号,不 web_search 扩展,不浪费时间)** → parse_account
2. **浏览器阶段到此结束** → 提示用户可关闭 shadow Chrome(不强制)
3. `python "${HERMES_SKILL_DIR}\scripts\cross_check.py" --base-dir <base_dir> --run-id <run_id>` → launch × 第三方模型名匹配 → `cross_checked.json`(cross_verified / 第三方信号)

### Step 6 — 5 分钟用户查看 + 倒计时(完整规则)

- 展示编号清单:`# | 公司 | 模型 | 一句话 | 置信度 | 验证/第三方状态`
- 倒计时:terminal `sleep 60` 连续 5 次,每次播报"剩 N 分钟";**用户任何消息即中断**:`跳过`/`继续`→立即推进;`修改:…`→按指令调整清单后推进;其余视为反馈,复述待确认点
- `run.unattended=true` → 整体跳过本步
- 调整只作用于后续文稿,不回改 raw/cross_checked(审计链不变)

### Step 7 — 文稿撰写

产物 `<run_dir>\manuscript.md`,机读分段 `## SEG-NN | type | 标题`,**结构/语法/硬约束全部按 `references\manuscript-format.md`**。要点:
- 先读 `config.user.yaml` `manuscript.structure_rules`:`false`/空 = 默认结构;有值 = 用户结构规范**优先**
- 只依据 cross_checked.json;数字必须带 `<!-- refs: -->`;单段 ≤120 字(4 字/秒);总长 ≈ `manuscript.target_minutes`;confidence<0.8 标"据报道";coming soon 不入稿;不编造

### Step 8 — 输出文稿 + 5 分钟倒计时

贴出全文 → 同 Step 6 倒计时规则(修改 → 改稿 → 重新贴;超时 → 定稿);定稿另存 `manuscript_final.md`;`unattended` 跳过直接定稿。

### Step 9 — 视频物料准备(5 子步;细则 `references\video-spec.md`)

1. **分段解析 + 物料清单**:manuscript_final.md → SEG 映射为卡片清单(cover/item/chart/ending),风格 = Step 0 选定(默认 ppt-reference)
2. **插画与封面 = grsai CLI**:提示词技巧按 Step 0 探查结果(用户 skill 或 GPT-Image2-Skill);**国内模型时强制禁负面提示词**;中文提示词,风格向 `assets\style-reference.png` 大地色暖调对齐;存 `<run_dir>\materials\art\`
3. **文字卡片(ppt-master 三级链)**:(a)探测 `%USERPROFILE%\.hermes\skills\ppt-master\SKILL.md` + 依赖可用 → 按 ppt-reference 风格产 PPTX → 导 PNG;(b)缺失 → **自动安装**:`git clone --depth 1 https://github.com/hugohe3/ppt-master` → 拷 `skills\ppt-master\` 到 `%USERPROFILE%\.hermes\skills\ppt-master\` → `pip install -r requirements.txt` → 复探测,本轮直接按其 SKILL.md 调用;(c)失败/PNG 3 次无产物 → **Pillow fallback** `make_cards.py`;记 `cards_engine: ppt|pillow`
4. **配音 + 时长对齐**:`audio.voice` 非空 → 逐段 `edge-tts --voice <voice> --write-media seg_NN.mp3` → ffprobe 时长 → 卡片时长 = max(音频+0.8s, 3s);失败降级静音+固定时长(记 `narration: silent-fallback`)
5. **汇总** `video_manifest.json`(`[{card, seg, text, audio, duration}]`)+ `make_srt.py` 出字幕 + 规格校验(尺寸/边距/字体)

### Step 10 — 视频编辑合成(需"继续"触发)

- 输出物料清单(卡片 N 张/配音 M 段/总时长)后**本轮结束**,等用户回复"**继续**";**无超时**;`unattended` 同样不自动合成(结尾提示"回复'继续'即可合成")
- 收到"继续" → `python "${HERMES_SKILL_DIR}\scripts\compose_video.py" --manifest "<run_dir>\video\video_manifest.json" --out "<run_dir>\video\<date>-ai-launches.mp4" [--bgm ...] [--srt subs.srt]`
- `video_check.json` `ok=true` 才算成功;失败按 stderr 修一次重试,再失败如实报告

### Step 11 — 物料存放 + 输出成品 + 结束

- 归档:`<base_dir>\runs\<run_id>\` 实际即 `<base_dir>\data\raw\<run_id>\` + `reports\`;成品 = 报告 md(`write_local.py` 已产)+ `manuscript_final.md` + `video\*.mp4`
- Notion(启用且 token 有效):`write_local.py` **必须先于** `notion_sync.py`;细则 `references\notion-schema.md`
- 最终汇报模板:
```
✅ 本期完成 · <窗口>(近 N 天)
   16 账号 · 抓取 X 条 · launch Y 条 · 第三方信号 Z 条 · browser_scheme=<...> · cards_engine=<...>
   1. ...(公司)— 一句话 [95%] ✓验证 ✓第三方
   ⚠️ @deepseek_ai no-x-data —— 不代表该厂商没发布
   📄 报告:<...md>  📝 文稿:<...md>  🎬 视频:<...mp4>(N 分 M 秒)  🗃️ Notion:新增 a 更新 b
```

### 浏览器错误分支(Step 2/3/5 通用)

- 通用规则:任何 🛑 STOP / 中止前,如实说明 shadow Chrome 状态(保留或关闭由用户定);v1.3.x 的流程 W/焦点归还**仅 browser_scheme=cua-driver 时适用**(cua-recipes.md §4/§5)
- 登录墙(exit 2,cookie 失效同表现)→ Step 2 第 4 步;CDP 断连(exit 5)→ `sync_cookies.py --check` + chrome_inspect 诊断 → 重试 1 次;节流(exit 7)→ 提示勿最小化 → 重试 1 次;handle 不可解析(exit 8)→ 标 no-x-data 勿重试
- 同一账号重试 ≤2;会话内 ≥2 账号 fatal → run 中止,报错指引 `--resume`
- cua fallback 时:browser_requires_setup/grant/焦点归还等按 cua-recipes.md 与 scan-failure-modes.md G8

## Pitfalls

1. **Chrome ≥136 默认 profile 忽略调试端口** → 一切 CDP 走 shadow profile;禁直接 attach 日常 Chrome
2. **shadow 窗口勿最小化**(可遮挡)→ 最小化渲染节流,IntersectionObserver 不触发(exit 7)
3. **profile URL 无 @**(@ 已在 xscan 入参剥离):落到 `x.com/search?q=` = X 拒绝解析 handle;xscan 找精确同名 profile 才重试,否则 exit 8(no-x-data,查 vendors 清单是否改名/typo)
4. **cookie 资产必须 Cookies + Local State 同拷**(app-bound 加密);跨机复制无效(解密绑机器+用户)
5. **raw 三禁不变**:web 来源字段 parse_account 拒收(exit 2);web_search 仅 Step 4
6. **时间窗全覆盖是硬要求**:终止 = 最老推文 < since 或 4 轮;宁可多滚
7. 空 timeline ≠ 没发布 → no-x-data 入报告;正文截断 → 详情页重抓
8. **Windows 编码**:JSON UTF-8 无 BOM;终端中文先 `PYTHONIOENCODING=utf-8`
9. **上下文保护**:xscan 落盘即弃、分类只读 to_classify.json、>120 条切 --api、每条验证 ≤2 搜索;中断后 `plan_scan.py --status --resume` 重新定位
10. 同一账号重试 ≤2(exit 8 除外,勿重试);cookie 彻底失效(exit 2 在 --force 重拷+手动登录后仍复现)→ 整体中止
11. Notion `object_not_found` → 父页面 Connections 添加 integration;`write_local` 必须先于 `notion_sync`
12. **edge-tts/网络依赖**:Step 0 预探,Step 9 失败降级静音,不阻塞成片;ffmpeg 缺 subtitles 滤镜 → 外挂 .srt
13. **ppt-master 自动安装**仅在缺失时执行一次;装不上立即 Pillow fallback,不反复重试
14. 生图:**国内模型禁负面提示词**写法;grsai 只用 CLI 本体命令,提示词技巧库只借鉴
15. 滚动加载参数:delta ≥2000-4000 才触发 X 加载(已在 xscan 内置,手工诊断时注意);置顶带视频推文占大量预算,必须滚动

## Verification

- Step 3 每账号 stdout 一行(ok/rounds/fetched/in_window/pinned);Step 10 后 `video_check.json ok=true`
- 最终断言:①`cross_checked.json` 的 launch 均带 `release_verified`(true/false/null)②raw 文件无 web 来源字段 ③`browser_scheme` 与 `cards_engine` 已入 run_report ④产物四件套存在:报告 md / manuscript_final.md / video_check.json(ok) / 成品 mp4(若 video.enabled)⑤本会话账号数 ≤ `session_batch_size`
- 定时任务模式:跳过 6/8 倒计时与 Step 10 等待,汇报文案标注"unattended,回复'继续'可合成视频"
