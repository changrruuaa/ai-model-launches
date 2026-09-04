"""prefilter.py — Step 2 candidate selection (zero-cost keyword + heuristic screen).

Reads all <handle>.json (main stage) + noise filter -> candidates.json.
Noise filter (dropped before LLM): pure retweets (RT @), replies (@...), text <20 chars
with no media and no external links. Kept: keyword match OR pinned-in-window OR
suspected-truncation (text ends with ellipsis). Thirdparty tweets are appended
separately (all pass noise filter) for Step 4a classification.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import models  # noqa: E402

KEYWORDS = [
    "launch", "releas", "announc", "introduc", " ship", "shipping", "available",
    "now live", "out now", "open source", "open-weight", "open weight", "benchmark",
    "state of the art", "sota", "preview", " API", "model", "update",
    "发布", "推出", "上线", "开源", "升级", "模型", "首发", "预览",
]


def _keyword_hit(text: str) -> bool:
    low = text.lower()
    return any(k.lower() in low for k in KEYWORDS)


def _noise(tweet: dict) -> bool:
    if tweet.get("is_retweet"):
        return True
    if tweet.get("is_reply"):
        return True
    if len(tweet.get("text", "")) < 20 and not tweet.get("media") and not tweet.get("external_links"):
        return True
    return False


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--base-dir", required=True)
    p.add_argument("--run-id", required=True)
    args = p.parse_args()

    rd = models.raw_dir(args.base_dir, args.run_id)
    report = models.load_run_report(args.base_dir, args.run_id)

    candidates, thirdparty, noise_dropped = [], [], 0
    for acct in report["accounts"]["main"]:
        fpath = rd / f"{acct['handle']}.json"
        if not fpath.exists() or acct["status"] != "ok":
            continue
        for t in models.read_json(fpath)["tweets"]:
            if _noise(t):
                noise_dropped += 1
                continue
            hit = _keyword_hit(t["text"]) or t["is_pinned"] or t["text"].rstrip().endswith(("…", "..."))
            if hit:
                t["handle"] = acct["handle"]
                t["company"] = acct["company"]
                candidates.append(t)

    for acct in report["accounts"]["thirdparty"]:
        fpath = rd / f"{acct['handle']}.json"
        if not fpath.exists() or acct["status"] != "ok":
            continue
        for t in models.read_json(fpath)["tweets"]:
            if _noise(t):
                noise_dropped += 1
                continue
            t["handle"] = acct["handle"]
            t["company"] = acct["company"]
            thirdparty.append(t)

    out = {"candidates": candidates, "thirdparty": thirdparty,
           "stats": {"candidates": len(candidates), "thirdparty": len(thirdparty),
                     "noise_dropped": noise_dropped}}
    models.write_json(rd / "candidates.json", out)
    report["stages"]["prefilter"] = {"candidates": len(candidates),
                                     "thirdparty": len(thirdparty),
                                     "noise_dropped": noise_dropped,
                                     "at": models.now_cst().isoformat(timespec="seconds")}
    models.save_run_report(args.base_dir, args.run_id, report)
    print(f"prefilter: candidates={len(candidates)} thirdparty={len(thirdparty)} "
          f"noise_dropped={noise_dropped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
