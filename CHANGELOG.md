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
- 55 个单元测试通过；离屏 UI 冒烟通过。
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
- 57 个单元测试通过；离屏 UI 冒烟通过。
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
