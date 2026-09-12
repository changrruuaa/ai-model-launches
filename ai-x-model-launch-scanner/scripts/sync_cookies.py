"""sync_cookies.py — Step 2: build/reuse the shadow Chrome profile that reuses local cookies.

Why shadow: Chrome >=136 ignores --remote-debugging-port on the DEFAULT user-data-dir,
so CDP can never attach the daily profile. We copy the cookie assets (Default\\Network\\Cookies
+ Local State) into a dedicated shadow profile and launch THAT with a debug port via
puppeteer. App-bound encryption (Chrome 127+): the key lives in Local State and is
decrypted by real Chrome on the same machine/user — so a same-user copy stays decryptable.

--check : probe only (locate daily profile, lock state, shadow freshness). No copy.
--force : copy even if shadow cookies look fresh (mtime unchanged normally reuses).

Exit 0 ok/copied/reused; 4 daily Chrome is running AND no usable shadow exists;
5 daily profile not found; 6 shadow Cookies is locked by a running shadow Chrome
  (close the shadow window, or reuse as-is; --force needs the window closed first).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import models  # noqa: E402

DEFAULT_SHADOW = Path(os.environ.get("LOCALAPPDATA", "")) / "xscan-shadow"
COPY_SPECS = [  # (relative dir under profile, filename) — must copy Local State together with Cookies
    ("Default\\Network", "Cookies"),
    ("Default\\Network", "Cookies-journal"),
    ("", "Local State"),
]
FRESH_DAYS = 7


def _daily_dir(override: str | None) -> Path | None:
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA", "")
    return Path(local) / "Google" / "Chrome" / "User Data" if local else None


def _cookies_mtime(prof: Path) -> float | None:
    c = prof / "Default" / "Network" / "Cookies"
    return c.stat().st_mtime if c.is_file() else None


def _locked(daily: Path) -> bool:
    """Chrome holds an exclusive lock on the Cookies DB while running."""
    c = daily / "Default" / "Network" / "Cookies"
    if not c.is_file():
        return False
    try:
        with open(c, "r+b"):
            return False
    except PermissionError:
        return True
    except OSError:
        return True


def main() -> int:
    models.ensure_utf8_stdout()
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true", help="probe only, no copy")
    p.add_argument("--force", action="store_true", help="copy even if shadow looks fresh")
    p.add_argument("--shadow", default=str(DEFAULT_SHADOW))
    p.add_argument("--daily", default=None, help="override daily 'User Data' dir")
    args = p.parse_args()

    daily = _daily_dir(args.daily)
    shadow = Path(args.shadow)
    out = {"daily": str(daily) if daily else None, "shadow": str(shadow)}

    if not daily or not (daily / "Local State").is_file():
        out.update(status="daily-profile-missing",
                   hint="未找到日常 Chrome profile(Local State 缺失)——确认 Chrome 已安装且至少启动过一次")
        print(json.dumps(out, ensure_ascii=False))
        return 5

    out["daily_locked"] = _locked(daily)
    shadow_mtime = _cookies_mtime(shadow)
    out["shadow_exists"] = shadow_mtime is not None
    if shadow_mtime:
        age_days = (time.time() - shadow_mtime) / 86400
        out["shadow_age_days"] = round(age_days, 2)

    if args.check:
        out["status"] = "ok" if (shadow_mtime and not out["daily_locked"]) else \
                        "reusable" if shadow_mtime else "needs-copy"
        print(json.dumps(out, ensure_ascii=False))
        return 0

    # decide: reuse fresh shadow when daily is locked or unchanged
    if shadow_mtime and out["daily_locked"] and not args.force:
        out.update(status="reused",
                   hint="Chrome 运行中,复用既有 shadow cookie(cookie 时效见 shadow_age_days)")
        print(json.dumps(out, ensure_ascii=False))
        return 0
    if shadow_mtime and not out["daily_locked"]:
        src_m = _cookies_mtime(daily)
        if src_m and abs(src_m - shadow_mtime) < 2 and not args.force:
            out.update(status="reused", hint="shadow 与日常 profile cookie 一致")
            print(json.dumps(out, ensure_ascii=False))
            return 0

    if out["daily_locked"] and not shadow_mtime:
        out.update(status="blocked",
                   hint="Chrome 正在运行(Cookies 被锁)且无既有 shadow——关闭 Chrome 后重试,或先跑一次让 shadow 建立")
        print(json.dumps(out, ensure_ascii=False))
        return 4

    # copy (shadow dir layout: <shadow>/Default/Network/Cookies + <shadow>/Local State)
    if _locked(shadow):
        out.update(status="shadow-locked",
                   hint="shadow Chrome 正在运行占用 Cookies——非强制重拷可直接复用现有 shadow;"
                        "需重拷(--force/登录墙处置)请先关闭 shadow Chrome 窗口后重跑")
        print(json.dumps(out, ensure_ascii=False))
        return 6
    (shadow / "Default" / "Network").mkdir(parents=True, exist_ok=True)
    copied = []
    try:
        for rel, name in COPY_SPECS:
            src = daily / rel / name
            if not src.is_file():
                continue
            dst = shadow / rel / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(name)
    except PermissionError:
        out.update(status="shadow-locked",
                   hint="复制被拒(Cookies 被运行中的 Chrome 独占)——关闭占用锁的 Chrome 窗口"
                        "(daily 或 shadow)后重跑")
        print(json.dumps(out, ensure_ascii=False))
        return 6
    out.update(status="copied", copied=copied,
               hint="cookie 资产已复制到 shadow(app-bound 同机自解密,Local State 已同拷)")
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
