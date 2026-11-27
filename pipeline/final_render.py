"""One video encode for main's entire post-production stage."""
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from core.captions import read_srt, validate_caption_layout, write_caption_ass, overlay_layout
from core.ffmpeg import FONT_PATH
from pipeline.source_preprocess import probe_source

MAIN_SPEED = 1.2


def validate_speed(speed):
    if isinstance(speed, bool) or not math.isfinite(float(speed)) or not .5 <= float(speed) <= 2:
        raise ValueError("成片速度必须在 0.5–2 之间")
    return float(speed)


def export_recognition_audio(source, destination, speed=MAIN_SPEED):
    """Only audio is decoded: match the final playback clock, without music."""
    speed = validate_speed(speed)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.stem+".encoding.mp3")
    try:
        subprocess.run(["ffmpeg", "-y", "-i", str(source), "-vn", "-af",
            f"asetpts=PTS-STARTPTS,atempo={speed:g}", "-ac", "2", "-ar", "44100",
            "-c:a", "libmp3lame", "-b:a", "192k", str(temporary)], check=True)
        if not temporary.is_file() or not temporary.stat().st_size:
            raise RuntimeError("识别音频未生成")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def render_final_video(source, destination, srt_path, title, subtitle, caption_layout,
                       popup_comments=None, *, speed=MAIN_SPEED, music_path=None,
                       music_volume=.08, gif_path=None, ass_path=None, text_layout=None):
    """Speed first, then lay out text/animation on the final 1080x1920 clock."""
    speed = validate_speed(speed)
    validate_caption_layout(caption_layout)
    text_layout = overlay_layout(text_layout)
    volume = float(music_volume)
    if not math.isfinite(volume) or not 0 <= volume <= 1:
        raise ValueError("背景音乐音量必须在 0 到 1 之间")
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if source == destination:
        raise ValueError("成片不能覆盖拼接源视频")
    info = probe_source(source)
    if not info["has_audio"]:
        raise ValueError("拼接成片没有音轨")
    duration = info["duration"]/speed
    destination.parent.mkdir(parents=True, exist_ok=True)
    ass_path = Path(ass_path) if ass_path else destination.with_suffix(".ass")
    ass_path.parent.mkdir(parents=True, exist_ok=True)
    write_caption_ass(read_srt(srt_path), ass_path, caption_layout)
    temporary = destination.with_name(destination.stem+".encoding.mp4")
    try:
        with tempfile.TemporaryDirectory(prefix="main_final_render_") as directory:
            folder = Path(directory)
            (folder/"fonts").mkdir()
            shutil.copy2(FONT_PATH, folder/"fonts"/FONT_PATH.name)
            shutil.copy2(ass_path, folder/"captions.ass")
            font = "fonts/"+FONT_PATH.name
            filters = [f"[0:v:0]setpts=(PTS-STARTPTS)/{speed:g},scale=1080:-2,"
                       "crop=w=iw:h='min(ih,1920)':x=0:y=(ih-oh)/2,"
                       "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30,"
                       "ass=filename=captions.ass:fontsdir=fonts"]

            def text_filter(text, name, size, color, x, y, extra=""):
                (folder/name).write_text(str(text), encoding="utf-8")
                return (f"drawtext=fontfile={font}:textfile={name}:expansion=none:"
                        f"fontcolor={color}:fontsize={size}:x={x}:y={y}"+extra)

            heading, subheading, popup = (text_layout[k] for k in ("title", "subtitle", "popup"))
            filters[0] += ","+text_filter(title or "", "title.txt", heading["font_size"], "0xFFCC00", "(w-text_w)/2", heading["y"])
            for i, line in enumerate(str(subtitle or "").splitlines()):
                y = subheading["y"]+i*round(subheading["font_size"]*1.25)
                if y+subheading["font_size"] > 1920:
                    raise ValueError("副标题超出竖屏底部，请上移或减小字号")
                filters[0] += ","+text_filter(line, f"subtitle_{i}.txt", subheading["font_size"], "0xFFCC00",
                                            "(w-text_w)/2", y)
            for i, item in enumerate(popup_comments or []):
                start = float(item["start_time"])
                if not math.isfinite(start) or start < 0:
                    raise ValueError("弹幕开始时间必须是非负秒数")
                filters[0] += ","+text_filter(item["text"], f"popup_{i}.txt", popup["font_size"], "white",
                    f"w-(t-{start:g})*200", popup["y"], f":borderw=3:bordercolor=black:enable='gte(t,{start:g})'")
            filters[0] += "[picture]"
            inputs, index, video = ["-i", str(source)], 1, "[picture]"
            if gif_path is not None:
                gif = Path(gif_path).resolve()
                if not gif.is_file():
                    raise FileNotFoundError(f"动画不存在: {gif}")
                inputs += ["-ignore_loop", "0", "-i", str(gif)]
                filters += [f"[{index}:v:0]setpts=PTS-STARTPTS,scale=iw*2:ih*2[gif]",
                            "[picture][gif]overlay=500:1500:eof_action=repeat:shortest=0[video]"]
                index += 1
                video = "[video]"
            filters += [f"[0:a:0]asetpts=PTS-STARTPTS,atempo={speed:g},aresample=48000[speech]"]
            audio = "[speech]"
            if music_path is not None:
                music = Path(music_path).resolve()
                if not music.is_file():
                    raise FileNotFoundError(f"背景音乐不存在: {music}")
                inputs += ["-stream_loop", "-1", "-i", str(music)]
                filters += [f"[{index}:a:0]asetpts=PTS-STARTPTS,aresample=48000,volume={volume:g}[bgm]",
                            "[speech][bgm]amix=inputs=2:duration=first:dropout_transition=0[audio]"]
                audio = "[audio]"
            # Relative generated filenames avoid escaping user titles/Windows paths.
            (folder/"filters.txt").write_text(";\n".join(filters), encoding="utf-8")
            subprocess.run(["ffmpeg", "-y", *inputs, "-filter_complex_script", "filters.txt",
                "-map", video, "-map", audio, "-t", f"{duration:.6f}", "-c:v", "libx264",
                "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(temporary)],
                cwd=folder, check=True)
        result = probe_source(temporary)
        if (result["width"], result["height"]) != (1080, 1920) or not result["has_audio"]:
            raise RuntimeError("合并渲染输出尺寸或音轨无效")
        if abs(result["duration"]-duration) > .25:
            raise RuntimeError("合并渲染时长异常，未采用本次输出")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": str(destination), "ass_path": str(ass_path.resolve()), "speed": speed,
            "video_encode_passes": 1, "video": result}
