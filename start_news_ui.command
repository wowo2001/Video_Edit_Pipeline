#!/bin/zsh -l
# macOS launcher. Export API keys in ~/.zprofile for Finder launches.
cd -- "${0:A:h}" || exit 1
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

pause_before_exit() {
    if [[ -t 0 ]]; then
        printf '\nPress Enter to close...'
        read -r
    fi
}

if [[ -x .venv/bin/python ]]; then
    python_bin="$PWD/.venv/bin/python"
elif [[ -x venv/bin/python ]]; then
    python_bin="$PWD/venv/bin/python"
else
    echo '[ERROR] Cannot find .venv/bin/python or venv/bin/python.'
    pause_before_exit
    exit 1
fi

# Make virtual-environment commands available to Python subprocesses.
export PATH="${python_bin:h}:$PATH"

missing_keys=0
if [[ -z "${YOUTUBE_API_KEY:-}" ]]; then
    echo '[ERROR] YOUTUBE_API_KEY is missing or empty.'
    missing_keys=1
fi
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    echo '[ERROR] OPENAI_API_KEY is missing or empty.'
    missing_keys=1
fi
if (( missing_keys )); then
    echo 'For Finder launches, export them in ~/.zprofile, then reopen this launcher.'
    pause_before_exit
    exit 1
fi

# Start/reuse the backend embedded by /news_comment.
"$python_bin" -m services.news_comment_server || exit 1

# Prevent idle system sleep while Streamlit runs; allow the display to sleep.
/usr/bin/caffeinate -i "$python_bin" -m streamlit run "$PWD/news_ui.py"
result=$?
if (( result != 0 )); then
    echo '[FAILED] News UI stopped. Review the error above.'
    pause_before_exit
fi
exit "$result"
