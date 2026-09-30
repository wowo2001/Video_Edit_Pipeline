@echo off
setlocal
title Conference Pipeline
cd /d "%~dp0"

rem A double-clicked batch file does not inherit newly created User variables.
rem Read the required keys directly from the current Windows user profile.
for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('YOUTUBE_API_KEY', 'User')"`) do set "YOUTUBE_API_KEY=%%A"
for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('OPENAI_API_KEY', 'User')"`) do set "OPENAI_API_KEY=%%A"

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Cannot find .venv\Scripts\python.exe
    pause
    exit /b 1
)

echo Starting full conference workflow...
echo Task file: conference_tasks.json
echo.
".venv\Scripts\python.exe" -u conference.py

echo.
if errorlevel 1 (
    echo [FAILED] The workflow stopped. Review the error above.
) else (
    echo [DONE] All candidate videos have been produced and uploaded.
)
pause
