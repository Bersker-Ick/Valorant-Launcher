# 开发日志 / CHANGELOG

本文件按阶段记录改动、验证结果与对应 PR。详细命令与证据见 [`docs/DEVLOG.md`](docs/DEVLOG.md)。

## 阶段 0 — 仓库初始化

- 初始化仓库骨架、`.gitignore`、安全边界说明。
- 初始提交：`chore: initialize repository skeleton and safety boundaries`

## 阶段 1 — 凭据存储 + 输入层 + 诊断/自检（F1/F2/F7 基础）

- DPAPI（CurrentUser + entropy）加解密；`accounts.json` 仅保存 base64 密文。
- 原子写入、`.bak` 备份、损坏文件备份、版本只读保护。
- 日志统一脱敏（键值对 + traceback）；异常钩子不记录局部变量。
- 字符 → VK/Shift/扫描码映射；`?` 扩展键回归修复。
- `SendInput` 扫描码输入、鼠标点击、逐事件返回/GetLastError 诊断。
- 窗口/焦点/完整性/IME/BlockInput/DPI Win32 封装。
- 账号 CRUD、设置、诊断面板、记事本自检、日志面板。
- 核心单元测试通过（DPAPI/keymap/store/redact）。
- 前台锁导致命令行自检无法抢焦点；正确路径为从 GUI 点击自检。
- **用户要求停止桌面控制后，所有桌面注入/焦点测试立即停止；后续验收改为用户手动执行。**

## 阶段 2 — 目标窗口 + 登录流程（F3/F4/F5/F6/F8）

- 标题/类名/排除/进程正则；手动选窗；候选优先前台；SourceGit 误报防护。
- 纯 ctypes UI Automation 客户端：Edit/Button/Text 枚举、IsPassword、BoundingRectangle、ValuePattern。
- 校准遮罩（无全局 hook）：账号框 → 密码框 → 登录按钮；尺寸/位置变化校验。
- 登录编排：完整性检查、严格抢焦点、UIA/校准、BlockInput、IME、三击+快捷键清空、扫描码输入、账号长度校验。
- 盲填判定：凭据错误/验证码/窗口关闭/按钮禁用/标题变化/输入未送达/部分输入/不确定。
- 明确凭据错误/验证码不自动重试；不确定最多自动重试 1 次。
- 登录 Worker（QThread）、取消、结果对话框、目标状态卡、UIA 探测。
- 55 个单元测试通过；离屏 UI 冒烟通过。
- 未进行完整“真实前台输入”实测（按用户要求停止桌面控制）；需用户手动验收。

## 阶段 3 — 打包、文档、验收

- `requirements.txt`（仅 PySide6）、`build.bat`、`run_dev.bat`、`run_tests.bat`。
- `LoginAssistant.spec`：PyInstaller onefile/windowed；过滤未使用 Qt DLL/插件（46MB → 22MB）。
- 图标/版本信息；打包后离屏冒烟测试（SMOKE TEST OK，应用初始化 487ms）。
- 开发机离屏启动约 2.9s（首次）/ 2.3s（后续）。
- `README.md`（首次使用、原理、故障排查表、限制）、`ACCEPTANCE.md`（A1-A7 + F1-F8）、`docs/DEVLOG.md`。
- 运行期无网络库导入测试。

## PR

| 阶段 | 分支 | PR |
| --- | --- | --- |
| 1 | `stage-1-core-storage-input` | [#1](https://github.com/Bersker-Ick/Valorant-Launcher/pull/1) |
| 2 | `stage-2-login-flow` | [#2](https://github.com/Bersker-Ick/Valorant-Launcher/pull/2) |
| 3 | `stage-3-packaging-docs` | [#3](https://github.com/Bersker-Ick/Valorant-Launcher/pull/3) |

## 后续修复

- **PR #4**：记事本自检点击文本区改为三击，配合 Ctrl+A/Backspace/Delete 清空，降低
  “第一次全选未生效导致测试串追加到旧内容”的误判概率。仅改自检/字段清空路径，不改变目标登录器逻辑。

## 后续修复（PR #5）

用户实机反馈：目标「无畏契约登录器」(Chrome_WidgetWin_1，高完整性) 在点击账号框/输入账号后提示
“目标窗口失去前台焦点”，但用户没有操作前台。日志显示：

- 本工具与目标均为高完整性（排除 UIPI）；
- 第一次：账号框点击成功、输入 9 个字符后前台校验失败；
- 第二次：重新校准后，6 个鼠标事件（三击）后前台校验失败，未进入输入。

修复：

- 登录期间**自动最小化主窗口**，避免 Windows 前台锁把焦点还给本工具；结果对话框前恢复。
- 点击前用 `WindowFromPoint` 校验坐标根窗口必须是目标；否则明确报“校准坐标不在目标窗口上”，不点击。
- 用 UIA `ElementFromPoint` 只读检查坐标下控件类型；账号/密码点落在按钮/链接等控件时报错，登录点落在 Edit 时也报错。
- 点击/输入后若前台被抢，先 `ensure_foreground` 重新聚焦；失败时结果详情显示实际抢占窗口的标题/类名/PID，不再笼统说用户移动了前台。
- 校准模式下字段点击改为单击（UIA 模式保留三击），减少三击误触链接/按钮的风险。
- 新增 4 个单元测试（坐标根窗口校验、UIA 控件类型校验、前台 root 匹配、抢占错误信息）；共 **61 tests OK**。

> 真实前台注入未由代理执行（用户要求停止桌面控制）；此修复需用户用新 EXE 复测。
> 密码仍只用 `SendInput` 扫描码逐字符输入，不使用剪贴板。

## 后续修复（PR #6）— TASLogin64 子进程输入框

用户复测提示“校准坐标当前不在目标窗口上”，但坐标下确实是一个 `Edit`：

- 启动器进程：`D:\ACLOS\Launcher\无畏契约登录器.exe` (PID 35168, Chrome_WidgetWin_1)
- 实际账号框：`TASLogin64.exe` (PID 45592) 的 `Edit`，其父进程正是启动器
- 旧检查只接受根窗口 == 启动器 hwnd，误拒绝了合法的登录组件

修复：

- `is_descendant_process`：按 Toolhelp 进程树接受目标子进程（TASLogin64）里的控件。
- `foreground_matches`：点击 TASLogin64 的 Edit 后 `GetForegroundWindow()` 是该 Edit，
  不是启动器 hwnd；现在按“目标/同进程/后代进程”认可，不再误报前台丢失。
- 点击点校验按实际输入控件进程做完整性检查；目标父进程受保护（WinError 5）时不再直接阻断。
- `_verify_field_focus` 支持子进程原生 Edit 的焦点校验。
- 新增 2 个单元测试（子进程坐标接受、子进程前台匹配）；共 **63 tests OK**。

> 仍需用户在真实启动器上复测；密码仍用 SendInput 扫描码，不使用剪贴板。

## 后续修复（PR #7）— 密码框焦点 / 只读 / 注入拒绝诊断

用户反馈：账号输入和点击登录都可以，但密码框一直为空。

日志显示：

- 账号坐标落在 `TASLogin64.exe` 的 `Edit` hwnd=0x5411D8；
- 密码坐标落在同进程的另一个 `Edit` hwnd=0x90D52；
- UIA 未把密码框标记为 `IsPassword`；
- 工具发送了 10 个密码字符，但登录仍失败；旧代码只检查“前台属于 TASLogin64”，没有确认**具体密码 Edit**获得焦点。

修复：

- 点击后检查具体控件 `hwnd` 是否真正持有键盘焦点；未持有时调用 `focus_control`（AttachThreadInput + SetForegroundWindow + SetFocus）强制聚焦，失败则中止，不再盲目输入。
- 记录原生样式：`ES_PASSWORD` / `ES_READONLY` / `WS_EX_NOACTIVATE` / 禁用位；只读控件直接提示手动输入。
- 密码输入后再次确认密码控件仍持有焦点，并读取**账号框**长度，确认密码没有误输入到账号框。
- 校准模式也使用账号框原生 hwnd 读取长度，结果判定更可靠。
- 保持 63 tests OK；未新增依赖。

> 若日志显示焦点正确、密码框非只读，但账号长度不变且密码仍为空，则说明 TASLogin64 的安全密码控件拒绝了模拟输入。
> 按项目硬性边界，工具不会 hook/驱动/绕过；此时只能手动输入密码。不会使用剪贴板。

## 后续功能（PR #8）— UIA ValuePattern 密码写入（实验）

用户确认密码框有光标但拒绝 SendInput 后，增加一条纯软件替代路径：

- `IUIAutomationValuePattern` 封装：只读探测 `IsReadOnly`，可选 `SetValue` 写入。
- 诊断页新增 **“密码框 UIA 写入探测”**：只检查 ValuePattern 是否可用/是否只读，不读取、不写入密码值。
- 设置 → 输入新增 **“密码用 UIA ValuePattern 写入（实验，非键盘）”**，默认关闭。
- 开启后：账号仍用 SendInput；密码框点击/聚焦后，用 UIA 直接写入密码，再点击登录；失败明确报错，不会静默回退。
- 密码不写日志；写入后 `bytearray` 覆写；UIA 字符串无法完全控制生命周期，尽力而为。
- 新增配置 roundtrip 测试；共 **65 tests OK**。

> 这不是键盘模拟，可能被控件拒绝；也可能触及启动器/游戏的自动化条款，风险自负。
> 探测不支持/只读时，仍然只能手动输入密码。

## 后续修复（PR #9）— 账号长度误判导致密码阶段被跳过

用户反馈：UIA 探测可写，但登录仍失败，工具没有切换到密码框就结束了。

日志（02:24）显示：

- 账号框点击成功，输入 9 个字符；
- 随后直接 `input_not_delivered`，两次尝试都没有进入密码框，也没有出现 UIA ValuePattern 日志。

只读检查同一个账号 Edit（TASLogin64 `0x5A1238`）：`GetWindowTextLengthW=0`，`WM_GETTEXT` 返回空串，
但界面上账号文字确实存在。也就是说 TASLogin64 的 Edit **不响应跨进程 WM_GETTEXT**。

PR #7 新增的账号长度校验把空串当成 0，误判“账号没输入”，所以在密码阶段前中止。

修复：

- 新增 `_read_hwnd_account_length`：跨进程读取为空时返回 `None`（未知），不再当成 0。
- 账号长度未知时跳过长度校验，继续进入密码阶段；不再误报 `input_not_delivered`。
- `_snapshot` 与密码后账号框检查同样使用该 helper，避免后续再次误判。
- 新增空文本/正常文本单元测试；共 **66 tests OK**。

> 当前启动器窗口客户区已变成 1152x720，而校准仍为 1728x1080；复测前需重新校准，否则会提示 `calibration_stale`。
> 这次修复后，UIA 写入才会真正执行；如果仍失败，请发新的 `密码框 UIA ValuePattern` / `密码已通过 UIA...` 日志。
