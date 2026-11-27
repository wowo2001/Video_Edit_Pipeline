@echo off
setlocal
title Main Source Selection
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Cannot find .venv\Scripts\python.exe
    pause
    exit /b 1
)
echo Configure the entire drama batch. No production or uploads will run.
".venv\Scripts\python.exe" -u main.py --configure-only --edit-preprocess %*
if errorlevel 1 echo [FAILED] Review the error above.
pause
