from pathlib import Path

from core.ffmpeg import add_gif_overlay as add_gif_overlay_ffmpeg
from core.ffmpeg import add_subtitles as add_subtitles_ffmpeg
from core.ffmpeg import add_text_overlay as add_text_overlay_ffmpeg
from core.ffmpeg import change_resolution as change_resolution_ffmpeg
from core.ffmpeg import concat_media as concat_videos_ffmpeg
from core.ffmpeg import cut_video as cut_video_ffmpeg
from core.ffmpeg import mask_sub as mask_sub_ffmpeg
from core.ffmpeg import mosaic_regions as mosaic_regions_ffmpeg
from core.ffmpeg import speed_up as speed_up_ffmpeg
from core.utils import ms_to_seconds


def cut_video(
    input_path,
    subtitles,
    narration_duration,
    output_path,
    narration_position="before",
    keep_gaps=False,
):
    """Cut a video from subtitle timestamps and return the output path."""
    if not subtitles:
        raise ValueError("没有可裁剪的字幕")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if keep_gaps:
        start = ms_to_seconds(_subtitle_time(subtitles[0], "start"))
        end = ms_to_seconds(_subtitle_time(subtitles[-1], "end"))
        if narration_position == "before":
            start = max(0, start - narration_duration)
        elif narration_position == "after":
            end += narration_duration
        cut_video_ffmpeg(input_path, output_path, start, end)
        return output_path

    temp_files = []
    for index, subtitle in enumerate(subtitles):
        start = ms_to_seconds(_subtitle_time(subtitle, "start"))
        end = ms_to_seconds(_subtitle_time(subtitle, "end"))
        if narration_position == "before" and index == 0:
            start = max(0, start - narration_duration)
        elif narration_position == "after" and index == len(subtitles) - 1:
            end += narration_duration

        temp_path = output_path.parent / f"temp_{output_path.stem}_{index}.mp4"
        cut_video_ffmpeg(input_path, temp_path, start, end)
        temp_files.append(temp_path)

    list_file = output_path.parent / f"{output_path.stem}_concat.txt"
    with open(list_file, "w", encoding="utf-8") as file:
        for temp_path in temp_files:
            file.write(f"file '{temp_path.name}'\n")

    concat_videos_ffmpeg(list_file, output_path)
    list_file.unlink(missing_ok=True)
    for temp_path in temp_files:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError as error:
            print(f"[WARN] delete failed: {temp_path} -> {error}")
    return output_path


def concat_video_paths(video_paths, output_path, list_file):
    if not video_paths:
        raise ValueError("没有可拼接的视频路径")

    with open(list_file, "w", encoding="utf-8") as file:
        for video_path in video_paths:
            path = Path(video_path)
            if not path.exists():
                raise FileNotFoundError(f"找不到待拼接视频: {path}")
            file.write(f"file '{path.resolve()}'\n")

    concat_videos_ffmpeg(list_file, output_path)
    list_file.unlink(missing_ok=True)


def change_resolution(input_file, output_file, width, height, fps):
    change_resolution_ffmpeg(Path(input_file), Path(output_file), width, height, fps)


def speed_up(input_path, output_path, speed):
    speed_up_ffmpeg(input_path, output_path, speed)


def mask_sub(input_video, output_video, y_offset, mask_height):
    mask_sub_ffmpeg(input_video, output_video, y_offset, mask_height)


def mosaic_regions(input_video, output_video, regions):
    mosaic_regions_ffmpeg(input_video, output_video, regions)


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


def add_gif_overlay(input_video, output_video, gif_path, x=50, y=50, scale=1.0):
    add_gif_overlay_ffmpeg(input_video, output_video, gif_path, x, y, scale)


def _subtitle_time(subtitle, field):
    return subtitle[field] if field in subtitle else subtitle[f"{field}_time"]
