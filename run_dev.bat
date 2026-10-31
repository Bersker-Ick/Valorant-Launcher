@echo off
setlocal
cd /d "%~dp0"
set "PY=py -3.13"
%PY% --version >nul 2>&1
if errorlevel 1 set "PY=python"
%PY% -m login_assistant
