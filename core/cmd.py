import subprocess


def run_cmd(cmd, capture_output=False):
    """Run a command, optionally capturing its text output."""
    cmd = [str(part) for part in cmd]

    print("\n>>>", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=capture_output, text=capture_output)

    if result.returncode != 0:
        raise RuntimeError(f"命令执行失败: {' '.join(cmd)}")

    return result
