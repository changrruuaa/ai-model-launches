# 视频规格规范(Step 9 物料 / Step 10 合成)

## 1. 尺寸与产物

- `video.aspect` = `16:9` → 1920x1080;`9:16` → 1080x1920(同构纵排:左右布局改上下)
- 产物:`<run_dir>\video\<date>-ai-launches.mp4`(H.264 yuv420p 30fps + AAC 192k)
- 中间产物:`cards\`(PNG 卡片)、`audio\seg_NN.mp3`、`subs.srt`、`video_manifest.json`、`video_check.json`

## 2. 默认主题 "ppt-reference"(对齐 assets\style-reference.png)

> 用户在 Step 0 未指定卡片风格时的默认主题。视觉基准:`assets\style-reference.png`。

**配色(大地色暖调)**:
| 用途 | 色值 |
|---|---|
| 背景 | `#F4EFE6` 暖米色 |
| 角部有机色块 | 鼠尾草绿 `#A8B5A0` / 浅褐 `#D9C7AE` / 灰绿 `#C5CDBF`,透明度 80-100%,分布在两对角 |
| 标题(衬线) | 深墨 `#1F2937` |
| 副标题/点缀 | 鼠尾草绿 `#8A9A8B` |
| 正文 | 深灰 `#374151` |
| 图表卡底 | 纯白 `#FFFFFF` 圆角(半径 24px) |
| 图表高亮条(前 5) | 青 `#7FA8A0` / 绿 `#8FA886` / 褐 `#C09B76` / 黄 `#D9C97E` / 灰绿 `#A8B5A0` |
| 图表其余条 | `#D6D3CC` 置灰 |

**字体**:标题 SimSun(衬线,`C:\Windows\Fonts\simsun.ttc`)大号;副标题/正文/图表标签 Microsoft YaHei(`msyh.ttc`,粗体 `msyhbd.ttc`)。

**布局(item 卡,16:9)**:左侧 45% 文本区(上 1/3 大标题 + 副标题 + 细分隔线 + 正文 + 底部页脚点标签"公司 · 日期 · 来源"),右侧 55% 白卡(配图或 benchmark 简条);9:16 时上 40% 文本、下 60% 白卡。cover 卡 = 全幅文本居左上 + 大号主标题;ending 卡 = 居中。

**安全边距**:四边 ≥96px(1080p)/ ≥60px(1080 宽),所有文字不越界。

## 3. 卡片生成(make_cards.py,Pillow fallback)

```
python "${HERMES_SKILL_DIR}\scripts\make_cards.py" --manifest cards.json --out "<run_dir>\video\cards" --size 1920x1080 --theme ppt-reference
```
`cards.json` 由 agent 从 manuscript_final.md 生成:`[{"type": "cover|item|chart|ending", "title", "lines": [...], "benchmark": [{"name","score","unit"}], "image": "<可选,grsai 配图路径>"}]`。chart 卡 = 纯 PIL 横向条形图(数值顶标、名称轴标、高亮前 5 其余置灰)。

## 4. ppt-master 优先路径(Step 9 子步③)

1. 探测 `%USERPROFILE%\.hermes\skills\ppt-master\SKILL.md` 存在且其依赖可 import → 按其 SKILL.md 用法产 PPTX(每卡一页,ppt-reference 风格:米色底/衬线标题/白圆角图表卡)
2. 缺失 → 自动安装:`git clone --depth 1 https://github.com/hugohe3/ppt-master` 到临时目录 → 拷 `skills\ppt-master\` 子树到 `%USERPROFILE%\.hermes\skills\ppt-master\` → `pip install -r requirements.txt` → 复探测;安装后本轮直接按其 SKILL.md 调用(不等 hermes 重载)
3. PNG 导出:PowerPoint COM `SaveAs ppSaveAsPNG` 或 soffice;**3 次尝试内无 PNG 产物 → 立即降级 make_cards.py**,不重试
4. 全程记 `cards_engine: ppt | pillow` 入 run_report

## 5. 配音与时长(Step 9 子步④)

- `audio.voice` 非空 → 逐段 `edge-tts --voice <voice> --write-media "<run_dir>\video\audio\seg_NN.mp3"`(文本 = SEG 口播文案)→ `ffprobe` 实测时长 → 卡片停留时长 = `max(音频+0.8s, 3.0s)`
- edge-tts 失败(网络/未装)→ 降级:静音,每卡固定 5s(cover 4s / ending 5s / item 按字数 `max(3, 字数/4 + 1)`);run_report 记 `narration: silent-fallback`
- `audio.bgm_path` 存在 → 合成时混入(`volume=0.15`,amix)

## 6. 合成(compose_video.py,Step 10)

```
python "${HERMES_SKILL_DIR}\scripts\compose_video.py" --manifest "<run_dir>\video\video_manifest.json" --out "<run_dir>\video\<date>-ai-launches.mp4" [--bgm <path>] [--srt subs.srt]
```

- manifest:`[{"card": "<cards\xx.png>", "seg": "SEG-01", "text": "<口播>", "audio": "<mp3|null>", "duration": 6.2}]`
- 逐段:`ffmpeg -loop 1 -i card.png [-i seg.mp3 -af apad] -ar 48000 -ac 2 -t <dur> -r 30 -c:v libx264 -pix_fmt yuv420p -c:a aac seg.mp4`(配音段 apad 把音频垫到 -t 上限;两分支统一 48k 立体声,concat `-c copy` 要求流参数一致)→ concat demuxer → 再 mux 字幕与 BGM(两步,避免重编码两次)
- 字幕:`subtitles=subs.srt:force_style=FontName=Microsoft YaHei,FontSize=14,MarginV=30`(Windows 路径转义:`C\:/...`);**冒烟预检** `ffmpeg -filters` 含 `subtitles`,缺 libass → 降级外挂 .srt 不烧录(记 run_report)
- 校验:`ffprobe` 时长 ≈ Σduration ±2s、双流存在 → 写 `video_check.json`;不过 → 报错不交付

## 7. 字幕(make_srt.py)

`python "${HERMES_SKILL_DIR}\scripts\make_srt.py" --manifest video_manifest.json -o subs.srt` —— 按 SEG 时长轴生成,长段按标点切 ≤20 字/条。
