import subprocess

def run_cmd(cmd):
    cmd = [str(c) for c in cmd]   # 🔥关键：统一转字符串

    print("\n>>>", " ".join(cmd))
    result = subprocess.run(cmd)

    if result.returncode != 0:
        raise Exception(f"命令执行失败: {' '.join(cmd)}")

def run_cmd_output(cmd):
    cmd = [str(c) for c in cmd]

    print("\n>>>", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise Exception(f"命令执行失败: {' '.join(cmd)}")

    return result