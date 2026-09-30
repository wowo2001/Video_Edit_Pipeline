import hashlib
import math
from pathlib import Path

from core.cmd import run_cmd
from core.ffmpeg import get_duration


CHUNK_SECONDS = 10 * 60


def _demucs_workspace(input_path: Path) -> Path:
    """Return a per-input workspace so separate jobs cannot overwrite each other."""
    identity = str(input_path.resolve()).encode("utf-8")
    suffix = hashlib.sha256(identity).hexdigest()[:12]
    return input_path.parent / "demucs" / f"{input_path.stem}_{suffix}"


def _split_audio(input_path: Path, chunks_dir: Path, duration: float) -> list[Path]:
    """Split an audio file into bounded inputs so Demucs never loads the whole file."""
    chunk_paths = []
    for index, start in enumerate(range(0, math.ceil(duration), CHUNK_SECONDS)):
        chunk_path = chunks_dir / f"chunk_{index:03d}.mp3"
        chunk_duration = min(CHUNK_SECONDS, duration - start)
        if not chunk_path.exists():
            run_cmd([
                "ffmpeg", "-y", "-ss", str(start), "-i", str(input_path),
                "-t", str(chunk_duration), "-vn", "-ac", "2", "-ar", "44100",
                "-c:a", "libmp3lame", "-q:a", "2", str(chunk_path),
            ])
        chunk_paths.append(chunk_path)
    return chunk_paths


def extract_vocals_demucs(input_path: Path):
    """Separate vocals in ten-minute chunks, then join them into one MP3.

    Chunking bounds Demucs' peak memory use on long sources. The final join is
    streamed by FFmpeg, so it does not reintroduce the original memory spike.
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"找不到待分离音频: {input_path}")

    workspace = _demucs_workspace(input_path)
    chunks_dir = workspace / "chunks"
    demucs_output_dir = workspace / "separated"
    vocals_mp3_path = workspace / "vocals.mp3"
    if vocals_mp3_path.exists():
        return vocals_mp3_path

    chunks_dir.mkdir(parents=True, exist_ok=True)
    duration = get_duration(input_path)
    if duration <= 0:
        raise ValueError(f"待分离音频时长无效: {input_path}")
    chunk_paths = _split_audio(input_path, chunks_dir, duration)

    vocal_wavs = []
    for chunk_path in chunk_paths:
        vocal_wav = demucs_output_dir / "htdemucs" / chunk_path.stem / "vocals.wav"
        if not vocal_wav.exists():
            run_cmd([
                "demucs", "-n", "htdemucs", "--two-stems=vocals",
                "--out", str(demucs_output_dir), str(chunk_path),
            ])
        if not vocal_wav.exists():
            raise FileNotFoundError(f"Demucs 未生成分离人声: {vocal_wav}")
        vocal_wavs.append(vocal_wav)

    filelist_path = workspace / "vocals_chunks.txt"
    with filelist_path.open("w", encoding="utf-8") as file:
        for vocal_wav in vocal_wavs:
            escaped_path = str(vocal_wav.resolve()).replace("'", r"'\\''")
            file.write(f"file '{escaped_path}'\n")
    run_cmd([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(filelist_path),
        "-c:a", "libmp3lame", "-q:a", "2", str(vocals_mp3_path),
    ])
    return vocals_mp3_path
