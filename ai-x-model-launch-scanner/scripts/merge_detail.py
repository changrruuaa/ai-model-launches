"""merge_detail.py — merge agent-dumped raw_detail_<id>.json files into detail_tweets.json.

Agent writes per-candidate detail page captures (Step 2):
  {"status_id": "...", "text_full": "...", "media": [...], "external_links": [...]}
Detail page text is never truncated (fixes B2); it overrides timeline text downstream.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import models  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--base-dir", required=True)
    p.add_argument("--run-id", required=True)
    args = p.parse_args()

    rd = models.raw_dir(args.base_dir, args.run_id)
    merged = {}
    for f in sorted(rd.glob("raw_detail_*.json")):
        try:
            d = models.read_json(f)
        except Exception as e:  # malformed agent dump: skip, count
            print(f"WARN skipping malformed {f.name}: {e}")
            continue
        sid = str(d.get("status_id", "")).strip()
        if not sid or not d.get("text_full"):
            continue
        merged[sid] = {"id": sid, "full_text_long": d["text_full"],
                       "media": list(d.get("media") or []),
                       "external_links": list(d.get("external_links") or [])}

    models.write_json(rd / "detail_tweets.json", merged)

    report = models.load_run_report(args.base_dir, args.run_id)
    report["stages"]["detail"] = {"merged": len(merged),
                                  "at": models.now_cst().isoformat(timespec="seconds")}
    models.save_run_report(args.base_dir, args.run_id, report)
    print(f"detail merged: {len(merged)} tweets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
