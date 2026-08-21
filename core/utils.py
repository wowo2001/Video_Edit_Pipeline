import json
from pathlib import Path
import os
import re
import shutil
from urllib.parse import urlparse
from core.ffmpeg import encode_to_standard


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

    mapping = read_json(mapping_path)
    for k, v in mapping.items():
        text = text.replace(f"[{k}]", f"[{v}]")

    subtitles_path.write_text(text, encoding="utf-8")


def apply_speaker_mapping_to_script(script_path, mapping_path):
    script = read_json(script_path)
    mapping = read_json(mapping_path)
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

    write_json(script, script_path, ensure_ascii=False, indent=2)
def apply_timeline(script_path, subtitles_path):
    script = read_json(script_path)
    subtitles = read_json(subtitles_path)
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
    write_json(script, script_path, ensure_ascii=False, indent=2)
def chunk_srt_by_scenes(
        srt_file,
        story_file,
        output_file
):

    story = read_json(story_file)

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

    subtitles = read_json(subtitle_json_path)
    speaker_mapping = read_json(speaker_mapping_path)
    story = read_json(story_path)

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

    


    write_json(
                subtitles,
                output_path,
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


    write_json(
                scenes,
                output_path,
                ensure_ascii=False,
                indent=2
            )
def restore_scene_subtitle(
    selected_scene_path,
    scene_path,
    output_path,
    postgres_client
):

    scenes = read_json(scene_path)

    selected_scene = read_json(selected_scene_path)

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

        scene["task"] = item["task"]


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
    # results.sort(
    #     key=lambda x: x["scene_id"]
    # )


    write_json(
                results,
                output_path,
                ensure_ascii=False,
                indent=2
            )

    return results

def restore_selected_subtitles(
    scene_with_subtitle_path,
    scene_clips_path,
    output_path
):

    scenes = read_json(scene_with_subtitle_path)

    scene_clips = read_json(scene_clips_path)

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


    write_json(
                results,
                output_path,
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

    scenes = read_json(scene_path)

    narrations = read_json(narration_path)

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


    write_json(
                results,
                output_path,
                ensure_ascii=False,
                indent=2
            )

    return results

def download_scene_videos(
    scene_path,
    download_dir,
    s3_client,
    standardize=True
):

    scenes = read_json(scene_path)

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
        # 3. 分辨率标准化
        # =====================

        final_path = local_path

        if standardize:

            standard_dir = os.path.join(
                download_dir,
                "standard"
            )

            os.makedirs(
                standard_dir,
                exist_ok=True
            )


            standard_path = os.path.join(
                standard_dir,
                filename
            )


            if not os.path.exists(standard_path):

                print(
                    f"标准化视频: {local_path}"
                )

                encode_to_standard(
                    local_path,
                    standard_path
                )


            final_path = standard_path



        # =====================
        # 4. 写回scene
        # =====================

        scene["local_video_path"] = final_path



    write_json(
                scenes,
                scene_path,
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

    scenes = read_json(scene_path)

    segments_data = read_json(segment_path)

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



    write_json(
                results,
                output_path,
                ensure_ascii=False,
                indent=2
            )

    return results

def extract_hook_segment(
    scene_path,
    hook_path,
    output_path
):

    scenes = read_json(scene_path)

    hook = read_json(hook_path)

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


    write_json(
                result,
                output_path,
                ensure_ascii=False,
                indent=2
            )

    return result
