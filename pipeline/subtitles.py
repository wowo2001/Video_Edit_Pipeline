import re

from core.utils import read_json, write_json


def strip_srt(input_file, output_file, keep_index):
    lines = input_file.read_text(encoding="utf-8").splitlines()
    time_pattern = re.compile(
        r"^\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}$"
    )
    result = []

    for line in lines:
        line = line.strip()
        if not line or time_pattern.match(line):
            continue
        if line.isdigit():
            current_index = int(line) - 1
            continue
        result.append(f"[{current_index}] {line}" if keep_index else line)

    output_file.write_text("\n".join(result), encoding="utf-8")


def apply_speaker_mapping(subtitles_path, mapping_path):
    text = subtitles_path.read_text(encoding="utf-8")
    for raw_speaker, speaker in read_json(mapping_path).items():
        text = text.replace(f"[{raw_speaker}]", f"[{speaker}]")
    subtitles_path.write_text(text, encoding="utf-8")


def apply_timeline(script_path, subtitles_path):
    script = read_json(script_path)
    utterances = read_json(subtitles_path)["utterances"]

    def build_clip(index_list):
        clips = []
        for index in index_list:
            if not 0 <= index < len(utterances):
                print(f"[WARN] index越界: {index}")
                continue
            utterance = utterances[index]
            clips.append({
                "index": index,
                "content": utterance["text"],
                "start": utterance["start_time"],
                "end": utterance["end_time"],
                "speaker": utterance.get("attribute", {}).get("speaker"),
            })
        return clips

    if "hook" in script:
        script["hook"]["clip"] = build_clip(script["hook"].get("clip", []))
    for section in script.get("clips", []):
        section["clip"] = build_clip(section.get("clip", []))
    write_json(script, script_path)


def chunk_srt_by_scenes(srt_file, story_file, output_file):
    story = read_json(story_file)
    recommend_ids = set(story["推荐解说场景"])
    keep_ids = set()

    for scene in story["场景"]:
        if scene["编号"] in recommend_ids:
            keep_ids.update(range(scene["开始SRT"], scene["结束SRT"] + 1))

    pattern = re.compile(r"^\[(\d+)\]")
    result = []
    for line in srt_file.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match and int(match.group(1)) in keep_ids:
            result.append(line)

    output_file.write_text("\n".join(result), encoding="utf-8")
    print(f"✅ 解说字幕生成: {output_file}")


def apply_character_scene_mapping(
    subtitle_json_path, speaker_mapping_path, story_path, scene_mapping, output_path
):
    subtitles = read_json(subtitle_json_path)
    speaker_mapping = read_json(speaker_mapping_path)
    scenes = read_json(story_path).get("场景", [])

    for srt_index, utterance in enumerate(subtitles.get("utterances", [])):
        raw_speaker = utterance.get("attribute", {}).get("speaker")
        utterance["speaker"] = speaker_mapping.get(raw_speaker, raw_speaker)

        scene_no = next(
            (
                scene["编号"]
                for scene in scenes
                if scene["开始SRT"] <= srt_index <= scene["结束SRT"]
            ),
            None,
        )
        utterance["scene_id"] = scene_mapping.get(scene_no) if scene_no is not None else None
        utterance.pop("words", None)
        utterance.pop("attribute", None)

    for field in ("attribute", "code", "message", "id", "duration"):
        subtitles.pop(field, None)
    write_json(subtitles, output_path)
