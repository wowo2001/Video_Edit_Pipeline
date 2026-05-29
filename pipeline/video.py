from core.cmd import  run_cmd
from core.ffmpeg import cut_video as cut_video_ffmpeg 
from core.ffmpeg import concat_videos as concat_videos_ffmpeg
from core.ffmpeg import change_resolution as change_resolution_ffmpeg
from core.ffmpeg import speed_up as speed_up_ffmpeg
from core.ffmpeg import mask_sub as mask_sub_ffmpeg
from core.ffmpeg import add_subtitles as add_subtitles_ffmpeg
from core.ffmpeg import add_text_overlay as add_text_overlay_ffmpeg
from core.ffmpeg import add_gif_overlay as add_gif_overlay_ffmpeg
import json
from pathlib import Path
import re

from core.utils import srt_to_seconds


def cut_video(input_path, output_path, script_path):
    _cut_hook_video(input_path, output_path, script_path)
    _cut_clip_video(input_path, output_path, script_path)

def _cut_hook_video(input_path, output_path, script_path):

    with open(script_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    narration_duration = srt_to_seconds(
        data["hook"]["narrative"]["length"]
    )

    clips = data["hook"]["clip"]

    temp_files = []

    # =========================
    # 1. 切 hook 小片段
    # =========================
    for idx, clip in enumerate(clips):

        start = srt_to_seconds(clip["start"])
        end = srt_to_seconds(clip["end"])

        # 最后一段后面补旁白时间
        if idx == len(clips) - 1:
            end += narration_duration

        temp_path = output_path / f"temp_{idx}.mp4"

        cut_video_ffmpeg(
            input_path,
            temp_path,
            start,
            end
        )

        temp_files.append(temp_path)

    # =========================
    # 2. concat txt
    # =========================
    list_file = output_path / "hook_concat.txt"

    with open(list_file, "w", encoding="utf-8") as f:
        for temp in temp_files:
            f.write(f"file '{temp.name}'\n")

    # =========================
    # 3. 拼接
    # =========================
    final_output = output_path / "hook.mp4"

    concat_videos_ffmpeg(
        list_file,
        str(final_output)
    )

    # =========================
    # 4. 清理 temp
    # =========================
    for temp in temp_files:
        try:
            if temp.exists():
                temp.unlink()
        except Exception as e:
            print(f"[WARN] delete failed: {temp} -> {e}")

def _cut_clip_video(input_path, output_path, script_path):

    with open(script_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for item in data["clips"]:

        place = item["place"]

        narration_duration = srt_to_seconds(
            item["narrative"]["length"]
        )

        clips = item["clip"]

        temp_files = []

        # =========================
        # 1. 切每个小片段
        # =========================
        for idx, clip in enumerate(clips):

            start = srt_to_seconds(clip["start"])
            end = srt_to_seconds(clip["end"])

            # 第一段前面预留旁白时间
            if idx == 0:
                start = max(0, start - narration_duration)

            temp_path = output_path / f"temp_{place}_{idx}.mp4"

            cut_video_ffmpeg(
                input_path,
                temp_path,
                start,
                end
            )

            temp_files.append(temp_path)

        # =========================
        # 2. 生成 concat txt
        # =========================
        list_file = output_path / f"concat_{place}.txt"

        with open(list_file, "w", encoding="utf-8") as f:
            for temp in temp_files:
                f.write(f"file '{temp.name}'\n")

        # =========================
        # 3. 拼接
        # =========================
        final_output = output_path / f"clip_{place}.mp4"

        concat_videos_ffmpeg(
            list_file,
            str(final_output)
        )
        # =========================
        # 4. 清理 temp 文件
        # =========================
        for temp in temp_files:
            try:
                if temp.exists():
                    temp.unlink()
            except Exception as e:
                print(f"[WARN] delete failed: {temp} -> {e}")

def concat_videos(input_path, output_path):

    files = list(input_path.glob("*.mp4"))
    if not files:
        raise Exception("No mp4 files found")

    files.sort(key=_sort_key)

    list_file = input_path / "filelist.txt"

    with open(list_file, "w", encoding="utf-8") as f:
        for p in files:
            f.write(f"file '{p.resolve()}'\n")
    
    concat_videos_ffmpeg(list_file, output_path)

    list_file.unlink(missing_ok=True)

def change_resolution(input_file, output_file,
                  width, height, fps):
    input_file = Path(input_file)
    output_file = Path(output_file)
    change_resolution_ffmpeg(input_file, output_file, width, height, fps)

def speed_up(input_path, output_path, speed):
    speed_up_ffmpeg(input_path, output_path, speed)

def mask_sub(
    input_video,
    output_video,
    y_offset,
    mask_height
):
    mask_sub_ffmpeg(
        input_video,
        output_video,
        y_offset,
        mask_height
    )

def add_subtitles(input_video, srt_file, output_video, y):
    add_subtitles_ffmpeg(input_video, srt_file, output_video, y=y)

def add_text_overlay(
    input_video,
    output_video,
    title,
    subtitle,
    font_size_title,
    font_size_sub,
    title_y,
    sub_y,
    title_color,
    sub_color
):
    add_text_overlay_ffmpeg(
        input_video,
        output_video,
        title,
        subtitle,
        font_size_title,
        font_size_sub,
        title_y,
        sub_y,
        title_color,
        sub_color
    )

def add_gif_overlay(
    input_video,
    output_video,
    gif_path,
    x=50,
    y=50,
    scale=1.0
):
    add_gif_overlay_ffmpeg(
        input_video,
        output_video,
        gif_path,
        x,
        y,
        scale
    )

def _sort_key(p: Path):
        name = p.stem

        if name == "hook_final":
            return 0

        if name.startswith("clip"):
            num = re.findall(r"\d+", name)
            return int(num[0]) if num else 999

        return 9999
