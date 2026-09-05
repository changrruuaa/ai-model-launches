"""chrome_inspect.py — Chrome 实例巡检（hermes 测试机通用诊断工具）。

枚举所有 chrome.exe 进程，区分主进程/子进程；从主进程命令行提取 CDP 调试端口、
user-data-dir、profile、headless 标记，并对端口做 CDP 探活，输出单个 JSON。

只读诊断：不做任何修复/终止动作；输出只含解析后的开关字段，不输出原始命令行全文。

用法：
    python chrome_inspect.py [--pretty]

退出码：0 = 存在 CDP 探活成功且非 headless 的实例；1 = 有 Chrome 但无可用
CDP 端口；2 = 无 chrome.exe 运行；3 = 脚本内部错误（stderr 写原因）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request

PS_QUERY = (
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
    "Select-Object ProcessId,ExecutablePath,CommandLine | "
    "ConvertTo-Json -Compress"
)

HINT_NO_BROWSER = "没有运行中的 chrome.exe → 立即 STOP 报告用户，请其先打开 Chrome；禁止自行拉起浏览器"
HINT_NO_PORT = (
    "有 chrome.exe 运行但无可用的非 headless CDP 端口（用户日常 Chrome 默认无调试端口，属预期）"
    "→ 立即 STOP 并把本 JSON 报告用户；禁止启动无头 Chrome"
)
HINT_NO_MAIN = "发现 chrome.exe 进程但无可识别的主进程实例 → 立即 STOP 并报告用户；禁止启动无头 Chrome"
HINT_READY = "attach 该实例；禁止启动无头 Chrome"


def query_processes() -> list[dict]:
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", PS_QUERY],
        capture_output=True, timeout=30,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()[:500]
        raise RuntimeError(f"PowerShell 调用失败 rc={proc.returncode}: {stderr}")
    out = proc.stdout.decode("utf-8", "replace").strip()
    if not out:
        return []
    data = json.loads(out)
    if isinstance(data, dict):  # PowerShell 5.1 对单元素不输出数组
        data = [data]
    return data


def split_commandline(s: str) -> list[str]:
    """按 Windows CommandLineToArgvW 语义切分（引号分组、反斜杠转义、空引号产出空参数、空格/Tab 分隔）。"""
    args: list[str] = []
    cur: list[str] = []
    in_q = False
    had_q = False
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            j = i
            while j < n and s[j] == "\\":
                j += 1
            bs = j - i
            if j < n and s[j] == '"':
                cur.append("\\" * (bs // 2))
                if bs % 2:
                    cur.append('"')
                    i = j + 1
                    continue
                i = j
                continue
            cur.append("\\" * bs)
            i = j
            continue
        if c == '"':
            in_q = not in_q
            had_q = True
        elif c in (" ", "\t") and not in_q:
            if cur or had_q:
                args.append("".join(cur))
                cur, had_q = [], False
        else:
            cur.append(c)
        i += 1
    if cur or had_q:
        args.append("".join(cur))
    return args


def switch_value(args: list[str], name: str) -> str | None:
    """取 --name=value（裸 --name 的下一参数作兜底，但下一参数本身是开关时不误吞）。"""
    prefix = "--" + name + "="
    bare = "--" + name
    for idx, a in enumerate(args):
        low = a.lower()
        if low.startswith(prefix):
            return a[len(prefix):]
        if low == bare and idx + 1 < len(args) and not args[idx + 1].lower().startswith("--"):
            return args[idx + 1]
    return None


def has_switch(args: list[str], name: str) -> bool:
    bare = "--" + name
    return any(a.lower() == bare or a.lower().startswith(bare + "=") for a in args)


def http_get_json(url: str, timeout: float = 2.0) -> dict:
    # 显式绕过系统代理：回环地址不该走代理（hermes 机器可能配置了全局代理）
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def probe_cdp(port: int, timeout: float = 2.0) -> tuple[bool, str | None, int | None, str | None]:
    """探活 CDP（IPv4/IPv6 回环都试）：返回 (alive, chrome_version, targets, host)。"""
    for host in ("127.0.0.1", "[::1]"):
        try:
            ver = http_get_json(f"http://{host}:{port}/json/version", timeout)
        except Exception:
            continue
        # 校验 CDP 特征：dict 且带 Browser 字段——端口被普通 JSON 服务占用时不误判为 Chrome
        if not isinstance(ver, dict) or not ver.get("Browser"):
            continue
        browser = str(ver["Browser"])
        version = browser.split("/", 1)[1] if "/" in browser else (browser or None)
        targets: int | None = None
        try:
            targets = len(http_get_json(f"http://{host}:{port}/json/list", timeout))
        except Exception:
            pass
        return True, version, targets, host
    return False, None, None, None


def read_devtools_active_port(user_data_dir: str | None) -> int | None:
    if not user_data_dir:
        return None
    try:
        path = os.path.join(user_data_dir, "DevToolsActivePort")
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            first = f.readline().strip()
        return int(first) if first.isdigit() else None
    except OSError:
        return None


def version_major(version: str | None) -> int:
    if not version:
        return 0
    try:
        return int(version.split(".")[0])
    except ValueError:
        return 0


def default_udd_for(exe: str | None) -> str:
    """按 exe 渠道推默认 user-data-dir（Stable/Beta/Dev/Canary 的目录名不同）。"""
    channel = "Chrome"
    if exe:
        cand = os.path.basename(os.path.dirname(os.path.dirname(os.path.normpath(exe))))
        if cand:
            channel = cand
    return os.path.normcase(os.path.normpath(os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Google", channel, "User Data")))


def inspect_instance(proc: dict) -> dict:
    args = split_commandline(proc.get("CommandLine") or "")
    port_raw = switch_value(args, "remote-debugging-port")
    port = int(port_raw) if port_raw and port_raw.isdigit() else None
    pipe = has_switch(args, "remote-debugging-pipe")
    udd = switch_value(args, "user-data-dir")
    # 不带 --user-data-dir 的 Chrome 本来就在默认目录
    is_default = not udd or os.path.normcase(os.path.normpath(udd)) == default_udd_for(proc.get("ExecutablePath"))
    devtools_port = read_devtools_active_port(udd)

    warnings: list[str] = []
    if pipe:
        warnings.append("--remote-debugging-pipe：CDP 走管道，无 HTTP 端口可探活")

    cdp_alive, chrome_version, targets = False, None, None
    effective_port = None
    candidates = [p for p in (port, devtools_port) if p]
    for cand in candidates:
        alive, ver, tgt, host = probe_cdp(cand)
        if alive:
            cdp_alive, chrome_version, targets = True, ver, tgt
            effective_port = cand
            if host == "[::1]":
                warnings.append("CDP 仅 IPv6 回环 [::1] 可达（IPv4 端口被其它进程占用或未绑定）")
            if port and cand != port:
                warnings.append(
                    f"CDP 实际端口 {cand}（DevToolsActivePort），与命令行 --remote-debugging-port={port} 不符"
                )
            break
    if not cdp_alive:
        if pipe:
            pass
        elif port == 0:
            warnings.append("--remote-debugging-port=0（随机端口，无法枚举；且 Chrome ≥136 对默认 user-data-dir 会整体忽略该开关）")
        elif not port:
            warnings.append("无 --remote-debugging-port（用户日常 Chrome 默认无调试端口，属预期）")
        elif is_default:
            warnings.append(f"--remote-debugging-port={port} 探活失败；Chrome ≥136 起对默认 user-data-dir 忽略该开关（常见根因，官方安全限制）")
        else:
            warnings.append(f"--remote-debugging-port={port} 探活失败")

    if is_default and version_major(chrome_version) >= 136:
        warnings.append("chrome>=136 对默认 user-data-dir 忽略 --remote-debugging-port")

    return {
        "pid": proc.get("ProcessId"),
        "exe": proc.get("ExecutablePath"),
        "port": effective_port,
        "cdp_alive": cdp_alive,
        "chrome_version": chrome_version,
        "headless": has_switch(args, "headless"),
        "user_data_dir": udd,
        "profile_directory": switch_value(args, "profile-directory"),
        "is_default_user_data_dir": is_default,
        "devtools_active_port": devtools_port,
        "targets": targets,
        "warnings": warnings,
    }


def build_output(procs: list[dict], pretty: bool) -> tuple[int, str]:
    instances: list[dict] = []
    child_count = 0
    for p in procs:
        cl = p.get("CommandLine")
        if not cl or any(a.lower().startswith("--type=") for a in split_commandline(cl)[1:]):
            child_count += 1
            continue
        instances.append(inspect_instance(p))

    ready = next((i for i in instances if i["cdp_alive"] and not i["headless"]), None)
    headless_list = [{"pid": i["pid"], "port": i["port"]} for i in instances if i["headless"]]

    if ready:
        hint = f"CDP 就绪：pid={ready['pid']} port={ready['port']}（headless=false）→ {HINT_READY}"
        code = 0
    elif instances:
        hint = HINT_NO_PORT
        code = 1
    else:
        hint = HINT_NO_MAIN
        code = 1
    if headless_list:
        hint += f"；另发现 headless 实例 {headless_list}（提示用户自行关闭，勿用于需要登录态的任务）"

    out = {
        "chrome_processes_total": len(procs),
        "instances": instances,
        "child_process_count": child_count,
        "summary": {"cdp_ready": ready, "headless_instances": headless_list, "action_hint": hint},
    }
    return code, json.dumps(out, ensure_ascii=False, indent=2 if pretty else None)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Chrome 实例巡检（CDP 端口/profile/headless，只读）")
    ap.add_argument("--pretty", action="store_true", help="缩进 JSON，便于人工阅读")
    try:
        ns = ap.parse_args()
    except SystemExit:
        # argparse 默认退出码（--help=0、错误=2）会冒充 0/2 契约语义 → 一律归 3
        print("参数错误：契约调用为 `python chrome_inspect.py [--pretty]`", file=sys.stderr)
        return 3

    if os.name != "nt":
        print("chrome_inspect.py 仅支持 Windows", file=sys.stderr)
        return 3

    try:
        procs = query_processes()
    except Exception as exc:
        print(f"内部错误：{exc}", file=sys.stderr)
        return 3

    if not procs:
        out = {
            "chrome_processes_total": 0, "instances": [], "child_process_count": 0,
            "summary": {"cdp_ready": None, "headless_instances": [], "action_hint": HINT_NO_BROWSER},
        }
        print(json.dumps(out, ensure_ascii=False, indent=2 if ns.pretty else None))
        return 2

    try:
        code, payload = build_output(procs, ns.pretty)
    except Exception as exc:
        print(f"内部错误：{exc}", file=sys.stderr)
        return 3
    print(payload)
    return code


if __name__ == "__main__":
    sys.exit(main())
