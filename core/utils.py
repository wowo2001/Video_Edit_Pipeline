import json
import re
import shutil
from pathlib import Path


def read_json(source, **kwargs):
    """Read JSON from a UTF-8 path or an already-open text stream."""
    if hasattr(source, "read"):
        return json.load(source, **kwargs)
    with open(source, "r", encoding="utf-8") as file:
        return json.load(file, **kwargs)


def write_json(data, destination, *, ensure_ascii=False, indent=2, **kwargs):
    """Write JSON to a UTF-8 path or an already-open text stream."""
    if hasattr(destination, "write"):
        json.dump(data, destination, ensure_ascii=ensure_ascii, indent=indent, **kwargs)
        return
    with open(destination, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=ensure_ascii, indent=indent, **kwargs)


def ms_to_srt_time(ms: int) -> str:
    ms = int(ms)
    hours = ms // 3_600_000
    minutes = (ms % 3_600_000) // 60_000
    seconds = (ms % 60_000) // 1_000
    milliseconds = ms % 1_000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def ms_to_seconds(ms: int) -> float:
    return ms / 1000


def srt_to_seconds(timestamp: str) -> float:
    hours, minutes, seconds = timestamp.split(":")
    seconds, milliseconds = seconds.split(",")
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(milliseconds) / 1000
    )


def safe_json_parse(text: str):
    text = text.strip()
    if "```" in text:
        text = re.sub(r"```json", "", text)
        text = re.sub(r"```", "", text)
    return json.loads(text)


def safe_filename(name: str):
    return re.sub(r'[\\/:*?"<>|()]', "_", name)


def clear_workdir(workdir: Path, demucs_path: Path):
    if workdir.exists():
        shutil.rmtree(workdir)
    if demucs_path.exists():
        shutil.rmtree(demucs_path)
    workdir.mkdir(parents=True, exist_ok=True)
