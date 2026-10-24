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

echo 'Starting main workflow...'
echo 'Task file: tasks.json'
echo
"$python_bin" -u main.py
result=$?
echo
if (( result != 0 )); then
    echo '[FAILED] The workflow stopped. Review the error above.'
else
    echo '[DONE] Workflow completed.'
fi
pause_before_exit
exit "$result"
