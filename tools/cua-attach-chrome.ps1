#Requires -Version 5.1
# 手动启动带 grant 的 cua-driver daemon 并 attach 已登录 Chrome
# 绕 hermes desktop floor（hermes 默认不传 --grant）
# 规范源码：本仓库 tools\cua-attach-chrome.ps1 → 部署到 hermes 机 %USERPROFILE%\cua-attach-chrome.ps1
# 实测机 exe 路径：C:\Users\SinoWhale\.cua-driver\packages\current\cua-driver.exe（2026-09-05）

# --- 1. 启 daemon（--grant 为进程级 flag，不经过 hermes config.yaml 检查）---
$exe = "$env:USERPROFILE\.cua-driver\packages\current\cua-driver.exe"
Start-Process -FilePath $exe `
    -ArgumentList "serve","--grant","existing-profile","--permission-mode","standard" `
    -WindowStyle Hidden
Start-Sleep -Seconds 4

# --- 2. 验证 daemon 已起来并带 grant flag ---
$driver = Get-Process cua-driver -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $driver) { Write-Error "Daemon 启动失败"; exit 1 }
$cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($driver.Id)").CommandLine
if ($cmd -notmatch "grant.*existing-profile") {
    Write-Error "Daemon 启动但没带 --grant flag（CommandLine: $cmd）"
    exit 1
}
Write-Host "[+] daemon PID=$($driver.Id) 已带 --grant existing-profile" -ForegroundColor Green

# --- 3. 找已登录的 Chrome（必须有可见 MainWindowHandle；pid/hwnd 每次启动都变，勿缓存）---
$chrome = Get-Process chrome -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $chrome) { Write-Error "Chrome 未运行或没有可见窗口"; exit 1 }
$pidVal = $chrome.Id
$hwnd = $chrome.MainWindowHandle
Write-Host "[+] Chrome PID=$pidVal HWND=$hwnd TITLE=$($chrome.MainWindowTitle)" -ForegroundColor Cyan

# --- 4. Attach（python stdin 发 JSON，避开 PowerShell 转义坑）---
$pyScript = @"
import subprocess, json
proc = subprocess.Popen(
    [r'$exe', 'call', 'browser_prepare'],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
)
out, _ = proc.communicate(
    json.dumps({'pid': $pidVal, 'window_id': $hwnd, 'strategy': {'kind': 'existing_profile'}}).encode('utf-8'),
    timeout=15
)
print(out.decode())
"@

Write-Host "[+] Attaching..." -ForegroundColor Cyan
$result = python -c $pyScript
Write-Host $result
# 预期输出含："action": "attached_existing_profile"
