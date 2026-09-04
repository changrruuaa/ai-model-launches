"""write_local.py — Step 7: render the Markdown report (local JSON already on disk in run dir)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import models  # noqa: E402


def _next_report_path(base: Path, date_str: str) -> Path:
    reports = base / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    first = reports / f"{date_str}-model-launches.md"
    if not first.exists():
        return first
    n = 2
    while (reports / f"{date_str}-model-launches-{n}.md").exists():
        n += 1
    return reports / f"{date_str}-model-launches-{n}.md"


def render(base_dir: Path, run_id: str, report: dict, cc: dict) -> tuple[str, str]:
    from jinja2 import Template
    tpl = (models.SKILL_DIR / "templates" / "report.md.j2").read_text(encoding="utf-8")

    launches = sorted(cc["launches"], key=lambda x: -x["confidence"])
    by_company: dict[str, list] = {}
    for l in launches:
        by_company.setdefault(l.get("company") or "未知", []).append(l)
    health = report["accounts"]["main"] + report["accounts"]["thirdparty"]
    failed = [f"@{a['handle']}" for a in health if a["status"] not in ("ok", "pending")]
    img_dir = models.raw_dir(base_dir, run_id) / "images"
    images = sorted(p.name for p in img_dir.iterdir()) if img_dir.exists() else []

    html = Template(tpl).render(
        date=run_id[:10],
        window=report["window"],
        n_accounts=len(report["accounts"]["main"]) + len(report["accounts"]["thirdparty"]),
        n_fetched=sum(a["fetched"] for a in health),
        n_in_window=sum(a["in_window"] for a in health),
        n_launches=len(launches),
        n_signals=len(cc["signals"]),
        launches=launches,
        by_company=by_company,
        signals=cc["signals"],
        health=health,
        failed_accounts=failed,
        images=images,
        generated_at=models.now_cst().isoformat(timespec="seconds"),
        run_id=run_id,
    )
    dest = _next_report_path(base_dir, run_id[:10])
    dest.write_text(html, encoding="utf-8", newline="\n")
    return str(dest), html


def main() -> int:
    models.ensure_utf8_stdout()
    p = argparse.ArgumentParser()
    p.add_argument("--base-dir", required=False)
    p.add_argument("--run-id", required=False)
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()

    if args.selftest:
        mock = models.SKILL_DIR / "tests" / "fixtures" / "mock_run"
        report = models.read_json(mock / "run_report.json")
        cc = models.read_json(mock / "cross_checked.json")
        out, _ = render(mock, "MOCKRUN", report, cc)
        print(f"selftest report written: {out}")
        return 0
    if not (args.base_dir and args.run_id):
        print("--base-dir and --run-id are required")
        return 2

    base = Path(args.base_dir)
    report = models.load_run_report(base, args.run_id)
    cc = models.read_json(models.raw_dir(base, args.run_id) / "cross_checked.json")
    dest, _ = render(base, args.run_id, report, cc)
    report["stages"]["local_report"] = dest
    models.save_run_report(base, args.run_id, report)
    print(f"report: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
