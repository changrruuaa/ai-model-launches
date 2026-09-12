# 文稿格式规范(manuscript.md,Step 7 撰稿 / Step 9/10 机读契约)

## 1. 文件与分段语法

产物:`<run_dir>\manuscript.md`(Step 8 定稿后另存 `manuscript_final.md`)。

**机读分段标记**(Step 9 卡片/配音、Step 10 合成均按此解析,正则 `^## SEG-(\d+) \| (\w+) \| (.+)$`):

```markdown
# <视频标题>

## SEG-01 | cover | <封面主标题,≤20 字>
<封面口播文案,开场 hook,80-150 字>

## SEG-02 | item | <公司 · 模型名>
<该条发布口播文案,80-150 字>
<!-- refs: <handle>-<status_id>, https://x.com/<handle>/status/<id> -->

## SEG-03 | chart | <图表标题,如 "Arena 竞技场得分对比">
<口播一句话引导,40-80 字>
<!-- chart: {"source": "<handle>-<status_id>", "items": [{"name": "...", "score": 1400, "unit": "分"}]} -->

## SEG-99 | ending | <尾板标题>
<收尾口播,60-100 字>
```

- `type` ∈ `cover | item | chart | ending`;item 段每条 launch 一个;有第三方 benchmark 数据的条目可在其后跟一个 chart 段
- refs 注释**必须存在**:每条事实(参数/日期/数字)可追溯到 `cross_checked.json` 的 id;chart 段用 `<!-- chart: {...} -->` 携带绘图数据
- 口播文案 = 纯中文口语,禁 markdown 列表/加粗混入口播正文

## 2. 默认结构(structure_rules=false 时)

1. cover:今日 N 条 AI 模型发布速报 + hook(最大亮点前置)
2. item × N:每条 launch 一段,按置信度降序;同公司合并
3. chart(可选):benchmark 对比,仅当推文原文带具体分数
4. 第三方信号(并入最后一个 item 段或单独一段):@arena/@ArtificialAnlys 佐证一句话
5. ending:总结 + 关注引导

**用户结构约束**(config.user.yaml `manuscript.structure_rules`):有值 = 硬约束叠加,与默认结构冲突时**用户规则优先**;`false` = 纯默认结构。

## 3. 硬约束(违反 = 文稿无效)

- **只依据 `cross_checked.json`**:禁编造、禁补外部知识;`confidence<0.8` 的条目措辞加"据报道";`coming soon` 不入稿(classify 已滤,双保险)
- **数字必须有 refs**;推文没提的参数(参数量/上下文/定价)不写
- 单段 ≤120 字(中文口播 4 字/秒 ≈ 30 秒);总时长目标 = config `video.target_minutes`(默认 3 分钟 ≈ 720 字,3-8 分钟区间)
- 全稿语言 = 中文(模型名/公司名/专有名词保留英文原文)
- 日期表述用相对口径("今天/本周")+ 绝对日期各一次,避免歧义
