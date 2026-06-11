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

def strip_srt(input_file, output_file, keep_timeline):
    with open(input_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    result = []

    time_pattern = re.compile(
        r"^\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}$"
    )

    for line in lines:
        line = line.strip()

        if not line:
            continue

        # 跳过序号
        if line.isdigit():
            continue

        # 跳过时间轴
        if time_pattern.match(line):
            if not keep_timeline:
                continue

        result.append(line)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(result))

def apply_speaker_mapping(subtitles_path, mapping_path):
    text = subtitles_path.read_text(encoding="utf-8")

    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    for k, v in mapping.items():
        text = text.replace(f"[{k}]", f"[{v}]")

    subtitles_path.write_text(text, encoding="utf-8")