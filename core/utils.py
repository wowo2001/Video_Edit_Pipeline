import json
from pathlib import Path
import re
import shutil

def ms_to_srt_time(ms: int) -> str:
    ms = int(ms)
    h = ms // 3600000
    m = (ms % 3600000) // 60000
    s = (ms % 60000) // 1000
    ms = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def srt_to_seconds(t: str) -> float:
    h, m, s = t.split(":")
    s, ms = s.split(",")

    return (
        int(h) * 3600
        + int(m) * 60
        + int(s)
        + int(ms) / 1000
    )

def safe_json_parse(text: str):

    text = text.strip()

    if "```" in text:
        text = re.sub(r"```json", "", text)
        text = re.sub(r"```", "", text)

    return json.loads(text)

def safe_filename(name: str):
    return re.sub(r'[\\/:*?"<>|()]', "_", name)

def clear_workdir(workdir: Path):
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)