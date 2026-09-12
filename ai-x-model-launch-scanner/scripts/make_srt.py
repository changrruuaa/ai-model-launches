"""make_srt.py — Step 9 子步⑤:由 video_manifest.json 生成字幕(按 SEG 时长轴,长段按标点切分)。

用法: python make_srt.py --manifest <run_dir>/video/video_manifest.json -o <run_dir>/video/subs.srt
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import models  # noqa: E402

MAX_LINE = 20  # 每条字幕 ≤20 字


def split_text(text: str, max_len: int = MAX_LINE) -> list[str]:
    text = re.sub(r"\s+", "", text)
    if len(text) <= max_len:
        return [text] if text else []
    # 先按标点切,再把超长块硬切
    chunks, cur = [], ""
    for ch in re.split(r"([,。;;!!??、])", text):
        cur += ch
        if ch in ",。;;!!??、":
            chunks.append(cur)
            cur = ""
    if cur:
        chunks.append(cur)
    out = []
    for c in chunks:
        while len(c) > max_len:
            out.append(c[:max_len])
            c = c[max_len:]
        if c:
            out.append(c)
    return out


def fmt_ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main() -> int:
    models.ensure_utf8_stdout()
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True)
    p.add_argument("-o", "--out", required=True)
    args = p.parse_args()

    segs = models.read_json(Path(args.manifest))
    t = 0.0
    idx = 0
    lines = []
    for seg in segs:
        dur = float(seg.get("duration") or 3.0)
        text = (seg.get("text") or "").strip()
        parts = split_text(text)
        if parts:
            per = dur / len(parts)
            for j, part in enumerate(parts):
                start = t + j * per
                end = start + per
                idx += 1
                lines.append(f"{idx}\n{fmt_ts(start)} --> {fmt_ts(end)}\n{part}\n")
        t += dur
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    print(f"srt: {idx} cues, total {t:.1f}s -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
