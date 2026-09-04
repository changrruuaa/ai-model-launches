"""cross_check.py — Step 5 third-party cross-validation (pure script, no browser).

- launch entries matched against @arena/@ArtificialAnlys tweet texts by model name
  -> cross_verified=true
- thirdparty tweets classified as benchmark -> "第三方信号" list (kept, is_launch=false)
- merges verified_part_*.json / verified.json (Step 4b, agent-written) into
  release_verified / external_refs; absent -> release_verified=null (unattended mode)
Output: cross_checked.json {launches, signals, stats}. --selftest uses embedded mocks.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import models  # noqa: E402


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9一-鿿]+", "", s.lower())


def _match(model_name: str, texts: list[str]) -> bool:
    n = _norm(model_name)
    if len(n) < 4:  # too generic (GPT / o3 ...), avoids false cross-verification
        return False
    for t in texts:
        if n in _norm(t):
            return True
    return False


def run(rd: Path, report: dict) -> dict:
    try:
        classified = models.read_json(rd / "classified.json")
    except FileNotFoundError:
        raise SystemExit("classified.json missing — run Step 4a first")

    third_texts = []
    for acct in report["accounts"]["thirdparty"]:
        f = rd / f"{acct['handle']}.json"
        if f.exists():
            for t in models.read_json(f)["tweets"]:
                third_texts.append(t["text"])

    # Step 4b verification (optional): verified.json or verified_part_*.json
    verified: dict[str, dict] = {}
    for f in [rd / "verified.json", *sorted(rd.glob("verified_part_*.json"))]:
        if not f.exists():
            continue
        data = models.read_json(f)
        if isinstance(data, list):
            for item in data:
                verified[str(item.get("id"))] = item

    launches, signals = [], []
    for it in classified["items"]:
        tweet = _find_tweet(rd, report, it["id"])
        entry = {**it,
                 "url": tweet.get("url") if tweet else None,
                 "created_at": tweet.get("created_at") if tweet else None,
                 "media": tweet.get("media", []) if tweet else [],
                 "external_links": tweet.get("external_links", []) if tweet else [],
                 "handle": tweet.get("handle") if tweet else None}
        if it["is_launch"]:
            v = verified.get(it["id"])
            entry["release_verified"] = v["release_verified"] if v and "release_verified" in v else None
            entry["external_refs"] = v.get("external_refs", []) if v else []
            entry["cross_verified"] = bool(
                it.get("model_name") and _match(it["model_name"], third_texts))
            launches.append(entry)
        elif it.get("category") == "benchmark" and tweet and tweet.get("is_third_party"):
            entry["cross_verified"] = _match(it.get("model_name") or "", third_texts)
            signals.append(entry)

    out = {"launches": launches, "signals": signals,
           "stats": {"launches": len(launches), "signals": len(signals),
                     "cross_verified": sum(1 for l in launches if l["cross_verified"]),
                     "release_verified": sum(1 for l in launches if l["release_verified"]),
                     "at": models.now_cst().isoformat(timespec="seconds")}}
    models.write_json(rd / "cross_checked.json", out)
    report["stages"]["cross_check"] = out["stats"]
    models.save_run_report(str(rd.parent.parent.parent), report["run_id"], report)
    return out


def _find_tweet(rd: Path, report: dict, tweet_id: str) -> dict | None:
    for stage in ("main", "thirdparty"):
        for acct in report["accounts"][stage]:
            f = rd / f"{acct['handle']}.json"
            if not f.exists():
                continue
            for t in models.read_json(f)["tweets"]:
                if t["id"] == tweet_id:
                    t = dict(t)
                    t["handle"] = acct["handle"]
                    return t
    return None


def selftest() -> None:
    # matching logic
    assert _match("Muse Spark 1.3", ["Arena leaderboard shows Muse Spark 1.3 topping vision"])
    assert not _match("Muse Spark 1.3", ["Totally unrelated chatter about gpt"])
    assert not _match("GPT", ["gpt is everywhere"])  # too generic
    assert _match("Qwen3.5-Max", ["qwen3.5max scores 88.2"])  # punctuation-insensitive
    print("cross_check selftest: all assertions passed")


def main() -> int:
    models.ensure_utf8_stdout()
    p = argparse.ArgumentParser()
    p.add_argument("--base-dir", required=False)
    p.add_argument("--run-id", required=False)
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()
    if args.selftest:
        selftest()
        return 0
    if not (args.base_dir and args.run_id):
        print("--base-dir and --run-id are required")
        return 2
    out = run(models.raw_dir(args.base_dir, args.run_id),
              models.load_run_report(args.base_dir, args.run_id))
    s = out["stats"]
    print(f"cross_check: launches={s['launches']} signals={s['signals']} "
          f"cross_verified={s['cross_verified']} release_verified={s['release_verified']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
