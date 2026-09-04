"""finalize.py — unattended post-processing chain (no browser, no cua-driver).

classify --api -> cross_check -> grab_images -> write_local -> notion_sync (best effort).
Requires ANTHROPIC_API_KEY / `ant auth login` for the --api classification step.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _run(script: str, *args: str, check=True) -> int:
    cmd = [sys.executable, str(HERE / script), *args]
    print(f"$ {' '.join(cmd)}")
    r = subprocess.run(cmd)
    if check and r.returncode != 0:
        print(f"ERROR {script} exited {r.returncode}")
        raise SystemExit(r.returncode)
    return r.returncode


def main() -> int:
    models_ok = True
    p = argparse.ArgumentParser()
    p.add_argument("--base-dir", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--parent-id", default=None)
    p.add_argument("--database-id", default=None)
    p.add_argument("--no-notion", action="store_true")
    p.add_argument("--no-images", action="store_true")
    args = p.parse_args()

    common = ("--base-dir", args.base_dir, "--run-id", args.run_id)
    _run("classify.py", *common, "--api")
    _run("cross_check.py", *common)
    if not args.no_images:
        _run("grab_images.py", *common, check=False)  # best effort
    _run("write_local.py", *common)
    if not args.no_notion and args.parent_id:
        rc = _run("notion_sync.py", *common, "--parent-id", args.parent_id,
                  *(("--database-id", args.database_id) if args.database_id else ()),
                  check=False)  # Notion failure must not eat local report
        models_ok = rc == 0
    print(f"finalize done (notion_ok={models_ok})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
