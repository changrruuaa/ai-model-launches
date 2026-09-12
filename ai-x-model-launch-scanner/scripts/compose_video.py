"""compose_video.py — Step 10:视频合成编排(ffmpeg,逐段图+音 -> concat -> 字幕/BGM)。

输入 video_manifest.json: [{"card": "<png>", "seg": "SEG-01", "text": "<口播>",
                             "audio": "<mp3|null>", "duration": 6.2}]
用法:
  python compose_video.py --manifest <run_dir>/video/video_manifest.json \
      --out <run_dir>/video/2026-09-11-ai-launches.mp4 [--bgm <mp3>] [--srt subs.srt]

行为:
  1. 预检 ffmpeg/ffprobe + subtitles 滤镜(缺 libass -> 字幕降级外挂 .srt,记入 video_check.json)
  2. 逐段: -loop 1 -i card [-i audio -af apad] -t dur -> seg_NN.mp4 (h264 yuv420p 30fps + aac 48k 立体声)
  3. concat demuxer 拼接 -> mux 字幕(subtitles=...force_style)与 BGM(volume 0.15 amix)
  4. 校验: ffprobe 总时长 ≈ Σduration ±2s、双流存在 -> video_check.json;不过 exit 6
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import models  # noqa: E402

BGM_VOL = 0.15


def run(cmd: list[str], desc: str) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"{desc} 失败(exit {r.returncode}):\n{(r.stderr or '')[-1200:]}")


def ffprobe_json(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {(r.stderr or '')[-300:]}")
    return json.loads(r.stdout)


def esc_filter_path(p: Path) -> str:
    """Windows 路径 -> ffmpeg filter 转义(盘符冒号 + 反斜杠)。"""
    s = str(p.resolve()).replace("\\", "/")
    s = s.replace(":", "\\:")
    s = s.replace("'", "\\'")
    return s


def has_subtitles_filter() -> bool:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode == 0 and "subtitles" in r.stdout


def probe_duration(path: Path) -> float:
    info = ffprobe_json(path)
    return float(info["format"]["duration"])


def main() -> int:
    models.ensure_utf8_stdout()
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--bgm", default=None)
    p.add_argument("--srt", default=None)
    args = p.parse_args()

    segs = models.read_json(Path(args.manifest))
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    check: dict = {"segments": len(segs), "warnings": []}

    # 1) 预检
    for binary in ("ffmpeg", "ffprobe"):
        r = subprocess.run([binary, "-version"], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"ERROR {binary} 不可用(references/environment-setup.md §2 #10)")
            return 5
    burn_subs = bool(args.srt and Path(args.srt).exists())
    if burn_subs and not has_subtitles_filter():
        check["warnings"].append("ffmpeg 无 subtitles 滤镜(缺 libass)——降级外挂 .srt 不烧录")
        burn_subs = False
    check["subtitles_burned"] = burn_subs

    # 2) 逐段合成
    with tempfile.TemporaryDirectory(prefix="xscan_video_") as td:
        tmp = Path(td)
        concat_list = tmp / "concat.txt"
        has_audio_any = any(s.get("audio") for s in segs)
        for i, seg in enumerate(segs, 1):
            card = Path(seg["card"])
            if not card.is_file():
                print(f"ERROR 卡片缺失: {card}")
                return 5
            dur = float(seg.get("duration") or 3.0)
            seg_mp4 = tmp / f"seg_{i:02d}.mp4"
            cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                   "-loop", "1", "-i", str(card)]
            audio = seg.get("audio")
            if audio and Path(audio).is_file():
                # apad:把音频垫到 -t 上限(manifest 时长恒 > 音频长,0.8s 尾垫是设计行为);
                # -ar/-ac:统一 48k 立体声,与静音段 concat -c copy 参数一致(edge-tts 是 24k 单声道)
                cmd += ["-i", str(audio)]
                cmd += ["-af", "apad", "-ar", "48000", "-ac", "2",
                        "-t", f"{dur:.3f}", "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "192k", str(seg_mp4)]
            else:
                cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                        "-t", f"{dur:.3f}", "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(seg_mp4)]
            run(cmd, f"seg_{i:02d} 合成")
            with open(concat_list, "a", encoding="utf-8") as f:
                f.write(f"file '{seg_mp4.as_posix()}'\n")

        # 3) concat
        if not has_audio_any:
            check["warnings"].append("全片无配音(静音/BGM-only fallback)")
        merged = tmp / "merged.mp4"
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(concat_list), "-c", "copy", str(merged)], "concat")

        # 字幕 + BGM mux(单次重编码,vf subtitles / amix)
        vf = []
        if burn_subs:
            vf.append(f"subtitles='{esc_filter_path(Path(args.srt))}'"
                      ":force_style='FontName=Microsoft YaHei,FontSize=14,Outline=1,MarginV=30'")
        bgm = Path(args.bgm) if args.bgm else None
        if bgm and bgm.is_file():
            final_cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(merged), "-i", str(bgm),
                         "-filter_complex",
                         "[1:a]volume=0.15[bg];[0:a][bg]amix=inputs=2:duration=first[a]",
                         "-map", "0:v", "-map", "[a]"]
            if vf:
                final_cmd += ["-vf", ",".join(vf)]
            final_cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                          "-shortest", str(out_path)]
        else:
            final_cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(merged)]
            if vf:
                final_cmd += ["-vf", ",".join(vf)]
            final_cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy", str(out_path)]
        run(final_cmd, "最终合成")

    # 4) 校验
    info = ffprobe_json(out_path)
    total = float(info["format"]["duration"])
    expect = sum(float(s.get("duration") or 3.0) for s in segs)
    v = next((st for st in info["streams"] if st["codec_type"] == "video"), None)
    a = next((st for st in info["streams"] if st["codec_type"] == "audio"), None)
    check.update({"total_duration": round(total, 2), "expected_duration": round(expect, 2),
                  "video_stream": bool(v), "audio_stream": bool(a),
                  "resolution": f'{v.get("width")}x{v.get("height")}' if v else None})
    ok = (v and a and abs(total - expect) <= 2.0)
    check["ok"] = bool(ok)
    models.write_json(out_path.parent / "video_check.json", check)
    print(f"video: {out_path} ({total:.1f}s, expect {expect:.1f}s) ok={ok}")
    for wmsg in check["warnings"]:
        print(f"WARN {wmsg}")
    return 0 if ok else 6


if __name__ == "__main__":
    raise SystemExit(main())
