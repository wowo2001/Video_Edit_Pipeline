from pathlib import Path

from core.cmd import run_cmd
from core.ffmpeg import wav_to_map3
from core.path import ProjectPaths


def extract_vocals_demucs(input_path: Path):
    """Separate vocals and store Demucs artifacts at the managed project path."""
    input_path = Path(input_path)
    project_paths = ProjectPaths(vocals_source=input_path.stem)

    cmd = [
        "demucs",
        "-n", "htdemucs",
        "--two-stems=vocals",
        str(input_path)
    ]

    run_cmd(cmd)

    vocals_path = project_paths.vocals_wav
    vocals_mp3_path = project_paths.vocals_mp3
    wav_to_map3(vocals_path, vocals_mp3_path)
    return vocals_mp3_path
