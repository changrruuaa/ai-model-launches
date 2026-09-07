# chrome-inspector — Chrome 实例巡检（hermes 测试机通用）

`chrome_inspect.py` 一次性枚举本机所有 chrome.exe 进程，区分主进程/子进程，从主进程命令行解析 CDP 调试端口、user-data-dir、profile、headless 标记并探活，输出结构化 JSON。**只读诊断**：不杀进程、不拉浏览器、不输出原始命令行全文。无常驻进程，单次调用 <1s，纯 Python 标准库。

## 为什么需要它

- 任务管理器 / PowerShell 进程列表**看不到** Chrome 各实例的 CDP 调试端口与 profile 归属——只看进程名，多个 chrome.exe 无法区分
- Chrome 内置任务管理器（Shift+Esc）**不显示端口**，且其窗口在进程/窗口枚举中与普通 Chrome 无差别，agent 无法识别——这条路彻底不可用
- 用户日常 Chrome 正常启动**没有调试端口**（属预期）；残留的无头 Chrome 实例则会误导 agent

## 🚫 hermes 使用硬规则（各 skill 引用，违反 = 本 run 无效）

1. **禁止**打开 Chrome 内置任务管理器查进程/端口（不显示端口且窗口无法识别）
2. **禁止** fallback 启动无头 Chrome 获取用户 cookie/登录态（headless 必无用户登录态）
3. 巡检 exit 0 → 按 `summary.cdp_ready` 选用实例；exit 1/2 → **立即 STOP**，把 `summary.action_hint` 原样报告用户，**不自行拉起/重启浏览器**

## 调用

```bat
python "%USERPROFILE%\.hermes\tools\chrome_inspect.py"
python "%USERPROFILE%\.hermes\tools\chrome_inspect.py" --pretty
```

（PowerShell 终端把 `%USERPROFILE%` 换成 `$env:USERPROFILE`。）

## 输出 schema

| 字段 | 说明 |
|---|---|
| `chrome_processes_total` | chrome.exe 进程总数（含子进程） |
| `instances[]` | 识别出的主进程实例（每实例一个对象） |
| `instances[].pid` / `.exe` | 进程 ID / 可执行文件路径（exe 可区分 Stable/Beta/Canary 渠道） |
| `instances[].port` | CDP 端口：命令行 `--remote-debugging-port`，探活失败时回落 `DevToolsActivePort` 文件 |
| `instances[].cdp_alive` | `GET /json/version` 探活结果 |
| `instances[].chrome_version` | 探活所得版本（如 `136.0.7103.113`） |
| `instances[].headless` | 命令行含 `--headless`（含 `=new`/`=old` 变体） |
| `instances[].user_data_dir` / `.profile_directory` / `.is_default_user_data_dir` | profile 归属信息（is_default：未传 `--user-data-dir` 或传的即该渠道默认目录，均算默认；按 exe 渠道区分 Stable/Beta/Dev/Canary） |
| `instances[].devtools_active_port` | `<user-data-dir>\DevToolsActivePort` 文件首行端口 |
| `instances[].targets` | `/json/list` 返回的 target 数 |
| `instances[].warnings` | 异常与版本限制提示（如 Chrome ≥136 默认 profile 忽略调试端口参数） |
| `child_process_count` | 子进程数（renderer/gpu/utility 等，不逐一列出） |
| `summary.cdp_ready` | 第一个 `cdp_alive` 且非 headless 的实例对象；无则 `null` |
| `summary.headless_instances` | headless 实例的 `{pid, port}` 列表 |
| `summary.action_hint` | 给 hermes 的动作提示（STOP 时原样转述给用户） |

## 退出码

| 码 | 含义 | hermes 动作 |
|---|---|---|
| 0 | 存在 CDP 就绪且非 headless 的实例 | 继续正常流程 |
| 1 | 有 Chrome 但无可用非 headless CDP 端口（日常 Chrome 默认无端口属预期） | 🛑 STOP + 报告 `action_hint` |
| 2 | 无 chrome.exe 运行 | 🛑 STOP + 请用户先打开 Chrome |
| 3 | 脚本内部错误（PowerShell 失败/参数解析错误等；`--help` 与未知 flag 也归 3，避免冒充 0/2 契约语义） | 报告 stderr 内容；跳过巡检继续主流程（不重试，不改机器） |

## 部署

本仓库 `tools\chrome-inspector\` 为规范源码；部署到 hermes 测试机（home `C:\Users\SinoWhale\.hermes`）：

```bat
copy chrome_inspect.py "%USERPROFILE%\.hermes\tools\chrome_inspect.py"
copy README.md "%USERPROFILE%\.hermes\tools\chrome_inspect_README.md"
```

（与 skill 相同的"本机规范源码 → 手动部署"流程；`tools` 目录不存在则先创建。）

## 局限声明

- 脚本**拿不到 cookie 内容**——用户登录态只能来自 cua attach 用户日常 Chrome 的主路径（或用户手动提供）
- 用户日常 Chrome 正常启动无调试端口时 exit 1 **属预期**，不是故障；此时按硬规则 STOP 交用户处理
- Chrome ≥136 起对默认 user-data-dir 忽略 `--remote-debugging-port`（官方安全限制），"带端口重启日常 Chrome"不是有效补救；脚本会以 warnings 标注该情形

## 附录：为什么不是"扩展 + 本地 cookie 桥"（缓建设计）

曾设计 MV3 扩展（`chrome.cookies` 读白名单域）+ 常驻 Native Messaging Host（本机端口暴露 cookie），因安装与维护成本缓建，**触发条件：出现需要直读 cookie 内容（而非 attach 驱动浏览器）的真实任务**。届时安装路线已实查定稿（2026-09，置信度 high）：

- 默认：chrome://extensions 开发者模式手动 Load unpacked（Chrome 152 仍完全可用，一次性 ~2 分钟）
- 真·自安装：Chrome Web Store 上架 unlisted（开发者账号 $5 一次性 + 审核）+ 注册表 `ExtensionInstallForcelist` 策略（静默、用户不可禁用、浏览器显示"由组织管理"）
- 已死路线勿试：`--load-extension`（Chrome 137 起 branded 版移除）、CDP `Extensions.loadUnpacked`（仅会话级，重启失效）、本地 CRX 注册表 path（Chrome 33 起移除）、自托管 update_url 强装（Windows 需域加入 / Chrome Enterprise Core）
