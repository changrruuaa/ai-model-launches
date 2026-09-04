"""plan_scan.py — run state machine: create run dir, shuffled account sequence, batch & resume.

Outputs ONE JSON line prefixed 'RUN>' (parse with json.loads(line[4:])) plus human lines.

Subcommands:
  --stage main|thirdparty --days N --base-dir DIR     new run (or new stage on existing run via --run-id)
  --resume [--base-dir DIR] [--run-id ID]             continue latest/existing run, print next batch
  --status [--base-dir DIR] [--run-id ID]             read-only progress report
Account states: pending -> in_progress (raw_<handle>.json exists) -> done (<handle>.json status=ok)
                                                         -> failed (attempts>=2, reason recorded)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import models, timewin, vendors  # noqa: E402


def _skeleton(run_id: str, days, since, until) -> dict:
    return {
        "run_id": run_id,
        "created_at": models.now_cst().isoformat(timespec="seconds"),
        "window": {"days": days, "since": since, "until": until},
        "accounts": {
            "main": [{**a, "status": "pending", "rounds": 0, "fetched": 0,
                      "in_window": 0, "attempts": 0, "notes": ""} for a in vendors.load("main")],
            "thirdparty": [{**a, "status": "pending", "rounds": 0, "fetched": 0,
                            "in_window": 0, "attempts": 0, "notes": ""} for a in vendors.load("thirdparty")],
        },
        "stages": {"prefilter": None, "detail": None, "classify": None, "verify": None,
                   "cross_check": None, "images": None, "local_report": None, "notion": None},
        "incidents": [],
        "database_id": None,
    }


def _next_batch(report: dict, stage: str, batch_size: int) -> list[dict]:
    retryable = ("pending", "in_progress", "failed")
    queue = [a for a in report["accounts"][stage]
             if a["status"] in retryable or (a["status"] == "failed" and a["attempts"] < 2)]
    return queue[:batch_size]


def _emit(report: dict, stage: str, batch: list[dict], extra: dict | None = None) -> None:
    acc = report["accounts"][stage]
    done = sum(1 for a in acc if a["status"] == "ok")
    failed = sum(1 for a in acc if a["status"] == "failed")
    other = report["accounts"]["thirdparty" if stage == "main" else "main"]
    payload = {
        "run_id": report["run_id"],
        "window": report["window"],
        "stage": stage,
        "batch": [a["handle"] for a in batch],
        "batch_companies": {a["handle"]: a["company"] for a in batch},
        "progress": {stage: f"{done}/{len(acc)} ok, {failed} failed"},
        "other_stage_done": sum(1 for a in other if a["status"] == "ok"),
        "stages": report["stages"],
        "ctx_hint": ("keep each scan session <= 3 accounts and <= 6 scroll rounds; "
                     "end session and --resume when budget hit"),
    }
    if extra:
        payload.update(extra)
    print("RUN>" + json.dumps(payload, ensure_ascii=False))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--stage", choices=["main", "thirdparty"], default="main")
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--since", default=None)
    p.add_argument("--until", default=None)
    p.add_argument("--base-dir", required=True)
    p.add_argument("--batch-size", type=int, default=3)
    p.add_argument("--run-id", default=None, help="existing run to resume/status")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--status", action="store_true")
    args = p.parse_args()

    base = Path(args.base_dir)

    # ---------- status ----------
    if args.status:
        run_id = args.run_id or models.latest_run_id(base)
        if not run_id:
            print("RUN>{\"error\": \"no run found\"}")
            return 1
        report = models.load_run_report(base, run_id)
        _emit(report, args.stage, [])
        return 0

    # ---------- resume ----------
    if args.resume:
        run_id = args.run_id or models.latest_run_id(base)
        if not run_id:
            print("RUN>{\"error\": \"no run found for resume\"}")
            return 1
        report = models.load_run_report(base, run_id)
        batch = _next_batch(report, args.stage, args.batch_size)
        if not batch:
            _emit(report, args.stage, [], {"note": "stage complete or all failed; nothing to scan"})
            return 0
        _emit(report, args.stage, batch)
        return 0

    # ---------- new run / new stage on existing run ----------
    days = args.days or 7
    since_dt, until_dt = timewin.window(days=days, since=args.since, until=args.until)
    run_id = args.run_id or models.new_run_id()
    rpath = models.run_report_path(base, run_id)
    if rpath.exists():  # new stage on existing run
        report = models.load_run_report(base, run_id)
    else:
        report = _skeleton(run_id, days, since_dt.isoformat(timespec="seconds"),
                           until_dt.isoformat(timespec="seconds"))
        rd = models.raw_dir(base, run_id)
        (rd / "logs").mkdir(parents=True, exist_ok=True)
        (rd / "images").mkdir(parents=True, exist_ok=True)
    models.save_run_report(base, run_id, report)
    batch = _next_batch(report, args.stage, args.batch_size)
    _emit(report, args.stage, batch, {"run_dir": str(models.raw_dir(base, run_id))})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
