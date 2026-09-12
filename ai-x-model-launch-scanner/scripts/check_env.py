"""check_env.py — Step 0 的 12 项自动检查。exit 0 = 就绪;exit 12 = 有致命缺失(fatal 非空)。

缺失项的探测/安装命令一律见 references/environment-setup.md §2(默认用户环境全空原则)。
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import models  # noqa: E402

SKILL_SCRIPTS = Path(__file__).resolve().parent
SETUP_DOC = "references/environment-setup.md"


def _probe(cmd: list[str], cwd: Path | None = None) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30, cwd=str(cwd) if cwd else None)
        return r.returncode == 0, (r.stdout or r.stderr).strip().split("\n")[0][:120]
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)[:120]


def _load_user_config() -> dict:
    cfg = SKILL_SCRIPTS.parent / "config.user.yaml"
    if cfg.is_file():
        try:
            import yaml
            return yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
    return {}


def main() -> int:
    models.ensure_utf8_stdout()
    checks: list[dict] = []

    def add(idx: int, name: str, ok: bool, detail: str, fatal: bool) -> None:
        checks.append({"id": idx, "name": name, "ok": bool(ok), "fatal": fatal,
                       "detail": detail, "setup": f"{SETUP_DOC}#2-依赖总表" if not ok else None})

    # ① py 核心依赖(致命)
    missing_core, missing_opt = [], []
    for mod, pip_name in (("yaml", "pyyaml"), ("jinja2", "jinja2"), ("requests", "requests"),
                          ("dateutil", "python-dateutil")):
        try:
            importlib.import_module(mod)
        except ImportError:
            missing_core.append(pip_name)
    # zoneinfo:Windows 无系统 IANA 库,python.org/Store 发行版必须 pip tzdata
    # (Anaconda 自带 share/zoneinfo 可免);models/timewin 在 import 期构造 ZoneInfo,缺它全部脚本崩溃
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        ZoneInfo("Asia/Shanghai")
    except (ZoneInfoNotFoundError, OSError):
        missing_core.append("tzdata")
    add(1, "py-core-deps", not missing_core,
        "ok" if not missing_core else f"缺 {missing_core};install: python -m pip install {' '.join(missing_core)}",
        fatal=True)

    # ② notion-client / anthropic(警告,静默降级)
    for mod, pip_name in (("notion_client", "notion-client"), ("anthropic", "anthropic")):
        try:
            importlib.import_module(mod)
            missing_opt.append((pip_name, False))
        except ImportError:
            missing_opt.append((pip_name, True))
    opt_missing = [n for n, miss in missing_opt if miss]
    add(2, "py-optional-deps", not opt_missing,
        "ok" if not opt_missing else f"缺 {opt_missing}(Notion/--api 分类降级);python -m pip install {' '.join(opt_missing)}",
        fatal=False)

    # ③ node ≥18(致命)
    ok, detail = _probe(["node", "--version"])
    ver = detail.lstrip("v").split(".")[0] if ok else "0"
    add(3, "node", ok and ver.isdigit() and int(ver) >= 18, detail or "node 未安装", fatal=True)

    # ④ puppeteer-core(致命)
    ok, detail = _probe(["node", "-e", "console.log(require.resolve('puppeteer-core'))"], cwd=SKILL_SCRIPTS)
    add(4, "puppeteer-core", ok, detail if ok else "未安装;install: cd scripts && npm install", fatal=True)

    # ⑤ chrome.exe(致命)
    chrome = None
    for c in ("C:/Program Files/Google/Chrome/Application/chrome.exe",
              "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
              os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google/Chrome/Application/chrome.exe")):
        if os.path.isfile(c):
            chrome = c
            break
    add(5, "chrome", chrome is not None, chrome or "chrome.exe 未找到;winget install Google.Chrome", fatal=True)

    # ⑥ 日常 profile Cookies(警告)
    daily_cookie = Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/User Data/Default/Network/Cookies"
    add(6, "daily-profile-cookies", daily_cookie.is_file(),
        str(daily_cookie) if daily_cookie.is_file() else "日常 Chrome 无 cookie 数据(Chrome 从未登录过任何站点?)", fatal=False)

    # ⑦ shadow cookie 新鲜度 <7 天(警告)
    shadow_cookie = Path(os.environ.get("LOCALAPPDATA", "")) / "xscan-shadow/Default/Network/Cookies"
    if shadow_cookie.is_file():
        age = (datetime.now().timestamp() - shadow_cookie.stat().st_mtime) / 86400
        add(7, "shadow-cookie-fresh", age < 7, f"shadow cookie {age:.1f} 天前复制", fatal=False)
    else:
        add(7, "shadow-cookie-fresh", False, "shadow 不存在(Step 2 sync_cookies.py 会建立)", fatal=False)

    # ⑧ ffmpeg/ffprobe(警告:视频步降级)
    ok_f, d_f = _probe(["ffmpeg", "-version"])
    ok_p, d_p = _probe(["ffprobe", "-version"])
    add(8, "ffmpeg", ok_f and ok_p, "ok" if (ok_f and ok_p) else "缺失;winget install Gyan.FFmpeg", fatal=False)

    # ⑨ edge-tts(警告:无旁白降级)
    ok, detail = _probe(["edge-tts", "--list-voices"])
    add(9, "edge-tts", ok, "ok" if ok else "缺失(无旁白降级);python -m pip install edge-tts", fatal=False)

    # ⑩ BGM 文件(警告;按 config.user.yaml audio.bgm_path)
    cfg = _load_user_config()
    bgm = ((cfg.get("audio") or {}).get("bgm_path")) if cfg else None
    if not bgm:
        add(10, "bgm", True, "未配置(无 BGM,跳过)", fatal=False)
    elif Path(bgm).is_file():
        add(10, "bgm", True, bgm, fatal=False)
    else:
        add(10, "bgm", False, f"配置的 BGM 不存在: {bgm}", fatal=False)

    # ⑪ Pillow(警告:卡片 fallback)
    try:
        importlib.import_module("PIL")
        add(11, "pillow", True, "ok", fatal=False)
    except ImportError:
        add(11, "pillow", False, "缺失(卡片 fallback 不可用);python -m pip install pillow", fatal=False)

    # ⑫ API token 探测(警告)
    tokens = {"ANTHROPIC_API_KEY": bool(os.environ.get("ANTHROPIC_API_KEY")),
              "NOTION_TOKEN": bool(os.environ.get("NOTION_TOKEN"))}
    absent = [k for k, v in tokens.items() if not v]
    add(12, "api-tokens", not absent,
        "ok" if not absent else f"未设 {absent}(对应功能静默降级;setx 后重启 Hermes desktop)", fatal=False)

    fatal_missing = [c for c in checks if c["fatal"] and not c["ok"]]
    print(json.dumps({
        "python": sys.version.split()[0],
        "checks": checks,
        "fatal_missing": [c["name"] for c in fatal_missing],
        "hint": "缺失项处置见 references/environment-setup.md(默认环境全空原则,逐项探测→安装)",
    }, ensure_ascii=False))
    return 12 if fatal_missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
