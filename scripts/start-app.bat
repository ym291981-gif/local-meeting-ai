@echo off
cd /d "%~dp0"
title Meeting Minutes

set "PY=%~dp0..\backend\.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [ERROR] backend\.venv was not found.
    echo Run the README setup steps first.
    pause
    exit /b 1
)

"%PY%" "%~dp0start_app.py" %*
if errorlevel 1 pause
