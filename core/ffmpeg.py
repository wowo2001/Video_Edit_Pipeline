import json
from pathlib import Path

from core.cmd import run_cmd


ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
FONT_PATH = ASSETS_DIR / "fonts" / "msyh.ttc"


def _font_filter_path(path):
    if not path.exists():
        raise FileNotFoundError(f"项目字体不存在: {path}")
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:")


def extract_audio(input_path, output_path):
    run_cmd(["ffmpeg", "-y", "-i", str(input_path), "-vn", "-ac", "2", "-ar", "44100", "-b:a", "192k", str(output_path)])


def cut_video(input_path, output_path, start, end):
    run_cmd(["ffmpeg", "-y", "-ss", str(start), "-i", str(input_path), "-t", str(end - start), "-c:v", "libx264", "-c:a", "aac", "-avoid_negative_ts", "make_zero", str(output_path)])


def get_duration(path):
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)]
    return round(float(json.loads(run_cmd(cmd, capture_output=True).stdout)["format"]["duration"]), 3)


def mix_narration(video, audio, output, alignment="start"):
    """Mix narration at the start or end of a video clip."""
    if alignment not in {"start", "end"}:
        raise ValueError("alignment must be 'start' or 'end'")
    narration_duration, video_duration = get_duration(audio), get_duration(video)
    start = 0 if alignment == "start" else max(0, video_duration - narration_duration)
    end, delay = (narration_duration if alignment == "start" else video_duration), int(start * 1000)
    filter_complex = (
        "[0:a]loudnorm=I=-20:LRA=7:TP=-2[vnorm];[1:a]loudnorm=I=-14:LRA=7:TP=-2[anorm];"
        "[vnorm]asplit=2[a0][a1];"
        f"[a0]volume=0.01:enable='between(t,{start},{end})'[a0_low];[a1]volume=1.0[a1_norm];"
        "[a0_low][a1_norm]amix=inputs=2[aout];"
        f"[anorm]adelay={delay}|{delay}[a1v];[aout][a1v]amix=inputs=2:normalize=0[outa]"
    )
    run_cmd(["ffmpeg", "-y", "-i", str(video), "-i", str(audio), "-filter_complex", filter_complex, "-map", "0:v", "-map", "[outa]", "-c:v", "copy", "-c:a", "aac", str(output)])


def mix_background_narration(video, audio, output):
    """Use the existing narration mix from the start of a background-only clip."""
    mix_narration(video, audio, output, alignment="start")


def encode_to_standard(input_path, output_path):
    run_cmd(["ffmpeg", "-y", "-i", str(input_path), "-vf", "scale=-2:720,pad=1280:720:(ow-iw)/2:(oh-ih)/2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25", "-preset", "ultrafast", "-c:a", "aac", "-ar", "48000", "-ac", "2", str(output_path)])


def concat_media(filelist, output):
    """Concatenate compatible media files listed in FFmpeg concat format."""
    run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(filelist), "-c", "copy", str(output)])


def change_resolution(input_file, output_file, width, height, fps):
    vf = f"crop=960:720:160:0,scale={width}:-2,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
    run_cmd(["ffmpeg", "-y", "-i", str(input_file), "-vf", vf, "-r", str(fps), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(output_file)])


def speed_up(input_path, output_path, speed):
    filters = f"[0:v]setpts=PTS/{speed}[v];[0:a]atempo={speed}[a]"
    run_cmd(["ffmpeg", "-y", "-i", str(input_path), "-filter_complex", filters, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-c:a", "aac", "-b:a", "192k", str(output_path)])


def mask_sub(input_video, output_video, y_offset, mask_height):
    vf = f"drawbox=x=0:y=ih-{y_offset}:w=iw:h={mask_height}:color=black:t=fill"
    run_cmd(["ffmpeg", "-y", "-i", str(input_video), "-vf", vf, "-c:v", "libx264", "-c:a", "copy", str(output_video)])


def mosaic_regions(input_video, output_video, regions):
    filter_parts, current = [], "[0:v]"
    for index, region in enumerate(regions):
        x, y, width, height = region["x"], region["y"], region["width"], region["height"]
        size = region.get("mosaic_size", 20)
        down_width, down_height = max(1, width // size), max(1, height // size)
        crop, output = f"m{index}", f"v{index}"
        filter_parts.append(f"[0:v]crop={width}:{height}:{x}:{y},scale={down_width}:{down_height},scale={width}:{height}:flags=neighbor[{crop}]")
        filter_parts.append(f"{current}[{crop}]overlay={x}:{y}[{output}]")
        current = f"[{output}]"
    run_cmd(["ffmpeg", "-y", "-i", str(input_video), "-filter_complex", ";".join(filter_parts), "-map", current, "-map", "0:a?", "-c:v", "libx264", "-c:a", "copy", str(output_video)])


def add_subtitles(input_video, srt_file, output_video, y, font_size=10):
    srt_path = _font_filter_path(Path(srt_file))
    font_dir = _font_filter_path(FONT_PATH.parent)
    vf = (
        f"subtitles=filename='{srt_path}':fontsdir='{font_dir}':"
        f"force_style='Alignment=2,MarginV={y},FontSize={font_size},"
        "PrimaryColour=&H00CCFF&,FontName=Microsoft YaHei'"
    )
    run_cmd(["ffmpeg", "-y", "-i", str(input_video), "-vf", vf, "-c:v", "libx264", "-crf", "23", "-preset", "fast", "-c:a", "copy", str(output_video)])


def add_text_overlay(input_video, output_video, title, subtitle, font_size_title, font_size_sub, title_y, sub_y, title_color, sub_color, popup_comments, popup_font_size, popup_color, popup_y):
    font_path, filters = _font_filter_path(FONT_PATH), []
    filters.append(f"drawtext=fontfile='{font_path}':text='{title}':fontcolor={title_color}:fontsize={font_size_title}:x=(w-text_w)/2:y={title_y}")
    filters.append(f"drawtext=fontfile='{font_path}':text='{subtitle}':fontcolor={sub_color}:fontsize={font_size_sub}:x=(w-text_w)/2:y=h-{sub_y}")
    for item in popup_comments or []:
        filters.append(f"drawtext=fontfile='{font_path}':text='{item['text']}':fontcolor={popup_color}:fontsize={popup_font_size}:borderw=3:bordercolor=black:x=w-(t-{item['start_time']})*200:y={popup_y}:enable='gte(t,{item['start_time']})'")
    vf = ",".join(filters)
    print(vf)
    run_cmd(["ffmpeg", "-y", "-i", str(input_video), "-vf", vf, "-c:v", "libx264", "-crf", "23", "-preset", "fast", "-c:a", "copy", str(output_video)])


def add_gif_overlay(input_video, output_video, gif_path, x, y, scale):
    filters = f"[1:v]scale=iw*{scale}:ih*{scale}[gif];[0:v][gif]overlay={x}:{y}:shortest=1"
    run_cmd(["ffmpeg", "-y", "-i", str(input_video), "-ignore_loop", "0", "-i", str(gif_path), "-filter_complex", filters, "-c:v", "libx264", "-crf", "23", "-preset", "fast", "-c:a", "copy", str(output_video)])


def wav_to_map3(wav_path, mp3_path):
    run_cmd(["ffmpeg", "-y", "-i", str(wav_path), "-codec:a", "libmp3lame", "-q:a", "2", str(mp3_path)])


def dub_video_segment(input_video, tts_audio, output_video, start_ms, end_ms, target_duration_ms):
    """Retiming source video and replacing its original audio with TTS."""
    source_duration_ms = end_ms - start_ms
    if source_duration_ms <= 0 or target_duration_ms <= 0:
        raise ValueError("视频和 TTS 时长必须大于 0")
    speed = source_duration_ms / target_duration_ms
    output_video = Path(output_video)
    output_video.parent.mkdir(parents=True, exist_ok=True)
    run_cmd([
        "ffmpeg", "-y", "-ss", str(start_ms / 1000), "-t", str(source_duration_ms / 1000),
        "-i", str(input_video), "-i", str(tts_audio),
        "-filter_complex", f"[0:v]setpts=PTS/{speed}[video]", "-map", "[video]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-c:a", "aac", "-shortest", str(output_video),
    ])
    return speed