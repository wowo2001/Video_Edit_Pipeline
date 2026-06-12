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

def ms_to_seconds(ms: int) -> float:
    return ms / 1000

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

def strip_srt(input_file, output_file, keep_index):
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
            current_index = int(line) - 1
            continue

        # 跳过时间轴
        if time_pattern.match(line):
            continue
        
        if keep_index :
            result.append(f"[{current_index}] {line}")
        else :
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

def apply_timeline(script_path, subtitles_path):
    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    with open(subtitles_path, "r", encoding="utf-8") as f:
        subtitles = json.load(f)

    utterances = subtitles["utterances"]

    def build_clip(index_list):
        clips = []

        for idx in index_list:
            if idx < 0 or idx >= len(utterances):
                print(f"[WARN] index越界: {idx}")
                continue

            u = utterances[idx]

            clips.append({
                "index": idx,
                "content": u["text"],
                "start": u["start_time"],
                "end": u["end_time"],
                "speaker": u.get("attribute", {}).get("speaker")
            })

        return clips

    # hook 回填
    if "hook" in script:
        script["hook"]["clip"] = build_clip(script["hook"].get("clip", []))

    # clips 回填
    for section in script.get("clips", []):
        section["clip"] = build_clip(section.get("clip", []))

    # 写回
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)