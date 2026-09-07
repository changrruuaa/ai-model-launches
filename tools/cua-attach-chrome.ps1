#Requires -Version 5.1
# 手动启动带 grant + 免审批（unrestricted）的 cua-driver daemon 并 attach 已登录 Chrome
# 绕 hermes desktop floor（hermes 默认不传 --grant）
# 规范源码：本仓库 tools\cua-attach-chrome.ps1 → 部署到 hermes 机 %USERPROFILE%\cua-attach-chrome.ps1
# 实测机 exe 路径：C:\Users\SinoWhale\.cua-driver\packages\current\cua-driver.exe（2026-09-05）

# --- 1. 启 daemon（--grant 为进程级 flag，不经过 hermes config.yaml 检查；
#         --dangerously-bypass-approvals 自选 unrestricted 免审批，mode 随 daemon 进程固定）---
$exe = "$env:USERPROFILE\.cua-driver\packages\current\cua-driver.exe"
Start-Process -FilePath $exe `
    -ArgumentList "serve","--grant","existing-profile","--dangerously-bypass-approvals" `
    -WindowStyle Hidden
Start-Sleep -Seconds 4

# --- 2. 验证 daemon 已起来并带 grant + bypass flag
#         （按 CommandLine 匹配 flag 选进程，避免多实例时误抓 hermes 拉起的旧 daemon）---
$proc = Get-CimInstance Win32_Process -Filter "Name='cua-driver.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "dangerously-bypass-approvals" } |
    Sort-Object CreationDate -Descending | Select-Object -First 1
if (-not $proc) { Write-Error "Daemon 启动失败（无带 --dangerously-bypass-approvals 的 cua-driver 进程）"; exit 1 }
$cmd = $proc.CommandLine
if ($cmd -notmatch "grant.*existing-profile") {
    Write-Error "Daemon 启动但没带 --grant flag（CommandLine: $cmd）"
    exit 1
}
Write-Host "[+] daemon PID=$($proc.ProcessId) 已带 --grant existing-profile + --dangerously-bypass-approvals（免审批）" -ForegroundColor Green

# --- 3. 找已登录的 Chrome（必须有可见 MainWindowHandle；pid/hwnd 每次启动都变，勿缓存）---
$chrome = Get-Process chrome -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $chrome) { Write-Error "Chrome 未运行或没有可见窗口"; exit 1 }
$pidVal = $chrome.Id
$hwnd = $chrome.MainWindowHandle
Write-Host "[+] Chrome PID=$pidVal HWND=$hwnd TITLE=$($chrome.MainWindowTitle)" -ForegroundColor Cyan

# --- 4. Attach（python stdin 发 JSON，避开 PowerShell 转义坑；stderr 回显 + exit code + 期望标记三重检查）---
$pyScript = @"
import subprocess, json, sys
proc = subprocess.Popen(
    [r'$exe', 'call', 'browser_prepare'],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
)
out, err = proc.communicate(
    json.dumps({'pid': $pidVal, 'window_id': $hwnd, 'strategy': {'kind': 'existing_profile'}}).encode('utf-8'),
    timeout=15
)
sys.stderr.write(err.decode(errors='replace'))
print(out.decode())
if proc.returncode != 0:
    sys.exit(proc.returncode)
"@

Write-Host "[+] Attaching..." -ForegroundColor Cyan
$result = python -c $pyScript
$pyExit = $LASTEXITCODE
Write-Host $result
if ($pyExit -ne 0) {
    Write-Error "browser_prepare 调用失败（exit $pyExit，输出/错误见上）"
    exit 1
}
if (-not ($result -match "attached_existing_profile")) {
    Write-Error "attach 未成功：输出缺 attached_existing_profile（见上）"
    exit 1
}
Write-Host "[+] attach 成功" -ForegroundColor Green
