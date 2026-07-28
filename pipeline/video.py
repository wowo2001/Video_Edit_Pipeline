from core.cmd import  run_cmd
from core.ffmpeg import cut_video as cut_video_ffmpeg 
from core.ffmpeg import concat_videos as concat_videos_ffmpeg
from core.ffmpeg import change_resolution as change_resolution_ffmpeg
from core.ffmpeg import speed_up as speed_up_ffmpeg
from core.ffmpeg import mask_sub as mask_sub_ffmpeg
from core.ffmpeg import add_subtitles as add_subtitles_ffmpeg
from core.ffmpeg import add_text_overlay as add_text_overlay_ffmpeg
from core.ffmpeg import add_gif_overlay as add_gif_overlay_ffmpeg
from core.ffmpeg import mosaic_regions as mosaic_regions_ffmpeg
import json
from pathlib import Path
import re

from core.utils import ms_to_seconds


def cut_video(input_path, output_path, script_path):
    _cut_hook_video(input_path, output_path, script_path)
    _cut_clip_video(input_path, output_path, script_path)

def _cut_hook_video(input_path, output_path, script_path):

    with open(script_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    narration_duration = ms_to_seconds(
        data["hook"]["narrative"]["length"]
    )

    clips = data["hook"]["clip"]

    temp_files = []

    # =========================
    # 1. 切 hook 小片段
    # =========================
    for idx, clip in enumerate(clips):

        start = ms_to_seconds(clip["start"])
        end = ms_to_seconds(clip["end"])

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

        narration_duration = ms_to_seconds(
            item["narrative"]["length"]
        )

        clips = item["clip"]

        temp_files = []

        # =========================
        # 1. 切每个小片段
        # =========================
        for idx, clip in enumerate(clips):

            start = ms_to_seconds(clip["start"])
            end = ms_to_seconds(clip["end"])

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
def mosaic_regions(
    input_video,
    output_video,
    regions):
    mosaic_regions_ffmpeg(input_video,
    output_video,
    regions)


def add_subtitles(input_video, srt_file, output_video, y, font_size):
    add_subtitles_ffmpeg(input_video, srt_file, output_video, y=y, font_size=font_size)

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
    sub_color,
    popup_text,
    popup_font_size,
    popup_color,
    popup_y,
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
        sub_color,
        popup_text,
        popup_font_size,
        popup_color,
        popup_y,
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
        
        else:
            return int(name)

        return 9999


def cut_segment_video_temp(
    scene_path,
    output_path
):

    output_path.mkdir(
        parents=True,
        exist_ok=True
    )


    with open(
        scene_path,
        "r",
        encoding="utf-8"
    ) as f:
        scenes = json.load(f)



    for scene in scenes:

        scene_id = scene["scene_id"]


        input_path = Path(
            scene["local_video_path"]
        )


        if not input_path.exists():

            print(
                f"[ERROR] 找不到视频: {input_path}"
            )

            continue



        for segment in scene.get(
            "segments",
            []
        ):

            segment_id = segment["segment_id"]


            subtitles = segment.get(
                "subtitles",
                []
            )


            if not subtitles:
                continue



            narration_length = segment.get(
                "narration_length",
                0
            )


            narration_duration = ms_to_seconds(
                narration_length
            )


            temp_files = []



            for index, subtitle in enumerate(subtitles):

                start = ms_to_seconds(
                    subtitle["start_time"]
                )

                end = ms_to_seconds(
                    subtitle["end_time"]
                )


                # 第一句对白之前放解说
                if index == 0:

                    start = max(
                        0,
                        start - narration_duration
                    )


                temp_path = (
                    output_path /
                    f"temp_{scene_id}_{segment_id}_{index}.mp4"
                )


                cut_video_ffmpeg(
                    input_path,
                    temp_path,
                    start,
                    end
                )


                temp_files.append(
                    temp_path
                )



            concat_file = (
                output_path /
                f"concat_{scene_id}_{segment_id}.txt"
            )


            with open(
                concat_file,
                "w",
                encoding="utf-8"
            ) as f:

                for temp in temp_files:
                    f.write(
                        f"file '{temp.name}'\n"
                    )



            final_output = (
                output_path /
                f"scene_{scene_id}_segment_{segment_id}.mp4"
            )


            concat_videos_ffmpeg(
                concat_file,
                str(final_output)
            )


            segment["clip_video"] = str(
                final_output
            )


            print(
                f"完成 scene {scene_id} segment {segment_id}"
            )



            for temp in temp_files:

                if temp.exists():

                    temp.unlink()



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
    
def concat_segment_videos(
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



    list_file = (
        Path(output_path).parent /
        "segment_concat_list.txt"
    )



    with open(
        list_file,
        "w",
        encoding="utf-8"
    ) as f:


        # =====================
        # 1. 先加入hook
        # =====================

        hook_video = hook.get(
            "final_video_path"
        )


        if hook_video:

            hook_path_obj = Path(
                hook_video
            )

            if hook_path_obj.exists():

                f.write(
                    f"file '{hook_path_obj.resolve()}'\n"
                )

            else:

                print(
                    f"[WARN] hook不存在: {hook_path_obj}"
                )



        # =====================
        # 2. 再加入正文segment
        # =====================

        # scenes.sort(
        #     key=lambda x: x["scene_id"]
        # )


        for scene in scenes:


            segments = scene.get(
                "segments",
                []
            )


            segments.sort(
                key=lambda x: x["segment_id"]
            )



            for segment in segments:


                video_path = segment.get(
                    "final_video_path"
                )


                if not video_path:
                    continue



                path = Path(
                    video_path
                )


                if not path.exists():

                    print(
                        f"[WARN] 不存在: {path}"
                    )

                    continue



                f.write(
                    f"file '{path.resolve()}'\n"
                )



    concat_videos_ffmpeg(
        list_file,
        output_path
    )


    list_file.unlink(
        missing_ok=True
    )

def cut_hook_video_temp(
    hook_path,
    output_path
):

    output_path.mkdir(
        parents=True,
        exist_ok=True
    )


    with open(
        hook_path,
        "r",
        encoding="utf-8"
    ) as f:
        hook = json.load(f)



    input_path = Path(
        hook["local_video_path"]
    )


    if not input_path.exists():

        raise Exception(
            f"找不到视频: {input_path}"
        )


    subtitles = hook.get(
        "subtitles",
        []
    )


    if not subtitles:

        raise Exception(
            "hook没有字幕"
        )



    # 原片开始
    start = ms_to_seconds(
        subtitles[0]["start_time"]
    )


    # 原片结束
    end = ms_to_seconds(
        subtitles[-1]["end_time"]
    )


    # 后面留hook旁白空间
    hook_length = ms_to_seconds(
        hook.get(
            "hook_length",
            0
        )
    )


    end = end + hook_length



    print(
        f"""
剪辑hook:
start={start}
end={end}
原片结束={end-hook_length}
旁白空间={hook_length}
"""
    )



    final_output = (
        output_path /
        "hook.mp4"
    )


    cut_video_ffmpeg(
        input_path,
        final_output,
        start,
        end
    )


    hook["hook_video"] = str(
        final_output
    )


    with open(
        hook_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            hook,
            f,
            ensure_ascii=False,
            indent=2
        )


    return hook