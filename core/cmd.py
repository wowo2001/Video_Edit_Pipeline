import subprocess
import os


def run_cmd(cmd, capture_output=False):
    """Run a command, optionally capturing its text output."""
    cmd = [str(part) for part in cmd]

    print("\n>>>", " ".join(cmd))
    environment = os.environ.copy()
    environment.setdefault('PYTHONUTF8', '1')
    environment.setdefault('PYTHONIOENCODING', 'utf-8')
    options = {'encoding': 'utf-8', 'errors': 'replace'} if capture_output else {}
    result = subprocess.run(cmd, capture_output=capture_output, text=capture_output,
                            env=environment, **options)

    if result.returncode != 0:
        raise RuntimeError(f"命令执行失败（退出码 {result.returncode}）: {' '.join(cmd)}")

    return result
