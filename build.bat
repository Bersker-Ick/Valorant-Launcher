@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PY=py -3.13"
%PY% --version >nul 2>&1
if errorlevel 1 set "PY=python"
%PY% --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.11+ not found. Install Python and retry.
    exit /b 1
)

echo [1/5] Check runtime + build dependencies...
%PY% -c "import PySide6, PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo     missing PySide6/PyInstaller, installing...
    %PY% -m pip install --disable-pip-version-check --no-input -r requirements.txt pyinstaller
    if errorlevel 1 (
        echo [ERROR] pip install failed.
        exit /b 1
    )
) else (
    echo     PySide6/PyInstaller already installed.
)

echo [2/5] Run unit tests...
%PY% -m unittest discover -s tests -v
if errorlevel 1 (
    echo [ERROR] Tests failed; build aborted.
    exit /b 1
)

echo [3/5] Clean previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [4/5] Build onefile windowed EXE...
%PY% -m PyInstaller --noconfirm --clean --distpath dist --workpath build LoginAssistant.spec
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed.
    exit /b 1
)

if not exist dist\LoginAssistant.exe (
    echo [ERROR] dist\LoginAssistant.exe not found.
    exit /b 1
)

echo [5/5] Smoke-test the packaged EXE (offscreen)...
set "SMOKE_HOME=%TEMP%\LoginAssistant-smoke-%RANDOM%"
set "QT_QPA_PLATFORM=offscreen"
set "LOGIN_ASSISTANT_HOME=%SMOKE_HOME%"
dist\LoginAssistant.exe --smoke-test
set "SMOKE_RC=%ERRORLEVEL%"
set "QT_QPA_PLATFORM="
set "LOGIN_ASSISTANT_HOME="
if not "%SMOKE_RC%"=="0" (
    echo [ERROR] Packaged EXE smoke test failed with code %SMOKE_RC%.
    exit /b 1
)
if exist "%SMOKE_HOME%" rmdir /s /q "%SMOKE_HOME%" 2>nul

echo.
echo BUILD OK: %CD%\dist\LoginAssistant.exe
for %%F in (dist\LoginAssistant.exe) do echo Size: %%~zF bytes
echo.
echo You can now run dist\LoginAssistant.exe (no console window).
if /i "%~1"=="--pause" pause
exit /b 0
