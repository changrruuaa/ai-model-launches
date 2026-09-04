"""Shared IO / run-state helpers. Dict-based, JSON on disk, UTF-8 no BOM (Windows GBK-safe)."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CST = ZoneInfo("Asia/Shanghai")

SKILL_DIR = Path(__file__).resolve().parent.parent.parent  # scripts/lib -> skill root


def ensure_utf8_stdout() -> None:
    """Windows console defaults to GBK; force UTF-8 so Chinese output never explodes."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def now_cst() -> datetime:
    return datetime.now(CST)


def new_run_id() -> str:
    """Filesystem-safe run id, e.g. 2026-09-04T1545+0800"""
    return now_cst().strftime("%Y-%m-%dT%H%M%z")


def read_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def raw_dir(base_dir: str | Path, run_id: str) -> Path:
    return Path(base_dir) / "data" / "raw" / run_id


def run_report_path(base_dir: str | Path, run_id: str) -> Path:
    return raw_dir(base_dir, run_id) / "run_report.json"


def load_run_report(base_dir: str | Path, run_id: str) -> dict:
    return read_json(run_report_path(base_dir, run_id))


def save_run_report(base_dir: str | Path, run_id: str, report: dict) -> None:
    write_json(run_report_path(base_dir, run_id), report)


def latest_run_id(base_dir: str | Path) -> str | None:
    root = Path(base_dir) / "data" / "raw"
    if not root.exists():
        return None
    runs = sorted((p for p in root.iterdir() if p.is_dir()), reverse=True)
    for p in runs:
        if (p / "run_report.json").exists():
            return p.name
    return None


def update_account(report: dict, stage: str, handle: str, **fields) -> None:
    for acct in report.get("accounts", {}).get(stage, []):
        if acct["handle"].lower() == handle.lower():
            acct.update(fields)
            return
    raise KeyError(f"account @{handle} not found in stage '{stage}'")


def append_incident(report: dict, itype: str, account: str, detail: str = "") -> None:
    report.setdefault("incidents", []).append({
        "type": itype,
        "account": account,
        "at": now_cst().isoformat(timespec="seconds"),
        "detail": detail,
    })
