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


def apply_timeline(script_path, subtitles_path, story_path=None):
    script = read_json(script_path)
    utterances = read_json(subtitles_path)["utterances"]
    from pipeline.scenes import NARRATION_ONLY, WITH_DIALOGUE, normalize_segment_type
    scenes = read_json(story_path).get("场景", []) if story_path else []

    def build_clip(index_list):
        if (not isinstance(index_list, list) or not index_list
                or any(type(i) is not int or not 0 <= i < len(utterances) for i in index_list)
                or any(b != a+1 for a, b in zip(index_list, index_list[1:]))):
            raise ValueError("clip 必须是有效且连续递增的全局字幕索引")
        clips = []
        for index in index_list:
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
    previous = -1
    for place, section in enumerate(script.get("clips", []), 1):
        segment_type = normalize_segment_type(section.get("type", WITH_DIALOGUE))
        if section.get("place") != place:
            raise ValueError("正文 place 必须从 1 连续递增")
        section["clip"] = build_clip(section.get("clip", []))
        first, last = section["clip"][0]["index"], section["clip"][-1]["index"]
        if first <= previous:
            raise ValueError("正文画面索引不能重复或倒退")
        previous = last
        if scenes:
            scene = next((s for s in scenes if s["开始SRT"] <= first <= last <= s["结束SRT"]), None)
            if scene is None:
                raise ValueError("正文 clip 必须属于同一个已知场景")
            if segment_type == NARRATION_ONLY:
                section["visual_bounds"] = {
                    "start": utterances[scene["开始SRT"]]["start_time"],
                    "end": utterances[scene["结束SRT"]]["end_time"]}
    write_json(script, script_path)


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
