import json
from pathlib import Path
import os
import re
import shutil
from urllib.parse import urlparse

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

def clear_workdir(workdir: Path, demucs_path: Path):
    if workdir.exists():
        shutil.rmtree(workdir)
    if demucs_path.exists():
        shutil.rmtree(demucs_path)
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


def apply_speaker_mapping_to_script(script_path, mapping_path):
    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    def replace_speaker(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "speaker" and isinstance(v, str):
                    obj[k] = mapping.get(v, v)
                else:
                    replace_speaker(v)
        elif isinstance(obj, list):
            for item in obj:
                replace_speaker(item)

    replace_speaker(script)

    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

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

def chunk_srt_by_scenes(
        srt_file,
        story_file,
        output_file
):

    with open(story_file, "r", encoding="utf-8") as f:
        story = json.load(f)


    # 推荐场景
    recommend_ids = set(
        story["推荐解说场景"]
    )


    # 收集需要的字幕编号范围
    keep_ids = set()

    for scene in story["场景"]:

        if scene["编号"] in recommend_ids:

            start = scene["开始SRT"]
            end = scene["结束SRT"]

            for i in range(start, end + 1):
                keep_ids.add(i)


    result = []


    pattern = re.compile(r"^\[(\d+)\]")


    with open(
        srt_file,
        "r",
        encoding="utf-8"
    ) as f:

        for line in f:

            line = line.rstrip()

            if not line:
                continue

            match = pattern.match(line)

            if not match:
                continue

            index = int(match.group(1))

            if index in keep_ids:
                result.append(line)


    with open(
        output_file,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "\n".join(result)
        )


    print(
        f"✅ 解说字幕生成: {output_file}"
    )

def apply_character_scene_mapping(
        subtitle_json_path,
        speaker_mapping_path,
        story_path,
        scene_mapping,
        output_path
):

    with open(subtitle_json_path, "r", encoding="utf-8") as f:
        subtitles = json.load(f)

    with open(speaker_mapping_path, "r", encoding="utf-8") as f:
        speaker_mapping = json.load(f)

    with open(story_path, "r", encoding="utf-8") as f:
        story = json.load(f)


    scenes = story.get("场景", [])


    for srt_index, utterance in enumerate(
        subtitles.get("utterances", [])
    ):

        # 人物映射
        raw_speaker = (
            utterance
            .get("attribute", {})
            .get("speaker")
        )

        utterance["speaker"] = speaker_mapping.get(
            raw_speaker,
            raw_speaker
        )


        # 根据SRT编号找到AI场景编号
        scene_no = None

        for scene in scenes:
            if (
                scene["开始SRT"] <= srt_index <= scene["结束SRT"]
            ):
                scene_no = scene["编号"]
                break


        # AI场景编号转换成数据库scene id
        utterance["scene_id"] = (
            scene_mapping.get(scene_no)
            if scene_no is not None
            else None
        )
        utterance.pop("words", None)
        utterance.pop("attribute", None)


        # 删除无用字段
    subtitles.pop("attribute", None)
    subtitles.pop("code", None)
    subtitles.pop("message", None)
    subtitles.pop("id", None)
    subtitles.pop("duration", None)

    


    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            subtitles,
            f,
            ensure_ascii=False,
            indent=2
        )

def save_scene_candidates(rows, output_path):

    scenes = []

    for row in rows:
        scenes.append(
            {
                "scene_id": row[0],
                "drama_title": row[1],
                "video_url": row[2],
                "title": row[3],
                "event": row[4],
                "summary": row[5],
            }
        )


    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            scenes,
            f,
            ensure_ascii=False,
            indent=2
        )

def restore_scene_subtitle(
    selected_scene_path,
    scene_path,
    output_path,
    postgres_client
):

    with open(
        scene_path,
        "r",
        encoding="utf-8"
    ) as f:
        scenes = json.load(f)


    with open(
        selected_scene_path,
        "r",
        encoding="utf-8"
    ) as f:
        selected_scene = json.load(f)


    # 原scene建立索引
    scene_map = {
        scene["scene_id"]: scene
        for scene in scenes
    }


    results = []


    for item in selected_scene:

        scene_id = item["scene_id"]


        # 找回原scene信息
        scene = scene_map.get(scene_id)

        if not scene:
            continue


        subtitles = []


        rows = postgres_client.get_subtitles_by_scene_id(
            scene_id
        )


        for row in rows:
            subtitles.append(
                {
                    "start_time": row[0],
                    "end_time": row[1],
                    "content": row[2],
                    "speaker": row[3],
                }
            )

        plain_lines = []
        for index, subtitle in enumerate(subtitles, start=1):
            plain_lines.append(
                f"[{index}] {subtitle['speaker']}：{subtitle['content']}"
        )


        # 加字幕
        scene["subtitles"] = subtitles
        scene["subtitles_plain_text"] = "\n".join(
            plain_lines
        )


        results.append(scene)



    # 按剧情顺序
    results.sort(
        key=lambda x: x["scene_id"]
    )


    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            results,
            f,
            ensure_ascii=False,
            indent=2
        )


    return results

def restore_selected_subtitles(
    scene_with_subtitle_path,
    scene_clips_path,
    output_path
):

    with open(
        scene_with_subtitle_path,
        "r",
        encoding="utf-8"
    ) as f:
        scenes = json.load(f)


    with open(
        scene_clips_path,
        "r",
        encoding="utf-8"
    ) as f:
        scene_clips = json.load(f)


    # scene_id -> clip index
    clip_mapping = {
        item["scene_id"]: item["clip"]
        for item in scene_clips
    }


    results = []


    for scene in scenes:

        scene_id = scene["scene_id"]

        indexes = clip_mapping.get(
            scene_id,
            []
        )

        if not indexes:
            continue


        selected_subtitles = []


        for idx in indexes:

            # AI编号从1开始
            subtitle_index = idx - 1

            if subtitle_index < len(scene["subtitles"]):

                selected_subtitles.append(
                    scene["subtitles"][subtitle_index]
                )


        scene["subtitles"] = selected_subtitles

        plain_lines = []

        for index, subtitle in enumerate(
            selected_subtitles,
            start=1
        ):

            plain_lines.append(
                f"{subtitle['speaker']}：{subtitle['content']}"
            )


        scene["selected_subtitles_plain_text"] = "\n".join(
            plain_lines
        )


        # 原始完整字幕文本删除
        scene.pop(
            "subtitles_plain_text",
            None
        )

        results.append(scene)


    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            results,
            f,
            ensure_ascii=False,
            indent=2
        )


    return results

import json


def merge_scene_narration(
    scene_path,
    narration_path,
    output_path
):

    with open(
        scene_path,
        "r",
        encoding="utf-8"
    ) as f:
        scenes = json.load(f)


    with open(
        narration_path,
        "r",
        encoding="utf-8"
    ) as f:
        narrations = json.load(f)


    narration_map = {
        item["scene_id"]: item["narration"]
        for item in narrations
    }


    results = []


    for scene in scenes:

        scene_id = scene["scene_id"]

        narration = narration_map.get(
            scene_id
        )

        if narration:
            scene["narration"] = narration


        results.append(scene)


    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            results,
            f,
            ensure_ascii=False,
            indent=2
        )


    return results

def download_scene_videos(
    scene_path,
    download_dir,
    s3_client
):

    with open(
        scene_path,
        "r",
        encoding="utf-8"
    ) as f:
        scenes = json.load(f)


    os.makedirs(
        download_dir,
        exist_ok=True
    )


    downloaded = {}


    for scene in scenes:

        s3_url = scene["video_url"]


        # =====================
        # 1. 获取本地路径
        # =====================

        if s3_url in downloaded:

            local_path = downloaded[s3_url]

        else:

            filename = get_filename_from_s3_url(
                s3_url
            )


            local_path = os.path.join(
                download_dir,
                filename
            )


            downloaded[s3_url] = local_path



        # =====================
        # 2. 下载
        # =====================

        if os.path.exists(local_path):

            print(
                f"已存在，跳过: {local_path}"
            )

        else:

            print(
                f"下载: {s3_url}"
            )

            s3_client.download_file(
                s3_url,
                local_path
            )


        # =====================
        # 3. 写回当前scene
        # =====================

        scene["local_video_path"] = local_path



    with open(
        scene_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            scenes,
            f,
            ensure_ascii=False,
            indent=2
        )


    return scenes

def get_filename_from_s3_url(s3_path):
    """
    从 s3 url 提取文件名
    """
    parsed = urlparse(s3_path)
    return os.path.basename(parsed.path)


def restore_segment_subtitles(
    scene_path,
    segment_path,
    output_path
):

    with open(
        scene_path,
        "r",
        encoding="utf-8"
    ) as f:
        scenes = json.load(f)


    with open(
        segment_path,
        "r",
        encoding="utf-8"
    ) as f:
        segments_data = json.load(f)


    # scene_id -> segments
    segment_mapping = {
        item["scene_id"]: item["segments"]
        for item in segments_data
    }


    results = []


    for scene in scenes:

        scene_id = scene["scene_id"]

        segments = segment_mapping.get(
            scene_id,
            []
        )


        if not segments:
            continue


        subtitle_map = {
            index + 1: subtitle
            for index, subtitle in enumerate(
                scene["subtitles"]
            )
        }


        new_segments = []


        for segment in segments:

            subtitle_ids = segment.get(
                "subtitle_ids",
                []
            )


            selected_subtitles = []


            for sid in subtitle_ids:

                subtitle = subtitle_map.get(
                    sid
                )

                if subtitle:
                    selected_subtitles.append(
                        subtitle
                    )


            segment["subtitles"] = selected_subtitles


            # 后面剪辑不用id了
            segment.pop(
                "subtitle_ids",
                None
            )


            new_segments.append(
                segment
            )


        scene["segments"] = new_segments


        results.append(scene)



    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            results,
            f,
            ensure_ascii=False,
            indent=2
        )


    return results

def extract_hook_segment(
    scene_path,
    hook_path,
    output_path
):

    with open(
        scene_path,
        "r",
        encoding="utf-8"
    ) as f:
        scenes = json.load(f)


    with open(
        hook_path,
        "r",
        encoding="utf-8"
    ) as f:
        hook = json.load(f)


    target_scene_id = hook["scene_id"]
    target_segment_id = hook["segment_id"]


    result = None


    for scene in scenes:

        if scene["scene_id"] != target_scene_id:
            continue


        for segment in scene["segments"]:

            if segment["segment_id"] == target_segment_id:

                result = segment.copy()

                result["scene_id"] = target_scene_id

                result["local_video_path"] = (
                scene["local_video_path"]
                )

                result["hook_narration"] = (
                    hook["hook_narration"]
                )

                break


    if result is None:
        raise Exception(
            "没有找到对应segment"
        )


    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            result,
            f,
            ensure_ascii=False,
            indent=2
        )


    return result