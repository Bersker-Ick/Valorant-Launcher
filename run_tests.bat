@echo off
setlocal
cd /d "%~dp0"
set "PY=py -3.13"
%PY% --version >nul 2>&1
if errorlevel 1 set "PY=python"
%PY% -m unittest discover -s tests -v
if /i "%~1"=="--pause" pause
exit /b %ERRORLEVEL%
