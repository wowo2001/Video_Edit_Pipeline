@echo off
setlocal

rem Read API keys from Windows user environment variables.  The keys are never
rem stored in this file, which keeps it safe to leave in the project folder.
for /f "usebackq delims=" %%K in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('YOUTUBE_API_KEY', 'User')"`) do set "YOUTUBE_API_KEY=%%K"
for /f "usebackq delims=" %%K in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('OPENAI_API_KEY', 'User')"`) do set "OPENAI_API_KEY=%%K"

if not defined YOUTUBE_API_KEY (
    echo ERROR: User environment variable YOUTUBE_API_KEY is not set.
    pause
    exit /b 1
)

if not defined OPENAI_API_KEY (
    echo ERROR: User environment variable OPENAI_API_KEY is not set.
    pause
    exit /b 1
)

set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

rem The Streamlit page embeds the commentary workbench from port 8510.
rem Start (or reuse) that local backend before launching the UI.
start "News Commentary Backend" /b "%~dp0.venv\Scripts\python.exe" -m services.news_comment_server
timeout /t 1 /nobreak >nul
"%~dp0.venv\Scripts\python.exe" -m streamlit run "%~dp0news_ui.py"
