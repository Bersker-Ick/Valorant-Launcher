# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec：onefile + windowed，裁掉未使用的 Qt DLL/插件。

为什么需要 spec：PySide6 的 PyInstaller hook 会把整个 PySide6 目录下的
Qt DLL 都收进来，即使 CLI 写了 --exclude-module。opengl32sw.dll（约 20MB）
以及 QtQuick/Qml/Pdf/Network 等会让 onefile 解压变慢。这里在 Analysis 之后
按文件名过滤，只保留 QtCore/QtGui/QtWidgets 及 Windows/Offscreen 平台插件。
"""

from PyInstaller.utils.hooks import collect_submodules  # noqa: F401

EXCLUDES = [
    "tkinter",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick",
    "PySide6.QtQml",
    "PySide6.QtQuickWidgets",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtUiTools",
    "PySide6.QtNetwork",
    "PySide6.QtNetworkAuth",
    "PySide6.QtWebSockets",
    "PySide6.QtWebChannel",
    "PySide6.QtHttpServer",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtSpatialAudio",
    "PySide6.QtTextToSpeech",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtStateMachine",
    "PySide6.QtHelp",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtPrintSupport",
    "PySide6.QtDBus",
    "PySide6.QtConcurrent",
    "PySide6.QtXml",
]

DROP_DLLS = {
    "opengl32sw.dll",
    "qt6quick.dll",
    "qt6qml.dll",
    "qt6qmlmodels.dll",
    "qt6qmlworkerscript.dll",
    "qt6quickwidgets.dll",
    "qt6pdf.dll",
    "qt6pdfwidgets.dll",
    "qt6network.dll",
    "qt6networkauth.dll",
    "qt6opengl.dll",
    "qt6openglwidgets.dll",
    "qt6virtualkeyboard.dll",
    "qt6svg.dll",
    "qt6svgwidgets.dll",
    "qt6printsupport.dll",
    "qt6dbus.dll",
    "qt6concurrent.dll",
    "qt6xml.dll",
    "qt6test.dll",
    "qt6sql.dll",
    "qt6websockets.dll",
    "qt6webchannel.dll",
    "qt6webenginecore.dll",
    "qt6webenginewidgets.dll",
    "qt6webenginequick.dll",
    "qt6positioning.dll",
    "qt6location.dll",
    "qt6sensors.dll",
    "qt6serialport.dll",
    "qt6bluetooth.dll",
    "qt6nfc.dll",
    "qt6multimedia.dll",
    "qt6multimediawidgets.dll",
    "qt6spatialaudio.dll",
    "qt6texttospeech.dll",
    "qt6charts.dll",
    "qt6datavisualization.dll",
    "qt6graphs.dll",
    "qt6remoteobjects.dll",
    "qt6scxml.dll",
    "qt6statemachine.dll",
    "qt6help.dll",
    "qt6designer.dll",
    "qt6uitools.dll",
    "qt6labsanimation.dll",
    "qt6labsfolderlistmodel.dll",
    "qt6labsqmlmodels.dll",
    "qt6labssettings.dll",
    "qt6labssharedimage.dll",
    "qt6labstemplates.dll",
    "qt6labswavefrontmesh.dll",
    "qt6shadertools.dll",
    "qt6httpserver.dll",
    "qt6oauth1.dll",
    "qt6oauth2.dll",
    "qt6opcua.dll",
    "qt6automation.dll",
    "qt6winextras.dll",
    "qt6axbase.dll",
    "qt6axcontainer.dll",
    "qt6axserver.dll",
    "libcrypto-3.dll",
    "libssl-3.dll",
}


def keep_binary(dest: str) -> bool:
    normalized = dest.replace("/", "\\").lower()
    base = normalized.rsplit("\\", 1)[-1]
    if base in DROP_DLLS:
        return False
    if normalized.startswith("pyside6\\translations\\"):
        return False
    if normalized.startswith("pyside6\\plugins\\"):
        if normalized.startswith("pyside6\\plugins\\platforms\\"):
            return base in {"qwindows.dll", "qoffscreen.dll"}
        # 不使用图片格式/主题/样式/TLS/输入法插件；QIcon 由 QPixmap 生成。
        return False
    return True


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)

a.binaries = [item for item in a.binaries if keep_binary(item[0])]
a.datas = [
    item
    for item in a.datas
    if not item[0].replace("/", "\\").lower().startswith("pyside6\\translations\\")
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LoginAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/app.ico",
    version="build_support/version_info.txt",
)
