# 环境查看与从零部署(独立文件,不依赖 SKILL.md 上下文)

> **核心原则:默认用户全部可用环境为空(fail-closed)**——每项依赖先探测,探测到才视为可用;
> 探测不到一律按缺失处理、给安装命令,**不做"应该已经装了"的假设**。
> 本文件与 `scripts\check_env.py` 的 12 项检查一一对应:check_env 输出的缺失项,在 §3 查到对应安装命令。
> 长期偏好与探查存档存 `config.user.yaml`(skill 同目录,§5)。

## 1. 一次性总检

```
python "${HERMES_SKILL_DIR}\scripts\check_env.py"
```
exit 0 = 可继续;exit 12 = 有致命缺失(输出 JSON 的 `fatal` 数组逐项按下节安装)。

## 2. 依赖总表(默认全空,逐项探测→安装)

| # | 组件 | 用途 | 探测命令(有输出=可用) | 安装命令(Windows) | 降级 |
|---|---|---|---|---|---|
| 1 | Python ≥3.10 | 脚本层 | `python --version` | `winget install Python.Python.3.12` | ❌ 致命 |
| 2 | pip 包:pyyaml/jinja2/requests/python-dateutil/**tzdata** | 配置/模板/HTTP/时间窗/时区 | `python -c "from zoneinfo import ZoneInfo; ZoneInfo('Asia/Shanghai')"`(功能探测;Anaconda 自带库可免装) | `python -m pip install pyyaml jinja2 requests python-dateutil tzdata`(tzdata 仅 python.org/Store Windows Python 需要) | ❌ 致命 |
| 3 | pip 包:edge-tts | 中文配音 | `edge-tts --list-voices`(或 `python -m pip show edge-tts`) | `python -m pip install edge-tts` | ⚠️ 无旁白模式 |
| 4 | pip 包:Pillow | 卡片 fallback | `python -c "import PIL"` | `python -m pip install pillow` | ⚠️ 仅 ppt 路径可用时 |
| 5 | pip 包:notion-client / anthropic | Notion / Haiku 分类 | `python -c "import notion_client,anthropic"` | `python -m pip install notion-client anthropic` | ⚠️ 静默降级 |
| 6 | Node ≥18 | xscan.mjs | `node --version` | `winget install OpenJS.NodeJS.LTS` | ❌ 致命 |
| 7 | puppeteer-core | 浏览器抓取 | `node -e "require('puppeteer-core')"`(在 scripts\ 下) | `cd "${HERMES_SKILL_DIR}\scripts" && npm install`;官方源网络失败时加 `--registry=https://registry.npmmirror.com` 重试 | ❌ 致命 |
| 8 | Chrome 稳定版 | 被驱动的浏览器 | `ls "C:\Program Files\Google\Chrome\Application"` 有版本目录 | `winget install Google.Chrome` | ❌ 致命 |
| 9 | chrome_inspect.py | CDP 巡检(可选) | `ls "%USERPROFILE%\.hermes\tools\chrome_inspect.py"` | 从仓库 `tools\chrome-inspector\chrome_inspect.py` 复制到 `%USERPROFILE%\.hermes\tools\` | ⚠️ 跳过巡检 |
| 10 | ffmpeg + ffprobe | 视频合成 | `ffmpeg -version` | `winget install Gyan.FFmpeg`(装后重开终端) | ⚠️ 无视频产物 |
| 11 | git | ppt-master 安装 | `git --version` | `winget install Git.Git` | ⚠️ ppt-master 装不了→Pillow |
| 12 | grsai CLI | 生图(封面/插画) | `grsai --help` | `npm install -g grsai-cli`(+`~/.grsai/config.json` 配 key) | ⚠️ 无插画(纯文字卡) |

## 3. 附带 skill(按需下载,下载后同步环境探查与适配)

| skill | 用途 | 探测 | 安装 | 下载后联动适配 |
|---|---|---|---|---|
| GPT-Image2-Skill | 生图提示词技巧库 | `grsai skill show` 能列出技巧库 | `grsai skill download`(**只下 skill 本体,不下载参考画廊**) | 跑一次 `grsai skill show` 冒烟;结果写 `probes.image_prompt_skill` |
| ppt-master | 文字卡片 PPT 路径 | `ls "%USERPROFILE%\.hermes\skills\ppt-master\SKILL.md"` | `git clone --depth 1 https://github.com/hugohe3/ppt-master` → 拷 `skills\ppt-master\` 到 `%USERPROFILE%\.hermes\skills\ppt-master\` → `python -m pip install -r "%USERPROFILE%\.hermes\skills\ppt-master\requirements.txt"` | 复探测 + 依赖 import 冒烟;结果写 `probes.ppt_master` |

## 4. 凭据(运行时探测,不写入本仓库)

- `NOTION_TOKEN`(可选):`setx NOTION_TOKEN "ntn_..."` 后**重启 Hermes desktop**;未配置 → Notion 全程静默降级为仅本地
- `ANTHROPIC_API_KEY`(可选):同上;未配置 → classify 只能 inline 模式(>120 条会被迫中止提示配置)
- grsai API key:`~/.grsai/config.json`(一次性,已配则跳过)

## 5. 长期约束文件 `config.user.yaml`

- 位置:**skill 同目录**(与 SKILL.md 同文件夹);首跑从 `config.user.example.yaml` 模板自动生成
- 用途:Step 0 全部探查结论 + 用户规范**只存这一个文件**(问询答案自动写回;探查存档进 `probes:` 段带日期)
- 修改:直接编辑即可改偏好;**删除某键 = 恢复"下次追问"**
- ⚠️ 重新部署 skill 到 hermes 机器时**保留此文件**(不在 git 内,`.gitignore` 已排除)
