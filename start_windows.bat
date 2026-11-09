@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m livechat_guard
) else (
    echo .venv was not found. See README.md to install requirements.
    pause
)
