"""grab_images.py — Step 6: download tweet media (pbs.twimg.com is public, no browser needed).

Reads cross_checked.json (launches + signals), downloads media[] to images/<tweet_id>_<n>.<ext>.
--todo: only write screenshots_todo.json (candidates for optional cua-driver card screenshots).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import models  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _ext(url: str) -> str:
    m = re.search(r"format=(\w+)", url)
    if m:
        return m.group(1)
    m = re.search(r"\.(\w{3,4})(?:\?|$)", url)
    return m.group(1) if m else "jpg"


def main() -> int:
    models.ensure_utf8_stdout()
    p = argparse.ArgumentParser()
    p.add_argument("--base-dir", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--todo", action="store_true", help="only list screenshot candidates")
    args = p.parse_args()

    rd = models.raw_dir(args.base_dir, args.run_id)
    cc = models.read_json(rd / "cross_checked.json")
    items = cc["launches"] + cc["signals"]

    if args.todo:
        todo = [{"id": t["id"], "url": t.get("url"), "company": t.get("company"),
                 "model_name": t.get("model_name")}
                for t in items if t.get("media") and t.get("category") == "benchmark"]
        models.write_json(rd / "screenshots_todo.json", todo)
        print(f"screenshot candidates: {len(todo)}")
        return 0

    import requests
    img_dir = rd / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    ok = fail = 0
    for t in items:
        for i, url in enumerate(t.get("media") or [], 1):
            dest = img_dir / f"{t['id']}_{i}.{_ext(url)}"
            if dest.exists():
                ok += 1
                continue
            try:
                r = requests.get(url, headers={"User-Agent": UA}, timeout=30, stream=True)
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(65536):
                        f.write(chunk)
                ok += 1
            except Exception as e:
                fail += 1
                print(f"WARN download failed {url[:80]}: {e}")

    report = models.load_run_report(args.base_dir, args.run_id)
    report["stages"]["images"] = {"downloaded": ok, "failed": fail,
                                  "at": models.now_cst().isoformat(timespec="seconds")}
    report["images_failed"] = fail
    models.save_run_report(args.base_dir, args.run_id, report)
    print(f"images: downloaded={ok} failed={fail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
