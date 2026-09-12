"""make_cards.py — Step 9 子步③ Pillow fallback:文字卡片直绘(ppt-reference 主题)。

规格见 references/video-spec.md。manifest (cards.json):
[{"type": "cover|item|chart|ending", "title": "...", "subtitle": "...",
  "lines": ["..."], "footer": ["OpenAI", "2026-09-11"],
  "benchmark": [{"name": "...", "score": 1400, "unit": "分"}],   # chart 卡
  "image": "<可选 配图路径>"}]                                   # item 卡右侧配图

用法: python make_cards.py --manifest cards.json --out <dir> --size 1920x1080 --theme ppt-reference
产物: <out>/card_01_cover.png ...(与 manifest 顺序对应)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import models  # noqa: E402

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

# ppt-reference 主题(video-spec.md §2)
BG = "#F4EFE6"
BLOBS = [("#A8B5A0", 1.00), ("#D9C7AE", 0.85), ("#C5CDBF", 0.75)]
INK = "#1F2937"
SAGE = "#8A9A8B"
BODY = "#374151"
CARD_BG = "#FFFFFF"
BAR_HI = ["#7FA8A0", "#8FA886", "#C09B76", "#D9C97E", "#A8B5A0"]
BAR_LO = "#D6D3CC"
RULE = "#C9C4B8"

FONTS = {
    "title": ["C:/Windows/Fonts/simsun.ttc", "C:/Windows/Fonts/msyh.ttc"],
    "subtitle": ["C:/Windows/Fonts/msyh.ttc"],
    "body": ["C:/Windows/Fonts/msyh.ttc"],
    "bold": ["C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc"],
}
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def F(kind: str, size: int) -> ImageFont.FreeTypeFont:
    key = (kind, size)
    if key not in _font_cache:
        last = None
        for p in FONTS.get(kind, FONTS["body"]):
            try:
                _font_cache[key] = ImageFont.truetype(p, size)
                break
            except OSError as e:
                last = e
        else:
            raise RuntimeError(f"字体缺失({kind}): {last}")
    return _font_cache[key]


def wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    """CJK 友好换行:逐字累计,英文单词不拆。"""
    lines, cur, cur_w = [], [], 0.0
    for ch in text:
        w = draw.textlength(ch, font=font)
        if ch == "\n" or (cur_w + w > max_w and cur):
            lines.append("".join(cur))
            cur, cur_w = ([] if ch == "\n" else [ch]), (0 if ch == "\n" else w)
        else:
            cur.append(ch)
            cur_w += w
    if cur:
        lines.append("".join(cur))
    return lines


def draw_blobs(img: Image.Image, w: int, h: int) -> None:
    """四角有机色块:对角两簇大椭圆(参考图风格近似)。"""
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    specs = [
        (BLOBS[0][0], -0.18 * w, -0.25 * h, 0.30 * w, 0.28 * h, int(255 * BLOBS[0][1])),
        (BLOBS[1][0], 0.80 * w, 0.72 * h, 1.25 * w, 1.30 * h, int(255 * BLOBS[1][1])),
        (BLOBS[2][0], 0.86 * w, -0.12 * h, 1.18 * w, 0.16 * h, int(255 * BLOBS[2][1])),
        (BLOBS[2][0], -0.10 * w, 0.86 * h, 0.18 * w, 1.14 * h, int(255 * BLOBS[2][1])),
    ]
    for color, x0, y0, x1, y1, alpha in specs:
        d.ellipse([x0, y0, x1, y1], fill=color + f"{alpha:02x}")
    img.alpha_composite(layer)


def rounded_card(img: Image.Image, box: tuple[int, int, int, int], radius: int = 24) -> ImageDraw.ImageDraw:
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, radius=radius, fill=CARD_BG)
    return d


def paste_cover_fit(card: Image.Image, img_path: str, box: tuple[int, int, int, int]) -> None:
    src = Image.open(img_path).convert("RGB")
    bw, bh = box[2] - box[0], box[3] - box[1]
    inset = int(min(bw, bh) * 0.04)
    tw, th = bw - 2 * inset, bh - 2 * inset
    scale = max(tw / src.width, th / src.height)
    src = src.resize((int(src.width * scale) + 1, int(src.height * scale) + 1))
    x0 = (src.width - tw) // 2
    y0 = (src.height - th) // 2
    src = src.crop((x0, y0, x0 + tw, y0 + th))
    mask = Image.new("L", (tw, th), 255)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, tw, th], radius=16, fill=255)
    card.paste(src, (box[0] + inset, box[1] + inset), mask)


def bar_chart(card: Image.Image, items: list[dict], box: tuple[int, int, int, int], scale: float) -> None:
    d = ImageDraw.Draw(card)
    x0, y0, x1, y1 = box
    pad = int(40 * scale)
    label_w = int(240 * scale)
    plot_x0, plot_y0 = x0 + pad + label_w, y0 + pad
    plot_x1, plot_y1 = x1 - pad, y1 - pad
    n = len(items)
    if n == 0:
        return
    gap = int(14 * scale)
    bar_h = min(int((plot_y1 - plot_y0 - gap * (n - 1)) / n), int(56 * scale))
    max_v = max(abs(float(it["score"])) for it in items) or 1.0
    label_f = F("body", int(24 * scale))
    val_f = F("bold", int(24 * scale))
    for i, it in enumerate(items):
        by = plot_y0 + i * (bar_h + gap)
        color = BAR_HI[i] if i < len(BAR_HI) else BAR_LO
        bw = int((plot_x1 - plot_x0) * abs(float(it["score"])) / max_v)
        d.rounded_rectangle([plot_x0, by, plot_x0 + max(bw, 4), by + bar_h], radius=bar_h // 4, fill=color)
        name = it["name"]
        while d.textlength(name, font=label_f) > label_w - 10 and len(name) > 2:
            name = name[:-2] + "…"
        d.text((plot_x0 - 16 - d.textlength(name, font=label_f), by + (bar_h - int(24 * scale)) / 2),
               name, font=label_f, fill=BODY)
        val = f'{it["score"]}{it.get("unit", "")}'
        d.text((min(plot_x0 + bw + 12, plot_x1 - d.textlength(val, font=val_f)), by + (bar_h - int(24 * scale)) / 2),
               val, font=val_f, fill=INK)


def render(card_spec: dict, idx: int, w: int, h: int, out_dir: Path) -> Path:
    img = Image.new("RGBA", (w, h), BG)
    draw_blobs(img, w, h)
    d = ImageDraw.Draw(img)
    landscape = w >= h
    m = int(96 * (w / 1920 if landscape else w / 1080))  # 安全边距
    ttype = card_spec.get("type", "item")

    if ttype == "cover":
        title_f = F("title", int(120 * (w / 1920)))
        y = int(h * 0.30)
        for ln in wrap(d, card_spec["title"], title_f, w - 2 * m):
            d.text((m, y), ln, font=title_f, fill=INK)
            y += int(title_f.size * 1.25)
        y += int(30 * (w / 1920))
        if card_spec.get("subtitle"):
            sub_f = F("subtitle", int(48 * (w / 1920)))
            for ln in wrap(d, card_spec["subtitle"], sub_f, w - 2 * m):
                d.text((m, y), ln, font=sub_f, fill=SAGE)
                y += int(sub_f.size * 1.4)
        _footer(d, card_spec, m, h - m - int(40 * (w / 1920)), int(30 * (w / 1920)), landscape)

    elif ttype == "ending":
        title_f = F("title", int(96 * (w / 1920)))
        y = int(h * 0.38)
        for ln in wrap(d, card_spec["title"], title_f, w - 2 * m):
            tw = d.textlength(ln, font=title_f)
            d.text(((w - tw) / 2, y), ln, font=title_f, fill=INK)
            y += int(title_f.size * 1.3)
        if card_spec.get("lines"):
            body_f = F("body", int(36 * (w / 1920)))
            y += int(50 * (w / 1920))
            for text in card_spec["lines"]:
                for ln in wrap(d, text, body_f, w - 2 * m):
                    tw = d.textlength(ln, font=body_f)
                    d.text(((w - tw) / 2, y), ln, font=body_f, fill=BODY)
                    y += int(body_f.size * 1.5)

    else:  # item / chart:一侧文本一侧白卡
        split = 0.46 if landscape else 0.60
        if landscape:
            text_box = (m, m, int(w * split) - int(m / 2), h - m)
            card_box = (int(w * split), m, w - m, h - m)
        else:
            text_box = (m, m, w - m, int(h * split) - int(m / 2))
            card_box = (m, int(h * split), w - m, h - m)
        title_f = F("title", int(76 * (w / 1920)))
        y = text_box[1]
        for ln in wrap(d, card_spec["title"], title_f, text_box[2] - text_box[0]):
            d.text((text_box[0], y), ln, font=title_f, fill=INK)
            y += int(title_f.size * 1.25)
        if card_spec.get("subtitle"):
            y += int(18 * (w / 1920))
            sub_f = F("subtitle", int(40 * (w / 1920)))
            for ln in wrap(d, card_spec["subtitle"], sub_f, text_box[2] - text_box[0]):
                d.text((text_box[0], y), ln, font=sub_f, fill=SAGE)
                y += int(sub_f.size * 1.4)
        y += int(34 * (w / 1920))
        d.line([text_box[0], y, text_box[0] + int(64 * (w / 1920)), y], fill=RULE, width=3)
        y += int(34 * (w / 1920))
        body_f = F("body", int(32 * (w / 1920)))
        for text in card_spec.get("lines", []):
            for ln in wrap(d, text, body_f, text_box[2] - text_box[0]):
                if y + body_f.size > text_box[3] - int(60 * (w / 1920)):
                    break
                d.text((text_box[0], y), ln, font=body_f, fill=BODY)
                y += int(body_f.size * 1.5)
            y += int(14 * (w / 1920))
        _footer(d, card_spec, text_box[0], text_box[3] - int(10 * (w / 1920)), int(26 * (w / 1920)), landscape)

        rounded_card(img, card_box)
        card_img = img.crop(card_box)
        if card_spec.get("image"):
            paste_cover_fit(card_img, card_spec["image"], (0, 0, card_box[2] - card_box[0], card_box[3] - card_box[1]))
        elif card_spec.get("benchmark"):
            bar_chart(card_img, card_spec["benchmark"],
                      (0, 0, card_box[2] - card_box[0], card_box[3] - card_box[1]), w / 1920)
        else:  # 无图无数据:白卡上放模型名大字占位
            cd = ImageDraw.Draw(card_img)
            bf = F("bold", int(56 * (w / 1920)))
            text = card_spec.get("subtitle") or card_spec["title"]
            cw, chh = card_img.size
            lines = wrap(cd, text, bf, cw - int(120 * (w / 1920)))
            yy = (chh - len(lines) * int(bf.size * 1.4)) / 2
            for ln in lines:
                tw = cd.textlength(ln, font=bf)
                cd.text(((cw - tw) / 2, yy), ln, font=bf, fill=SAGE)
                yy += int(bf.size * 1.4)
        img.paste(card_img, (card_box[0], card_box[1]))

    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"card_{idx:02d}_{ttype}.png"
    img.convert("RGB").save(dest, "PNG")
    return dest


def _footer(d, spec, x, y, size, landscape):
    tags = spec.get("footer") or []
    if not tags:
        return
    f = F("body", size)
    cx = x
    for i, t in enumerate(tags):
        d.text((cx, y), t, font=f, fill=SAGE)
        cx += d.textlength(t, font=f) + size
        if i < len(tags) - 1:
            d.ellipse([cx, y + size * 0.35, cx + 6 * (size / 30), y + size * 0.35 + 6 * (size / 30)], fill=SAGE)
            cx += size


def main() -> int:
    models.ensure_utf8_stdout()
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--size", default="1920x1080")
    p.add_argument("--theme", default="ppt-reference", choices=["ppt-reference"])
    args = p.parse_args()

    w, h = (int(x) for x in args.size.lower().split("x"))
    cards = models.read_json(Path(args.manifest))
    results = []
    for i, spec in enumerate(cards, 1):
        dest = render(spec, i, w, h, Path(args.out))
        results.append(str(dest))
    print(f"cards: {len(results)} -> {args.out}")
    for r in results:
        print(f"  {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
