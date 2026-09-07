"""parse_account.py — normalize one agent-dumped raw_<handle>.json into <handle>.json.

Input schema (agent writes this compact JSON per account, UTF-8, incremental-dedup already applied):
{
  "handle": "OpenAI", "company": "OpenAI", "rounds": 2,
  "tweets": [
    {"status_id": "1956...", "text": "...",
     "time_raw": "Wed Sep 03 10:12:33 +0000 2026",          # X created_at (second precision), OR
     "time_display": "11h ago / 2026-09-04 03:32 UTC",      # fallback (minute precision)
     "engagement_raw": "81 replies, 328 reposts, ...",      # aria-label string, OR
     "engagement": "798/1754/14966/4084763",                # slash shorthand r/rt/likes/views
     "media": ["https://pbs.twimg.com/..."], "pinned": false}
  ]
}

🚨 web_search 三禁 enforcement: raw files containing web/搜索-derived keys (external_sources,
   web_search, sources, ...) are REJECTED (exit 2) — scan blockers must yield no-x-data, never
   web backfill (violation of run 20260904-142109, fixed 2026-09-04).

Output <handle>.json: normalized, deduped, window-filtered (schema per plan §5).
Also updates run_report.json. Exit 0 ok/empty; exit 2 validation error (agent fixes raw once);
exit 3 raw file missing.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import metrics_parse, models, timewin  # noqa: E402

REQUIRED_TWEET = ("status_id", "text")
FORBIDDEN_KEYS = ("external_sources", "external_refs", "web_search", "web_results",
                  "web_sources", "sources", "search_results")
FORBIDDEN_RE = re.compile(r"external_sources|web_search|search_results|web_results|web_sources", re.IGNORECASE)

# canonical key is "tweets"; tolerate the natural alias hermes agents used pre-schema (run 20260904-153150)
TWEETS_ALIASES = ("tweets", "tweets_in_scope_this_week")


def tweets_list(raw: dict) -> list | None:
    for k in TWEETS_ALIASES:
        if k in raw and isinstance(raw[k], list):
            return raw[k]
    return None


def validate(raw: dict) -> list[str]:
    errs = []
    if FORBIDDEN_RE.search(str(sorted(raw.keys()))):
        bad = [k for k in raw if k in FORBIDDEN_KEYS or FORBIDDEN_RE.search(k)]
        errs.append(f"web_search 三禁违规: raw 含 web/搜索来源字段 {bad} —— 扫描被阻断必须标 no-x-data，"
                    f"禁止 web 回填；本 raw 拒收")
    for key in ("handle", "company"):
        if key not in raw:
            errs.append(f"missing top-level key '{key}'")
    if "handle" in raw and "@" in str(raw["handle"]):
        errs.append(f"top-level handle '{raw['handle']}' 含 @ —— profile URL 格式约束要求 handle 无 @"
                    f"（带 @ 的 URL 会被 X 解释成搜索 fallback，2026-09-05 实测）；请改为无 @ 形式后重跑")
    tweets = tweets_list(raw)
    if tweets is None:
        errs.append(f"missing top-level key 'tweets' (aliases: {', '.join(TWEETS_ALIASES)})")
        return errs
    for i, t in enumerate(tweets):
        if not isinstance(t, dict):
            errs.append(f"tweets[{i}] must be an object")
            continue
        bad = [k for k in t if k in FORBIDDEN_KEYS or FORBIDDEN_RE.search(k)]
        if bad:
            errs.append(f"tweets[{i}] web_search 三禁违规: 含字段 {bad}")
        for key in REQUIRED_TWEET:
            if key not in t or t[key] in (None, ""):
                errs.append(f"tweets[{i}] missing/empty '{key}'")
        if "status_id" in t and not str(t["status_id"]).isdigit():
            errs.append(f"tweets[{i}].status_id must be numeric string")
        if "time_raw" not in t and "time_display" not in t:
            errs.append(f"tweets[{i}] needs 'time_raw' (X created_at) or 'time_display' (absolute UTC)")
    return errs


def _tweet_time(t: dict) -> tuple[object, str]:
    """Return (aware_datetime, precision) from time_raw or time_display."""
    if t.get("time_raw"):
        return timewin.parse_x_time(t["time_raw"]), "second"
    return timewin.parse_display_time(t["time_display"]), "minute"


def _tweet_metrics(t: dict) -> dict:
    if t.get("engagement_raw"):
        return metrics_parse.parse_engagement(t["engagement_raw"])
    return metrics_parse.parse_slash_engagement(t.get("engagement"))


def selftest() -> int:
    """Offline check: validation + normalization against bundled fixtures (no run dir touched)."""
    fx = models.SKILL_DIR / "tests" / "fixtures"

    # 1) bundled synthetic fixture: aria-label engagement + X created_at
    raw = models.read_json(fx / "raw_account_sample.json")
    errs = validate(raw)
    assert not errs, errs
    win = timewin.window(days=7, now=timewin.now_cst())
    seen = set()
    for t in raw["tweets"]:
        dt = timewin.parse_x_time(t["time_raw"])          # must not raise
        assert dt.tzinfo is not None
        assert str(t["status_id"]) not in seen
        seen.add(str(t["status_id"]))
        m = metrics_parse.parse_engagement(t.get("engagement_raw"))
        assert m["likes"] is not None
        _ = timewin.in_window(dt, win)
    print(f"parse_account selftest: fixture ok ({len(raw['tweets'])} tweets)")

    # 2) real fixture from hermes run 20260904-153150: display time + slash engagement -> must pass
    raw3 = models.read_json(fx / "raw_openai_run3_real.json")
    errs = validate(raw3)
    assert not errs, errs
    tweets3 = raw3["tweets_in_scope_this_week"]
    dt, precision = _tweet_time(tweets3[0])
    assert precision == "minute", precision
    assert dt == timewin.parse_display_time("2026-09-04 03:32 UTC")
    m = _tweet_metrics({"engagement": "798/1754/14966/4084763"})
    assert m["views"] == 4084763, m
    print("parse_account selftest: run3 real-format ok (display time + slash engagement)")

    # 3) real fixture from run 20260904-142109 (web_search backfill) -> must be REJECTED
    raw1 = models.read_json(fx / "raw_openai_run1_reject.json")
    errs = validate(raw1)
    assert errs, "web-backfill raw must be rejected"
    assert any("三禁" in e for e in errs), errs
    print("parse_account selftest: run1 web-backfill correctly rejected (三禁)")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--base-dir", required=False)
    p.add_argument("--run-id", required=False)
    p.add_argument("handle", nargs="?")
    p.add_argument("--mark-failed", default=None, metavar="REASON",
                   help="skip normalization, record failure reason in run_report")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()

    if args.selftest:
        raise SystemExit(selftest())
    if not (args.base_dir and args.run_id and args.handle):
        print("--base-dir, --run-id and handle are required")
        return 2

    stage = "main"
    report = models.load_run_report(args.base_dir, args.run_id)
    for s in ("main", "thirdparty"):
        if any(a["handle"].lower() == args.handle.lower() for a in report["accounts"][s]):
            stage = s
            break

    if args.mark_failed:
        acct = next(a for a in report["accounts"][stage]
                    if a["handle"].lower() == args.handle.lower())
        acct["status"] = "failed"
        acct["attempts"] += 1
        acct["notes"] = args.mark_failed
        models.append_incident(report, "account-failed", args.handle, args.mark_failed)
        models.save_run_report(args.base_dir, args.run_id, report)
        print(f"@{args.handle} failed ({args.mark_failed}); attempts={acct['attempts']}")
        return 0

    raw_path = models.raw_dir(args.base_dir, args.run_id) / f"raw_{args.handle}.json"
    if not raw_path.exists():
        print(f"ERROR raw file missing: {raw_path}")
        return 3

    raw = models.read_json(raw_path)
    errs = validate(raw)
    if errs:
        print("PARSE-ERRORS>")
        for e in errs[:10]:
            print(f"  - {e}")
        print("fix raw_<handle>.json once and rerun; after 2nd failure use --mark-failed parse-failed")
        return 2

    win = timewin.window(days=report["window"].get("days"),
                         since=report["window"].get("since"),
                         until=report["window"].get("until"))

    seen: set[str] = set()
    tweets, in_window_count = [], 0
    for t in tweets_list(raw) or []:
        sid = str(t["status_id"])
        if sid in seen:
            continue
        seen.add(sid)
        dt, precision = _tweet_time(t)
        text = t.get("text", "")
        tweet = {
            "id": sid,
            "text": text,
            "created_at": dt.isoformat(timespec="seconds"),
            "time_precision": precision,
            "url": f"https://x.com/{raw['handle']}/status/{sid}",
            "is_pinned": bool(t.get("pinned", False)),
            "is_retweet": text.startswith("RT @"),
            "is_reply": text.startswith("@"),
            "is_third_party": stage == "thirdparty",
            "metrics": _tweet_metrics(t),
            "media": list(t.get("media") or []),
            "external_links": [],
            "source": "cua-snapshot",
        }
        # URLs in text -> external_links (strip trailing punctuation)
        tweet["external_links"] = [u.rstrip(").,;\"'!?")
                                   for u in re.findall(r"https?://\S+", text.replace("\n", " "))]
        if timewin.in_window(dt, win):
            tweets.append(tweet)
            in_window_count += 1

    out = {
        "handle": raw["handle"],
        "company": raw.get("company", raw["handle"]),
        "scanned_at": models.now_cst().isoformat(timespec="seconds"),
        "status": "ok" if (tweets_list(raw) or []) else "empty",
        "rounds": int(raw.get("rounds", 1)),
        "fetched": len(seen),
        "in_window": in_window_count,
        "tweets": tweets,
    }
    models.write_json(models.raw_dir(args.base_dir, args.run_id) / f"{args.handle}.json", out)

    models.update_account(report, stage, args.handle, status=out["status"],
                          rounds=out["rounds"], fetched=out["fetched"],
                          in_window=out["in_window"], attempts=1, notes="")
    models.save_run_report(args.base_dir, args.run_id, report)

    pinned = sum(1 for t in tweets if t["is_pinned"])
    print(f"@{args.handle} {out['status']} rounds={out['rounds']} "
          f"fetched={out['fetched']} in_window={out['in_window']} pinned={pinned}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
