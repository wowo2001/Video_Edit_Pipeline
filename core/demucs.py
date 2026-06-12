from core.cmd import run_cmd
import shutil
from pathlib import Path
def extract_vocals_demucs(input_path: Path, work_place_dir: Path):
    cmd = [
        "demucs",
        "-n", "htdemucs_ft",
        "--two-stems=vocals",
        str(input_path)
    ]

    run_cmd(cmd)

    vocals_path = work_place_dir / "htdemucs" / input_path.stem / "vocals.wav"
    shutil.copy(vocals_path, input_path)