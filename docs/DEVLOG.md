# 开发日志 / DEVLOG

本文件记录每个阶段的实现范围、验证命令/结果、踩坑与已知问题。面向开发/验收，不包含任何密码或真实账号。

- 仓库：`https://github.com/Bersker-Ick/Valorant-Launcher`
- 版本：0.1.0
- 日期：2026-11-01
- 环境：Windows 11 `10.0.26300` x64，Python 3.13.0，PySide6 6.12.0，PyInstaller 6.22.3
- 桌面：2560×1440 @ 150% 缩放；本工具进程完整性 = 中 (Medium)
- 约束：运行期不联网；仅使用公开 Win32/UIA API

> **重要记录（桌面操作）**：开发过程中曾尝试用自动化方式对本地 mock 窗口做输入自检。用户在 2026-11-01 明确要求“别控制我电脑”后，**立即停止**了所有 `desktop_control`、焦点切换、`SendInput` 注入和可见窗口操作，并终止了本地 mock 测试进程。此后不再代替用户操作桌面；记事本自检、实机登录和最终验收均由用户按 `README.md` / `ACCEPTANCE.md` 手动执行。

---

## 阶段 0 — 仓库初始化

- `.gitignore`、README 骨架、本日志骨架。
- 初始提交：`chore: initialize repository skeleton and safety boundaries`
- 远程仓库为空仓库；配置本地 `http.proxy`/`https.proxy` 为空（系统代理对 GitHub TLS 不稳定，直连正常）。

---

## 阶段 1 — F2 凭据存储 + 输入层 + F7 诊断 + F1 账号管理

### 实现

| 模块 | 内容 |
| --- | --- |
| `security/dpapi.py` | `CryptProtectData`/`CryptUnprotectData`，CurrentUser，`CRYPTPROTECT_UI_FORBIDDEN`，专用 entropy，LocalFree |
| `security/redact.py` | `RedactingFormatter` + `RedactingFilter`；`password=`/`密码：` 等键值对脱敏；traceback 也经过 formatter |
| `security/secret.py` | `bytearray` 覆写（尽力而为） |
| `core/store.py` | `accounts.json` 原子写入、覆盖前 `.bak`、损坏备份、版本只读保护、base64 密文校验 |
| `core/keymap.py` | `VkKeyScanExW`/`MapVirtualKeyExW` → (VK, Shift, scan)；`?` 的扩展键回归；ASCII 白名单 |
| `core/input.py` | `SendInput` + `KEYEVENTF_SCANCODE`；逐事件返回/GetLastError；40–80ms 抖动；Shift down/tap/up；鼠标点击；诊断环形缓冲 |
| `core/winapi.py` | 窗口枚举、标题/类名/PID/EXE、完整性级别、焦点校验、IME、BlockInput、DPI、WM_GETTEXT（仅自检/账号长度） |
| `core/selftest.py` | 记事本自检：启动新窗口、点击文本区、清空、输入、回读比对 |
| `ui/*` | 账号 CRUD、设置、诊断、日志面板、主题 |
| `tests/*` | DPAPI、keymap、store、redact、windowmatch、verify、automation helpers |

### 关键实现选择

- DPAPI 附加 entropy：`LoginAssistant:v1:dpapi:7c1f2a9e`；密文 base64 落盘。
- 账号列表密码列固定 8 个圆点，不泄露真实长度。
- 日志只记录 record id / 目标窗口 / 事件计数；从不记录账号密码。
- 输入使用**目标线程键盘布局**（`GetKeyboardLayout`），而不是盲目 US 布局。
- `?` 的扫描码是主键盘 `/`（0x35），与数字键盘 `/` 共用；扩展键必须按 VK 判断，否则 `?` 会打错。已修复并加回归测试。
- BlockInput 在工作线程内调用，`try/finally` 恢复；线程退出时 Windows 也会解除。

### 验证

```text
py -3.13 -m unittest discover -s tests -v
→ 55 tests OK（阶段 1 结束时的数量）
```

- DPAPI 往返：ASCII/UTF-8/长串/篡改失败/错误 entropy 失败。
- 落盘文件扫描：无测试密码明文。
- keymap：A-Z/a-z/0-9/常见符号的 VK、Shift、扫描码逐项断言；`?` 非扩展键。
- 日志脱敏：`logger.info("password=%s", secret)` 与 traceback 均被替换；修复了“filter 改 msg 导致 %s 参数不匹配”的 logging 报错。
- QT offscreen：`QT_QPA_PLATFORM=offscreen py -3.13 -m login_assistant --smoke-test` → `SMOKE TEST OK`。
- 离屏截图：`py -3.13 tools\ui_snapshot.py .tmp_ui.png`，人工检查布局。

### 踩坑

1. **前台锁**：从后台命令行启动记事本并调用 `SetForegroundWindow` 会失败（`AttachThreadInput` 成功但前台不变）。这是 Windows 前台锁，不是输入层故障。正确路径是从本工具界面点击自检按钮（本工具是前台进程）。
2. **PySide6 安装**：系统 HTTP 代理对 GitHub/PyPI 大文件不稳定；改用清华镜像 + 强制 IPv4 `sitecustomize` 完成安装。运行期无网络依赖。
3. **UIA 属性错位**：不同 SDK 的 `IUIAutomationElement` vtable 在 20 号之后可能不同，按序号调用 `get_CurrentIsPassword`/`IsOffscreen`/`BoundingRectangle` 会读错。改为 `GetCurrentPropertyValue(propertyId)` + VARIANT/SAFEARRAY 解析。
4. **BoundingRectangle 是 [left, top, width, height]**，不是 RECT 的 right/bottom；最初解析导致所有矩形为空。
5. **mock 输入实测**：一次对前台 mock 的注入把 `test` 写入了账号框（说明字母扫描码链路有效），但当时的 UIA `ValuePattern` 读取返回 0，被误判为“输入未送达”，工具跳过提交并重试。已增加：
   - 输入后 0.7 s 内多次重读；
   - 对非密码 Win32 Edit 使用 `WM_GETTEXT` 读取长度（不读取密码框）；
   - 三击 + Ctrl+A + Backspace + Delete 清空；
   - 修饰键同时填充 `wVk`。
   这些修复**未再**进行桌面注入验证（按用户要求停止）。

---

## 阶段 2 — F3/F4/F5/F6/F8 + 完整登录流程

### 实现

| 模块 | 内容 |
| --- | --- |
| `core/windowmatch.py` | 标题/类名/排除/进程正则；`require_both`；手动目标签名；候选优先前台 |
| `core/uia.py` | 纯 ctypes COM：`CoCreateInstance`、`ElementFromHandle`、`CreatePropertyCondition`、`FindAll`、ValuePattern、BoundingRectangle、文本枚举 |
| `core/automation.py` | 目标校验 → 完整性 → 焦点 → UIA/校准 → BlockInput/IME → 输入 → 提交 → 快照 → 判定 → 最多 1 次重试 |
| `core/verify.py` | 盲填判定：窗口关闭/最小化/凭据错误/验证码/成功文本/通用错误/按钮禁用/标题变化/输入未送达/部分输入/不确定 |
| `ui/manual_target_dialog.py` | 可见顶层窗口列表（标题/类名/PID/进程/完整性），手动选窗 |
| `ui/calibration.py` | 无 hook 的全屏半透明遮罩，捕获 3 个 Win32 物理坐标，校验客户区/尺寸/位置 |
| `ui/login_worker.py` | 所有 UIA/SendInput/BlockInput 在 QThread 内执行 |
| `ui/main_window.py` | 目标状态卡、刷新/选窗/校准/清除手动、登录/取消、结果对话框 |
| `ui/diagnostics.py` | 目标信息、UIA 探测、事件表、自检、调试开关 |

### 设计要点

- 默认匹配规则要求标题+类名同时命中，且默认不包含 Avalonia；避免把标题为 `Valorant-Launcher` 的 SourceGit 误判为登录器（有单元测试）。
- 完整性：目标 RID > 自身 RID → 直接提示“请以管理员身份运行本工具”，不尝试静默失败；`OpenProcess` 拒绝访问（WinError 5）也按可能更高权限处理。
- 焦点：AttachThreadInput → SetForegroundWindow → 循环校验 `GetForegroundWindow()`；目标已在前台时直接成功。
- 定位：
  - UIA Edit 按 IsPassword/名称/相对位置分类；按钮按名称 + 密码框下方选择；没有把握时宁可不点（回退 Enter 或校准）。
  - 校准坐标相对客户区、物理像素；窗口尺寸/位置变化 → 拒绝使用。
- 点击字段后校验：
  - 前台仍是目标；
  - UIA 元素的原生 HWND 与 `GetGUIThreadInfo` 焦点一致（Win32）；CEF/自绘控件退回“焦点在目标窗口内”；
  - 账号框长度异常时在提交前中止，避免把密码输到账号框。
- 输入前 `ImmAssociateContext(hwnd, None)`，`finally` 恢复。
- 输入账号/密码后检查账号框长度；密码框内容从不读取。
- 判定顺序：窗口关闭/最小化 → 明确凭据错误/验证码/成功/通用错误 → 按钮禁用 → 标题变化 → 账号长度 → 不确定。
- 明确凭据错误/验证码：**不自动重试**（风控优先）；不确定/输入未送达：最多自动重试 1 次。
- 报告 `ok_likely` 只用于图标/语气，文案始终要求手动确认。

### 验证

```text
py -3.13 -m unittest discover -s tests -v
→ 57 tests OK（含 no-network / automation helpers）
```

- `verify.py` 判定用例覆盖：window_closed、minimized、credential_error、challenge_required、success_text、login_error、progress_button_disabled、input_not_delivered、partial_input、title_changed、uncertain、input_rejected_suspected。
- UIA 只读探测（离屏、无输入）在本地 mock 上验证：
  - `find_all(Edit)` 返回 2 个 Edit，`IsPassword` 第二个为 True；
  - BoundingRectangle 中心计算正确；
  - ValuePattern 读取非密码账号框；密码框返回 None；
  - Button 名称/矩形/启用状态可读。
- 校准计划用真实客户区矩形验证坐标换算。
- 最小化目标 `run_login` → `window_minimized`，0 次事件、0 次密码解密调用（安全短路）。
- QT offscreen 主界面/诊断面板截图检查：
  - 目标未找到状态、按钮禁用、提示文案；
  - 诊断页目标信息/自检/事件表布局。

### 未完成 / 风险

- **未进行完整的“真实前台窗口 → 输入 → 提交 → 结果判定”实测**（用户要求停止桌面控制）。UIA/判定/错误路径已用离屏/只读/最小化场景验证；完整链路需用户按 `ACCEPTANCE.md` 手动执行。
- 账号框长度读取依赖 UIA ValuePattern 或 Win32 `WM_GETTEXT`；对 CEF/自绘控件可能不可用，此时判定退化为“无变化→重试 1 次→手动”。
- 三击/快捷键清空在极少数自绘控件上可能无效；重试可能追加字符。已在 README 标注。
- `SendInput` 的 `LLKHF_INJECTED` 无法规避；目标若检查该标志，工具只能提示“可能拒绝了模拟输入”。
- 非 ASCII / 键盘布局不匹配仍是无解限制（按需求）。

---

## 阶段 3 — 打包、文档、验收

### 实现

- `requirements.txt`：仅 `PySide6`；PyInstaller 仅构建期。
- `build.bat`：依赖检查（已安装则跳过网络）→ 57 个测试 → `LoginAssistant.spec`（onefile/windowed + Qt DLL/插件过滤）→ offscreen 冒烟测试。
- `LoginAssistant.spec`：在 Analysis 后按文件名过滤 `opengl32sw.dll`、QtQuick/Qml/Pdf/Network/OpenGL/Svg、翻译、图片格式/样式/TLS 插件等，仅保留 QtCore/QtGui/QtWidgets、qwindows/qoffscreen 平台插件与 Python 运行库。
- `assets/app.ico` / `assets/app.png`：QPainter 生成的多尺寸图标。
- `build_support/version_info.txt`：产品名/版本/说明。
- `README.md`、`ACCEPTANCE.md`、本日志。
- `main.py`：PyInstaller 入口（避免包内相对导入问题）。
- 运行期无网络库导入测试。

### 打包踩坑

- 最初用 CLI `--version-file build_support/version_info.txt` + `--specpath build`，relative 路径被按 `build/` 解析导致 `FileNotFoundError`；改用 `LoginAssistant.spec` 后不再有该问题。
- PySide6 的 hook 默认把整个 PySide6 目录的 Qt DLL 都收进来（包括 20MB 的 `opengl32sw.dll`、QtQuick/Qml/Pdf/Network），即使 CLI 写了 `--exclude-module`。改用 spec 过滤后：46MB → **22MB**，onefile 解压/启动明显变快。
- 过滤后必须保留 `qwindows.dll`（正常窗口）和 `qoffscreen.dll`（打包冒烟测试）；已保留。
- 过滤掉翻译/图片格式/样式插件；应用设置 Fusion 风格，QIcon 由 QPixmap 生成，不依赖图片格式插件。

### 验证

```text
py -3.13 -m unittest discover -s tests -v
→ 57 tests OK

py -3.13 -m PyInstaller --noconfirm --clean --distpath dist --workpath build LoginAssistant.spec
→ Build complete; dist\LoginAssistant.exe = 22MB

QT_QPA_PLATFORM=offscreen dist\LoginAssistant.exe --smoke-test
→ SMOKE TEST OK
→ 应用初始化耗时 487 ms

离屏计时（总耗时 - 0.9s 冒烟等待）：
  run1 2921 ms
  run2 2337 ms
  run3 2232 ms
```

- 首次运行（含 onefile 解压/杀软扫描）约 2.9 秒；后续约 2.3 秒。均不含真实桌面窗口显示，最终以用户秒表为准。
- `build.bat` 全流程（测试 → 打包 → 冒烟）返回 0；EXE 大小 46MB（旧 CLI 构建）/ 22MB（新 spec 构建）。

---

## PR 记录

| 阶段 | 分支 | PR |
| --- | --- | --- |
| 0 | `main` | 初始骨架 |
| 1 | `stage-1-core-storage-input` | [#1](https://github.com/Bersker-Ick/Valorant-Launcher/pull/1) |
| 2 | `stage-2-login-flow` | [#2](https://github.com/Bersker-Ick/Valorant-Launcher/pull/2) |
| 3 | `stage-3-packaging-docs` | [#3](https://github.com/Bersker-Ick/Valorant-Launcher/pull/3) |

> PR 使用堆叠分支（stage-2 基于 stage-1，stage-3 基于 stage-2），便于逐阶段审查；合并顺序 1 → 2 → 3。

---

## 复现命令

```bat
:: 测试
py -3.13 -m unittest discover -s tests -v

:: 离屏 UI 冒烟（不显示窗口）
set QT_QPA_PLATFORM=offscreen
py -3.13 -m login_assistant --smoke-test

:: 离屏截图
py -3.13 tools\ui_snapshot.py .tmp_ui.png

:: 打包
build.bat

:: 打包后冒烟
set QT_QPA_PLATFORM=offscreen
dist\LoginAssistant.exe --smoke-test
```

> 涉及真实窗口/输入的命令（`tools\selftest_input.py`、`tools\mock_login.py`、实际登录）必须由用户在自己的桌面上执行。
