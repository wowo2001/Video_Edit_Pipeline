from core.cmd import run_cmd
import shutil
from pathlib import Path
from core.ffmpeg import wav_to_map3
def extract_vocals_demucs(input_path: Path, work_place_dir: Path):
    cmd = [
        "demucs",
        "-n", "htdemucs",
        "--two-stems=vocals",
        str(input_path)
    ]

    run_cmd(cmd)

    vocals_path = work_place_dir / "vocals.wav"
    vocals_mp3_path = work_place_dir / "vocals.mp3"
    wav_to_map3(vocals_path, vocals_mp3_path)
    shutil.copy(vocals_mp3_path, input_path)