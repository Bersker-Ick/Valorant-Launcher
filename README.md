# 登录助手 (Login Assistant)

本地 Windows 桌面小工具：安全保存账号密码，并把凭据自动输入到**已经运行**的游戏官方登录器窗口。

> 本仓库正在按阶段开发中，完整文档见后续提交。

## 安全边界

- 不注入、不 hook、不调试、不读写任何其他进程的内存
- 不修改/绕过反作弊，不伪造设备指纹，不做驱动
- 不联网、不上传、无遥测
- 不实现硬件 HID 或规避输入检测的手段
- 不修改游戏文件

## 技术栈

- Python 3.11+ / PySide6
- Windows DPAPI (`CryptProtectData`, CurrentUser)
- Win32 `SendInput` (scan code) + UI Automation
- PyInstaller `--onefile --windowed`
