from core.cmd import run_cmd, run_cmd_output
import json
def extract_audio(input_path, output_path):

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),

        "-vn",
        "-ac", "2",
        "-ar", "44100",
        "-b:a", "192k",
        str(output_path)
    ]
    run_cmd(cmd)
def cut_video(input_path, output_path, start, end):
    duration = end - start

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(start),
        "-i", str(input_path),
        "-t", str(duration),

        "-c:v", "libx264",
        "-c:a", "aac",
        "-avoid_negative_ts", "make_zero",

        str(output_path)
    ]
    run_cmd(cmd)

def get_duration(path):

    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(path)
    ]

    result = run_cmd_output(cmd)
    data = json.loads(result.stdout)
    return round(float(data["format"]["duration"]),3)

def mix_end_aligned(
    video,
    audio,
    output,
    narration_duration,
    video_duration
):

    narration_start_time = max(0, video_duration - narration_duration)
    delay = int(narration_start_time * 1000)

    filter_complex = (
    "[0:a]loudnorm=I=-20:LRA=7:TP=-2[vnorm];"
    "[1:a]loudnorm=I=-14:LRA=7:TP=-2[anorm];"

    "[vnorm]asplit=2[a0][a1];"

    f"[a0]volume=0.01:enable='between(t,{narration_start_time},{video_duration})'[a0_low];"
    "[a1]volume=1.0[a1_norm];"

    "[a0_low][a1_norm]amix=inputs=2[aout];"

    f"[anorm]adelay={delay}|{delay}[a1v];"

    "[aout][a1v]amix=inputs=2:normalize=0[outa]"
)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-i", str(audio),
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[outa]",
        "-c:v", "copy",
        "-c:a", "aac",
         str(output)
    ]

    run_cmd(cmd)

def mix_start_aligned(
    video,
    audio,
    output,
    narration_duration
):
    filter_complex = (
    # 归一化视频原声
    "[0:a]loudnorm=I=-20:LRA=7:TP=-2[vnorm];"

    # 归一化配音
    "[1:a]loudnorm=I=-14:LRA=7:TP=-2[anorm];"

    # 你的原逻辑
    "[vnorm]asplit=2[a0][a1];"
    f"[a0]volume=0.01:enable='between(t,0,{narration_duration})'[a0_low];"
    "[a1]volume=1.0[a1_norm];"
    "[a0_low][a1_norm]amix=inputs=2[aout];"

    "[anorm]adelay=0|0[a1v];"

    "[aout][a1v]amix=inputs=2:normalize=0[outa]"
)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-i", str(audio),
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[outa]",
        "-c:v", "copy",
        "-c:a", "aac",
        str(output)
    ]

    run_cmd(cmd)

def encode_to_standard(input_path, output_path):
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),

        # 统一视频规格（关键）
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", "25",
        "-preset", "ultrafast",

        # 统一音频
        "-c:a", "aac",
        "-ar", "48000",
        "-ac", "2",

        output_path
    ]

    run_cmd(cmd)

def concat_videos(filelist, output):

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(filelist),

        "-c", "copy",
        output
    ]

    run_cmd(cmd)

def concat_mp3s(filelist, output):
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(filelist),
        "-c", "copy",
        str(output),
    ]

    run_cmd(cmd)

def change_resolution(input_file, output_file,
                  width, height, fps):

    vf = (
        f"scale={width}:-2,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
        "setsar=1"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_file),

        "-vf", vf,

        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",

        "-c:a", "aac",
        "-b:a", "192k",

        "-r", str(fps),

        str(output_file)
    ]

    run_cmd(cmd)

def speed_up(input_path, output_path, speed):

    video_filter = f"[0:v]setpts=PTS/{speed}[v]"

    audio_filter = f"[0:a]atempo={speed}[a]"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),

        "-filter_complex",
        f"{video_filter};{audio_filter}",

        "-map", "[v]",
        "-map", "[a]",

        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",

        "-c:a", "aac",
        "-b:a", "192k",

        output_path
    ]

    run_cmd(cmd)

def mask_sub(
    input_video,
    output_video,
    y_offset,
    mask_height
):

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_video),

        "-vf",
        (
            f"drawbox="
            f"x=0:"
            f"y=ih-{y_offset}:"
            f"w=iw:"
            f"h={mask_height}:"
            f"color=black:"
            f"t=fill"
        ),

        "-c:v", "libx264",
        "-c:a", "copy",

        str(output_video)
    ]

    run_cmd(cmd)

def mosaic_regions(
    input_video,
    output_video,
    regions,
):
    """
    regions:
    [
        {
            "x": 10,
            "y": 10,
            "width": 120,
            "height": 60,
            "mosaic_size": 8,
        },
        {
            "x": 1700,
            "y": 20,
            "width": 180,
            "height": 80,
            "mosaic_size": 10,
        }
    ]
    """

    filter_parts = []

    current = "[0:v]"

    for i, region in enumerate(regions):

        x = region["x"]
        y = region["y"]
        w = region["width"]
        h = region["height"]
        mosaic_size = region.get("mosaic_size", 20)

        down_w = max(1, w // mosaic_size)
        down_h = max(1, h // mosaic_size)

        crop_label = f"m{i}"
        out_label = f"v{i}"

        filter_parts.append(
            f"[0:v]"
            f"crop={w}:{h}:{x}:{y},"
            f"scale={down_w}:{down_h},"
            f"scale={w}:{h}:flags=neighbor"
            f"[{crop_label}]"
        )

        filter_parts.append(
            f"{current}[{crop_label}]"
            f"overlay={x}:{y}"
            f"[{out_label}]"
        )

        current = f"[{out_label}]"

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_video),

        "-filter_complex", filter_complex,

        "-map", current,
        "-map", "0:a?",

        "-c:v", "libx264",
        "-c:a", "copy",

        str(output_video)
    ]

    run_cmd(cmd)

def add_subtitles(input_video, srt_file, output_video, y):
    srt_path = str(srt_file).replace("\\", "/")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),

        "-vf",
        (
            f"subtitles={srt_path}:"
            f"force_style='Alignment=2,MarginV={y},FontSize=10,PrimaryColour=&H00CCFF&,FontName=Microsoft YaHei'"
        ),

        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "fast",
        "-c:a", "copy",

        str(output_video)
    ]

    run_cmd(cmd)

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

    font_path = "C\\:/Windows/Fonts/msyh.ttc"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),

        "-vf",
        (
            f"drawtext="
            f"fontfile='{font_path}':"
            f"text='{title}':"
            f"fontcolor={title_color}:"
            f"fontsize={font_size_title}:"
            f"x=(w-text_w)/2:"
            f"y={title_y},"
            
            f"drawtext="
            f"fontfile='{font_path}':"
            f"text='{subtitle}':"
            f"fontcolor={sub_color}:"
            f"fontsize={font_size_sub}:"
            f"x=(w-text_w)/2:"
            f"y=h-{sub_y}"
        ),

        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "fast",
        "-c:a", "copy",

        str(output_video)
    ]

    run_cmd(cmd)


def add_gif_overlay(
    input_video,
    output_video,
    gif_path,
    x,
    y,
    scale
):
    """
    在视频上叠加 GIF 动画
    """

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-ignore_loop", "0",
        "-i", str(gif_path),

        "-filter_complex",
        (
            f"[1:v]scale=iw*{scale}:ih*{scale}[gif];"
            f"[0:v][gif]overlay={x}:{y}:shortest=1"
        ),

        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "fast",
        "-c:a", "copy",

        str(output_video)
    ]

    run_cmd(cmd)

def wav_to_map3(wav_path, mp3_path):
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(wav_path),
        "-codec:a", "libmp3lame",
        "-q:a", "2",
        str(mp3_path)
    ]

    run_cmd(cmd)